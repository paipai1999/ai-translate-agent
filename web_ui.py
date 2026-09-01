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
from urllib.parse import quote
from typing import Optional, List

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.downloader_agent import DownloaderAgent
from agents.master import MasterAgent
from agents.video_merger_agent import detect_hardware_encoder
from brain.sqlite_store import delete_movie_state, list_movie_states
from brain import config as cfg
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
    # Check SQLite database first for persistence across restarts
    try:
        from brain.sqlite_store import get_active_job
        if get_active_job() is not None:
            return True
    except Exception:
        pass
    # Check in-memory jobs dictionary
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
        if not jid and self.buffers:
            # Fallback: associate with active job buffer if current_job_id wasn't inherited
            if len(self.buffers) == 1:
                jid = next(iter(self.buffers.keys()))
            else:
                jid = list(self.buffers.keys())[-1]

        if jid and jid in self.buffers:
            try:
                self.buffers[jid].write(s)
            except Exception:
                pass
            if jid in self.subscribers:
                for item in list(self.subscribers.get(jid, [])):
                    try:
                        if isinstance(item, tuple):
                            q, loop = item
                            if loop.is_running():
                                loop.call_soon_threadsafe(q.put_nowait, s)
                        else:
                            item.put_nowait(s)
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

def pipeline_worker(
    job_id,
    input_source,
    language="burmese",
    subtitle_mode="burn",
    resolution="1080p",
    tts_engine=None,
    custom_thumb_title=None,
    watermark_enabled=None,
    watermark_text=None,
    watermark_opacity=None,
    reels_enabled=True,
):
    current_job_id.set(job_id)
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    if reels_enabled is False:
        os.environ["DISABLE_REELS"] = "true"
        os.environ.pop("ENABLE_REELS", None)
    elif reels_enabled is True:
        os.environ["ENABLE_REELS"] = "true"
        os.environ.pop("DISABLE_REELS", None)

    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        from brain.sqlite_store import create_job, update_job
        create_job(job_id, str(input_source), phase="Starting...")
    except Exception:
        pass
    
    try:
        if DownloaderAgent.is_url(input_source):
            with jobs_lock:
                jobs[job_id]['phase'] = 'Downloading Video...'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, phase='Downloading Video...')
            except Exception:
                pass
            print(f"[URL] Detected URL: {input_source} - starting auto-download...")
            downloader = DownloaderAgent(output_dir="movies")
            movie_path = downloader.download_video(input_source)
        else:
            with jobs_lock:
                jobs[job_id]['phase'] = 'Processing Local File...'
            movie_path = _resolve_input_source(input_source)
        
        # Multi-Voice Mapping
        tts_voice_override = None
        clean_lang = language
        if language == "burmese_thiha":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"
        elif language == "burmese_nilar":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-NilarNeural"
        elif language == "burmese":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"  # Auto multi-voice enabled
        elif language == "english_guy":
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"
        elif language == "english_jenny":
            clean_lang = "english"
            tts_voice_override = "en-US-JennyNeural"
        elif language == "english":
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"    # Auto multi-voice enabled

        master = MasterAgent(
            movie_path,
            language=clean_lang,
            subtitle_mode=subtitle_mode,
            resolution=resolution,
            tts_engine=tts_engine,
            tts_voice=tts_voice_override,
            custom_thumb_title=custom_thumb_title,
            watermark_enabled=watermark_enabled,
            watermark_text=watermark_text,
            watermark_opacity=watermark_opacity,
        )
        master.run_pipeline()
        
        if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            import traceback
            traceback.print_exc()
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='error', phase='Error')
            except Exception:
                pass
    finally:
        # Free log buffer immediately on job end
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

