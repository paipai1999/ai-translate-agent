import os
import sys
import io
import time
import json
import datetime
from copy import deepcopy
from brain.memory import MovieState
from brain import config
from brain.sqlite_store import save_movie_state
from agents.video_agent import VideoAgent
from agents.audio_agent import AudioAgent
from agents.writer_agent import WriterAgent
from agents.seo_agent import SEOAgent
from agents.voice_agent import VoiceAgent
from agents.video_merger_agent import VideoMergerAgent
from agents.thumbnail_agent import ThumbnailAgent
from agents.qa_agent import QAAgent
import contextvars

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Phase Constants for Checkpoint Resume
# ─────────────────────────────────────────────────────────────────────────────
PHASE_1_ANALYSIS = "phase_1_video_analysis"
PHASE_2_AUDIO    = "phase_2_audio_stt"
PHASE_3_SCENES   = "phase_3_scene_detection"
PHASE_4_SCRIPT   = "phase_4_script_seo_thumbnail"
PHASE_5_VOICE    = "phase_5_voice_generation"
PHASE_6_MERGE    = "phase_6_video_merge"
PHASE_7_QA       = "phase_7_qa"

# Force UTF-8 output on Windows to prevent emoji/Unicode encode errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

class _PipelineLogWriter:
    """Tee logger that writes to console and appends to the movie's pipeline.log with timestamps."""
    def __init__(self, log_file_path: str, stream):
        self.log_file_path = log_file_path
        self.stream = stream
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    def write(self, text: str):
        self.stream.write(text)
        try:
            self.stream.flush()
        except Exception:
            pass
        if text.strip():
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    for line in text.splitlines():
                        if line.strip():
                            f.write(f"[{ts}] {line}\n")
                    f.flush()
            except Exception:
                pass

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.stream, "isatty", lambda: False)()

    def fileno(self):
        if hasattr(self.stream, "fileno"):
            return self.stream.fileno()
        raise io.UnsupportedOperation("fileno")

    def __getattr__(self, name):
        return getattr(self.stream, name)


