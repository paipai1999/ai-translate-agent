import os
import sys
from brain.memory import MovieState
import brain.config as cfg

# Force UTF-8 output on Windows to prevent emoji/Unicode encode errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

_DETECTED_ENCODER = None

def _get_ffmpeg_bin() -> str:
    import shutil
    ffmpeg_bin = os.environ.get("IMAGEIO_FFMPEG_EXE") or shutil.which("ffmpeg")
    if not ffmpeg_bin or not os.path.exists(ffmpeg_bin):
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            ffmpeg_bin = get_ffmpeg_exe()
            os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_bin
        except Exception:
            ffmpeg_bin = "ffmpeg"
    return ffmpeg_bin

def detect_hardware_encoder() -> dict:
    """Detects available hardware video encoders (NVIDIA NVENC, Intel QSV, AMD AMF) or CPU libx264."""
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None:
        return _DETECTED_ENCODER

    import subprocess
    ffmpeg_bin = _get_ffmpeg_bin()

    candidates = [
        {"codec": "h264_nvenc", "label": "NVIDIA GPU (NVENC)", "type": "gpu", "preset": "p4"},
        {"codec": "h264_qsv", "label": "Intel QuickSync (QSV)", "type": "gpu", "preset": "faster"},
        {"codec": "h264_amf", "label": "AMD Radeon (AMF)", "type": "gpu", "preset": "speed"},
        {"codec": "libx264", "label": "CPU Multi-Core (libx264)", "type": "cpu", "preset": "faster"},
    ]

    chosen = candidates[-1]
    for c in candidates[:-1]:
        cmd = [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1", "-c:v", c["codec"], "-f", "null", "-"]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            if res.returncode == 0:
                chosen = c
                break
        except Exception:
            continue

    _DETECTED_ENCODER = chosen
    return chosen

class VideoMergerAgent:
    def __init__(self, output_dir: str = "outputs", subtitle_blur_override: bool = None):
        self.output_dir = output_dir
        self.subtitle_blur_override = subtitle_blur_override

    def merge_video(self, state, movie_path: str):
        # Lazy import moviepy so the module can still be loaded even if moviepy is missing
        try:
            from moviepy.editor import VideoFileClip, AudioFileClip
        except ImportError:
            try:
                from moviepy import VideoFileClip, AudioFileClip
            except ImportError:
                print("[ERROR] VideoMerger: moviepy is not installed. Run: pip install moviepy")
                return state

        output_dir = os.path.join(self.output_dir, state.project_dir)
        os.makedirs(output_dir, exist_ok=True)
        final_output = os.path.join(output_dir, "final_recap.mp4")

        config_data = cfg.load_config()
        copyright_cfg   = config_data.get("copyright_protection", {})
        copyright_enabled = copyright_cfg.get("enabled", True)
        blur_cfg        = config_data.get("subtitle_blur", {})
        blur_enabled    = blur_cfg.get("enabled", True)
        if self.subtitle_blur_override:
            blur_enabled = True
        blur_region_pct = float(blur_cfg.get("region_height_pct", 0.18))   # bottom 18%
        blur_strength   = int(blur_cfg.get("blur_strength", 18))            # boxblur radius
        color_cfg       = config_data.get("color_grading", {})
        color_enabled   = color_cfg.get("enabled", True)
        cg_brightness   = float(color_cfg.get("brightness", 0.03))
        cg_contrast     = float(color_cfg.get("contrast", 1.02))
        cg_saturation   = float(color_cfg.get("saturation", 1.08))

        print(f"[*] VideoMerger: Starting video merge process (Copyright-Safe Mode: {copyright_enabled})...")

        # --- LOAD AUDIO FIRST TO CALCULATE DURATION ---
        audio_clips = []
        script_blocks = getattr(state, "generated_script", []) or []
        script_blocks_with_audio = []
        
        voiceover_dir = os.path.join(output_dir, "voiceover")
        if os.path.exists(voiceover_dir):
            # Sort script blocks chronologically first to ensure correct scene flow
            try:
                script_blocks.sort(key=lambda x: float(x.get("start_sec") or 0.0) if isinstance(x, dict) else 0.0)
            except Exception as e:
                print(f"[WARN] Failed to sort script blocks: {e}")

            # BUG-H1 Fix: Use enumerate instead of list.index(b) to avoid O(n²) and
            # wrong index on duplicate-content dict blocks.
            for sorted_idx, b in enumerate(script_blocks):
                if not isinstance(b, dict):
                    continue
                # VoiceAgent saves audio files using enumerate index (0,1,2...) of generated_script
                # generated_script is already sorted chronologically before VoiceAgent runs
                # So we MUST use the same chronological enumerate index here to match filenames
                fname = f"scene_{(sorted_idx+1):04d}.mp3"
                fpath = os.path.join(voiceover_dir, fname)
                if not os.path.exists(fpath):
                    for root, _, files in os.walk(voiceover_dir):
                        if fname in files:
                            fpath = os.path.join(root, fname)
                            break
                if os.path.exists(fpath):
                    try:
                        audio_clips.append(AudioFileClip(fpath))
                        script_blocks_with_audio.append(b)
                    except Exception as e:
                        print(f"[WARN] VideoMerger: Failed to load voiceover {fname}: {e}")
                else:
                    print(f"[WARN] VideoMerger: Missing audio file {fname} for script block.")

                    
        # Update script_blocks to only include those that have successful audio
        script_blocks = script_blocks_with_audio

        try:
            # Load original video stream
            main_video = VideoFileClip(movie_path)
            print(f"[*] VideoMerger: Loaded original video stream untouched ({main_video.duration:.1f}s, size: {main_video.w}x{main_video.h}).")

            # --- REPLACE ORIGINAL AUDIO WITH NO_VOCALS (SFX ONLY) IF AVAILABLE ---
            has_no_vocals = False
            base_name = os.path.splitext(os.path.basename(movie_path))[0]
            no_vocals_path = os.path.join("temp", state.project_dir, "audio", "htdemucs", base_name, "no_vocals.wav")
            if os.path.exists(no_vocals_path):
                has_no_vocals = True
                print(f"[*] VideoMerger: Found Demucs no_vocals.wav (SFX Only). Replacing original audio to remove dialogue...")
                try:
                    sfx_only_audio = AudioFileClip(no_vocals_path)
                    if hasattr(main_video, "with_audio"):
                        main_video = main_video.with_audio(sfx_only_audio)
                    else:
                        main_video = main_video.set_audio(sfx_only_audio)
                except Exception as e:
                    print(f"[WARN] VideoMerger: Failed to load no_vocals.wav: {e}")
            else:
                print(f"[WARN] VideoMerger: no_vocals.wav not found at {no_vocals_path}. Will use original mixed audio.")

            # H.264 requires width and height to be divisible by 2 (even numbers)
            w, h = main_video.size
            new_w = w if w % 2 == 0 else w - 1
            new_h = h if h % 2 == 0 else h - 1
            if (new_w, new_h) != (w, h):
                print(f"[*] VideoMerger: Fixing odd video dimensions ({w}x{h} -> {new_w}x{new_h}) for H.264 encoder compatibility...")
                try:
                    try:
                        # MoviePy v2
                        from moviepy.video.fx.Crop import Crop
                        main_video = main_video.with_effects([Crop(x1=0, y1=0, x2=new_w, y2=new_h)])
                    except ImportError:
                        # MoviePy v1
                        import moviepy.video.fx.all as vfx
                        main_video = main_video.fx(vfx.crop, x1=0, y1=0, x2=new_w, y2=new_h)
                except Exception as e:
                    print(f"[WARN] Failed to crop odd dimensions: {e}")

            # 1. Video remains UNTOUCHED
            # We strictly keep the source video duration and speed identical to original
            # No MultiplySpeed applied.
            if not audio_clips:
                print("[WARN] VideoMerger: No audio found.")

            if copyright_enabled:
                print("[*] VideoMerger (Copyright-Safe): Applying Fair Use anti-copyright visual transformations...")
                effects = []

                # Default to True for maximum safety against Content ID
                mirror_enabled = copyright_cfg.get("mirror_video", True)
                if mirror_enabled:
                    print("[*] -> Applying horizontal mirror/flip effect for max anti-copyright protection...")
                    try:
                        from moviepy import vfx
                        if hasattr(vfx, "MirrorX"):
                            effects.append(vfx.MirrorX())
                        elif hasattr(vfx, "mirror_x"):
                            main_video = main_video.fx(vfx.mirror_x)
                    except Exception as e:
                        print(f"[WARN] Failed to apply mirror effect: {e}")

                resize_factor = float(copyright_cfg.get("resize_factor", 1.02))
                if resize_factor != 1.0:
                    print(f"[*] -> Applying subtle scale/resize ({resize_factor}x) to modify pixel boundaries...")
                    try:
                        from moviepy import vfx
                        if hasattr(vfx, "Resize"):
                            effects.append(vfx.Resize(resize_factor))
                        elif hasattr(vfx, "resize"):
                            main_video = main_video.fx(vfx.resize, resize_factor)
                    except Exception as e:
                        print(f"[WARN] Failed to apply resize: {e}")
                
                # Apply elegant cinematic transitions (fade-in & fade-out)
                print("[*] -> Applying cinematic FadeIn and FadeOut transitions (1 second)...")
                try:
                    from moviepy import vfx
                    if hasattr(vfx, "FadeIn") and hasattr(vfx, "FadeOut"):
                        effects.append(vfx.FadeIn(1.0))
                        effects.append(vfx.FadeOut(1.0))
                    elif hasattr(vfx, "fadein") and hasattr(vfx, "fadeout"):
                        main_video = main_video.fx(vfx.fadein, 1.0).fx(vfx.fadeout, 1.0)
                except Exception as e:
                    print(f"[WARN] Failed to apply fade transitions: {e}")

                if effects and hasattr(main_video, "with_effects"):
                    try:
                        main_video = main_video.with_effects(effects)
                    except Exception as e:
                        print(f"[WARN] Failed to apply with_effects: {e}")
        except Exception as e:
            print(f"[ERROR] VideoMerger: Failed to load main video: {e}")
            return state
            
        subtitle_timings = []

        try:
            if audio_clips:
                total_speech = sum(c.duration for c in audio_clips)
                video_dur    = main_video.duration
                n_blocks     = len(audio_clips)
                print(
                    f"[*] VideoMerger: PASS 2 -> Laying out {n_blocks} audio blocks across synced {video_dur:.1f}s video..."
                )

                positioned_clips = []
                total_orig_sec = state.timeline[-1].end_sec if (state.timeline and len(state.timeline) > 0) else 120.0

                # ─────────────────────────────────────────────────────────────────
                # RECAP MODE (Fast-Paced Cinematic Recap)
                # Instead of keeping the original video untouched, we extract the action 
                # scenes based on Gemini's timestamps, stretch/squeeze the video to match 
                # the TTS audio length perfectly, and concatenate them back-to-back.
                # ─────────────────────────────────────────────────────────────────
                
                has_exact_timestamps = (
                    len(script_blocks) > 0
                    and isinstance(script_blocks[0], dict)
                    and "start_sec" in script_blocks[0]
                )

                print("[*] VideoMerger: CONTINUOUS MODE - Original video will play smoothly without jump cuts.")
                
                # Build positions based on exact timestamps if available, otherwise proportional
                starts = []
                if has_exact_timestamps:
                    print("[*] VideoMerger: Using EXACT Gemini timestamps for perfect audio sync.")
                    for b in script_blocks:
                        s = float(b.get("start_sec", 0.0))
                        # Prevent Gemini hallucination: ensure starts are within video bounds
                        if s > video_dur - 1.0:
                            s = max(0.0, video_dur - 2.0)
                        starts.append(s)
                else:
                    print("[WARN] No exact timestamps. Falling back to simple proportional dubbing mode.")
                    starts = [0.2 + (idx / max(n_blocks - 1, 1)) * (video_dur - 0.4) for idx in range(n_blocks)]

                # --- SLOW MOTION CHECK ---
                # Check if total audio length exceeds video length
                sim_curr_t = 0.0
                for idx, c in enumerate(audio_clips):
                    place_time = max(sim_curr_t, starts[idx])
                    sim_curr_t = place_time + c.duration + 0.05
                
                if video_dur > 0 and sim_curr_t > video_dur:
                    factor = max(0.2, video_dur / sim_curr_t)
                    print(f"[*] VideoMerger: Audio total ({sim_curr_t:.1f}s) exceeds video ({video_dur:.1f}s).")
                    print(f"[*] VideoMerger: Applying SLOW MOTION (factor {factor:.2f}x) to fit audio perfectly!")
                    try:
                        try:
                            # moviepy v2
                            from moviepy.video.fx.MultiplySpeed import MultiplySpeed
                            main_video = main_video.with_effects([MultiplySpeed(factor)])
                        except ImportError:
                            # moviepy v1
                            import moviepy.video.fx.all as vfx
                            main_video = main_video.fx(vfx.speedx, factor)
                            
                        video_dur = main_video.duration
                        starts = [s / factor for s in starts]
                    except Exception as e:
                        print(f"[WARN] VideoMerger: Failed to apply slow motion: {e}")

                # ─────────────────────────────────────────────────────────────────
                # HYBRID APPROACH: STEP 3 — Region-Based Placement with Sequential Fallback
                #
                # Instead of pinning TTS to an EXACT timestamp (which fails when Gemini
                # hallucinates), we treat each Gemini timestamp as the CENTER of a
                # "preferred region window". The clip is placed at the BEST available
                # position inside that window — or falls back to sequential placement
                # if the window has already been passed by a previous clip.
                #
                # Rules:
                #   1. Preferred position = start_sec from script
                #   2. If preferred position < curr_t (already passed), use curr_t (sequential)
                #   3. If TTS is longer than the remaining gap to next block, speed it up (max 1.35x)
                #   4. Never place audio beyond video_dur
                # ─────────────────────────────────────────────────────────────────
                curr_t = 0.0
                for idx, c in enumerate(audio_clips):
                    preferred_start = starts[idx]

                    # Rule 2: If preferred window already passed, use sequential position
                    if preferred_start < curr_t:
                        preferred_start = curr_t
                        if idx > 0:
                            print(f"[*] VideoMerger [Hybrid]: Block {idx+1} preferred window passed — using sequential placement at {curr_t:.2f}s.")

                    # Rule 3: Calculate available gap to next block and speed up if needed
                    if idx < n_blocks - 1:
                        available_gap = max(starts[idx+1], curr_t + c.duration) - preferred_start
                        # Use actual next preferred start if it's ahead
                        next_preferred = starts[idx+1]
                        if next_preferred > preferred_start:
                            available_gap = next_preferred - preferred_start
                    else:
                        available_gap = video_dur - preferred_start

                    if available_gap > 0.5 and c.duration > available_gap:
                        speed_factor = min(c.duration / available_gap, 1.35)
                        print(f"[*] VideoMerger [Hybrid]: Block {idx+1} audio ({c.duration:.1f}s) > gap ({available_gap:.1f}s). Speeding up {speed_factor:.2f}x.")
                        try:
                            from moviepy import vfx
                            if hasattr(vfx, "MultiplySpeed") and hasattr(c, "with_effects"):
                                c = c.with_effects([vfx.MultiplySpeed(speed_factor)])
                            else:
                                import moviepy.audio.fx.all as afx
                                c = afx.speedx(c, speed_factor)
                        except Exception as e:
                            print(f"[WARN] VideoMerger: Speed-up failed for block {idx+1}: {e}")

                    # Rule 4: Clamp to video bounds
                    place_time = min(preferred_start, max(0.0, video_dur - c.duration - 0.05))
                    place_time = max(place_time, curr_t)  # Never go backwards

                    if hasattr(c, "with_start"):
                        positioned_clips.append(c.with_start(place_time))
                    else:
                        positioned_clips.append(c.set_start(place_time))

                    curr_t = place_time + c.duration + 0.05

                    # Store timings for subtitles
                    if idx < len(script_blocks):
                        b = script_blocks[idx]
                        narration_text = b.get("narration", "").strip() if isinstance(b, dict) else ""
                        subtitle_timings.append((place_time, c.duration, narration_text))

                    
                sfx_cfg = config_data.get("sfx", {})
                
                # Regardless of no_vocals, the BGM/SFX in these mini-dramas is extremely loud.
                # Lowering the volume to 15% (0.15) to ensure Burmese TTS is perfectly clear.
                sfx_vol = 0.15
                print(f"[*] VideoMerger: Lowering background audio volume to {sfx_vol*100}% to prevent drowning out TTS.")
                
                try:
                    from moviepy import CompositeAudioClip
                except ImportError:
                    from moviepy.editor import CompositeAudioClip

                try:
                    # Lower original audio (which is now SFX only if no_vocals exists) volume
                    orig_audio = main_video.audio
                    if orig_audio is not None:
                        try:
                            # MoviePy v2
                            from moviepy.audio.fx.MultiplyVolume import MultiplyVolume
                            orig_audio = orig_audio.with_effects([MultiplyVolume(sfx_vol)])
                        except ImportError:
                            try:
                                # MoviePy v1
                                import moviepy.audio.fx.all as afx
                                orig_audio = afx.volumex(orig_audio, sfx_vol)
                            except Exception:
                                if hasattr(orig_audio, 'volumex'):
                                    orig_audio = orig_audio.volumex(sfx_vol)

                    # Mix original audio with positioned voiceover clips only if vocals were removed
                    if orig_audio is not None and has_no_vocals:
                        final_audio = CompositeAudioClip([orig_audio] + positioned_clips)
                    else:
                        final_audio = CompositeAudioClip(positioned_clips)
                        
                    if hasattr(main_video, "with_audio"):
                        main_video = main_video.with_audio(final_audio)
                    else:
                        main_video = main_video.set_audio(final_audio)
                except Exception as e:
                    print(f"[ERROR] Failed to composite audio: {e}")


                # --- SUBTITLE OVERLAY ---
                subtitle_clips = []
                if subtitle_timings:
                    print(f"[*] VideoMerger: Gathered {len(subtitle_timings)} subtitle timings. Will apply via FFmpeg ASS pass.")

                final_clip = main_video
            else:
                print("[WARN] VideoMerger: No voiceover audio files found. Exporting original video.")
                final_clip = main_video

            # --- WATERMARK OVERLAY ---
            wm_cfg = config_data.get("watermark", {})
            wm_override = getattr(state, "watermark_override", {}) or {}
            wm_enabled = wm_override.get("enabled", wm_cfg.get("enabled", False))
            if wm_enabled:
                wm_text = wm_override.get("text") or wm_cfg.get("text", "PAI AI Movie Translate")
                wm_opacity = float(wm_override.get("opacity") if wm_override.get("opacity") is not None else wm_cfg.get("opacity", 0.4))
                wm_font_size = int(wm_override.get("font_size") or wm_cfg.get("font_size", 40))
                wm_margin = int(wm_override.get("margin") or wm_cfg.get("margin", 30))
                
                try:
                    wm_png = self._create_watermark_image(wm_text, wm_font_size, wm_opacity)
                    if os.path.exists(wm_png):
                        print(f"[*] VideoMerger: Applying Watermark '{wm_text}' (Opacity: {wm_opacity})")
                        try:
                            from moviepy import ImageClip, CompositeVideoClip
                        except ImportError:
                            from moviepy.editor import ImageClip, CompositeVideoClip
                            
                        wm_clip = ImageClip(wm_png)
                        if hasattr(wm_clip, "with_duration"):
                            wm_clip = wm_clip.with_duration(final_clip.duration)
                        else:
                            wm_clip = wm_clip.set_duration(final_clip.duration)
                            
                        x_pos = max(0, final_clip.size[0] - wm_clip.size[0] - wm_margin)
                        y_pos = wm_margin
                        
                        if hasattr(wm_clip, "with_position"):
                            wm_clip = wm_clip.with_position((x_pos, y_pos))
                        else:
                            wm_clip = wm_clip.set_position((x_pos, y_pos))
                            
                        final_clip = CompositeVideoClip([final_clip, wm_clip])
                except Exception as e:
                    print(f"[WARN] VideoMerger: Failed to apply watermark: {e}")

            # --- THUMBNAIL INTRO STITCH (3 SECONDS) ---
            # NOTE: output_dir already includes the project subdirectory path
            thumbnail_path = os.path.join(output_dir, "thumbnail.jpg")
            if os.path.exists(thumbnail_path):
                print("[*] VideoMerger: Stitching Thumbnail as a 3-second Intro...")
                try:
                    try:
                        from moviepy.editor import ImageClip, concatenate_videoclips
                    except ImportError:
                        from moviepy import ImageClip, concatenate_videoclips
                        
                    intro_clip = ImageClip(thumbnail_path)
                    if hasattr(intro_clip, "with_duration"):
                        intro_clip = intro_clip.with_duration(3.0)
                    else:
                        intro_clip = intro_clip.set_duration(3.0)
                        
                    # Match FPS
                    if hasattr(intro_clip, "with_fps"):
                         intro_clip = intro_clip.with_fps(final_clip.fps if final_clip.fps else 24)
                    else:
                         intro_clip.fps = final_clip.fps if final_clip.fps else 24
                         
                    w, h = intro_clip.size
                    new_w, new_h = final_clip.size
                    if (w, h) != (new_w, new_h):
                        try:
                            try:
                                from moviepy.video.fx.Resize import Resize
                                intro_clip = intro_clip.with_effects([Resize((new_w, new_h))])
                            except ImportError:
                                import moviepy.video.fx.all as vfx
                                intro_clip = intro_clip.fx(vfx.resize, (new_w, new_h))
                        except Exception as e:
                            print(f"[WARN] Failed to resize intro image: {e}")

                    final_clip = concatenate_videoclips([intro_clip, final_clip], method="compose")
                    
                    # CRITICAL: Shift subtitle timings by 3 seconds so Myanmar ASS subtitles stay perfectly synced!
                    if subtitle_timings:
                        subtitle_timings = [(start + 3.0, dur, txt) for (start, dur, txt) in subtitle_timings]
                except Exception as e:
                    print(f"[WARN] VideoMerger: Failed to stitch thumbnail intro: {e}")

            enc_info = detect_hardware_encoder()
            print(f"[*] VideoMerger (Hardware Acceleration): Exporting video using {enc_info['label']} [{enc_info['codec']}]...")
            try:
                final_clip.write_videofile(
                    final_output,
                    codec=enc_info["codec"],
                    audio_codec='aac',
                    preset=enc_info.get("preset", "faster"),
                    threads=4,
                    ffmpeg_params=["-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                    logger='bar'
                )
            except Exception as enc_err:
                print(f"[WARN] Hardware encoder '{enc_info['codec']}' failed: {enc_err}. Falling back to CPU libx264...")
                final_clip.write_videofile(
                    final_output,
                    codec='libx264',
                    audio_codec='aac',
                    preset='superfast',
                    threads=4,
                    ffmpeg_params=["-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                    logger='bar'
                )
            print("[OK] VideoMerger: Video merge complete! Original video untouched with cohesive story recap.")

            # ── Subtitle Blur Post-pass (FFmpeg) ────────────────────────────────
            # Blurs the bottom subtitle region in a single fast FFmpeg pass.
            # Analyzes the ORIGINAL MOVIE (not the recap) to correctly detect subtitles.
            if blur_enabled or color_enabled:
                self._blur_subtitle_region(
                    state,
                    final_output,
                    source_video_for_detection = movie_path,   # <-- Original movie to detect subtitles from
                    region_pct    = blur_region_pct    if blur_enabled  else 0.0,
                    blur_strength = blur_strength      if blur_enabled  else 0,
                    color_enabled = color_enabled,
                    brightness    = cg_brightness,
                    contrast      = cg_contrast,
                    saturation    = cg_saturation,
                )

            # ── Myanmar Subtitle Overlay Post-pass (FFmpeg drawtext) ─────────
            sub_cfg = config_data.get("subtitle_overlay", {})
            if sub_cfg.get("enabled", True) and subtitle_timings:
                self._burn_myanmar_subtitles(
                    video_path    = final_output,
                    timings       = subtitle_timings,
                    output_dir    = output_dir,
                    font_name     = (sub_cfg.get("font_name") or "Myanmar Text") if sys.platform == "win32" else "Padauk",
                    font_size     = int(sub_cfg.get("font_size", 40)),
                    bold          = bool(sub_cfg.get("bold", True)),
                    border_style  = int(sub_cfg.get("border_style", 3)),
                    outline_width = int(sub_cfg.get("outline_width", 3)),
                    margin_bottom = int(sub_cfg.get("margin_bottom", 50)),
                    max_chars     = int(sub_cfg.get("max_chars_per_line", 28)),
                )

            # Thumbnail is now stitched as a video intro, skipping cover art embedding.
                    
        except Exception as e:
            print(f"[ERROR] VideoMerger: Failed during video merge/writing: {e}")
        finally:
            # Safely close all opened clips to prevent memory leaks and FFmpeg zombie processes
            for clip_obj in [locals().get('main_video'), locals().get('sfx_only_audio'),
                             locals().get('intro_clip'), locals().get('final_clip')]:
                if clip_obj is not None:
                    try: clip_obj.close()
                    except Exception: pass
            for ac in audio_clips:
                try: ac.close()
                except Exception: pass
            # BUG-H6 Fix: Also close speed-adjusted positioned clips (orphaned from audio_clips after speed adjustment)
            for pc in locals().get('positioned_clips', []):
                try: pc.close()
                except Exception: pass

        return state

    # ─────────────────────────────────────────────────────
    # WATERMARK GENERATION (Adaptive Contrast)
    # ─────────────────────────────────────────────────────

    def _create_watermark_image(self, text: str, font_size: int, opacity: float) -> str:
        """
        Creates a transparent PNG with the watermark text and a subtle drop shadow using Pillow.
        Returns the path to the saved PNG.
        """
        from PIL import Image, ImageDraw, ImageFont
        import os
        
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, "watermark.png")
        
        try:
            font = ImageFont.truetype("arialbd.ttf", font_size) # Arial Bold
        except IOError:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()

        # Dummy draw to get text size
        dummy_img = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except AttributeError:
            text_width, text_height = draw.textsize(text, font=font)
        
        padding = 10
        img_width = text_width + (padding * 2)
        img_height = text_height + (padding * 2)
        
        img = Image.new('RGBA', (img_width, img_height), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        
        shadow_offset = (2, 2)
        shadow_color = (0, 0, 0, 200) # Soft Black Shadow
        text_color = (255, 255, 255, 255) # Pure White Text
        
        draw.text((padding + shadow_offset[0], padding + shadow_offset[1]), text, font=font, fill=shadow_color)
        draw.text((padding, padding), text, font=font, fill=text_color)
        
        if opacity < 1.0:
            alpha = img.split()[3]
            alpha = alpha.point(lambda p: p * opacity)
            img.putalpha(alpha)
            
        img.save(out_path, "PNG")
        return out_path

    # ─────────────────────────────────────────────────────
    # MYANMAR SUBTITLE OVERLAY — ASS Generation + FFmpeg Burn
    # ─────────────────────────────────────────────────────

    def _sec_to_ass_ts(self, sec: float) -> str:
        """Convert seconds to ASS timestamp format H:MM:SS.cs (centiseconds)."""
        total_cs = int(round(max(0.0, float(sec)) * 100))
        cs = total_cs % 100
        total_s = total_cs // 100
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _wrap_burmese_text(self, text: str, max_chars: int) -> str:
        """Wrap long Myanmar text into multiple lines at word boundaries (ASS uses {\\N})."""
        if len(text) <= max_chars:
            return text
        words = text.split(" ")
        lines, current = [], ""
        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = (current + " " + word).strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return "{\\N}".join(lines)

    def _write_ass(
        self,
        timings: list,
        ass_path: str,
        font_name: str    = "Myanmar Text",
        font_size: int    = 40,
        bold: bool        = True,
        border_style: int = 3,
        outline_width: int = 3,
        margin_bottom: int = 50,
        max_chars: int    = 28,
    ) -> str:
        """
        Write an ASS (Advanced SubStation Alpha) subtitle file.
        All styling is embedded — no FFmpeg force_style needed.
        ASS colour: &HAABBGGRR (alpha 00=opaque, 80=50% transparent)
        BorderStyle=1: outline+shadow  |  BorderStyle=3: opaque box background
        """
        bold_flag = "-1" if bold else "0"

        if border_style == 3:
            # Box background mode (YouTube-style): Outline=box_padding, Shadow for depth
            outline_val = 10      # box padding in px
            shadow_val  = 2       # subtle depth shadow
            back_colour = "&HB0000000"   # 70% opacity deep dark box for maximum contrast
        else:
            # Classic outline mode
            outline_val = outline_width
            shadow_val  = 2
            back_colour = "&H90000000"

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "WrapStyle: 0\n"
            "PlayResX: 1920\n"
            "PlayResY: 1080\n"
            "Collisions: Normal\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{font_name},{font_size},"
            f"&H00FFFFFF,&H000000FF,&H00000000,{back_colour},"
            f"{bold_flag},0,0,0,100,100,0,0,{border_style},{outline_val},{shadow_val},"
            f"2,10,10,{margin_bottom},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        dialogue_lines = []
        for (start_sec, duration, text) in timings:
            if not text:
                continue
            text = text.strip()

            # Split long narration into proportional chunks
            words = text.split(" ")
            chunks, line = [], ""
            for word in words:
                if len(line) + len(word) + 1 <= max_chars * 2:
                    line = (line + " " + word).strip()
                else:
                    if line:
                        chunks.append(line)
                    line = word
            if line:
                chunks.append(line)
            if not chunks:
                continue

            seg_dur = duration / len(chunks)
            for i, chunk in enumerate(chunks):
                seg_start = start_sec + i * seg_dur
                seg_end   = seg_start + seg_dur - 0.05
                # BUG-M7 Fix: Escape ASS special chars { } to prevent format code injection
                safe_chunk = chunk.replace('\\', '').replace('{', '').replace('}', '')
                ass_text  = self._wrap_burmese_text(safe_chunk, max_chars)
                ts_start  = self._sec_to_ass_ts(seg_start)
                ts_end    = self._sec_to_ass_ts(seg_end)
                dialogue_lines.append(
                    f"Dialogue: 0,{ts_start},{ts_end},Default,,0,0,0,,{ass_text}"
                )

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(dialogue_lines) + "\n")

        print(f"[*] MyanmarSubs: ASS written → {ass_path} ({len(dialogue_lines)} subtitle entries)")
        return ass_path

    def _find_myanmar_font(self) -> str:
        """Find a suitable Myanmar Unicode font path for reference/logging."""
        candidates = [
            r"assets\fonts\NotoSansMyanmar-Regular.ttf",
            r"assets/fonts/NotoSansMyanmar-Regular.ttf",
            r"C:\Windows\Fonts\mmrtext.ttf",     # Myanmar Text (Win10+)
            r"C:\Windows\Fonts\mmrtextb.ttf",
            r"C:\Windows\Fonts\NotoSansMyanmar-Regular.ttf",
            r"C:\Windows\Fonts\Padauk-Regular.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def _burn_myanmar_subtitles(
        self,
        video_path: str,
        timings: list,
        output_dir: str,
        font_name: str     = "Myanmar Text",
        font_size: int     = 40,
        bold: bool         = True,
        border_style: int  = 3,
        outline_width: int = 3,
        margin_bottom: int = 50,
        max_chars: int     = 28,
    ):
        """
        Burns Myanmar subtitles into video using FFmpeg 'ass' filter.
        Uses ASS format (all styling embedded) to avoid Windows path/space escaping issues.
        ASS file written to temp/ with a simple no-space filename.
        """
        import sys
        if sys.platform != "win32" and font_name == "Myanmar Text":
            font_name = "Padauk"
        import subprocess, shutil

        # Write ASS to temp/ with no spaces in filename — avoids FFmpeg filter parsing issues
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)
        ass_path = os.path.join(temp_dir, "myanmar_subs.ass")

        font_found = self._find_myanmar_font()
        if font_found:
            print(f"[*] MyanmarSubs: Using font → {font_found}")

        self._write_ass(timings, ass_path, font_name, font_size, bold, border_style, outline_width, margin_bottom, max_chars)

        if not os.path.exists(ass_path):
            print("[WARN] MyanmarSubs: ASS file was not created. Skipping subtitle burn.")
            return

        # -----------------------------------------------------------------------------------
        # BUG FIX: FFmpeg's filter graph escaping is notoriously brittle on Windows.
        # If the absolute path to the .ass file contains a single quote (e.g., Pai's Recap)
        # or a comma, FFmpeg will crash because `ass='D\:/path'` breaks the filter string.
        # FIX: We run ffmpeg with `cwd=temp_dir` and just pass `ass=myanmar_subs.ass` 
        # (no quotes, no spaces, no absolute paths) to bypass FFmpeg path parsing completely!
        # -----------------------------------------------------------------------------------
        ass_basename = os.path.basename(ass_path)
        abs_video_path = os.path.abspath(video_path)
        name, ext = os.path.splitext(abs_video_path)
        temp_output = f"{name}_subtitled.mp4"

        # BUG-M8 Fix: Use consistent ffmpeg lookup: imageio env var → shutil.which → fallback
        ffmpeg_bin = _get_ffmpeg_bin()
        cmd = [
            ffmpeg_bin, "-y",
            "-i", abs_video_path,
            "-vf", f"ass={ass_basename}",
            "-c:v", "libx264",
            "-preset", "superfast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            temp_output
        ]

        print(f"[*] MyanmarSubs: Burning ASS subtitles (font: {font_name}, size: {font_size}px)...")
        result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")

        if result.returncode == 0 and os.path.exists(temp_output) and os.path.getsize(temp_output) > 100_000:
            shutil.move(temp_output, video_path)
            # Also copy ASS to output dir for reference
            shutil.copy2(ass_path, os.path.join(output_dir, "myanmar_subs.ass"))
            print(f"[OK] MyanmarSubs: Subtitle burn complete! ({font_size}px '{font_name}')")
        else:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            err_tail = (result.stderr or "")[-600:]
            print(f"[WARN] MyanmarSubs: Subtitle burn failed (code={result.returncode}).")
            print(f"[WARN] FFmpeg stderr: {err_tail}")



    # ─────────────────────────────────────────────────────
    # SUBTITLE BLUR — Vision AI Auto-Detection + FFmpeg Pass
    # ─────────────────────────────────────────────────────

    def _detect_subtitle_region_with_vision(self, video_path: str, state: MovieState = None):
        """
        Uses Gemini Vision AI to analyze sample frames from the ORIGINAL SOURCE video
        and detect the EXACT vertical region (start_y_pct, height_pct) where
        hardcoded subtitles appear.
        Samples frames at Whisper dialogue timestamps to guarantee subtitle visibility.

        Returns:
            (start_y_pct, height_pct, subtitle_found)
        """
        import os, cv2, json
        from brain.gemini_client import call_gemini_vision
        import brain.config as cfg

        print(f"[*] VisionAI Subtitle Detector: Analyzing source video for subtitles: {os.path.basename(video_path)}")
        temp_dir = os.path.join("temp", "sub_detect")
        os.makedirs(temp_dir, exist_ok=True)

        default_start_y = 0.82
        default_height  = 0.18

        try:
            config_data = cfg.load_config()
            gemini_cfg = config_data.get("gemini", {})
            api_keys = gemini_cfg.get("api_keys", [])
            model = gemini_cfg.get("model", "gemini-3.5-flash-lite")

            prompt = (
                "Analyze this video frame carefully. Look at the lower half of the frame (bottom 50%). "
                "Are there any hardcoded DIALOGUE subtitles or captions? "
                "IGNORE watermarks, channel logos, or title cards at the top or middle of the screen. "
                "Respond ONLY in valid JSON with NO markdown formatting: "
                '{"has_subtitles": true, "start_y_pct": 0.75, "height_pct": 0.12} '
                "where start_y_pct (0.0=top, 1.0=bottom) is where the dialogue text STARTS, "
                "and height_pct is the vertical height of the text region. "
                "If no dialogue subtitles exist in the lower half, respond: "
                '{"has_subtitles": false, "start_y_pct": 0.82, "height_pct": 0.18}'
            )

            def get_sample_frames(pcts, stage_prefix):
                frames = []
                cap = cv2.VideoCapture(video_path)
                try:
                    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 300)
                    
                    dialogue_times = []
                    if state and getattr(state, "transcript", None):
                        for s in state.transcript[:15]:
                            t_val = getattr(s, "start", None) if hasattr(s, "start") else s.get("start") if isinstance(s, dict) else None
                            if t_val is not None and float(t_val) > 1.0:
                                dialogue_times.append(float(t_val) + 0.5)

                    if dialogue_times and stage_prefix == "s1":
                        step = max(1, len(dialogue_times) // 5)
                        for idx, sec in enumerate(dialogue_times[::step][:5]):
                            frame_idx = min(int(sec * fps), total_frames - 1)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                frame_path = os.path.join(temp_dir, f"frame_dialogue_{idx}_{int(sec)}s.jpg")
                                cv2.imwrite(frame_path, frame)
                                frames.append(frame_path)

                    if not frames:
                        for sample_pct in pcts:
                            sample_frame_idx = int(total_frames * sample_pct)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, sample_frame_idx)
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                frame_path = os.path.join(temp_dir, f"frame_{stage_prefix}_{int(sample_pct*100):03d}.jpg")
                                cv2.imwrite(frame_path, frame)
                                frames.append(frame_path)
                finally:
                    cap.release()
                return frames

            def scan_frames(sample_frames, stage_name):
                print(f"[*] VisionAI Subtitle Detector ({stage_name}): Analyzing {len(sample_frames)} frames...")
                results = []
                for i, frame_path in enumerate(sample_frames):
                    try:
                        res_text, used_model = call_gemini_vision(
                            system_prompt=(
                                "You are a precise computer vision AI. Your job is to detect ANY text, "
                                "subtitles, captions, or overlaid text in video frames. "
                                "Look at the ENTIRE frame carefully. Respond ONLY in valid JSON."
                            ),
                            user_text=prompt,
                            image_path=frame_path,
                            api_key=api_keys,
                            model=model,
                            temperature=0.05
                        )
                        clean_json = res_text.strip().strip("`").replace("json", "").strip()
                        parsed = json.loads(clean_json)
                        if isinstance(parsed, list) and len(parsed) > 0:
                            parsed = parsed[0]
                        elif not isinstance(parsed, dict):
                            parsed = {}
                            
                        results.append(parsed)
                        found = parsed.get("has_subtitles", False)
                        print(f"[*] VisionAI [{stage_name}] Frame {i+1}/{len(sample_frames)}: has_subtitles={found} "
                              f"y={parsed.get('start_y_pct', '?')} h={parsed.get('height_pct', '?')} (model: {used_model})")
                    except Exception as e:
                        print(f"[WARN] VisionAI [{stage_name}] Frame {i+1} failed: {e}")
                        continue
                return results

            # Stage 1: Scan first 50% of the video (5%, 15%, 25%, 35%, 50%)
            stage1_frames = get_sample_frames([0.05, 0.15, 0.25, 0.35, 0.50], "s1")
            if not stage1_frames:
                print("[WARN] VisionAI Subtitle Detector: Could not read any frame. Skipping blur.")
                return default_start_y, default_height, False

            detection_results = scan_frames(stage1_frames, "Stage 1 (0-50%)")
            frames_with_subs = [r for r in detection_results if r.get("has_subtitles", False)]

            # Stage 2 Fallback: If no subtitles found in first 50%, scan second half (60%, 70%, 80%, 90%)
            if not frames_with_subs:
                print("[*] VisionAI Stage 1 (0-50%) found NO subtitles. Triggering Stage 2: Scanning remaining 50-90% of video...")
                stage2_frames = get_sample_frames([0.60, 0.70, 0.80, 0.90], "s2")
                if stage2_frames:
                    stage2_results = scan_frames(stage2_frames, "Stage 2 (50-90%)")
                    detection_results.extend(stage2_results)
                    frames_with_subs = [r for r in detection_results if r.get("has_subtitles", False)]

            if not detection_results:
                print("[WARN] VisionAI: All frame analyses failed. Skipping blur.")
                return default_start_y, default_height, False

            # Filter out false positives (e.g., watermarks at the top of the screen)
            # Dialogue subtitles are almost always in the lower half (y >= 0.5)
            valid_subs = [r for r in frames_with_subs if float(r.get("start_y_pct", default_start_y)) >= 0.5]
            
            subtitle_found = len(valid_subs) > 0

            if subtitle_found:
                import statistics
                y_values = [float(r.get("start_y_pct", default_start_y)) for r in valid_subs]
                h_values = [float(r.get("height_pct", default_height)) for r in valid_subs]
                
                # Use median to ignore extreme outliers instead of average
                median_y = statistics.median(y_values)
                max_h = max(h_values)  # Use max height to ensure we cover 2-line subtitles if detected
                
                y_start  = max(0.5, median_y - 0.02)
                y_height = min(1.0 - y_start, max_h + 0.04)

                print(
                    f"[OK] VisionAI: Subtitles CONFIRMED ({len(valid_subs)}/{len(detection_results)} frames positive)! "
                    f"Region -> Y: {y_start*100:.1f}%, Height: {y_height*100:.1f}% — Will blur."
                )
                return y_start, y_height, True
            else:
                print(f"[*] VisionAI: No subtitles detected across ENTIRE video ({len(detection_results)} frames tested). Skipping blur.")
                return default_start_y, default_height, False

        except Exception as e:
            print(f"[WARN] VisionAI Subtitle Detector: Detection failed ({e}). Skipping blur to be safe.")
            return default_start_y, default_height, False
        finally:
            # Clean up temp frames
            import shutil
            if os.path.exists(temp_dir):
                try: shutil.rmtree(temp_dir)
                except Exception: pass

    def _blur_subtitle_region(
        self,
        state: MovieState,
        video_path: str,
        source_video_for_detection: str = None,
        region_pct: float = 0.18,
        blur_strength: int = 18,
        color_enabled: bool = False,
        brightness: float = 0.03,
        contrast: float = 1.02,
        saturation: float = 1.08,
    ):
        """
        Single FFmpeg post-pass that applies two copyright-protection layers:

        Layer 1 — Vision AI Powered Subtitle Blur:
          Uses Gemini Vision AI to detect exact subtitle Y-boundaries from the
          ORIGINAL SOURCE movie (not the recap), crops that exact region,
          applies boxblur, and overlays back. Skipped if AI says no subtitles.

        Layer 2 — Color Grading (eq filter):
          Applies slight brightness / contrast / saturation shift via FFmpeg.
        """
        import subprocess, shutil, os

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            try:
                from imageio_ffmpeg import get_ffmpeg_exe
                ffmpeg_bin = get_ffmpeg_exe()
            except ImportError:
                pass

        if not ffmpeg_bin:
            print("[WARN] PostProcess: ffmpeg not found. Skipping post-pass.")
            return

        do_blur  = blur_strength > 0
        do_color = color_enabled

        user_sub_mode = getattr(state, "subtitle_mode", "auto") if state is not None else "auto"
        user_sub_mode = user_sub_mode or "auto"

        if user_sub_mode == "no":
            print("[*] Subtitle Blur: Disabled by user setting ('No Subtitles'). Skipping blur pass.")
            do_blur = False

        # Run Vision AI on ORIGINAL MOVIE to get exact subtitle coordinates
        # (The recap output does NOT have subtitles — always analyze the source)
        start_y_pct, height_pct = 0.82, 0.18
        subtitle_found = False
        if do_blur:
            detect_target = source_video_for_detection if source_video_for_detection and os.path.exists(source_video_for_detection) else video_path

            if user_sub_mode == "yes":
                print("[*] Subtitle Blur: User selected 'Has Subtitles' — Forcing subtitle blur mode on.")
                y, h, found = self._detect_subtitle_region_with_vision(detect_target, state=state)
                start_y_pct = y if found else 0.82
                height_pct = h if found else 0.18
                subtitle_found = True
            else:
                cache = getattr(state, "subtitle_detection", None) if state is not None else None
                # Only reuse cache if it previously FOUND subtitles
                # If cache says no subtitles, always re-detect (Gemini may have been wrong)
                cache_valid = (
                    cache
                    and cache.get("video_path") == os.path.abspath(detect_target)
                    and cache.get("has_subtitles", False) is True  # Only trust positive cache
                )
                if cache_valid:
                    start_y_pct = float(cache.get("start_y_pct", start_y_pct))
                    height_pct = float(cache.get("height_pct", height_pct))
                    subtitle_found = True
                    print("[*] VideoMerger: Reusing cached subtitle detection (subtitles confirmed previously).")
                else:
                    if cache and not cache.get("has_subtitles", False):
                        print("[*] VideoMerger: Previous detection found no subtitles — re-running with improved detector...")
                    start_y_pct, height_pct, subtitle_found = self._detect_subtitle_region_with_vision(detect_target, state=state)
                if state is not None:
                    state.subtitle_detection = {
                        "video_path": os.path.abspath(detect_target),
                        "has_subtitles": subtitle_found,
                        "start_y_pct": start_y_pct,
                        "height_pct": height_pct,
                    }
                if not subtitle_found:
                    print("[*] PostProcess: No subtitles detected in source — skipping blur pass.")
                    do_blur = False

        if do_blur:
            start_y_pct = max(0.0, min(float(start_y_pct), 0.95))
            height_pct = max(0.02, min(float(height_pct), 1.0 - start_y_pct))

        steps = []
        if do_blur:  steps.append(f"VisionAI subtitle blur (Y-start={start_y_pct*100:.1f}%, h={height_pct*100:.1f}%, r={blur_strength})")
        if do_color: steps.append(f"color grade (b={brightness:+.2f}, c={contrast:.2f}, s={saturation:.2f}), dynamic noise, vignette")
        print(f"[*] PostProcess: Applying — {', '.join(steps)}")

        base, ext = os.path.splitext(video_path)
        tmp_path  = base + "_posttmp" + ext

        # ── Build filter_complex ─────────────────────────────────────────
        # Step 1: Fix even dimensions
        base_filter = "crop=w='trunc(iw/2)*2':h='trunc(ih/2)*2'"

        if do_blur:
            r = blur_strength
            # Guarantee even integer pixel boundaries for libx264 / yuv420p encoder
            flt = (
                f"[0:v]{base_filter},split=2[orig][sub];"
                f"[sub]crop=iw:'trunc(ih*{height_pct:.3f}/2)*2':0:'trunc(ih*{start_y_pct:.3f}/2)*2',"
                f"boxblur=luma_radius={r}:luma_power=2"
                f":chroma_radius={max(1,r//2)}:chroma_power=2[blurred];"
                f"[orig][blurred]overlay=0:'trunc(H*{start_y_pct:.3f}/2)*2'[blended]"
            )
            last_out = "[blended]"
        else:
            flt = f"[0:v]{base_filter}[blended]"
            last_out = "[blended]"

        if do_color:
            eq_str = (
                f"eq=brightness={brightness:.3f}"
                f":contrast={contrast:.3f}"
                f":saturation={saturation:.3f}"
                f",noise=alls=2:allf=t"       # Dynamic Film Grain
                f",vignette=PI/4"             # Subtle Edge Darkening
            )
            flt += f";{last_out}{eq_str}[out]"
            last_out = "[out]"

        # Map last output label
        filter_args = ["-filter_complex", flt, "-map", last_out]

        cmd = [
            _get_ffmpeg_bin(), "-y",
            "-i", video_path,
            *filter_args,
            "-map", "0:a?",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-crf", "20",
            "-movflags", "+faststart",
            "-c:a", "copy",
            tmp_path,
        ]

        # Dynamically scale timeout to allow ample time for full movies
        dur_sec = getattr(state, "duration_sec", 0.0) if state else 0.0
        if not dur_sec and state and getattr(state, "duration", None):
            try:
                parts = str(state.duration).split(":")
                if len(parts) == 3:
                    dur_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                dur_sec = 600.0
        dyn_timeout = max(1200, int((dur_sec or 600.0) * 2.5))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=dyn_timeout)
            if result.returncode == 0 and os.path.exists(tmp_path):
                os.replace(tmp_path, video_path)
                print("[OK] PostProcess: Copyright-safe post-processing complete!")
            else:
                print(f"[WARN] PostProcess: FFmpeg returned exit code {result.returncode}.")
                if result.stderr:
                    print(f"[WARN] FFmpeg stderr: {result.stderr[-400:]}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except subprocess.TimeoutExpired:
            print("[WARN] PostProcess: FFmpeg timed out. Original video kept.")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass
        except Exception as e:
            print(f"[WARN] PostProcess: {e}. Original video kept.")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass

    def generate_reels_video(
        self,
        source_video_path: str,
        output_dir: str,
        hook_title: str = "",
        subtitle_timings: list = None,
        duration_sec: float = 600.0,
    ) -> str | None:
        """
        Exports a dedicated 9:16 (1080x1920) Vertical Video for Facebook Reels, TikTok, and Shorts.
        Layout (The 'Viral Recap Frame'):
          - Top 20%: Catchy golden Burmese Hook Title.
          - Middle 55%: Uncropped, high-quality 16:9 recap video centered over blurred dynamic video background.
          - Bottom 25%: Facebook Safe Zone for Myanmar ASS subtitles, well above bottom UI controls.
        Hardware-accelerated via NVENC on Colab or QSV/libx264 on PC.
        """
        import sys, subprocess, shutil

        if not os.path.exists(source_video_path):
            print(f"[WARN] ReelsExporter: Source video not found: {source_video_path}")
            return None

        os.makedirs(output_dir, exist_ok=True)
        reels_output = os.path.join(output_dir, "final_reels.mp4")
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)

        config_data = cfg.load_config()
        reels_cfg = config_data.get("reels", {})
        if not reels_cfg.get("enabled", True):
            print("[*] ReelsExporter: Disabled in config.json -> reels.enabled = false")
            return None

        w_target = int(reels_cfg.get("width", 1080))
        h_target = int(reels_cfg.get("height", 1920))
        blur_sigma = int(reels_cfg.get("blur_sigma", 25))
        safe_margin = int(reels_cfg.get("safe_zone_margin", 160))

        font_name = "Myanmar Text" if sys.platform == "win32" else "Padauk"
        font_found = self._find_myanmar_font()
        if font_found and os.path.exists(font_found):
            base_font = os.path.splitext(os.path.basename(font_found))[0]
            if "padauk" in base_font.lower():
                font_name = "Padauk"
            elif "mmrtext" in base_font.lower() or "myanmar" in base_font.lower():
                font_name = "Myanmar Text"

        # 1. Create Reels ASS Subtitle & Hook Title File
        ass_path = os.path.join(temp_dir, "reels_subs.ass")
        title_clean = str(hook_title or "").replace("|", "-").strip()
        if not title_clean:
            title_clean = "Movie Recap"
        # Truncate title if extremely long
        if len(title_clean) > 80:
            title_clean = title_clean[:77] + "..."

        # Word wrap title for 1080px width (approx 20-22 chars per line)
        words = title_clean.split()
        lines = []
        cur_line = ""
        for word in words:
            if len(cur_line + " " + word) <= 22:
                cur_line = (cur_line + " " + word).strip()
            else:
                if cur_line: lines.append(cur_line)
                cur_line = word
        if cur_line: lines.append(cur_line)
        wrapped_title = "\\N".join(lines) if lines else title_clean

        # Generate ASS with two styles:
        # Style 1: ReelsHook (Top Center, Gold/Yellow, Big, MarginV=90)
        # Style 2: ReelsSubs (Bottom Center Safe Zone, White with Black Outline, MarginV=280)
        ass_content = f"""[Script Info]
Title: Facebook Reels Canvas Overlay
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {w_target}
PlayResY: {h_target}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ReelsHook,{font_name},52,&H0000D7FF,&H00000000,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,3,8,40,40,90,1
Style: ReelsSubs,{font_name},44,&H00FFFFFF,&H00000000,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,{safe_margin + 120},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,9:59:59.99,ReelsHook,,0,0,0,,{wrapped_title}
"""
        if subtitle_timings:
            for item in subtitle_timings:
                try:
                    start_s = float(item[0])
                    dur_s   = float(item[1])
                    raw_txt = str(item[2]).strip()
                    if not raw_txt: continue
                    words = raw_txt.split(" ")
                    chunks, line = [], ""
                    for word in words:
                        if len(line) + len(word) + 1 <= 48:
                            line = (line + " " + word).strip()
                        else:
                            if line: chunks.append(line)
                            line = word
                    if line: chunks.append(line)
                    if not chunks: continue
                    seg_dur = dur_s / len(chunks)
                    for i, chunk in enumerate(chunks):
                        seg_start = start_s + i * seg_dur
                        seg_end   = seg_start + seg_dur - 0.05
                        safe_chunk = chunk.replace('\\', '').replace('{', '').replace('}', '')
                        ass_text  = self._wrap_burmese_text(safe_chunk, max_chars=24)
                        t_start   = self._sec_to_ass_ts(seg_start)
                        t_end     = self._sec_to_ass_ts(seg_end)
                        ass_content += f"Dialogue: 1,{t_start},{t_end},ReelsSubs,,0,0,0,,{ass_text}\n"
                except Exception:
                    pass

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # 2. Build FFmpeg Filter Graph:
        ffmpeg_bin = _get_ffmpeg_bin()
        enc_info = detect_hardware_encoder()
        abs_src = os.path.abspath(source_video_path)
        ass_basename = os.path.basename(ass_path)
        temp_reels_out = os.path.join(temp_dir, "temp_reels_render.mp4")

        # 16x faster silky bokeh background: downscale to 270x480, blur lightly, then upscale
        bg_w = w_target // 4
        bg_h = h_target // 4
        filter_complex = (
            f"[0:v]scale={bg_w}:{bg_h}:force_original_aspect_ratio=increase,"
            f"crop={bg_w}:{bg_h},boxblur=12:3,"
            f"scale={w_target}:{h_target}[bg];"
            f"[0:v]scale={w_target}:-2[fg];"
            f"[bg][fg]overlay=0:({h_target}-h)/2,"
            f"ass={ass_basename}[out]"
        )

        codec = enc_info["codec"]
        preset = enc_info.get("preset", "faster")
        cmd = [
            ffmpeg_bin, "-y",
            "-i", abs_src,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", codec,
            "-preset", preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            temp_reels_out
        ]

        print(f"[*] ReelsExporter: Rendering 9:16 Canvas Reels ({w_target}x{h_target}) using {enc_info['label']} [{codec}]...")
        timeout_sec = max(600, int((duration_sec or 600.0) * 1.5))
        try:
            res = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_sec)
            if res.returncode == 0 and os.path.exists(temp_reels_out) and os.path.getsize(temp_reels_out) > 500_000:
                shutil.move(temp_reels_out, reels_output)
                print(f"🎉 [OK] ReelsExporter: Successfully created 9:16 Facebook Reels video -> {reels_output}")
                return reels_output
            else:
                err_msg = (res.stderr or "")[-500:]
                print(f"[WARN] ReelsExporter: Hardware encoding failed (code={res.returncode}). Retrying with CPU ultrafast...")
                # Fallback to libx264
                cmd[cmd.index("-c:v") + 1] = "libx264"
                cmd[cmd.index("-preset") + 1] = "ultrafast"
                res2 = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_sec)
                if res2.returncode == 0 and os.path.exists(temp_reels_out) and os.path.getsize(temp_reels_out) > 500_000:
                    shutil.move(temp_reels_out, reels_output)
                    print(f"🎉 [OK] ReelsExporter: Created 9:16 Reels video via CPU fallback -> {reels_output}")
                    return reels_output
                else:
                    print(f"[ERROR] ReelsExporter failed completely: {(res2.stderr or '')[-400:]}")
                    return None
        except Exception as e:
            print(f"[ERROR] ReelsExporter encountered error: {e}")
            return None
        finally:
            if os.path.exists(temp_reels_out):
                try: os.remove(temp_reels_out)
                except Exception: pass



