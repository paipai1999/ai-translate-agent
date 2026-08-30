import os
import sys
import json
import uuid
import time
import threading
import io
import shutil
import posixpath
import asyncio
import contextvars
from urllib.parse import quote, unquote
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.downloader_agent import DownloaderAgent
from agents.master import MasterAgent
from agents.video_merger_agent import detect_hardware_encoder
from brain.sqlite_store import delete_movie_state, list_movie_states
from main import check_dependencies

# Setup FFmpeg path at startup
try:
    check_dependencies()
except Exception as e:
    print(f"[WARN] check_dependencies failed: {e}")

app = FastAPI(title="AI Movie Recap API", version="2.2.0")
templates = Jinja2Templates(directory="templates")

VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v')

jobs = {}
jobs_lock = threading.Lock()
JOB_RETENTION_SECONDS = 7200  # Clean up finished jobs after 2 hours

def _cleanup_old_jobs():
    """Remove completed/error jobs older than JOB_RETENTION_SECONDS to prevent memory growth."""
    now = time.time()
    with jobs_lock:
        to_delete = [
            jid for jid, job in list(jobs.items())
            if job.get('status') in ('done', 'error')
            and now - job.get('created_at', now) > JOB_RETENTION_SECONDS
        ]
        for jid in to_delete:
            jobs.pop(jid, None)
            # BUG-C6 Fix: Also free thread_stdout buffers and subscribers to prevent memory leak
            if hasattr(thread_stdout, 'buffers'):
                thread_stdout.buffers.pop(jid, None)
            if hasattr(thread_stdout, 'subscribers'):
                thread_stdout.subscribers.pop(jid, None)

def _has_running_job():
    # NOTE: Caller must hold jobs_lock or this is best-effort.
    return any(job.get('status') == 'running' for job in jobs.values())

def _resolve_input_source(input_source: str) -> str:
    """Resolve a dashboard filename to movies/ while still allowing valid local paths."""
    source = str(input_source or '').strip()
    if not source:
        raise ValueError("No input provided")
    if DownloaderAgent.is_url(source):
        return source
    if os.path.exists(source):
        return os.path.abspath(source)
    if not os.path.dirname(source):
        movies_path = os.path.join('movies', source)
        if os.path.exists(movies_path):
            return os.path.abspath(movies_path)
    raise FileNotFoundError(f"File not found: '{source}'")

def _safe_child_path(folder_type: str, item_name: str):
    if folder_type not in {'outputs', 'movies', 'temp'} or not item_name:
        return None
    base = os.path.abspath(folder_type)
    candidate = os.path.abspath(os.path.join(base, item_name))
    try:
        return candidate if os.path.commonpath([base, candidate]) == base else None
    except ValueError:
        return None


# Use contextvars to propagate Job ID across thread pools automatically (Python 3.7+)
current_job_id = contextvars.ContextVar("current_job_id", default=None)

class ThreadedStdout:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.buffers = {}
        self.subscribers = {}

    def write(self, s):
        jid = current_job_id.get()
        if jid and jid in self.buffers:
            self.buffers[jid].write(s)
            if jid in self.subscribers:
                for q in list(self.subscribers[jid]):
                    try:
                        q.put_nowait(s)
                    except Exception:
                        pass
        try:
            self.original_stdout.write(s)
            self.original_stdout.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.original_stdout, "isatty", lambda: False)()

    def fileno(self):
        if hasattr(self.original_stdout, "fileno"):
            return self.original_stdout.fileno()
        raise io.UnsupportedOperation("fileno")

    def reconfigure(self, **kwargs):
        if hasattr(self.original_stdout, "reconfigure"):
            self.original_stdout.reconfigure(**kwargs)

    def __getattr__(self, name):
        return getattr(self.original_stdout, name)

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

thread_stdout = ThreadedStdout(sys.stdout)
sys.stdout = thread_stdout
sys.stderr = thread_stdout

def pipeline_worker(job_id, input_source, language="burmese", subtitle_mode="auto", tts_engine=None):
    current_job_id.set(job_id)
    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        if DownloaderAgent.is_url(input_source):
            print("[URL] Detected URL - starting auto-download...")
            downloader = DownloaderAgent(output_dir="movies")
            movie_path = downloader.download_video(input_source)
        else:
            movie_path = _resolve_input_source(input_source)
        
        master = MasterAgent(movie_path, language=language, subtitle_mode=subtitle_mode, tts_engine=tts_engine)
        master.run_pipeline()
        with jobs_lock:
            jobs[job_id]['status'] = 'done'
    except Exception as e:
        import traceback
        traceback.print_exc()
        with jobs_lock:
            jobs[job_id]['status'] = 'error'
    finally:
        # BUG-C3 Fix: Free log buffer immediately on job end (not after 2-hour JOB_RETENTION).
        # subscriber list and job metadata are still cleaned by _cleanup_old_jobs() later.
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

