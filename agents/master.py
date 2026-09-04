import os
import sys
import io
import time
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
    ):
        self.movie_path = movie_path
        movie_name = os.path.splitext(os.path.basename(movie_path))[0]
        cfg = config.load_config()

        self.subtitle_mode = str(subtitle_mode or "burn").lower()
        self.resolution = str(resolution or "1080p").lower()

        self.state = MovieState(movie_name=movie_name)
        self.state.movie_path = movie_path
        self.state.subtitle_mode = self.subtitle_mode
        self.state.resolution = self.resolution
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

        # Preserve existing subtitle detection cache if the same movie already ran before
        state_file = os.path.join(output_dir, self.state.project_dir, "state.json")
        if os.path.exists(state_file):
            try:
                prev_state = MovieState.load_from_json(state_file)
                self.state.subtitle_detection = prev_state.subtitle_detection
            except Exception:
                pass

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
            print(f"[CONFIG] Lang: {self.language.upper()} | Subtitles: {self.subtitle_mode.upper()} | Res: {self.resolution} | Voice: {self.tts_voice} | Engine: {self.tts_engine.upper()}")
            print(f"[LOG FILE] {log_path}")
            print(f"{'='*60}")

            # Phase 1: Foundation
            p1_t0 = time.time()
            self._phase("Phase 1: Video & Metadata Analysis", progress=10)
            self.state = self.video_agent.analyze_metadata(self.state)
            self.state.phase_durations["Phase 1: Video Analysis"] = round(time.time() - p1_t0, 2)
            print(f"[⏱️ TIMING] Phase 1 finished in {self.state.phase_durations['Phase 1: Video Analysis']}s")
            self.save_state()

            # Phase 2 & 3: Audio STT and Scene Detection (Parallel)
            p23_t0 = time.time()
            self._phase("Phase 2 & 3: Audio STT and Scene Detection", progress=25)
            temp_audio_dir = os.path.join("temp", self.state.project_dir, "audio")
            
            import concurrent.futures
            
            def run_audio_pipeline(state):
                state = self.audio_agent.extract_audio(state, temp_audio_dir)
                print("[*] MasterAgent: Running Whisper Transcription...")
                state = self.audio_agent.transcribe_audio(state, self.whisper_model)
                if not state.transcript:
                    print("[WARN] MasterAgent: No transcript available.")
                state = self.audio_agent.correct_transcript(state)
                return state
                
            def run_scene_pipeline(state):
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
            self.save_state()

            # Phase 4: Script Writing, SEO & Thumbnail
            p4_t0 = time.time()
            self._phase("Phase 4: Script Writing, SEO & Thumbnail", progress=65)
            
            # 4.1 Script Writing (Needs Phase 2 & 3 outputs)
            self.state = self.writer_agent.generate_script(self.state)
            
            # 4.1b Auto-Rewrite Over-length Blocks (QA Sync)
            self.state = self.qa_agent.enforce_duration_constraints(self.state)
            
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
            self.save_state()

            # Phase 5: Voice Generation
            p5_t0 = time.time()
            if self.tts_enabled:
                self._phase("Phase 5: Text-to-Speech Voice Generation", progress=80)
                self.state = self.voice_agent.generate_voiceover(self.state)
                self.state.phase_durations["Phase 5: Voice Generation"] = round(time.time() - p5_t0, 2)
                print(f"[⏱️ TIMING] Phase 5 finished in {self.state.phase_durations['Phase 5: Voice Generation']}s")
                self.save_state()
            else:
                print("\n[*] VoiceAgent: Skipped (disabled in config.json -> voice.enabled = false)")
                self.state.phase_durations["Phase 5: Voice Generation"] = 0.0

            # Phase 6: Video Merge & Subtitle Blur Pass
            p6_t0 = time.time()
            self._phase("Phase 6: Merging Video + Voiceover + Subtitle Blur", progress=90)
            self.state = self.video_merger.merge_video(self.state, self.movie_path)
            self.state.phase_durations["Phase 6: Video Merge & Subtitles"] = round(time.time() - p6_t0, 2)
            print(f"[⏱️ TIMING] Phase 6 finished in {self.state.phase_durations['Phase 6: Video Merge & Subtitles']}s")

            # Optional Phase 6b: 9:16 Facebook Reels / TikTok Canvas Video Export
            cfg_data = config.load_config()
            reels_cfg = cfg_data.get("reels", {})
            reels_enabled = (os.getenv("ENABLE_REELS") == "true") or reels_cfg.get("enabled", True)
            if os.getenv("DISABLE_REELS") == "true":
                reels_enabled = False

            if reels_enabled:
                final_video_path = os.path.join(self.output_dir, self.state.project_dir, "final_recap.mp4")
                if os.path.exists(final_video_path):
                    self._phase("Phase 6b: Generating 9:16 Facebook Reels Canvas Video", progress=95)
                    hook_title = (
                        self.custom_thumb_title
                        or (self.state.seo_metadata.get("title") if isinstance(self.state.seo_metadata, dict) else "")
                        or self.state.movie_name
                    )
                    sub_timings = getattr(self.state, "subtitle_timings", None) or []
                    if not sub_timings and self.state.generated_script:
                        for block in self.state.generated_script:
                            if isinstance(block, dict):
                                s_start = float(block.get("start_sec") or 0.0)
                                s_end = float(block.get("end_sec") or (s_start + 3.0))
                                txt = str(block.get("narration") or block.get("text") or "").strip()
                                if txt:
                                    sub_timings.append((s_start, max(s_end - s_start, 0.8), txt))
                    
                    clean_vid = getattr(self.state, "clean_video_path", None)
                    src_to_use = clean_vid if (clean_vid and os.path.exists(clean_vid)) else final_video_path

                    try:
                        reels_path = self.video_merger.generate_reels_video(
                            source_video_path=src_to_use,
                            output_dir=os.path.join(self.output_dir, self.state.project_dir),
                            hook_title=hook_title,
                            subtitle_timings=sub_timings,
                            duration_sec=self.state.duration_sec,
                            subtitle_mode=self.subtitle_mode,
                            resolution=self.resolution,
                        )
                        self.state.reels_video_path = reels_path
                    except Exception as e:
                        print(f"[WARN] MasterAgent: Failed to generate Reels video: {e}")

            self.save_state()

            # Phase 7: QA Review — Gemini checks sync accuracy & language naturalness
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
                    self.save_state()
                else:
                    print("[!] QA: final_recap.mp4 not found — skipping QA phase.")
                    self.state.phase_durations["Phase 7: QA Review"] = 0.0
            else:
                print("[*] QA Phase: Disabled (set qa.enabled=true in config.json to enable)")
                self.state.phase_durations["Phase 7: QA Review"] = 0.0

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
            import brain.config as cfg
            config_data = cfg.load_config()
            if config_data.get("paths", {}).get("clean_temp_after_merge", True):
                self._cleanup_temp_files()

            final_video_path = os.path.join(self.output_dir, self.state.project_dir, "final_recap.mp4")
            if os.path.exists(final_video_path) and os.name == 'nt':
                print(f"\n[VIDEO READY] Auto-opening final recap video in your media player...")
                try:
                    os.startfile(os.path.abspath(final_video_path))
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
        """Safely clean up intermediate temp files to free disk space."""
        try:
            temp_dir = os.path.abspath("temp")
            if os.path.exists(temp_dir):
                cleaned_count = 0
                for item in os.listdir(temp_dir):
                    if item.endswith((".wav", ".mp3", ".tmp", ".part", ".ass")) or item.startswith("temp_"):
                        item_path = os.path.join(temp_dir, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                cleaned_count += 1
                        except Exception:
                            pass
                if cleaned_count > 0:
                    print(f"[*] Disk Optimizer: Cleaned up {cleaned_count} intermediate files from temp/.")
        except Exception as e:
            print(f"[!] Disk Optimizer notice: {e}")