def batch_worker(
    job_id,
    inputs_list,
    language="burmese",
    subtitle_mode="burn",
    resolution="1080p",
    tts_engine=None,
    custom_thumb_title=None,
    watermark_enabled=None,
    watermark_text=None,
    watermark_opacity=None,
    reels_enabled=True,
):
    from brain.planner import BatchProcessor
    current_job_id.set(job_id)
    os.environ["CURRENT_JOB_CANCELLED"] = "0"
    if reels_enabled is False:
        os.environ["DISABLE_REELS"] = "true"
        os.environ.pop("ENABLE_REELS", None)
    elif reels_enabled is True:
        os.environ["ENABLE_REELS"] = "true"
        os.environ.pop("DISABLE_REELS", None)

    buffer = io.StringIO()
    thread_stdout.buffers[job_id] = buffer
    with jobs_lock:
        jobs[job_id]['buffer'] = buffer
    
    try:
        from brain.sqlite_store import create_job, update_job
        create_job(job_id, f"Batch ({len(inputs_list)} items)", phase="Starting...")
    except Exception:
        pass
    
    try:
        urls = [i for i in inputs_list if DownloaderAgent.is_url(i)]
        local_paths = [_resolve_input_source(i) for i in inputs_list if not DownloaderAgent.is_url(i)]
        # Multi-Voice Mapping
        tts_voice_override = None
        clean_lang = language
        if language == "burmese_thiha":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"
        elif language == "burmese_nilar":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-NilarNeural"
        elif language == "burmese":
            clean_lang = "burmese"
            tts_voice_override = "my-MM-ThihaNeural"
        elif language == "english_guy":
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"
        elif language == "english_jenny":
            clean_lang = "english"
            tts_voice_override = "en-US-JennyNeural"
        elif language == "english":
            clean_lang = "english"
            tts_voice_override = "en-US-GuyNeural"

        processor = BatchProcessor(
            movies_folder="movies",
            skip_completed=True,
            language=clean_lang,
            subtitle_mode=subtitle_mode,
            resolution=resolution,
            tts_engine=tts_engine,
            tts_voice=tts_voice_override,
            custom_thumb_title=custom_thumb_title,
            watermark_enabled=watermark_enabled,
            watermark_text=watermark_text,
            watermark_opacity=watermark_opacity,
        )
        print(f"[*] Batch Mode: Starting batch run for {len(inputs_list)} item(s)...")
        processor.process_all(url_list=urls, local_paths=local_paths)
        
        if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            with jobs_lock:
                jobs[job_id]['status'] = 'done'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='done', phase='Done')
            except Exception:
                pass
    except Exception as e:
        is_cancel = isinstance(e, (InterruptedError, KeyboardInterrupt)) or (os.environ.get("CURRENT_JOB_CANCELLED") == "1")
        if is_cancel:
            print(f"\n🛑 [STOP] Batch job {job_id} was force-stopped by user.")
            with jobs_lock:
                jobs[job_id]['status'] = 'cancelled'
                jobs[job_id]['phase'] = 'Stopped by user'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='cancelled', phase='Stopped by user')
            except Exception:
                pass
        else:
            import traceback
            traceback.print_exc()
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
            try:
                from brain.sqlite_store import update_job
                update_job(job_id, status='error', phase='Error')
            except Exception:
                pass
    finally:
        # Free log buffer immediately on batch job end
        if hasattr(thread_stdout, 'buffers'):
            thread_stdout.buffers.pop(job_id, None)

# ── Pydantic Request Models ──
class StartRequest(BaseModel):
    input: str
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "burn"
    resolution: Optional[str] = "1080p"
    tts_engine: Optional[str] = None
    custom_thumb_title: Optional[str] = None
    watermark_enabled: Optional[bool] = True
    watermark_text: Optional[str] = None
    watermark_opacity: Optional[float] = None
    reels_enabled: Optional[bool] = True

class BatchStartRequest(BaseModel):
    inputs: List[str]
    language: Optional[str] = "burmese"
    subtitle_mode: Optional[str] = "burn"
    resolution: Optional[str] = "1080p"
    tts_engine: Optional[str] = None
    custom_thumb_title: Optional[str] = None
    watermark_enabled: Optional[bool] = True
    watermark_text: Optional[str] = None
    watermark_opacity: Optional[float] = None
    reels_enabled: Optional[bool] = True

class BrandingConfigRequest(BaseModel):
    watermark_enabled: bool = True
    watermark_text: str = "PAI AI Movie Translate"
    watermark_opacity: float = 0.4
    watermark_margin: int = 30
    watermark_font_size: int = 40

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