def batch_worker(job_id, inputs_list, language="burmese", subtitle_mode="auto", tts_engine=None):
    from brain.planner import BatchProcessor
    current_job_id.set(job_id)
    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        urls = [i for i in inputs_list if DownloaderAgent.is_url(i)]
        local_paths = [_resolve_input_source(i) for i in inputs_list if not DownloaderAgent.is_url(i)]
        processor = BatchProcessor(movies_folder="movies", skip_completed=True, language=language, subtitle_mode=subtitle_mode, tts_engine=tts_engine)
        print(f"[*] Batch Mode: Starting batch run for {len(inputs_list)} item(s)...")
        processor.process_all(url_list=urls, local_paths=local_paths)
        with jobs_lock:
            jobs[job_id]['status'] = 'done'
    except Exception as e:
        import traceback
        traceback.print_exc()
        with jobs_lock:
            jobs[job_id]['status'] = 'error'
    finally:
        # BUG-C3 Fix: Free log buffer immediately on batch job end.
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

# ── Pydantic Request Models ──
class StartRequest(BaseModel):
    input: str
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "auto"
    tts_engine: Optional[str] = None

class BatchStartRequest(BaseModel):
    inputs: List[str]
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "auto"
    tts_engine: Optional[str] = None

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

class SaveKeysRequest(BaseModel):
    keys: List[str]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/system/info")
async def system_info():
    enc = detect_hardware_encoder()
    with jobs_lock:
        active = _has_running_job()
    return {
        "hardware_encoder": enc,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "active_jobs": active
    }

@app.post("/api/upload")
async def upload_file(video: UploadFile = File(...)):
    if not video.filename:
        raise HTTPException(status_code=400, detail="No selected file")

    import re as _re
    def _secure_filename(fname: str) -> str:
        """Stdlib-based secure_filename: strips unsafe chars, no werkzeug needed."""
        fname = os.path.basename(fname).strip()
        fname = _re.sub(r'[^\w\-_. ]', '_', fname)
        fname = fname.strip('. ')
        return fname or "upload"

    filename = _secure_filename(video.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File is not a supported video format")
        
    os.makedirs("movies", exist_ok=True)
    save_path = os.path.join("movies", filename)
    with open(save_path, "wb") as f:
        # BUG-M3 Fix: Stream in 1MB chunks — avoids loading a 4GB file entirely into RAM
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


    return {"success": True, "filename": filename}

@app.post("/api/start")
async def start_pipeline(req: StartRequest):
    input_source = req.input
    language = req.language or 'burmese'
    subtitle_mode = req.subtitle_mode or 'auto'
    tts_engine = req.tts_engine
    if not input_source:
        raise HTTPException(status_code=400, detail="No input provided")
    
    _cleanup_old_jobs()
    with jobs_lock:
        if _has_running_job():
            raise HTTPException(status_code=409, detail="A pipeline job is already running. Wait for it to finish first.")
        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "status": "running",
            "phase": "Starting...",
            "buffer": None,
            "created_at": time.time()
        }
    
    t = threading.Thread(target=pipeline_worker, args=(job_id, input_source, language, subtitle_mode, tts_engine), daemon=True)
    t.start()
    return {"job_id": job_id}

@app.post("/api/batch/start")
async def start_batch_pipeline(req: BatchStartRequest):
    inputs = req.inputs
    language = req.language or 'burmese'
    subtitle_mode = req.subtitle_mode or 'auto'
    tts_engine = req.tts_engine
    if not inputs or not all(isinstance(item, str) and item.strip() for item in inputs):
        raise HTTPException(status_code=400, detail="No inputs provided for batch mode")
        
    _cleanup_old_jobs()
    with jobs_lock:
        if _has_running_job():
            raise HTTPException(status_code=409, detail="A pipeline job is already running. Wait for it to finish first.")
        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "status": "running",
            "phase": "Batch Mode Starting...",
            "buffer": None,
            "created_at": time.time()
        }
    
    t = threading.Thread(target=batch_worker, args=(job_id, inputs, language, subtitle_mode, tts_engine), daemon=True)
    t.start()
    return {"job_id": job_id}

