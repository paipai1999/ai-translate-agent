import os
from brain.memory import MovieState, TranscriptSegment

class AudioAgent:
    def __init__(self, movie_path: str):
        self.movie_path = movie_path

    def extract_audio(self, state: MovieState, output_dir: str) -> MovieState:
        """Extracts audio from video file into a standalone WAV file using MoviePy or FFmpeg fallback."""
        print(f"[*] AudioAgent: Extracting audio from {self.movie_path}...")
        os.makedirs(output_dir, exist_ok=True)
        audio_filename = f"{state.movie_name}.wav"
        audio_path = os.path.join(output_dir, audio_filename)

        # If already extracted, skip
        if os.path.exists(audio_path):
            print(f"[*] AudioAgent: Audio already exists, reusing -> {audio_path}")
            state.audio_path = audio_path
            return state

        # Try MoviePy first (v1.x and v2.x compatible)
        extracted = False
        try:
            try:
                from moviepy.editor import VideoFileClip
            except ImportError:
                from moviepy import VideoFileClip

            video = VideoFileClip(self.movie_path)
            if video.audio is not None:
                video.audio.write_audiofile(audio_path, logger=None)
                state.audio_path = audio_path
                extracted = True
                print(f"[*] AudioAgent: Audio extracted via MoviePy -> {audio_path}")
            else:
                print("[!] AudioAgent: No audio stream detected in the video.")
            video.close()
        except Exception as e:
            print(f"[!] AudioAgent: MoviePy failed ({e}). Trying FFmpeg fallback...")

        # FFmpeg fallback
        if not extracted:
            result = self._ffmpeg_extract_audio(audio_path)
            if result:
                state.audio_path = result
                print(f"[*] AudioAgent: Audio extracted via FFmpeg -> {audio_path}")
            else:
                print("[!] AudioAgent: Both extraction methods failed. Transcription will be skipped.")

        if getattr(state, 'audio_path', None):
            state.audio_path = self.separate_vocals(state.audio_path, output_dir)

        return state

    def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        """Separates vocals from background music using Demucs to improve Whisper accuracy."""
        import subprocess, shutil, sys
        
        demucs_cmd = None
        if shutil.which("demucs"):
            demucs_cmd = ["demucs"]
        else:
            # Fallback to python module execution (for virtualenv without global PATH)
            try:
                r = subprocess.run([sys.executable, "-m", "demucs", "--help"], capture_output=True, timeout=15)
                if r.returncode == 0:
                    demucs_cmd = [sys.executable, "-m", "demucs"]
            except Exception:
                demucs_cmd = None

        if not demucs_cmd:
            print("[!] AudioAgent: 'demucs' not found in PATH or environment. Skipping vocal separation.")
            return audio_path
            
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                print(f"[*] AudioAgent (Demucs): 🚀 Separating vocals via NVIDIA GPU ({gpu_name}) [CUDA Active]...")
                device_flag = ["-d", "cuda"]
            else:
                print("[*] AudioAgent (Demucs): 💻 Separating vocals via CPU Multi-Core...")
                device_flag = ["-d", "cpu"]
            cmd = [*demucs_cmd, "--two-stems=vocals", "-n", "htdemucs", *device_flag, audio_path, "-o", output_dir]
            subprocess.run(cmd, check=True, capture_output=True)
            
            base_name = os.path.splitext(os.path.basename(audio_path))[0]
            vocals_path = os.path.join(output_dir, "htdemucs", base_name, "vocals.wav")
            if os.path.exists(vocals_path):
                print(f"[*] AudioAgent: Vocal separation successful -> {vocals_path}")
                return vocals_path
        except Exception as e:
            print(f"[!] AudioAgent: Demucs vocal separation failed: {e}. Falling back to original audio.")
            
        return audio_path

    def _ffmpeg_extract_audio(self, audio_path: str):
        """Direct FFmpeg fallback — works even if MoviePy is not configured correctly."""
        import subprocess, shutil
        ffmpeg_bin = shutil.which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE")
        if not ffmpeg_bin:
            try:
                from imageio_ffmpeg import get_ffmpeg_exe
                ffmpeg_bin = get_ffmpeg_exe()
            except Exception:
                ffmpeg_bin = None
        if not ffmpeg_bin:
            print("[!] AudioAgent: ffmpeg not found in PATH.")
            return None
        try:
            cmd = [
                ffmpeg_bin, "-y", "-i", self.movie_path,
                "-vn",                      # no video
                "-acodec", "pcm_s16le",     # WAV format
                "-ar", "44100",             # 44.1kHz — required for high quality Demucs separation
                "-ac", "2",                 # Stereo — required for Demucs
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0 and os.path.exists(audio_path):
                return audio_path
            print(f"[!] AudioAgent FFmpeg stderr: {result.stderr[-300:]}")
            return None
        except Exception as e:
            print(f"[!] AudioAgent FFmpeg exception: {e}")
            return None

    def transcribe_audio(self, state: MovieState, model_size: str = "small") -> MovieState:
        """
        Transcribes audio via faster-whisper running in a child subprocess.
        This isolates any native-library crash (e.g. ctranslate2 on Python 3.14)
        so the main pipeline always continues even if Whisper fails.
        """
        if not state.audio_path or not os.path.exists(state.audio_path):
            print("[!] AudioAgent: No audio file found for transcription. Skipping STT.")
            return state

        print(f"[*] AudioAgent: Starting local Speech-to-Text (Whisper model: {model_size})...")

        import subprocess, sys, json, tempfile

        # Find Python interpreter with faster-whisper available
        def _find_python312():
            # 1. First test if the current active Python interpreter has faster_whisper
            try:
                r = subprocess.run([sys.executable, "-c", "import faster_whisper"], capture_output=True, timeout=10)
                if r.returncode == 0:
                    return sys.executable
            except Exception:
                pass

            # 2. If current interpreter is Python 3.10-3.12, use it
            if sys.version_info[:2] in [(3, 10), (3, 11), (3, 12)]:
                return sys.executable

            # 3. If running on incompatible Python (e.g. 3.13+), look for Python 3.12
            try:
                r = subprocess.run(["py", "-3.12", "-c", "import sys; print(sys.executable)"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and os.path.exists(r.stdout.strip()):
                    return r.stdout.strip()
            except Exception:
                pass

            for candidate in [
                r"C:\Python312\python.exe",
                r"C:\Users\\" + os.environ.get("USERNAME", "") + r"\AppData\Local\Programs\Python\Python312\python.exe",
            ]:
                if os.path.exists(candidate):
                    return candidate
            return sys.executable

        python_exe = _find_python312()
        print(f"[*] AudioAgent: Using Python interpreter -> {python_exe}")
        if sys.version_info[:2] < (3, 10):
            print("[WARN] AudioAgent: Python 3.10+ recommended for best Whisper compatibility.")

        # Write a self-contained transcription helper script to a temp file
        helper_script = f"""
import os, sys, json
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from faster_whisper import WhisperModel

audio_path  = sys.argv[1]
model_size  = sys.argv[2]
output_path = sys.argv[3]
movie_name  = sys.argv[4]

try:
    import torch
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        device = "cuda"
        compute_type = "float16"
        print(f"[*] AudioAgent (Faster-Whisper): 🚀 Active Hardware -> NVIDIA GPU ({{gpu_name}}) [CUDA float16 Tensor Cores]")
    else:
        device = "cpu"
        compute_type = "int8"
        print("[*] AudioAgent (Faster-Whisper): 💻 Active Hardware -> CPU Multi-Core [INT8 Quantized Mode]")
except Exception:
    device = "cpu"
    compute_type = "int8"
    print("[*] AudioAgent (Faster-Whisper): 💻 Active Hardware -> CPU Fallback Mode")

num_threads = min(8, os.cpu_count() or 4)
try:
    model = WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=num_threads)
except Exception:
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=num_threads)

segments, info = model.transcribe(
    audio_path,
    beam_size=1,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
    initial_prompt=f"This is a dialogue transcript for the movie {{movie_name}}."
)

results = []
for seg in segments:
    results.append({{"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}})

with open(output_path, "w", encoding="utf-8") as f:
    json.dump({{"language": info.language, "segments": results}}, f, ensure_ascii=False)
print(f"[Whisper] Transcribed {{len(results)}} segments in language: {{info.language}}")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(helper_script)
            helper_path = tmp.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as out_tmp:
            result_path = out_tmp.name

        try:
            proc = subprocess.run(
                [python_exe, helper_path, state.audio_path, model_size, result_path, state.movie_name],
                capture_output=True, text=True, timeout=600
            )
            if proc.stdout:
                print(f"[*] AudioAgent: {proc.stdout.strip()}")

            if proc.returncode == 0 and os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                transcript_list = [
                    TranscriptSegment(start=s["start"], end=s["end"], text=s["text"])
                    for s in data.get("segments", [])
                ]
                state.transcript = transcript_list
                print(f"[*] AudioAgent completed: Transcribed {len(transcript_list)} dialogue segments "
                      f"(lang: {data.get('language','?')}).")
            else:
                err = (proc.stderr or "")[-400:]
                print(f"[WARN] AudioAgent: Whisper subprocess failed (exit {proc.returncode}): {err}. Proceeding with Native Video Mode.")
                state.transcript = []
        except subprocess.TimeoutExpired:
            print("[WARN] AudioAgent: Whisper timed out. Proceeding smoothly with Native Video Mode.")
            state.transcript = []
        except Exception as e:
            print(f"[WARN] AudioAgent: Unexpected error during transcription: {e}. Proceeding with Native Video Mode.")
            state.transcript = []
        finally:
            for f in [helper_path, result_path]:
                try:
                    os.unlink(f)
                except Exception:
                    pass

        return state

    def correct_transcript(self, state: MovieState) -> MovieState:
        """Uses LLM to correct spelling and character names in the transcript."""
        if not state.transcript:
            return state

        print("[*] AudioAgent: Running LLM error correction on transcript...")
        try:
            from brain.gemini_client import call_gemini
            from brain import config as cfg
            config_data = cfg.load_config()
            gemini_cfg = config_data.get("gemini", {})
            if not gemini_cfg.get("enabled", False):
                return state
                
            api_key = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                return state
                
            # Convert transcript to text block (limit length to prevent context overflow)
            full_text = "\n".join([f"[{s.start}-{s.end}] {s.text}" for s in state.transcript])
            if len(full_text) > 40000:
                print("[!] AudioAgent: Transcript too long for correction, taking first 40000 chars.")
                full_text = full_text[:40000]
                
            sys_prompt = "You are an AI assistant that corrects movie transcripts."
            user_prompt = (
                f"Correct obvious spelling errors and ensure character names are spelled correctly for the movie '{state.movie_name}'. "
                f"Return ONLY valid JSON as an array of objects. Each object must have keys "
                f"'start' (number), 'end' (number), and 'text' (string). "
                f"Keep the original timestamps intact and do not add markdown blocks.\n\n"
                f"{full_text}"
            )
            
            raw, _ = call_gemini(sys_prompt, user_prompt, api_key, model=gemini_cfg.get("model", "gemini-3.5-flash-lite"), temperature=0.1)

            import re, json
            corrected_segments = []
            cleaned = raw.strip().strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    parsed = parsed.get("segments", [])
                if isinstance(parsed, list):
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        try:
                            corrected_segments.append(
                                TranscriptSegment(
                                    start=float(item["start"]),
                                    end=float(item["end"]),
                                    text=str(item["text"]).strip(),
                                )
                            )
                        except Exception:
                            continue
            except Exception:
                for line in raw.split("\n"):
                    m = re.match(r'\[([\d.]+)-([\d.]+)\]\s*(.*)', line.strip())
                    if m:
                        corrected_segments.append(TranscriptSegment(start=float(m.group(1)), end=float(m.group(2)), text=m.group(3).strip()))

            if corrected_segments:
                state.transcript = corrected_segments
                print(f"[*] AudioAgent: Transcript corrected successfully ({len(corrected_segments)} segments).")
        except Exception as e:
            print(f"[!] AudioAgent: Transcript correction failed: {e}")
            
        return state