@app.get("/api/jobs/active")
async def get_active_job():
    try:
        from brain.sqlite_store import get_active_job as _db_active
        db_job = _db_active()
        if db_job:
            return {
                "job_id": db_job["job_id"],
                "status": "running",
                "phase": db_job.get("phase", "Running..."),
                "created_at": db_job.get("created_at")
            }
    except Exception:
        pass

    with jobs_lock:
        for jid, jdata in list(jobs.items()):
            if jdata.get("status") == "running":
                return {
                    "job_id": jid,
                    "status": "running",
                    "phase": jdata.get("phase", "Running..."),
                    "created_at": jdata.get("created_at")
                }
    return {"job_id": None, "status": "idle"}

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
    # Support automatic YouTube cookies.txt installation
    if filename.lower() in ["cookies.txt", "cookie.txt"] or filename.lower().endswith(".txt"):
        content = await video.read()
        if b"youtube" in content.lower() or b"# Netscape" in content or b"# HTTP Cookie File" in content:
            with open("cookies.txt", "wb") as f:
                f.write(content)
            os.makedirs("assets", exist_ok=True)
            with open(os.path.join("assets", "cookies.txt"), "wb") as f:
                f.write(content)
            drive_out = "/content/drive/MyDrive/MovieRecapOutputs"
            if os.path.exists(drive_out):
                try:
                    with open(os.path.join(drive_out, "cookies.txt"), "wb") as df:
                        df.write(content)
                    print("[*] Upload: cookies.txt permanently saved to Google Drive!")
                except Exception:
                    pass
            print("[*] Upload: cookies.txt installed successfully into root and assets/!")
            return {"success": True, "filename": "cookies.txt", "message": "YouTube cookies installed successfully!"}

    ext = os.path.splitext(filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File is not a supported video format or cookies.txt")
        
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
    subtitle_mode = req.subtitle_mode or 'burn'
    resolution = req.resolution or '1080p'
    tts_engine = req.tts_engine
    custom_thumb_title = req.custom_thumb_title
    watermark_enabled = req.watermark_enabled
    watermark_text = req.watermark_text
    watermark_opacity = req.watermark_opacity

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
    
    t = threading.Thread(
        target=pipeline_worker,
        args=(
            job_id,
            input_source,
            language,
            subtitle_mode,
            resolution,
            tts_engine,
            custom_thumb_title,
            watermark_enabled,
            watermark_text,
            watermark_opacity,
            req.reels_enabled,
        ),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}

@app.post("/api/batch/start")
async def start_batch_pipeline(req: BatchStartRequest):
    inputs = req.inputs
    language = req.language or 'burmese'
    subtitle_mode = req.subtitle_mode or 'burn'
    resolution = req.resolution or '1080p'
    tts_engine = req.tts_engine
    custom_thumb_title = req.custom_thumb_title
    watermark_enabled = req.watermark_enabled
    watermark_text = req.watermark_text
    watermark_opacity = req.watermark_opacity

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
    
    t = threading.Thread(
        target=batch_worker,
        args=(
            job_id,
            inputs,
            language,
            subtitle_mode,
            resolution,
            tts_engine,
            custom_thumb_title,
            watermark_enabled,
            watermark_text,
            watermark_opacity,
            req.reels_enabled,
        ),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}

@app.post("/api/stop")
@app.post("/api/cancel")
@app.post("/api/cancel/{job_id}")
async def stop_pipeline(job_id: Optional[str] = None):
    """Force-stop any currently running single or batch pipeline job."""
    stopped_count = 0
    os.environ["CURRENT_JOB_CANCELLED"] = "1"
    
    with jobs_lock:
        target_jids = [job_id] if (job_id and job_id in jobs) else [jid for jid, j in jobs.items() if j.get("status") == "running"]
        for jid in target_jids:
            if jid in jobs:
                jobs[jid]["status"] = "cancelled"
                jobs[jid]["phase"] = "Stopped by user"
                stopped_count += 1
                try:
                    from brain.sqlite_store import update_job
                    update_job(jid, status="cancelled", phase="Stopped by user")
                except Exception:
                    pass
                print(f"\n🛑 [STOP] Force-stop signal received! Cancelled job {jid}.")

    # Terminate any spawned ffmpeg / yt-dlp child subprocesses if lingering
    try:
        import subprocess, sys
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe", "/T"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "ffprobe.exe", "/T"], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", "ffmpeg"], capture_output=True)
            subprocess.run(["pkill", "-f", "ffprobe"], capture_output=True)
    except Exception:
        pass

    return {"success": True, "stopped_count": stopped_count, "message": "Pipeline force-stopped successfully."}

@app.get("/api/config/branding")
async def get_branding_config():
    c = cfg.load_config()
    return {"watermark": c.get("watermark", {})}

@app.post("/api/config/branding")
async def save_branding_config(req: BrandingConfigRequest):
    c = cfg.load_config()
    if "watermark" not in c:
        c["watermark"] = {}
    c["watermark"]["enabled"] = req.watermark_enabled
    c["watermark"]["text"] = req.watermark_text
    c["watermark"]["opacity"] = req.watermark_opacity
    c["watermark"]["margin"] = req.watermark_margin
    c["watermark"]["font_size"] = req.watermark_font_size
    cfg.save_config(c)
    return {"status": "ok", "watermark": c["watermark"]}