@app.get("/api/stream/{job_id}")
async def stream_job_logs(job_id: str, request: Request):
    """Server-Sent Events (SSE) stream for zero-latency live logs and progress updates."""
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        import re
        q = asyncio.Queue()
        if job_id not in thread_stdout.subscribers:
            thread_stdout.subscribers[job_id] = []
        thread_stdout.subscribers[job_id].append(q)

        try:
            with jobs_lock:
                job = jobs.get(job_id, {})
                buf = job.get('buffer')
                initial_content = buf.getvalue() if buf else ""

            if initial_content:
                lines = [l for l in initial_content.split('\n') if l]
                for l in lines[-25:]:
                    yield {"event": "log", "data": json.dumps({"line": l})}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=1.0)
                    lines = chunk.split('\n')
                    for l in lines:
                        if l.strip():
                            current_phase = "Running..."
                            batch_status = None
                            if '--- [Phase' in l or '--- [DONE]' in l:
                                current_phase = l.strip().strip('-').strip()
                            elif '[DONE]' in l:
                                current_phase = 'Done'

                            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', l)
                            if m: batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"

                            # BUG-L2 Fix: Read status under lock to avoid data race
                            with jobs_lock:
                                cur_status = jobs.get(job_id, {}).get('status', 'running')

                            yield {
                                "event": "log",
                                "data": json.dumps({
                                    "line": l,
                                    "phase": current_phase,
                                    "batch_status": batch_status,
                                    "status": cur_status
                                })
                            }
                except asyncio.TimeoutError:
                    pass

                with jobs_lock:
                    current_job = jobs.get(job_id)
                    if not current_job:
                        break
                    job_status = current_job.get('status')

                if job_status in ('done', 'error'):
                    yield {
                        "event": "done",
                        "data": json.dumps({"status": job_status})
                    }
                    break

        finally:
            # BUG-C5 Fix: Always clean up subscriber queue, even on client disconnect / exception
            subs = thread_stdout.subscribers.get(job_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                thread_stdout.subscribers.pop(job_id, None)

    return EventSourceResponse(event_generator())

@app.get("/api/status/{job_id}")
async def status_endpoint(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[job_id]
        
    buffer = job.get('buffer')
    log_lines = []
    current_phase = job.get('phase', 'Starting...')
    batch_status = None
    
    if buffer:
        content = buffer.getvalue()
        lines = content.split('\n')
        log_lines = [line for line in lines if line][-20:]

        for line in reversed(lines):
            if '--- [Phase' in line or '--- [DONE]' in line:
                current_phase = line.strip().strip('-').strip()
                break
            if '[DONE]' in line:
                current_phase = 'Done'
                break

        import re
        for line in reversed(lines):
            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', line)
            if m:
                batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"
                break
            m2 = re.search(r'\[(\d+)/(\d+)\] Downloading:', line)
            if m2 and not batch_status:
                batch_status = f"Downloading: {m2.group(1)} of {m2.group(2)}"
                break
                
    return {
        "status": job["status"],
        "phase": current_phase,
        "batch_status": batch_status,
        "log": log_lines
    }

@app.get("/api/outputs")
async def list_outputs():
    metadata = list_movie_states("outputs")
    outputs_dir = "outputs"
    if not os.path.exists(outputs_dir):
        return {"metadata": metadata, "outputs": {}}

    result = {}
    for root, dirs, files in os.walk(outputs_dir):
        if os.path.basename(root) in ["temp", "voiceover"]:
            dirs[:] = []
            continue

        if "state.json" not in files:
            continue

        rel_dir = os.path.relpath(root, outputs_dir).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        entry = {"files": [], "progress": 100, "phase": "Done", "total_duration": "", "phase_durations": {}}
        for f in sorted(files):
            if f == "state.json":
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as sf:
                        state_data = json.load(sf)
                        entry["progress"] = state_data.get("progress", 100)
                        entry["phase"] = state_data.get("current_phase", "Done")
                        entry["total_duration"] = state_data.get("total_duration_formatted", "")
                        entry["total_duration_sec"] = state_data.get("total_duration_sec", 0.0)
                        entry["phase_durations"] = state_data.get("phase_durations", {})
                except Exception:
                    pass
                continue
            entry["files"].append(posixpath.join(rel_dir, f) if rel_dir else f)

        result[rel_dir or os.path.basename(root)] = entry
        dirs[:] = []

    return {"metadata": metadata, "outputs": result}

@app.get("/api/logs/{movie_name:path}")
async def get_movie_logs(movie_name: str):
    safe_name = os.path.normpath(movie_name).strip(" /\\.")
    log_path = os.path.join("outputs", safe_name, "pipeline.log")
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found for this movie")
    
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return PlainTextResponse(content)

@app.get("/api/outputs/file")
async def serve_output(path: str = Query("")):
    rel_path = path
    if not rel_path:
        raise HTTPException(status_code=400, detail="No file path specified")

    safe_path = os.path.normpath(rel_path)
    if safe_path.startswith('..') or os.path.isabs(safe_path):
        raise HTTPException(status_code=400, detail="Invalid file path")

    outputs_dir = os.path.abspath("outputs")
    full_path = os.path.normpath(os.path.join(outputs_dir, safe_path))
    if os.path.commonpath([outputs_dir, full_path]) != outputs_dir:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    if os.path.isdir(full_path):
        files = [
            {"name": f, "url": f"/api/outputs/file?path={quote(os.path.join(rel_path, f))}"}
            for f in sorted(os.listdir(full_path))
        ]
        return {"directory": rel_path, "files": files}

    return FileResponse(full_path)

@app.get("/api/movies")
async def list_movies():
    movies_dir = "movies"
    if not os.path.exists(movies_dir):
        return []
    files = [f for f in os.listdir(movies_dir) if f.lower().endswith(VIDEO_EXTENSIONS)]
    return sorted(files)

@app.delete("/api/delete/cache")
async def clear_cache():
    cleared = 0
    for d in ["temp", "voiceover"]:
        if os.path.exists(d):
            for item in os.listdir(d):
                p = os.path.join(d, item)
                try:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                    cleared += 1
                except:
                    pass

    for root, dirs, files in os.walk('.'):
        for d in list(dirs):
            if d == '__pycache__':
                try:
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
                    cleared += 1
                except:
                    pass

    return {"success": True, "cleared_items": cleared}

@app.api_route("/api/config", methods=["GET", "POST"])
async def handle_config(request: Request):
    import brain.config as cfg
    config_data = cfg.load_config()
    if request.method == 'POST':
        data = await request.json() or {}
        if "mirror_video" in data:
            if "copyright_protection" not in config_data:
                config_data["copyright_protection"] = {}
            config_data["copyright_protection"]["mirror_video"] = bool(data["mirror_video"])
            cfg.save_config(config_data)
        if "tts_engine" in data:
            if "voice" not in config_data:
                config_data["voice"] = {}
            config_data["voice"]["engine"] = str(data["tts_engine"]).strip().lower()
            cfg.save_config(config_data)
        public_config = json.loads(json.dumps(config_data))
        public_config.get("gemini", {}).pop("api_keys", None)
        return {"success": True, "config": public_config}
    else:
        public_config = json.loads(json.dumps(config_data))
        public_config.get("gemini", {}).pop("api_keys", None)
        return public_config

@app.get("/api/keys/status")
async def get_key_status():
    import brain.config as cfg
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    
    config_data = cfg.load_config()
    gemini_cfg = config_data.get("gemini", {})
    configured_keys = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY") or []
    if isinstance(configured_keys, str):
        configured_keys = [k.strip() for k in configured_keys.split(",") if k.strip()]
        
    from brain.tracker import load_usage_db, get_google_utc_date
    db = load_usage_db()
    recorded_keys = db.get("keys", {})
    current_utc = get_google_utc_date()
    
    def ping_google_key(key):
        key_str = str(key).strip()
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key_str}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    return "ONLINE", 200
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return "RATE LIMITED (429)", 429
            elif e.code in [400, 401, 403]:
                return "INVALID KEY", e.code
            return f"HTTP {e.code}", e.code
        except Exception:
            return "UNREACHABLE", 0
        return "UNKNOWN", 0

    key_statuses = []
    total_remaining = 0
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        ping_results = list(executor.map(ping_google_key, configured_keys))

    for idx, key in enumerate(configured_keys):
        if not key or not str(key).strip(): continue
        key_str = str(key).strip()
        masked = key_str[:6] + "..." + key_str[-4:] if len(key_str) > 10 else key_str
        
        live_state, http_code = ping_results[idx]
        kdata = recorded_keys.get(masked, {})
        
        model_limits = gemini_cfg.get("model_limits", {})
        models_data = kdata.get("models", {})
        
        model_stats = []
        for m_name, m_limit in model_limits.items():
            used = models_data.get(m_name, {}).get("used_today", 0)
            if kdata.get("utc_date") != current_utc:
                used = 0
            remaining = max(0, int(m_limit) - used)
            total_remaining += remaining
            model_stats.append({
                "name": m_name,
                "used_today": used,
                "limit": int(m_limit),
                "remaining": remaining
            })
            
        key_statuses.append({
            "key": masked,
            "live_status": live_state,
            "http_code": http_code,
            "models": model_stats
        })
        
    hardware = detect_hardware_encoder()
    return {
        "total_keys": len(key_statuses),
        "total_remaining_requests": total_remaining,
        "daily_limit_per_key": int(gemini_cfg.get("daily_limit_per_key", 20)),
        "hardware_encoder": hardware,
        "keys": key_statuses
    }

@app.delete("/api/delete/{folder_type}/{item_name:path}")
async def delete_item(folder_type: str, item_name: str):
    target_path = _safe_child_path(folder_type, item_name)
    if not target_path:
        raise HTTPException(status_code=400, detail="Invalid target")
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Item not found")
        
    try:
        if os.path.isdir(target_path):
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            os.remove(target_path)
            
        if folder_type == "outputs":
            temp_path = os.path.join("temp", item_name)
            if os.path.exists(temp_path):
                shutil.rmtree(temp_path, ignore_errors=True)
            try:
                delete_movie_state(item_name)
            except Exception as e:
                print(f"[WARN] Could not remove output DB entry for {item_name}: {e}")
                
        print(f"[*] WebUI: Successfully deleted {folder_type}/{item_name}")
        return {"success": True, "message": f"Deleted {item_name}"}
    except Exception as e:
        print(f"[!] WebUI: Delete failed ({e})")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/delete_all/{folder_type}")
async def delete_all(folder_type: str):
    if folder_type not in {'movies', 'outputs', 'temp', 'all'}:
        raise HTTPException(status_code=400, detail="Invalid target")
    
    targets = ['movies', 'outputs', 'temp'] if folder_type == 'all' else [folder_type]
    deleted = 0
    try:
        for target_folder in targets:
            root = os.path.abspath(target_folder)
            if not os.path.isdir(root):
                continue
            for item_name in os.listdir(root):
                if target_folder == 'outputs' and item_name in ['api_usage_db.json', 'movie_metadata.db']:
                    continue
                    
                target = _safe_child_path(target_folder, item_name)
                if not target:
                    continue
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                deleted += 1
        return {"success": True, "deleted_items": deleted}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not delete all items: {error}")

@app.post("/api/rename/movie")
async def rename_movie(req: RenameRequest):
    old_name = os.path.basename(req.old_name.strip())
    new_name = os.path.basename(req.new_name.strip())
    if not old_name or not new_name or old_name != req.old_name or new_name != req.new_name:
        raise HTTPException(status_code=400, detail="Use a filename only; folders are not allowed.")
    if not old_name.lower().endswith(VIDEO_EXTENSIONS) or not new_name.lower().endswith(VIDEO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Movie files must use a supported video extension.")
        
    source = _safe_child_path('movies', old_name)
    destination = _safe_child_path('movies', new_name)
    if not source or not destination or not os.path.isfile(source):
        raise HTTPException(status_code=404, detail="Source movie was not found.")
    if os.path.exists(destination):
        raise HTTPException(status_code=409, detail="A movie with that name already exists.")
    try:
        os.replace(source, destination)
        return {"success": True, "name": new_name}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not rename movie: {error}")

@app.get("/api/keys/list")
async def list_raw_keys():
    import brain.config as cfg
    config_data = cfg.load_config()
    gemini_cfg = config_data.get("gemini", {})
    keys = gemini_cfg.get("api_keys", [])
    masked_keys = [k[:8] + '...' + k[-4:] if len(k) > 12 else '***' for k in keys]
    return {'keys': masked_keys, 'count': len(masked_keys)}

@app.post("/api/keys/save")
async def save_keys(req: SaveKeysRequest):
    import brain.config as cfg
    try:
        new_keys = req.keys
        cleaned_keys = []
        for k in new_keys:
            k = str(k).strip()
            if k and k not in cleaned_keys:
                cleaned_keys.append(k)
                
        config_data = cfg.load_config()
        config_data.setdefault("gemini", {})["api_keys"] = cleaned_keys
        cfg.save_config(config_data)
            
        print(f"[*] WebUI: Updated API keys in config.json ({len(cleaned_keys)} keys)")
        return {"success": True, "keys_count": len(cleaned_keys)}
    except Exception as e:
        print(f"[ERROR] Failed to save API keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0" if ("COLAB_GPU" in os.environ or "KAGGLE_KERNEL_RUN_TYPE" in os.environ) else "127.0.0.1")
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host=host, port=port, log_level='info')