class MasterAgent:
    def __init__(
        self,
        movie_path: str,
        language: str = None,
        subtitle_mode: str = "burn",
        resolution: str = "1080p",
        tts_engine: str = None,
        custom_thumb_title: str = None,
        watermark_enabled: bool = None,
        watermark_text: str = None,
        watermark_opacity: float = None,
        tts_voice: str = None,
        video_format: str = None,
        subtitle_style: str = None,
        thumbnail_intro: bool = None,
        source_language: str = "auto",
        resume: bool = True,
    ):
        self.movie_path = movie_path
        self.resume = bool(resume)
        movie_name = os.path.splitext(os.path.basename(movie_path))[0]
        cfg = config.load_config()

        self.subtitle_mode = str(subtitle_mode or "burn").lower()
        self.subtitle_style = str(subtitle_style or os.getenv("SUBTITLE_STYLE") or cfg.get("subtitle_overlay", {}).get("style_preset", "box_black")).lower()
        self.resolution = str(resolution or "1080p").lower()

        fmt_candidate = str(video_format or os.getenv("VIDEO_FORMAT") or cfg.get("pipeline", {}).get("video_format", "both")).lower()
        if fmt_candidate in ["16:9", "landscape", "youtube", "horizontal"]:
            self.video_format = "16:9"
        elif fmt_candidate in ["9:16", "reels", "portrait", "vertical", "tiktok", "shorts"]:
            self.video_format = "9:16"
        else:
            self.video_format = "both"

        self.state = MovieState(movie_name=movie_name)
        self.state.movie_path = movie_path
        self.state.subtitle_mode = self.subtitle_mode
        self.state.subtitle_style_preset = self.subtitle_style
        self.state.resolution = self.resolution
        self.state.video_format = self.video_format
        self.state.source_language = str(source_language or "auto").lower().strip()
        if thumbnail_intro is not None:
            self.state.thumbnail_intro_enabled = bool(thumbnail_intro)
        else:
            self.state.thumbnail_intro_enabled = cfg.get("thumbnail_intro", {}).get("enabled", False)
        self.custom_thumb_title = custom_thumb_title
        if custom_thumb_title:
            self.state.custom_thumb_title = custom_thumb_title.strip()
        if watermark_enabled is not None or watermark_text or watermark_opacity is not None:
            self.state.watermark_override = {
                "enabled": watermark_enabled if watermark_enabled is not None else True,
                "text": watermark_text,
                "opacity": watermark_opacity,
            }

        # Read config values for agents
        whisper_model  = cfg["pipeline"]["whisper_model"]
        output_dir     = cfg["paths"]["output_dir"]

        # Checkpoint Resume: restore existing state, completed phases, and artifacts
        state_file = os.path.join(output_dir, self.state.project_dir, "state.json")
        ckpt_file = os.path.join(output_dir, self.state.project_dir, "checkpoint.json")

        if self.resume and os.path.exists(state_file):
            try:
                prev_state = MovieState.load_from_json(state_file)
                self.state.completed_phases = getattr(prev_state, "completed_phases", []) or []
                self.state.phase_checkpoints = getattr(prev_state, "phase_checkpoints", {}) or {}
                self.state.speaker_profiles = getattr(prev_state, "speaker_profiles", {}) or {}
                self.state.subtitle_detection = prev_state.subtitle_detection

                if getattr(prev_state, "duration_sec", 0) > 0:
                    self.state.duration_sec = prev_state.duration_sec
                if getattr(prev_state, "video_duration", 0) > 0:
                    self.state.video_duration = prev_state.video_duration
                if getattr(prev_state, "resolution", None):
                    self.state.resolution = prev_state.resolution
                if getattr(prev_state, "transcript", None) and len(prev_state.transcript) > 0:
                    self.state.transcript = prev_state.transcript
                if getattr(prev_state, "timeline", None) and isinstance(prev_state.timeline, list) and len(prev_state.timeline) > 0:
                    self.state.timeline = prev_state.timeline
                if getattr(prev_state, "audio_path", None) and os.path.exists(prev_state.audio_path):
                    self.state.audio_path = prev_state.audio_path
                if getattr(prev_state, "generated_script", None) and len(prev_state.generated_script) > 0:
                    self.state.generated_script = prev_state.generated_script
                if getattr(prev_state, "seo_metadata", None):
                    self.state.seo_metadata = prev_state.seo_metadata
                if getattr(prev_state, "custom_thumb_title", None):
                    self.state.custom_thumb_title = prev_state.custom_thumb_title
                if getattr(prev_state, "thumbnail_path", None) and os.path.exists(prev_state.thumbnail_path):
                    self.state.thumbnail_path = prev_state.thumbnail_path
                if getattr(prev_state, "phase_durations", None):
                    self.state.phase_durations = prev_state.phase_durations

                # Check checkpoint.json to ensure any completed phases are synchronized
                if os.path.exists(ckpt_file):
                    try:
                        with open(ckpt_file, "r", encoding="utf-8") as cf:
                            cdata = json.load(cf)
                        for ph in cdata.get("completed_phases", []):
                            if ph not in self.state.completed_phases:
                                self.state.completed_phases.append(ph)
                    except Exception:
                        pass

                print(f"[*] MasterAgent: Checkpoint Resume loaded. Completed phases: {self.state.completed_phases}")
            except Exception as e:
                print(f"[WARN] MasterAgent: Failed to restore state for resume: {e}")
        elif not self.resume:
            print("[*] MasterAgent: Fresh run requested (--fresh). Bypassing checkpoints.")

        # Determine active language and corresponding TTS voice
        self.language  = language or cfg["pipeline"].get("language", "burmese")
        self.state.language = self.language
        is_burmese     = self.language.lower() in ["burmese", "mm", "myanmar"]
        self.tts_engine = tts_engine or os.getenv("TTS_ENGINE") or cfg.get("voice", {}).get("engine", "edge_tts")

        if tts_voice:
            self.tts_voice = tts_voice
        elif is_burmese:
            self.tts_voice = (
                cfg["voice"].get("myanmar_voice")
                or cfg["voice"].get("tts_voice_mm")
                or "my-MM-ThihaNeural"
            )
        else:
            self.tts_voice = (
                cfg["voice"].get("english_voice")
                or cfg["voice"].get("tts_voice_en")
                or "en-US-GuyNeural"
            )

        self.whisper_model          = whisper_model
        self.tts_enabled            = cfg["voice"]["enabled"]
        self.subtitle_blur_override = None
        self.output_dir             = output_dir

        # Instantiate all agents
        self.video_agent     = VideoAgent(movie_path=self.movie_path)
        self.audio_agent     = AudioAgent(movie_path=self.movie_path)
        self.writer_agent    = WriterAgent(language=self.language)
        self.seo_agent       = SEOAgent(language=self.language)
        self.voice_agent     = VoiceAgent(
            voice=self.tts_voice,
            output_dir=output_dir,
            tts_engine=self.tts_engine,
        )
        self.video_merger    = VideoMergerAgent(
            output_dir=output_dir,
            subtitle_blur_override=self.subtitle_blur_override,
            subtitle_mode=self.subtitle_mode,
            resolution=self.resolution,
        )
        self.thumbnail_agent = ThumbnailAgent()
        self.qa_agent        = QAAgent(
            output_dir=output_dir,
            auto_rewrite_threshold=cfg.get("qa", {}).get("auto_rewrite_threshold", 6),
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Formats seconds into readable HH:MM:SS or MM:SS format."""
        s = int(round(seconds))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _validate_artifacts(self, phase_id: str) -> bool:
        """Deterministically validates whether on-disk artifacts for a phase actually exist and are non-corrupt."""
        proj_dir = os.path.join(self.output_dir, self.state.project_dir)

        if phase_id == PHASE_1_ANALYSIS:
            return bool((getattr(self.state, "duration_sec", 0) > 0 or getattr(self.state, "video_duration", 0) > 0) and getattr(self.state, "resolution", None))

        elif phase_id == PHASE_2_AUDIO:
            has_transcript = bool(getattr(self.state, "transcript", None) and len(self.state.transcript) > 0)
            audio_f = getattr(self.state, "audio_path", "")
            has_audio = bool(audio_f and os.path.exists(audio_f) and os.path.getsize(audio_f) > 1000)
            return has_transcript and has_audio

        elif phase_id == PHASE_3_SCENES:
            return bool(getattr(self.state, "timeline", None) and len(self.state.timeline) > 0)

        elif phase_id == PHASE_4_SCRIPT:
            has_script = bool(getattr(self.state, "generated_script", None) and len(self.state.generated_script) > 0)
            thumb_p = getattr(self.state, "thumbnail_path", "") or os.path.join(proj_dir, "thumbnail.jpg")
            has_thumb = os.path.exists(thumb_p) and os.path.getsize(thumb_p) > 1000
            has_seo = bool(getattr(self.state, "seo_metadata", None))
            return has_script and (has_thumb or has_seo)

        elif phase_id == PHASE_5_VOICE:
            if not self.tts_enabled:
                return True
            vo_dir = os.path.join(proj_dir, "voiceover")
            if not os.path.exists(vo_dir):
                return False
            n_script = len(getattr(self.state, "generated_script", []) or [])
            if n_script == 0:
                return False
            mp3s = [f for f in os.listdir(vo_dir) if f.startswith("scene_") and f.endswith(".mp3") and os.path.getsize(os.path.join(vo_dir, f)) > 1000]
            return len(mp3s) >= n_script

        elif phase_id == PHASE_6_MERGE:
            final_mp4 = os.path.join(proj_dir, "final_recap.mp4")
            has_16_9 = os.path.exists(final_mp4) and os.path.getsize(final_mp4) > 50000
            if self.video_format == "9:16":
                reels_mp4 = os.path.join(proj_dir, "final_reels.mp4")
                return os.path.exists(reels_mp4) and os.path.getsize(reels_mp4) > 50000
            elif self.video_format == "both":
                reels_mp4 = os.path.join(proj_dir, "final_reels.mp4")
                has_reels = os.path.exists(reels_mp4) and os.path.getsize(reels_mp4) > 50000
                return has_16_9 and has_reels
            return has_16_9

        elif phase_id == PHASE_7_QA:
            return bool(getattr(self.state, "qa_report", None) or not config.load_config().get("qa", {}).get("enabled", False))

        return False

    def _should_run_phase(self, phase_id: str) -> bool:
        """Checks whether a phase needs execution or can be safely resumed/skipped."""
        if not self.resume:
            return True
        if self.state.is_phase_completed(phase_id):
            if self._validate_artifacts(phase_id):
                print(f"⏩ [RESUME]: Phase '{phase_id}' verified with valid on-disk artifacts — skipping execution.")
                return False
            else:
                print(f"⚠️ [RESUME]: Phase '{phase_id}' was marked complete in state, but disk artifacts are missing/incomplete — re-running.")
                return True
        return True

    def save_checkpoint(self, phase_id: str, phase_label: str):
        """Saves an atomic checkpoint.json and updates state.json for the completed phase."""
        self.state.mark_phase_completed(phase_id)
        self.save_state()
        ckpt_dir = os.path.join(self.output_dir, self.state.project_dir)
        os.makedirs(ckpt_dir, exist_ok=True)
        ckpt_path = os.path.join(ckpt_dir, "checkpoint.json")
        ckpt_data = {
            "movie_name": self.state.movie_name,
            "project_dir": self.state.project_dir,
            "last_completed_phase": phase_id,
            "phase_label": phase_label,
            "completed_phases": self.state.completed_phases,
            "phase_checkpoints": self.state.phase_checkpoints,
            "timestamp": datetime.datetime.now().isoformat(),
            "duration_sec": getattr(self.state, "duration_sec", 0.0),
            "script_blocks_count": len(self.state.generated_script or []),
            "speaker_profiles": self.state.speaker_profiles,
        }
        try:
            tmp_ckpt = ckpt_path + ".tmp"
            with open(tmp_ckpt, "w", encoding="utf-8") as f:
                json.dump(ckpt_data, f, indent=2, ensure_ascii=False)
            if os.path.exists(ckpt_path):
                os.replace(tmp_ckpt, ckpt_path)
            else:
                os.rename(tmp_ckpt, ckpt_path)
        except Exception as e:
            print(f"[WARN] Failed to write checkpoint.json: {e}")

    def run_pipeline(self):
        total_start = time.time()
        self.state.start_time = datetime.datetime.now().isoformat()
        
        # Setup real-time process log file
        log_dir = os.path.join(self.output_dir, self.state.project_dir)
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "pipeline.log")

        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        pipe_logger = _PipelineLogWriter(log_path, orig_stdout)
        sys.stdout = pipe_logger
        sys.stderr = pipe_logger

        try:
            import torch
            from agents.video_merger_agent import detect_hardware_encoder
            enc = detect_hardware_encoder()
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                hw_str = f"🚀 Dedicated GPU: {gpu_name} ({vram_gb:.1f} GB VRAM) [Encoder: {enc['label']}]"
            else:
                hw_str = f"💻 CPU Multi-Core [Encoder: {enc['label']}]"

            print(f"\n{'='*60}")
            print(f"[MOVIE RECAP AI] End-to-End Autonomous Pipeline")
            print(f"[INPUT] {self.movie_path}")
            print(f"[HARDWARE] {hw_str}")
            print(f"[CONFIG] Lang: {self.language.upper()} | Subtitles: {self.subtitle_mode.upper()} | Res: {self.resolution} | Voice: {self.tts_voice} | Engine: {self.tts_engine.upper()} | Resume: {self.resume}")
            print(f"[LOG FILE] {log_path}")
            print(f"{'='*60}")

            # Phase 1: Foundation
            if self._should_run_phase(PHASE_1_ANALYSIS):
                p1_t0 = time.time()
                self._phase("Phase 1: Video & Metadata Analysis", progress=10)
                self.state = self.video_agent.analyze_metadata(self.state)
                self.state.phase_durations["Phase 1: Video Analysis"] = round(time.time() - p1_t0, 2)
                print(f"[⏱️ TIMING] Phase 1 finished in {self.state.phase_durations['Phase 1: Video Analysis']}s")
                self.save_checkpoint(PHASE_1_ANALYSIS, "Phase 1: Video & Metadata Analysis")
            else:
                print(f"[*] Phase 1: Video & Metadata Analysis skipped (reusing cached metadata).")

            # Phase 2 & 3: Audio STT and Scene Detection (Parallel)
            run_p2 = self._should_run_phase(PHASE_2_AUDIO)
            run_p3 = self._should_run_phase(PHASE_3_SCENES)

            if run_p2 or run_p3:
                p23_t0 = time.time()
                self._phase("Phase 2 & 3: Audio STT and Scene Detection", progress=25)
                temp_audio_dir = os.path.join("temp", self.state.project_dir, "audio")
                
                import concurrent.futures
                
                def run_audio_pipeline(state):
                    if not run_p2:
                        print(f"[*] MasterAgent: Reusing cached transcript ({len(getattr(state, 'transcript', []) or [])} segments)...")
                        return state
                    state = self.audio_agent.extract_audio(state, temp_audio_dir)
                    if getattr(state, "transcript", None) and len(state.transcript) > 0:
                        print(f"[*] MasterAgent: Reusing cached transcript ({len(state.transcript)} segments)...")
                        return state
                    print("[*] MasterAgent: Running Whisper Transcription...")
                    state = self.audio_agent.transcribe_audio(state, self.whisper_model)
                    if not state.transcript:
                        print("[WARN] MasterAgent: No transcript available.")
                    state = self.audio_agent.correct_transcript(state)
                    return state
                    
                def run_scene_pipeline(state):
                    if not run_p3:
                        print(f"[*] MasterAgent: Reusing cached scene detection ({len(getattr(state, 'timeline', []) or [])} scenes)...")
                        return state
                    if getattr(state, "timeline", None) and isinstance(state.timeline, list) and len(state.timeline) > 0:
                        print(f"[*] MasterAgent: Reusing cached scene detection ({len(state.timeline)} scenes)...")
                        return state
                    cfg_data = config.load_config()
                    scene_cfg = cfg_data.get("pipeline", {}).get("scene_detection", False)
                    skip_scenes = os.environ.get("SKIP_SCENES", "").lower() in ("1", "true", "yes") or not scene_cfg
                    if skip_scenes:
                        print("[*] MasterAgent: Scene detection skipped (1:1 dialogue mode uses Whisper timestamps). Populating fallback macro scene.")
                        dur = getattr(state, "video_duration", 0.0) or 0.0
                        if dur <= 0.0:
                            try:
                                from moviepy import VideoFileClip
                                clip = VideoFileClip(self.movie_path)
                                dur = clip.duration
                                clip.close()
                            except Exception:
                                try:
                                    import moviepy.editor as mp
                                    clip = mp.VideoFileClip(self.movie_path)
                                    dur = clip.duration
                                    clip.close()
                                except Exception:
                                    dur = 120.0
                        from brain.memory import SceneData
                        max_dur = max(float(dur), 120.0)
                        state.timeline = [SceneData(scene_id=1, start_sec=0.0, end_sec=max_dur, start_time="00:00:00", end_time=f"{int(max_dur//60):02d}:{int(max_dur%60):02d}")]
                        return state
                    from agents.scene_agent import SceneAgent
                    scene_agent = SceneAgent()
                    return scene_agent.extract_scenes(state, self.movie_path)
                    
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    ctx_audio = contextvars.copy_context()
                    ctx_scene = contextvars.copy_context()
                    audio_future = executor.submit(ctx_audio.run, run_audio_pipeline, deepcopy(self.state))
                    scene_future = executor.submit(ctx_scene.run, run_scene_pipeline, deepcopy(self.state))
                    
                    futures = [audio_future, scene_future]
                    done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
                    
                    for f in done:
                        if f.exception() is not None:
                            print(f"[CRITICAL ERROR] MasterAgent: Phase 2/3 thread failed: {f.exception()}")
                            for pending in not_done:
                                pending.cancel()
                            self.state.current_phase = "Error"
                            self.state.progress = -1
                            self.save_state()
                            raise f.exception()
                    
                    try:
                        audio_state = audio_future.result()
                        scene_state = scene_future.result()

                        self.state = audio_state
                        self.state.timeline = scene_state.timeline
                    except Exception as e:
                        print(f"[CRITICAL ERROR] MasterAgent: Audio/Scene pipeline failed: {e}")
                        self.state.current_phase = "Error"
                        self.state.progress = -1
                        self.save_state()
                        raise e
                self.state.phase_durations["Phase 2 & 3: Audio STT and Scenes"] = round(time.time() - p23_t0, 2)
                print(f"[⏱️ TIMING] Phase 2 & 3 finished in {self.state.phase_durations['Phase 2 & 3: Audio STT and Scenes']}s")
                if run_p2:
                    self.save_checkpoint(PHASE_2_AUDIO, "Phase 2: Audio STT Transcription")
                if run_p3:
                    self.save_checkpoint(PHASE_3_SCENES, "Phase 3: Scene Detection")
            else:
                print(f"[*] Phase 2 & 3 skipped (reusing cached audio transcript & scene timeline).")

            # Phase 4: Script Writing, SEO & Thumbnail
            if self._should_run_phase(PHASE_4_SCRIPT):
                p4_t0 = time.time()
                self._phase("Phase 4: Script Writing, SEO & Thumbnail", progress=65)
                
                # 4.1 Script Writing (Needs Phase 2 & 3 outputs)
                if getattr(self.state, "generated_script", None) and len(self.state.generated_script) > 0:
                    print(f"[*] MasterAgent: Reusing cached script ({len(self.state.generated_script)} blocks)...")
                else:
                    self.state = self.writer_agent.generate_script(self.state, movie_path=self.movie_path)
                    # 4.1b Auto-Rewrite Over-length Blocks (QA Sync)
                    self.state = self.qa_agent.enforce_duration_constraints(self.state)
                    # 4.1c Pre-TTS Language Check & Natural Burmese Auto-Rewrite
                    self.state = self.qa_agent.review_and_rewrite_script(self.state)
                
                # 4.2 SEO and Thumbnail Frame Extraction (Parallel)
                def run_seo(state):
                    return self.seo_agent.generate_seo(state)
                    
                def run_thumbnail_base(state):
                    return self.thumbnail_agent.extract_base_frame(state, self.movie_path)
                    
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    ctx_seo = contextvars.copy_context()
                    ctx_thumb = contextvars.copy_context()
                    seo_future = executor.submit(ctx_seo.run, run_seo, deepcopy(self.state))
                    thumb_future = executor.submit(ctx_thumb.run, run_thumbnail_base, deepcopy(self.state))
                    
                    futures_p4 = [seo_future, thumb_future]
                    done_p4, not_done_p4 = concurrent.futures.wait(futures_p4, return_when=concurrent.futures.FIRST_EXCEPTION)
                    
                    for f in done_p4:
                        if f.exception() is not None:
                            print(f"[CRITICAL ERROR] MasterAgent: Phase 4 thread failed: {f.exception()}")
                            for pending in not_done_p4:
                                pending.cancel()
                            self.state.current_phase = "Error"
                            self.state.progress = -1
                            self.save_state()
                            raise f.exception()
                    
                    # Merge SEO state back
                    seo_state = seo_future.result()
                    self.state.seo_metadata = seo_state.seo_metadata
                    if not self.state.custom_thumb_title and getattr(seo_state, "custom_thumb_title", None):
                        self.state.custom_thumb_title = seo_state.custom_thumb_title
                    
                    temp_base_path = thumb_future.result()
                    
                # 4.3 Thumbnail Text Overlay (Depends on SEO)
                if temp_base_path:
                    self.state = self.thumbnail_agent.overlay_text(self.state, temp_base_path)
                    
                self.state.phase_durations["Phase 4: Script, SEO & Thumbnail"] = round(time.time() - p4_t0, 2)
                print(f"[⏱️ TIMING] Phase 4 finished in {self.state.phase_durations['Phase 4: Script, SEO & Thumbnail']}s")
                self.save_checkpoint(PHASE_4_SCRIPT, "Phase 4: Script Writing, SEO & Thumbnail")
            else:
                print(f"[*] Phase 4: Script Writing, SEO & Thumbnail skipped (reusing cached script & thumbnail).")

            # Phase 5: Voice Generation
            if self.tts_enabled:
                if self._should_run_phase(PHASE_5_VOICE):
                    p5_t0 = time.time()
                    self._phase("Phase 5: Text-to-Speech Voice Generation", progress=80)
                    self.state = self.voice_agent.generate_voiceover(self.state)
                    self.state.phase_durations["Phase 5: Voice Generation"] = round(time.time() - p5_t0, 2)
                    print(f"[⏱️ TIMING] Phase 5 finished in {self.state.phase_durations['Phase 5: Voice Generation']}s")
                    self.save_checkpoint(PHASE_5_VOICE, "Phase 5: Voice Generation")
                else:
                    print(f"[*] Phase 5: Voice Generation skipped (all voice clips already synthesized).")
            else:
                print("\n[*] VoiceAgent: Skipped (disabled in config.json -> voice.enabled = false)")
                self.state.phase_durations["Phase 5: Voice Generation"] = 0.0

            # Phase 6: Video Merge & Subtitle Blur Pass
            if self._should_run_phase(PHASE_6_MERGE):
                p6_t0 = time.time()
                self._phase("Phase 6: Merging Video + Voiceover + Subtitle Blur", progress=90)
                self.state = self.video_merger.merge_video(self.state, self.movie_path)
                self.state.phase_durations["Phase 6: Video Merge & Subtitles"] = round(time.time() - p6_t0, 2)
                print(f"[⏱️ TIMING] Phase 6 finished in {self.state.phase_durations['Phase 6: Video Merge & Subtitles']}s")

                # Phase 6b: 9:16 Facebook Reels / TikTok Canvas Video Export
                cfg_data = config.load_config()
                reels_cfg = cfg_data.get("reels", {})
                reels_enabled = (self.video_format in ["9:16", "both"]) and reels_cfg.get("enabled", True)
                if os.getenv("ENABLE_REELS") == "true":
                    reels_enabled = True
                elif os.getenv("DISABLE_REELS") == "true" or self.video_format == "16:9":
                    reels_enabled = False

                if reels_enabled:
                    final_video_path = getattr(self.state, "final_video_path", None) or os.path.join(self.output_dir, self.state.project_dir, "final_recap.mp4")
                    clean_vid = getattr(self.state, "clean_video_path", None)
                    src_to_use = clean_vid if (clean_vid and os.path.exists(clean_vid)) else final_video_path
                    if src_to_use and os.path.exists(src_to_use):
                        self._phase("Phase 6b: Generating 9:16 Facebook Reels Canvas Video", progress=95)
                        hook_title = (
                            self.custom_thumb_title
                            or (self.state.seo_metadata.get("title") if isinstance(self.state.seo_metadata, dict) else "")
                            or self.state.movie_name
                        )
                        if hook_title and "|" in hook_title:
                            hook_title = hook_title.split("|")[0].strip()
                        sub_timings = getattr(self.state, "subtitle_timings", None) or []
                        if not sub_timings and self.state.generated_script:
                            for block in self.state.generated_script:
                                if isinstance(block, dict):
                                    s_start = float(block.get("start_sec") or 0.0)
                                    s_end = float(block.get("end_sec") or (s_start + 3.0))
                                    txt = str(block.get("narration") or block.get("text") or "").strip()
                                    if txt:
                                        sub_timings.append((s_start, max(s_end - s_start, 0.8), txt))

                        try:
                            reels_path = self.video_merger.generate_reels_video(
                                source_video_path=src_to_use,
                                output_dir=os.path.join(self.output_dir, self.state.project_dir),
                                hook_title=hook_title,
                                subtitle_timings=sub_timings,
                                duration_sec=self.state.duration_sec,
                                subtitle_mode=self.subtitle_mode,
                                resolution=self.resolution,
                                preset=self.subtitle_style,
                                state=self.state,
                            )
                            self.state.reels_video_path = reels_path
                        except Exception as e:
                            print(f"[WARN] MasterAgent: Failed to generate Reels video: {e}")
                else:
                    print(f"[*] Phase 6b (9:16 Reels): Skipped (Video format is '{self.video_format}')")

                self.save_checkpoint(PHASE_6_MERGE, "Phase 6: Video Merge & Subtitle Pass")
            else:
                print(f"[*] Phase 6: Video Merge skipped (reusing completed final recap video).")

            # Phase 7: QA Review — Gemini checks sync accuracy & language naturalness
            if self._should_run_phase(PHASE_7_QA):
                p7_t0 = time.time()
                qa_cfg = config.load_config().get("qa", {})
                if qa_cfg.get("enabled", False):
                    final_video_path = os.path.join(self.output_dir, self.state.project_dir, "final_recap.mp4")
                    if os.path.exists(final_video_path):
                        self.state = self.qa_agent.review(
                            state=self.state,
                            original_video_path=self.movie_path,
                            recap_video_path=final_video_path,
                        )
                        self.state.phase_durations["Phase 7: QA Review"] = round(time.time() - p7_t0, 2)
                        print(f"[⏱️ TIMING] Phase 7 finished in {self.state.phase_durations['Phase 7: QA Review']}s")
                        self.save_checkpoint(PHASE_7_QA, "Phase 7: QA Review")
                    else:
                        print("[!] QA: final_recap.mp4 not found — skipping QA phase.")
                        self.state.phase_durations["Phase 7: QA Review"] = 0.0
                else:
                    print("[*] QA Phase: Disabled (set qa.enabled=true in config.json to enable)")
                    self.state.phase_durations["Phase 7: QA Review"] = 0.0
            else:
                print("[*] Phase 7: QA Review skipped.")

            # Calculate total duration
            total_elapsed = round(time.time() - total_start, 2)
            self.state.total_duration_sec = total_elapsed
            self.state.total_duration_formatted = self._format_duration(total_elapsed)
            self.state.end_time = datetime.datetime.now().isoformat()

            # Done
            self.state.progress = 100
            self.state.current_phase = "Done"
            self.save_state()

            print(f"\n{'='*60}")
            print(f"🎉 [DONE] Pipeline Complete in {self.state.total_duration_formatted} ({total_elapsed}s)!")
            print(f"{'='*60}")
            print(f"⏱️  PHASE DURATION BREAKDOWN:")
            for phase_name, dur in self.state.phase_durations.items():
                print(f"   • {phase_name:<42} : {dur:>7.2f}s ({self._format_duration(dur)})")
            print(f"   {'-'*56}")
            print(f"   🌟 TOTAL DURATION                          : {total_elapsed:>7.2f}s ({self.state.total_duration_formatted})")
            print(f"\n📦 OUTPUT DIRECTORY: outputs/{self.state.project_dir}/")
            if self.video_format in ["16:9", "both"]:
                print(f"   ├─ final_recap.mp4         (16:9 YouTube Video)")
            if getattr(self.state, "reels_video_path", None) and os.path.exists(self.state.reels_video_path):
                print(f"   ├─ final_reels.mp4         (9:16 Facebook Reels Canvas Video)")
            print(f"   ├─ thumbnail.jpg           (High-CTR Thumbnail)")
            print(f"   ├─ final_recap_script.txt  (Narration Script + SEO)")
            print(f"   ├─ seo_metadata.json       (Title/Tags/Hashtags)")
            print(f"   ├─ pipeline.log            (Complete Process Log)")
            print(f"   ├─ state.json              (Full State Metadata)")
            print(f"   └─ voiceover/              (Audio Clips per Scene)")
            print(f"{'='*60}\n")

            # Auto Cleanup of intermediate temp files if enabled
            config_data = config.load_config()
            if config_data.get("paths", {}).get("clean_temp_after_merge", True):
                self._cleanup_temp_files()

            # Select preferred output video for media player auto-launch
            reels_file = getattr(self.state, "reels_video_path", None)
            final_16_9 = os.path.join(self.output_dir, self.state.project_dir, "final_recap.mp4")
            
            if self.video_format == "9:16" and reels_file and os.path.exists(reels_file):
                preferred_open_video = reels_file
            elif os.path.exists(final_16_9):
                preferred_open_video = final_16_9
            elif reels_file and os.path.exists(reels_file):
                preferred_open_video = reels_file
            else:
                preferred_open_video = None

            if preferred_open_video and os.name == 'nt':
                print(f"\n[VIDEO READY] Auto-opening video in your media player: {os.path.basename(preferred_open_video)}")
                try:
                    os.startfile(os.path.abspath(preferred_open_video))
                except Exception as e:
                    print(f"[!] Could not auto-open video: {e}")
                    output_folder = os.path.join(self.output_dir, self.state.project_dir)
                    try:
                        os.startfile(os.path.abspath(output_folder))
                    except Exception:
                        pass

        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def _phase(self, label: str, progress: int = 0):
        if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
            print(f"\n🛑 [STOP] MasterAgent: Pipeline force-stopped by user at {label}.")
            raise InterruptedError(f"Pipeline force-stopped by user at {label}.")
        print(f"\n--- [{label}] ---")
        self.state.current_phase = label
        if progress > 0:
            self.state.progress = progress
        self.save_state()

    def save_state(self):
        output_dir = os.path.join(self.output_dir, self.state.project_dir)
        os.makedirs(output_dir, exist_ok=True)
        state_file = os.path.join(output_dir, "state.json")
        self.state.save_to_json(state_file)
        save_movie_state(self.state, output_dir=self.output_dir)

    def _cleanup_temp_files(self):
        """Safely clean up intermediate temp files to free disk space (recursive)."""
        try:
            temp_dir = os.path.abspath("temp")
            if os.path.exists(temp_dir):
                cleaned_count = 0
                cleaned_bytes = 0
                # Walk all subdirectories recursively (fixes disk-leak bug where
                # Demucs vocals.wav / extracted audio in temp/<project>/audio/ were never removed)
                for root, dirs, files in os.walk(temp_dir, topdown=False):
                    for item in files:
                        if item.endswith((".wav", ".mp3", ".tmp", ".part", ".ass")) or item.startswith("temp_"):
                            item_path = os.path.join(root, item)
                            try:
                                size = os.path.getsize(item_path)
                                os.remove(item_path)
                                cleaned_count += 1
                                cleaned_bytes += size
                            except Exception:
                                pass
                    # Remove empty subdirectories after cleaning
                    try:
                        if root != temp_dir and not os.listdir(root):
                            os.rmdir(root)
                    except Exception:
                        pass
                if cleaned_count > 0:
                    mb = cleaned_bytes / (1024 * 1024)
                    print(f"[*] Disk Optimizer: Cleaned up {cleaned_count} temp files ({mb:.1f} MB freed).")
        except Exception as e:
            print(f"[!] Disk Optimizer notice: {e}")