@app.get("/api/stream/{job_id}")
async def stream_job_logs(job_id: str, request: Request):
    """Server-Sent Events (SSE) stream for zero-latency live logs and progress updates."""
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        import re
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        sub_item = (q, loop)
        if job_id not in thread_stdout.subscribers:
            thread_stdout.subscribers[job_id] = []
        thread_stdout.subscribers[job_id].append(sub_item)

        try:
            with jobs_lock:
                job = jobs.get(job_id, {})
                buf = job.get('buffer') or thread_stdout.buffers.get(job_id)
                initial_content = buf.getvalue() if buf else ""

            if initial_content:
                lines = [l for l in initial_content.split('\n') if l.strip()]
                for l in lines[-30:]:
                    yield {"event": "log", "data": json.dumps({"line": l})}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=1.5)
                    lines = chunk.replace('\r', '\n').split('\n')
                    for l in lines:
                        if l.strip():
                            current_phase = "Running..."
                            batch_status = None
                            if '--- [Phase' in l or '--- [DONE]' in l:
                                current_phase = l.strip().strip('-').strip()
                            elif '[DONE]' in l:
                                current_phase = 'Done'
                            elif 'Downloading:' in l or 'Downloading video' in l:
                                current_phase = 'Downloading Video...'

                            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', l)
                            if m: batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"

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
                    # Cloudflare keepalive ping to prevent proxy/tunnel dropping the connection
                    yield {"comment": "ping"}

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
            subs = thread_stdout.subscribers.get(job_id, [])
            if sub_item in subs:
                subs.remove(sub_item)
            if not subs:
                thread_stdout.subscribers.pop(job_id, None)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.get("/api/status/{job_id}")
async def status_endpoint(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[job_id]
        
    buffer = job.get('buffer') or thread_stdout.buffers.get(job_id)
    log_lines = []
    current_phase = job.get('phase', 'Starting...')
    batch_status = None
    phase_timings = {}
    
    if buffer:
        content = buffer.getvalue()
        lines = [line for line in content.split('\n') if line.strip()]
        log_lines = lines[-35:]

        import re
        for line in reversed(lines):
            if '--- [Phase' in line or '--- [DONE]' in line:
                current_phase = line.strip().strip('-').strip()
                break
            if '[DONE]' in line:
                current_phase = 'Done'
                break
            if 'Downloading:' in line or 'Downloading video' in line:
                current_phase = 'Downloading Video...'
                break

        for line in reversed(lines):
            m = re.search(r'\[(\d+)/(\d+)\] Processing:\s*(.*)', line)
            if m:
                batch_status = f"Queue: {m.group(1)} of {m.group(2)} ({m.group(3)})"
                break
            m2 = re.search(r'\[(\d+)/(\d+)\] Downloading:', line)
            if m2 and not batch_status:
                batch_status = f"Downloading: {m2.group(1)} of {m2.group(2)}"
                break

        # Extract live phase completion durations
        for line in lines:
            if '[⏱️ TIMING]' in line:
                tm = re.search(r'\[⏱️ TIMING\] (Phase [^f]+) finished in ([\d\.]+)s', line)
                if tm:
                    phase_timings[tm.group(1).strip()] = float(tm.group(2))

    created_at = job.get("created_at")
    elapsed_sec = round(time.time() - created_at, 1) if created_at else None
                
    return {
        "status": job["status"],
        "phase": current_phase,
        "batch_status": batch_status,
        "elapsed_sec": elapsed_sec,
        "phase_timings": phase_timings,
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
    import urllib.error
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

@app.get("/api/keys")
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
        # Permanent Google Drive Sync for Colab
        drive_out = "/content/drive/MyDrive/MovieRecapOutputs"
        if os.path.exists(drive_out):
            try:
                import shutil
                shutil.copy2("config.json", os.path.join(drive_out, "config.json"))
                for db_name in ["movie_metadata.db", "database.db"]:
                    for src_path in [os.path.join("outputs", db_name), db_name]:
                        if os.path.exists(src_path):
                            shutil.copy2(src_path, os.path.join(drive_out, db_name))
                print("[*] WebUI: Permanently synced config.json and database to Google Drive!")
            except Exception:
                pass

        return {"success": True, "keys_count": len(cleaned_keys)}
    except Exception as e:
        print(f"[ERROR] Failed to save API keys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn, argparse
    parser = argparse.ArgumentParser(description="AI Movie Recap Web UI Server")
    parser.add_argument("--host", type=str, default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    args, _ = parser.parse_known_args()

    default_host = "0.0.0.0" if ("COLAB_GPU" in os.environ or "KAGGLE_KERNEL_RUN_TYPE" in os.environ or "COLAB_RELEASE_TAG" in os.environ) else "127.0.0.1"
    host = args.host or os.getenv("HOST", default_host)
    port = args.port or int(os.getenv("PORT", 5000))
    uvicorn.run(app, host=host, port=port, log_level='info')
