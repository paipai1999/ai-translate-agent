import os
import re
import shutil
import asyncio
import subprocess
from brain.memory import MovieState
from agents.f5_tts_engine import F5TTSEngine

class VoiceAgent:
    def __init__(self, voice: str = None, output_dir: str = "outputs", engine: str = None, tts_engine: str = None):
        """
        VoiceAgent supports:
          1. Microsoft Edge TTS (100% free cloud TTS - Thiha / Nilar / Guy)
          2. F5-TTS (Zero-Shot Flow-Matching Voice Cloning with Auto Character Slicing)
        """
        import brain.config as cfg
        config_data = cfg.load_config()
        voice_cfg = config_data.get("voice", {})
        
        self.engine = engine or tts_engine or os.getenv("TTS_ENGINE") or voice_cfg.get("engine", "edge_tts")
        self.tts_engine = self.engine
        self.voice = self._resolve_voice(voice, voice_cfg)
        self.rate_mm = os.getenv("EDGE_TTS_RATE_MM") or voice_cfg.get("tts_rate_mm", "+8%")
        self.rate_en = os.getenv("EDGE_TTS_RATE_EN") or voice_cfg.get("tts_rate_en", "+15%")
        self.output_dir = output_dir

        self.f5_cfg = voice_cfg.get("f5_tts", {})
        self.f5_engine = None
        if self.engine == "f5_tts":
            model_type = self.f5_cfg.get("model_type", "F5-TTS")
            device = self.f5_cfg.get("device", "auto")
            speed = float(self.f5_cfg.get("speed", 1.0))
            self.f5_engine = F5TTSEngine(model_type=model_type, device=device, speed=speed)
            if self.f5_engine.device == "cpu":
                print("💡 [F5-TTS NOTICE] Running on CPU. For 50x faster zero-shot voice cloning, consider using Google Colab T4 GPU or Edge-TTS.")

        print(f"[*] VoiceAgent: Active TTS Engine: {self.engine.upper()} (Voice: {self.voice})")

    def _resolve_voice(self, preferred_voice: str, voice_cfg: dict) -> str:
        """Prefer a configured voice but gracefully fall back to a known-good Edge TTS voice."""
        candidates = []
        for candidate in [
            preferred_voice,
            os.getenv("EDGE_TTS_VOICE"),
            voice_cfg.get("tts_voice_mm"),
            voice_cfg.get("tts_voice_en"),
            voice_cfg.get("tts_voice"),
            "my-MM-ThihaNeural",
            "en-US-GuyNeural",
        ]:
            value = str(candidate or "").strip()
            if value and value not in candidates:
                candidates.append(value)

        try:
            import edge_tts
            import asyncio
            available_voices = []
            
            async def get_voices():
                return await edge_tts.list_voices()
            
            # FIX-W1: Kaggle/Colab already has a running event loop
            try:
                voices_list = asyncio.run(get_voices())
            except RuntimeError:
                try:
                    import nest_asyncio; nest_asyncio.apply()
                    voices_list = asyncio.get_event_loop().run_until_complete(get_voices())
                except Exception:
                    voices_list = []
            for item in voices_list:
                if isinstance(item, dict):
                    available_voices.append(str(item.get("ShortName") or item.get("Name") or "").strip())
                else:
                    available_voices.append(str(item).strip())
            available_lower = {v.lower() for v in available_voices if v}
            for candidate in candidates:
                if candidate.lower() in available_lower:
                    return candidate
        except Exception:
            pass

        # If the environment cannot list voices (offline or package mismatch), use a known-good default.
        for candidate in candidates:
            if candidate.lower().startswith("my-"):
                return candidate
        return "en-US-GuyNeural"

    def _extract_character_reference_clips(self, state: MovieState) -> dict:
        """
        Extracts 3-10s clean reference voice clips for each detected character from Demucs vocals.wav.
        Returns: {character_name: {"audio_path": ..., "text": ...}}
        """
        character_clips = {}
        movie_path = getattr(state, "movie_path", None) or getattr(state, "file_path", None)
        if not movie_path:
            return character_clips

        base_candidates = [
            getattr(state, "movie_name", None),
            os.path.splitext(os.path.basename(movie_path))[0],
        ]
        vocals_path = None
        for b_name in base_candidates:
            if not b_name:
                continue
            cand = os.path.join("temp", state.project_dir, "audio", "htdemucs", b_name, "vocals.wav")
            if os.path.exists(cand):
                vocals_path = cand
                break

        if not vocals_path or not os.path.exists(vocals_path):
            vocals_path = getattr(state, "audio_path", None)
            if not vocals_path or not os.path.exists(vocals_path):
                return character_clips

        ffmpeg_bin = shutil.which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"
        voices_temp_dir = os.path.join("temp", state.project_dir, "voices")
        os.makedirs(voices_temp_dir, exist_ok=True)

        speaker_segments = getattr(state, "speaker_transcript", []) or []
        if not speaker_segments and state.transcript:
            # Fallback to general transcript segments
            speaker_segments = [{"speaker": "Narrator", "text": getattr(s, "text", ""), "start_sec": getattr(s, "start", 0.0), "end_sec": getattr(s, "end", 0.0)} for s in state.transcript]

        # Group candidate segments per speaker
        by_speaker = {}
        for seg in speaker_segments:
            if not isinstance(seg, dict):
                continue
            spkr = str(seg.get("speaker", "Unknown")).strip()
            if not spkr or spkr.lower() == "unknown":
                spkr = "Narrator"
            start_s = float(seg.get("start_sec", 0.0))
            end_s = float(seg.get("end_sec", start_s))
            dur = end_s - start_s
            text = str(seg.get("text", "")).strip()

            if 2.5 <= dur <= 12.0 and text and len(text) > 8:
                if spkr not in by_speaker:
                    by_speaker[spkr] = []
                by_speaker[spkr].append({"start": start_s, "end": end_s, "dur": dur, "text": text})

        print(f"[*] VoiceAgent: Slicing character reference audio for {len(by_speaker)} speaker(s)...")

        for spkr, candidates in by_speaker.items():
            # Pick candidate closest to 5.0 seconds
            best = min(candidates, key=lambda c: abs(c["dur"] - 5.0))
            safe_name = re.sub(r'[^\w\-]', '_', spkr)
            out_clip = os.path.join(voices_temp_dir, f"{safe_name}_ref.wav")

            cmd = [
                ffmpeg_bin, "-y",
                "-ss", str(best["start"]),
                "-to", str(best["end"]),
                "-i", vocals_path,
                "-acodec", "pcm_s16le",
                "-ar", "24000", # 24kHz optimal for F5-TTS
                "-ac", "1",
                out_clip
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.exists(out_clip) and os.path.getsize(out_clip) > 1000:
                    character_clips[spkr.lower()] = {
                        "audio_path": out_clip,
                        "text": best["text"]
                    }
                    print(f"    - [OK] Extracted {spkr} voice ({best['dur']:.1f}s) -> '{best['text'][:40]}...'")
            except Exception as e:
                print(f"    - [WARN] Failed to slice reference for {spkr}: {e}")

        return character_clips

    def generate_voiceover(self, state: MovieState) -> MovieState:
        """Converts the generated narration script to MP3 audio files using Edge TTS or F5-TTS."""
        if not state.generated_script:
            print("[!] VoiceAgent: No script found. Skipping TTS generation.")
            return state

        if self.output_dir.endswith("voiceover"):
            audio_out_dir = self.output_dir
        elif state.project_dir in self.output_dir:
            audio_out_dir = os.path.join(self.output_dir, "voiceover")
        else:
            audio_out_dir = os.path.join(self.output_dir, state.project_dir, "voiceover")
        os.makedirs(audio_out_dir, exist_ok=True)
        # Check if complete voiceover files already exist
        existing_mp3s = [f for f in os.listdir(audio_out_dir) if f.startswith("scene_") and f.endswith(".mp3") and os.path.getsize(os.path.join(audio_out_dir, f)) > 1000]
        if state.generated_script and len(existing_mp3s) >= len(state.generated_script):
            print(f"[*] VoiceAgent: Reusing {len(existing_mp3s)} cached voiceover clips from {audio_out_dir}...")
            return state

        for old_file in os.listdir(audio_out_dir):
            if old_file.endswith(".mp3"):
                try:
                    os.remove(os.path.join(audio_out_dir, old_file))
                except Exception:
                    pass

        # Check if F5-TTS engine is requested
        use_f5 = self.engine == "f5_tts"
        if use_f5:
            # F5-TTS flow-matching model is trained strictly for English & Chinese.
            # For Burmese narration, Microsoft Neural Edge-TTS (Thiha / Nilar) is the dedicated high-quality engine.
            sample_text = "".join([str(item.get("narration", "")) for item in (state.generated_script or [])[:5]])
            has_burmese = any('\u1000' <= char <= '\u109F' or '\uAA60' <= char <= '\uAA7F' for char in sample_text) or getattr(state, "language", "").lower() == "burmese"
            if has_burmese:
                print("[*] VoiceAgent: Burmese narration detected. F5-TTS model is trained for English/Chinese.")
                print("[*] VoiceAgent: Automatically routing to Microsoft Neural Edge-TTS (my-MM-ThihaNeural / my-MM-NilarNeural) for natural, fluent Myanmar voiceover.")
                use_f5 = False
            elif not self.f5_engine or not self.f5_engine.is_available():
                print("[WARN] VoiceAgent: F5-TTS is requested but not installed. Falling back to Edge TTS.")
                print("[TIP] To use F5-TTS Voice Cloning, run: pip install f5-tts soundfile")
                use_f5 = False

        if use_f5:
            return self._generate_f5_voiceover(state, audio_out_dir)
        else:
            return self._generate_edge_voiceover(state, audio_out_dir)

    def _generate_f5_voiceover(self, state: MovieState, audio_out_dir: str) -> MovieState:
        """Generates voiceover using F5-TTS Zero-Shot Voice Cloning."""
        print(f"[*] VoiceAgent: Starting F5-TTS Voice Cloning (Model: {self.f5_cfg.get('model_type', 'F5-TTS')})...")
        
        # 1. Extract character reference clips from Demucs isolated vocals
        char_clips = {}
        if self.f5_cfg.get("auto_character_cloning", True):
            char_clips = self._extract_character_reference_clips(state)

        default_ref = self.f5_cfg.get("default_ref_audio", "assets/voices/default_ref.wav")
        default_ref_text = self.f5_cfg.get("default_ref_text", "")

        audio_files = []
        for idx, item in enumerate(state.generated_script):
            narration = item.get("narration", "").strip()
            scene_id = item.get("scene_id", idx + 1)
            speaker = str(item.get("speaker", "Narrator")).strip().lower()
            start_sec = float(item.get("start_sec") or 0.0)
            end_sec = float(item.get("end_sec") or (start_sec + 3.0))
            target_dur = max(0.5, end_sec - start_sec)

            if not narration:
                continue

            clean_narration = self._prepare_tts_text(narration)
            out_file = os.path.join(audio_out_dir, f"scene_{(idx+1):04d}.mp3")

            # Determine best reference audio for this speaker
            ref_info = char_clips.get(speaker)
            if not ref_info and "narrator" in char_clips:
                ref_info = char_clips.get("narrator")

            ref_audio = ref_info["audio_path"] if ref_info else default_ref
            ref_text = ref_info["text"] if ref_info else default_ref_text

            # If no ref audio exists, fallback to first available or Edge TTS
            if not os.path.exists(ref_audio):
                if char_clips:
                    first_ref = list(char_clips.values())[0]
                    ref_audio = first_ref["audio_path"]
                    ref_text = first_ref["text"]

            success = False
            if os.path.exists(ref_audio):
                print(f"[*] VoiceAgent (F5-TTS): Scene {scene_id} [Speaker: {speaker}] -> target_dur={target_dur:.1f}s...")
                success = self.f5_engine.generate_speech(
                    text=clean_narration,
                    ref_audio_path=ref_audio,
                    ref_text=ref_text,
                    output_path=out_file,
                    target_dur=target_dur
                )

            # Fallback to Edge TTS if F5-TTS synthesis failed or ref audio was missing
            if not success:
                print(f"[!] VoiceAgent: F5-TTS fallback to Edge TTS for Scene {scene_id}...")
                is_myanmar = str(self.voice).startswith("my-")
                gender = str(item.get("gender", "Unknown")).strip().lower()
                voice_override = "my-MM-NilarNeural" if (is_myanmar and gender == "female") else self.voice
                rate = self.rate_mm if str(voice_override).startswith("my-") else self.rate_en
                emotion = item.get("emotion", "normal").lower()
                asyncio.run(self._speak_with_retry(clean_narration, out_file, scene_id, emotion, rate=rate, target_dur=target_dur, voice_override=voice_override))

            if os.path.exists(out_file):
                audio_files.append(out_file)

        print(f"[OK] VoiceAgent: Generated {len(audio_files)} audio segments via F5-TTS in -> {audio_out_dir}")
        return state

    def _generate_edge_voiceover(self, state: MovieState, audio_out_dir: str) -> MovieState:
        """Converts the generated narration script to MP3 audio files using Edge TTS ($0 cost)."""
        selected_rate = self.rate_mm if str(self.voice).startswith("my-") else self.rate_en
        print(f"[*] VoiceAgent: Starting Text-to-Speech using Edge TTS (Voice: {self.voice}, Pace: {selected_rate})...")

        try:
            import edge_tts
        except ImportError:
            print("[!] VoiceAgent: 'edge-tts' is not installed. Please run: pip install edge-tts")
            return state

        audio_files = []
        
        async def _run_all(tasks):
            sem = asyncio.Semaphore(5)
            async def _wrap(task):
                async with sem:
                    return await task
            return await asyncio.gather(*[_wrap(t) for t in tasks], return_exceptions=True)
            
        tasks = []
        output_files = []

        for idx, item in enumerate(state.generated_script):
            narration = item.get("narration", "").strip()
            emotion = item.get("emotion", "normal").lower()
            gender = str(item.get("gender", "male")).strip().lower()
            character = str(item.get("character", "Narrator")).strip()
            scene_id = item.get("scene_id", idx + 1)
            if not narration:
                continue
            
            is_myanmar = str(self.voice).startswith("my-") or getattr(self, "language", "") == "burmese"
            voice_override = self.voice
            if is_myanmar:
                if self.voice == "my-MM-NilarNeural":
                    voice_override = "my-MM-NilarNeural"
                elif gender == "female":
                    voice_override = "my-MM-NilarNeural"
                    print(f"    👩 [Multi-Voice]: Block {idx+1} ({character}) -> Female Voice (my-MM-NilarNeural)")
                else:
                    voice_override = "my-MM-ThihaNeural"
            else:
                if self.voice == "en-US-JennyNeural":
                    voice_override = "en-US-JennyNeural"
                elif gender == "female":
                    voice_override = "en-US-JennyNeural"
                    print(f"    👩 [Multi-Voice]: Block {idx+1} ({character}) -> Female Voice (en-US-JennyNeural)")
                else:
                    voice_override = "en-US-GuyNeural"
            
            selected_rate = self.rate_mm if str(voice_override).startswith("my-") else self.rate_en
            
            # GET EXACT TIMESTAMPS
            start_sec = float(item.get("start_sec") or 0.0)
            end_sec = float(item.get("end_sec") or (start_sec + 3.0))
            target_dur = max(0.5, end_sec - start_sec)
            
            clean_narration = self._prepare_tts_text(narration)
            out_file = os.path.join(audio_out_dir, f"scene_{(idx+1):04d}.mp3")
            print(f"[*] VoiceAgent: Generating audio block {idx+1} (Scene {scene_id}) voice={voice_override} target_dur={target_dur:.1f}s...")
            
            tasks.append(self._speak_with_retry(clean_narration, out_file, scene_id, emotion, rate=selected_rate, target_dur=target_dur, voice_override=voice_override))
            output_files.append(out_file)

        # FIX-W1: In Kaggle/Colab Jupyter, asyncio.run() raises RuntimeError("This event loop
        # is already running") because Jupyter runs its own persistent event loop.
        # Use nest_asyncio.apply() if available, otherwise create a new thread with its own loop.
        try:
            results = asyncio.run(_run_all(tasks))
        except RuntimeError as _loop_err:
            if "event loop is already running" in str(_loop_err).lower():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    results = asyncio.get_event_loop().run_until_complete(_run_all(tasks))
                    print("[*] VoiceAgent: Used nest_asyncio for Jupyter/Colab compatibility.")
                except ImportError:
                    # nest_asyncio not installed → run in a separate thread with its own loop
                    import concurrent.futures as _cf
                    def _run_in_new_loop():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(_run_all(tasks))
                        finally:
                            loop.close()
                    with _cf.ThreadPoolExecutor(max_workers=1) as _exe:
                        results = _exe.submit(_run_in_new_loop).result()
                    print("[*] VoiceAgent: Used ThreadPoolExecutor for Jupyter/Colab compatibility.")
            else:
                raise
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[WARN] VoiceAgent: Block {i} TTS failed: {result}")
            elif result:
                audio_files.append(output_files[i])

        print(f"[OK] VoiceAgent: Generated {len(audio_files)} audio segments in -> {audio_out_dir}")
        return state

    async def _speak_with_retry(self, text: str, output_file: str, scene_id, emotion: str = "normal", rate: str = "+15%", target_dur: float = None, voice_override: str = None) -> bool:
        """Async helper to synthesize a single narration chunk via Edge TTS with retry logic and emotion tuning."""
        import edge_tts
        import subprocess
        try:
            from moviepy import AudioFileClip
        except ImportError:
            from moviepy.editor import AudioFileClip

        # Lock parameters to a consistent professional tone
        pitch = "+2Hz"
        volume = "+30%"

        success = False
        voice_to_use = voice_override if voice_override else self.voice
        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(text, voice_to_use, rate=rate, pitch=pitch, volume=volume)
                await communicate.save(output_file)
                success = True
                break
            except Exception as e:
                print(f"[RETRY] VoiceAgent: Retrying Scene {scene_id} (attempt {attempt}/3)...")
                await asyncio.sleep(2 ** attempt)
        
        if not success:
            print(f"[WARN] VoiceAgent: Scene {scene_id} TTS failed after 3 attempts.")
            print(f"[*] VoiceAgent: FALLBACK -> Generating silent audio of {target_dur or 3.0}s to preserve video sync.")
            try:
                dur = target_dur if target_dur else 3.0
                ffmpeg_bin = shutil.which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"
                cmd = [
                    ffmpeg_bin, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(dur),
                    "-codec:a", "libmp3lame",
                    output_file
                ]
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 0 and os.path.exists(output_file):
                    success = True
                else:
                    try:
                        from moviepy.audio.AudioClip import AudioClip
                    except ImportError:
                        from moviepy.editor import AudioClip
                    make_frame = lambda t: [0, 0]
                    silent_clip = AudioClip(make_frame, duration=dur, fps=44100)
                    silent_clip.write_audiofile(output_file, fps=44100, logger=None)
                    success = True
            except Exception as e:
                print(f"[ERROR] VoiceAgent: Fallback silent audio failed: {e}")
                return False

        # --- EXACT SYNC: Pitch-Preserving FFmpeg atempo Stretch ---
        if target_dur is not None and os.path.exists(output_file):
            try:
                clip = AudioFileClip(output_file)
                raw_dur = clip.duration
                clip.close()

                if raw_dur > 0:
                    stretch_ratio = target_dur / raw_dur
                    effective_ratio = min(1.1, max(0.7, stretch_ratio))

                    if abs(effective_ratio - 1.0) > 0.05:
                        base, ext = os.path.splitext(output_file)
                        temp_file = base + "_temp" + ext
                        os.rename(output_file, temp_file)
                        
                        atempo_val = 1.0 / effective_ratio
                        if atempo_val > 2.0:
                            filter_str = f"atempo=2.0,atempo={atempo_val/2.0:.3f}"
                        elif atempo_val < 0.5:
                            filter_str = f"atempo=0.5,atempo={atempo_val/0.5:.3f}"
                        else:
                            filter_str = f"atempo={atempo_val:.3f}"
                        
                        ffmpeg_bin = shutil.which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"
                        cmd = [
                            ffmpeg_bin, "-y", "-i", temp_file,
                            "-filter:a", filter_str,
                            output_file
                        ]
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                        os.remove(temp_file)
                        print(f"[*] VoiceAgent (Exact Sync): Scene {scene_id} stretched (raw: {raw_dur:.1f}s -> target: {target_dur:.1f}s | filter: {filter_str})") 
            except Exception as stretch_err:
                print(f"[WARN] VoiceAgent: FFmpeg atempo stretch failed for Scene {scene_id}: {stretch_err}")
                base, ext = os.path.splitext(output_file)
                temp_fallback = base + "_temp" + ext
                if not os.path.exists(output_file) and os.path.exists(temp_fallback):
                    os.rename(temp_fallback, output_file)

        return True

    def _prepare_tts_text(self, text: str) -> str:
        """Normalize script text so Edge TTS / F5-TTS reads narration naturally."""
        try:
            from brain.burmese_utils import replace_numbers_with_burmese, transliterate_english_acronyms
            text = replace_numbers_with_burmese(text)
            text = transliterate_english_acronyms(text)
        except Exception as e:
            print(f"[WARN] VoiceAgent: Failed to normalize text with burmese_utils: {e}")

        text = re.sub(r'[\*#_~`]', '', str(text))
        text = text.replace("…", "။")
        
        # English letter handling for Myanmar TTS
        if str(self.voice).startswith("my-"):
            stripped = re.sub(r'[A-Za-z]', '', text)
            stripped = re.sub(r'\s+', ' ', stripped).strip()
            if stripped and re.search(r'[\u1000-\u109F]', stripped):
                text = stripped

        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return ""

        text = re.sub(r'\s*([,;:])\s*', r'၊ ', text)
        text = re.sub(r'\s*([!?])\s*', r'။ ', text)
        text = re.sub(r'\s*([.])\s*', r'။ ', text)

        parts = [p.strip() for p in re.split(r'(?<=[။!?])\s+', text) if self._has_meaningful_text(p)]
        if not parts:
            parts = [text]

        normalized_parts = []
        for part in parts:
            if len(part) <= 120:
                normalized_parts.append(part)
                continue

            clauses = [c.strip() for c in re.split(r'\s*([၊])\s*', part) if c and c.strip()]
            if len(clauses) > 1:
                rebuilt = []
                current = ""
                for clause in clauses:
                    if clause == "၊":
                        current = current.rstrip() + "၊"
                        continue
                    candidate = f"{current} {clause}".strip() if current else clause
                    if len(candidate) > 80 and current:
                        rebuilt.extend(self._chunk_text(current.strip(), 70))
                        current = clause
                    else:
                        current = candidate
                if current:
                    rebuilt.extend(self._chunk_text(current.strip(), 70))
                normalized_parts.extend(rebuilt)
            else:
                normalized_parts.extend(self._chunk_text(part, 70))

        text = "\n".join(normalized_parts)
        if text and text[-1] not in "။!?":
            text += "။"
        return text

    def _chunk_text(self, text: str, chunk_size: int) -> list[str]:
        """Break a long clause into short, speakable chunks.

        FIX-BUG5: Splits at word boundary (space) or Burmese punctuation (၊ ။)
        nearest to the chunk_size limit. If no space exists, splits at clean
        Burmese syllable boundaries so syllables are never cut mid-character.
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        # Burmese combining marks, medials, tone marks, virama that CANNOT start a chunk
        BURMESE_NON_INITIALS = set(
            [chr(c) for c in range(0x102B, 0x103F)] +
            ['\uAA7B', '\uAA7C', '\uAA7D']
        )

        chunks = []
        start = 0
        while start < len(text):
            if len(text) - start <= chunk_size:
                piece = text[start:].strip()
                if piece:
                    chunks.append(piece)
                break

            end = start + chunk_size

            # Priority 1: Search backwards for space or punctuation
            cut = -1
            for i in range(end, start + 5, -1):
                if text[i - 1] in (' ', '\u104A', '\u104B', ',', '.', '!', '?', ';', ':'):
                    cut = i
                    break

            # Priority 2: Search backwards for a clean Burmese syllable boundary
            # The character starting the next chunk must NOT be a combining mark,
            # and the character ending the current chunk must not be a prefix vowel or virama.
            if cut == -1:
                for i in range(end, start + 5, -1):
                    if text[i] not in BURMESE_NON_INITIALS and text[i - 1] not in ('\u1031', '\u1039'):
                        cut = i
                        break

            if cut == -1:
                cut = end

            piece = text[start:cut].strip()
            if piece:
                if piece[-1] not in ('၊', '။', '!', '?', '.', ',', ' '):
                    piece += '၊'
                chunks.append(piece)
            start = cut

        return chunks

    def _has_meaningful_text(self, text: str) -> bool:
        """Return True when a fragment contains real text, not just punctuation."""
        if not text:
            return False
        return bool(re.search(r'[A-Za-z0-9\u1000-\u109F]', str(text)))
