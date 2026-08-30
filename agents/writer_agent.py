import json
import math
import os
import re
from brain.memory import MovieState
from brain.prompts import (
    FULL_RECAP_SYSTEM_PROMPT,
    get_full_recap_writer_prompt,
)
from brain.gemini_client import call_gemini
from brain import config as cfg


# How many time-based chapters to split the transcript into
DEFAULT_CHAPTERS = 10


class WriterAgent:
    def __init__(
        self,
        language: str = "burmese",
        max_blocks: int | None = None,
    ):
        self.language = language
        self.max_blocks = max_blocks or (int(os.getenv("MAX_BLOCKS")) if os.getenv("MAX_BLOCKS") else None)

    # ─────────────────────────────────────────────────────
    # PUBLIC: generate_script
    # ─────────────────────────────────────────────────────
    def generate_script(self, state: MovieState) -> MovieState:
        """
        Full-story recap script generator.
        Strategy:
          1. Split the entire transcript into N time-based chapters.
          2. Call Gemini with FULL_RECAP_SYSTEM_PROMPT asking for 1 block per chapter.
          3. If Gemini fails or is disabled, fall back to a transcript-driven heuristic script.
        """
        print(
            f"[*] WriterAgent: Generating FULL STORY recap script "
            f"(Lang: {self.language})..."
        )

        if not state.transcript and not state.timeline:
            print("[!] WriterAgent: No transcript or timeline found. Skipping script generation.")
            return state

        # ── Build chapter list from transcript ──────────────────────────
        chapters = self._build_chapters(state)
        n_chapters = len(chapters)
        print(f"[*] WriterAgent: Transcript split into {n_chapters} chapters for full-story coverage.")

        # ── Config ─────────────────────────────────────────────────────
        config_data = cfg.load_config()
        gemini_cfg   = config_data.get("gemini", {})
        gemini_enabled = gemini_cfg.get("enabled", False)
        gemini_key   = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY") or ""
        gemini_model = gemini_cfg.get("model", "gemini-3.5-flash-lite")
        models_dict = gemini_cfg.get("models", {})
        model_heavy = models_dict.get("heavy", "gemini-3.5-flash-lite")
        model_workhorse = models_dict.get("workhorse", "gemini-3.5-flash-lite")

        generated = None

        # ── Get previous episode context if available ──────────────────
        prev_context = self._get_previous_episode_context(state)

        # ── 1. Gemini Vision — per-chapter frame + subtitle grounded narration ──
        if gemini_enabled and gemini_key:
            movie_path = getattr(state, "movie_path", None) or getattr(state, "source_path", None)
            use_vision = bool(movie_path and os.path.exists(str(movie_path)))

            if use_vision:
                file_size_mb = os.path.getsize(movie_path) / (1024 * 1024)
                duration_sec = 120.0
                if getattr(state, "duration", None):
                    try:
                        parts = str(state.duration).split(":")
                        if len(parts) == 3:
                            duration_sec = int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
                    except:
                        pass
                else:
                    if chapters:
                        duration_sec = chapters[-1].get("t_start", 0) + 15.0

                print(f"[*] WriterAgent (Native Video Mode): Uploading full video ({file_size_mb:.1f}MB, {duration_sec}s) to Gemini for maximum context...")
                generated = self._native_video_recap(chapters, state, movie_path, gemini_key, model_heavy, model_workhorse)
                if not generated:
                    print("[!] Native Video Mode failed.")

            else:
                user_prompt = get_full_recap_writer_prompt(
                    movie_name      = state.movie_name,
                    genre           = state.genre or "Action / Drama",
                    story_structure = {},
                    chapters        = chapters,
                    language        = self.language,
                    prev_context    = prev_context,
                )
                try:
                    print(f"[*] WriterAgent: Calling Gemini ({model_workhorse}) text-only fallback ({n_chapters} chapters)...")
                    raw, used_model = call_gemini(
                        FULL_RECAP_SYSTEM_PROMPT, user_prompt, gemini_key, model_workhorse,
                        temperature=0.7, max_tokens=8192,
                    )
                    print(f"[*] WriterAgent: Gemini model '{used_model}' responded.")
                    generated = self._parse_script(raw)
                except Exception as e:
                    print(f"[!] WriterAgent: Gemini text-only failed ({e}). Falling back to heuristic recap...")
        else:
            print("[TIP] WriterAgent: Gemini disabled or no API key. Using heuristic recap fallback.")

        if not generated:
            print("[!] WriterAgent: Native Video Mode failed. Raising error to prevent corrupted fallback output.")
            raise Exception("Gemini API (Native Video Mode) failed. Please try again.")

        if self.max_blocks is not None and self.max_blocks > 0 and len(generated) > self.max_blocks:
            generated = generated[: self.max_blocks]
            print(f"[*] WriterAgent: Trimmed script to MAX_BLOCKS={self.max_blocks} narrative blocks.")

        # Normalise scene IDs and attach exact subtitle t_start timestamps
        n_ch = len(chapters) if chapters else 1
        n_blocks = len(generated)
        blocks_per_ch = max(1, n_blocks // max(n_ch, 1))

        # Estimate total video duration from chapter data for interpolation
        total_dur_sec = 120.0
        if chapters:
            last_ch = chapters[-1]
            last_t = last_ch.get("t_start", 0.0)
            if len(chapters) > 1:
                avg_chunk = last_t / max(len(chapters) - 1, 1)
                total_dur_sec = last_t + avg_chunk
            else:
                total_dur_sec = max(last_t + 15.0, 120.0)

        for idx, item in enumerate(generated):
            if not isinstance(item, dict):
                print(f"[WARN] WriterAgent: Skipping non-dict script block at index {idx}: {type(item)}")
                continue
            item["scene_id"] = str(idx + 1)
            
            # Skip timestamp interpolation if native video mode already provided exact timestamps
            if "start_sec" in item and "end_sec" in item:
                continue
                
            ch_idx = min(idx // blocks_per_ch, n_ch - 1)
            if chapters and ch_idx < len(chapters):
                ch_t_start = chapters[ch_idx].get("t_start", 0.0)
                # Interpolate within the chapter window to give each block a unique timestamp
                if ch_idx + 1 < len(chapters):
                    ch_t_end = chapters[ch_idx + 1].get("t_start", total_dur_sec)
                else:
                    ch_t_end = total_dur_sec
                within_ch_idx = idx - (ch_idx * blocks_per_ch)
                frac = within_ch_idx / max(blocks_per_ch, 1)
                item["start_sec"] = round(ch_t_start + frac * (ch_t_end - ch_t_start), 2)
            else:
                item["start_sec"] = round((idx / max(n_blocks, 1)) * total_dur_sec, 2)

        state.generated_script = generated
        print(
            f"[OK] WriterAgent: Script ready — {len(generated)} narrative blocks "
            f"covering the full story arc."
        )
        return state

    def _native_video_recap(self, chapters: list, state: MovieState, movie_path: str, api_key, model_heavy: str, model_workhorse: str) -> list:
        """
        2-Phase Gemini Native Video Pipeline:
          Phase 1 — Upload video → extract every spoken line with speaker + exact timestamps
          Phase 2 — Send Phase 1 speaker transcript → write Myanmar narration (timestamps copied exactly)
        This eliminates all timestamp approximation and guarantees narration sync.
        """
        from brain.gemini_client import upload_video_file, ask_gemini_with_video, delete_video_file
        from brain.prompts import PHASE1_SPEAKER_SYSTEM_PROMPT, PHASE2_NARRATION_SYSTEM_PROMPT

        file_name = None
        working_key = None
        try:
            # ── Upload video once — reused for both phases ───────────────────
            file_name, working_key = upload_video_file(movie_path, api_key)

            # ─────────────────────────────────────────────────────────────────
            # PHASE 1: Extract speaker-tagged transcript with exact timestamps
            # ─────────────────────────────────────────────────────────────────
            print("[*] WriterAgent Phase 1: Extracting speaker-tagged transcript from video...")
            phase1_prompt = (
                f"Movie Title: {state.movie_name}\n"
                f"Watch the full video carefully and extract EVERY spoken dialogue line "
                f"with the speaker's name and exact start/end timestamps in seconds.\n"
                f"Output a JSON array. Each entry must have: speaker, text, start_sec, end_sec."
            )
            phase1_raw = ask_gemini_with_video(
                file_name, PHASE1_SPEAKER_SYSTEM_PROMPT, phase1_prompt,
                working_key, model=model_heavy, temperature=0.1
            )
            speaker_segments = self._parse_speaker_transcript(phase1_raw)

            if not speaker_segments:
                print("[!] WriterAgent Phase 1: No speaker segments extracted. Falling back to chapter-based method.")
                return self._native_video_recap_fallback(chapters, state, file_name, working_key, model_workhorse)

            print(f"[OK] WriterAgent Phase 1: Extracted {len(speaker_segments)} speaker segments.")

            # Align Phase 1 Gemini timestamps with Whisper waveform STT timestamps for 100% exact sync
            if state.transcript:
                speaker_segments = self._align_speaker_segments_with_whisper(speaker_segments, state.transcript)
                print(f"[OK] WriterAgent: Aligned Phase 1 timestamps with Whisper STT waveform accuracy.")

            # CRITICAL: Sort speaker_segments chronologically so out-of-order Gemini output
            # never causes curr_t to jump forward and create silent gaps in the final video
            try:
                speaker_segments = sorted(
                    speaker_segments,
                    key=lambda s: float(s.get("start_sec") or 0.0) if isinstance(s, dict) else 0.0
                )
                print(f"[OK] WriterAgent: Speaker segments sorted chronologically ({len(speaker_segments)} segments).")
            except Exception as sort_err:
                print(f"[WARN] WriterAgent: Could not sort speaker segments: {sort_err}")

            # ── HYBRID APPROACH: STEP 1 ─────────────────────────────────────
            # CLAMP out-of-bounds timestamps to video duration.
            # Gemini sometimes hallucinates timestamps from next-episode previews
            # that exceed the actual video length. These segments are unusable.
            video_total_dur = state.duration_sec
            if video_total_dur is None or video_total_dur >= 9999.0:
                # Cannot determine duration — skip clamping to avoid dropping valid segments
                video_total_dur = 99999.0

            pre_clamp_count = len(speaker_segments)
            speaker_segments = [
                s for s in speaker_segments
                if float(s.get("start_sec", 0)) < video_total_dur
            ]
            dropped = pre_clamp_count - len(speaker_segments)
            if dropped > 0:
                print(f"[*] WriterAgent [Hybrid]: Dropped {dropped} out-of-bounds segments (beyond {video_total_dur:.1f}s video).")

            # ── HYBRID APPROACH: STEP 2 ─────────────────────────────────────
            # DROP segments with impossible short available gap (< 1.5s).
            # A gap this short cannot fit any meaningful Myanmar TTS audio.
            # These arise when Gemini assigns overlapping speakers the same start_sec.
            cleaned_segments = []
            for i, seg in enumerate(speaker_segments):
                if i < len(speaker_segments) - 1:
                    # Use end_sec → start_sec gap (actual silence between segments)
                    # NOT start_sec → start_sec (which falsely merges long overlapping speech)
                    s_next = float(speaker_segments[i+1].get("start_sec", 0) or 0)
                    s_curr_end = float(seg.get("end_sec", seg.get("start_sec", 0)) or 0)
                    gap = s_next - s_curr_end
                    if gap < 0.5:  # Only merge truly overlapping/touching segments
                        # Absorb text into next segment instead of dropping it silently
                        next_seg = speaker_segments[i+1]
                        combined_text = str(seg.get("text", "")) + " " + str(next_seg.get("text", ""))
                        next_seg["text"] = combined_text.strip()
                        next_seg["start_sec"] = float(seg.get("start_sec", next_seg.get("start_sec", 0)) or 0)
                        print(f"[*] WriterAgent [Hybrid]: Merged short-gap segment '{str(seg.get('text',''))[:30]}...' into next block.")
                        continue  # Skip adding this segment; its text is now in next_seg
                cleaned_segments.append(seg)
            speaker_segments = cleaned_segments
            print(f"[OK] WriterAgent [Hybrid]: {len(speaker_segments)} clean segments after gap-filter.")

            # --- ANTI-OVERLAP CLAMP (Final Pass) ---
            # Ensure no overlapping durations which cause TTS "chipmunk/slow" bugs.
            for i in range(len(speaker_segments) - 1):
                s_curr = float(speaker_segments[i].get("start_sec", 0) or 0)
                e_curr = float(speaker_segments[i].get("end_sec", s_curr + 0.5) or 0)
                s_next = float(speaker_segments[i+1].get("start_sec", 0) or 0)
                e_next = float(speaker_segments[i+1].get("end_sec", s_next + 0.5) or 0)
                if s_curr == s_next:
                    speaker_segments[i+1]["start_sec"] = s_curr + 0.5
                    speaker_segments[i+1]["end_sec"] = max(speaker_segments[i+1]["start_sec"] + 0.5, e_next)
                if e_curr > s_next:
                    speaker_segments[i]["end_sec"] = max(s_curr + 0.5, s_next)

            # ── HYBRID APPROACH: STEP 3 ─────────────────────────────────────
            # LARGE GAP AUTO-FILL: Detect gaps > 8s where Whisper confirms
            # speech exists. Gemini sometimes assigns wrong timestamps to
            # dialogues, leaving large silent gaps in the output video even
            # though characters are actively talking in the original.
            # We fill these gaps using Whisper transcript text.
            GAP_THRESHOLD = 8.0  # seconds
            if state.transcript:
                filled_segments = []
                for i, seg in enumerate(speaker_segments):
                    filled_segments.append(seg)

                    # Check gap to next segment
                    if i < len(speaker_segments) - 1:
                        gap_start = seg.get("end_sec", 0)
                        gap_end = speaker_segments[i + 1].get("start_sec", 0)
                        gap_size = gap_end - gap_start

                        if gap_size > GAP_THRESHOLD:
                            # Check if Whisper has speech in this gap
                            whisper_in_gap = []
                            for w in state.transcript:
                                w_start = getattr(w, "start", 0.0) if hasattr(w, "start") else w.get("start", 0.0) if isinstance(w, dict) else 0.0
                                w_end = getattr(w, "end", 0.0) if hasattr(w, "end") else w.get("end", 0.0) if isinstance(w, dict) else 0.0
                                w_text = getattr(w, "text", "") if hasattr(w, "text") else w.get("text", "") if isinstance(w, dict) else ""

                                # Whisper segment overlaps with the gap
                                if w_end > gap_start and w_start < gap_end and w_text.strip():
                                    is_duplicate = False
                                    w_lower = w_text.strip().lower()
                                    if len(w_lower) > 5:
                                        for existing_seg in speaker_segments:
                                            e_lower = existing_seg.get("text", "").strip().lower()
                                            if len(e_lower) > 5:
                                                if w_lower in e_lower or e_lower in w_lower:
                                                    is_duplicate = True
                                                    break
                                                from difflib import SequenceMatcher
                                                if SequenceMatcher(None, w_lower, e_lower).ratio() > 0.65:
                                                    is_duplicate = True
                                                    break
                                                    
                                    if not is_duplicate:
                                        whisper_in_gap.append({
                                            "start": max(w_start, gap_start),
                                            "end": min(w_end, gap_end),
                                            "text": w_text.strip()
                                        })

                            if whisper_in_gap:
                                print(f"[*] WriterAgent [Hybrid Gap-Fill]: Found {gap_size:.1f}s gap at {gap_start:.1f}-{gap_end:.1f}s with {len(whisper_in_gap)} Whisper segment(s). Filling...")

                                for wi, wg in enumerate(whisper_in_gap):
                                    # Split long Whisper chunks into smaller segments (~6-8s each)
                                    w_dur = wg["end"] - wg["start"]
                                    if w_dur > 10.0:
                                        # Split into roughly equal sub-segments
                                        n_splits = max(2, int(w_dur / 7.0))
                                        split_dur = w_dur / n_splits
                                        words = wg["text"].split()
                                        words_per_split = max(1, len(words) // n_splits)

                                        for si in range(n_splits):
                                            sub_start = wg["start"] + si * split_dur
                                            sub_end = wg["start"] + (si + 1) * split_dur
                                            word_start = si * words_per_split
                                            word_end = (si + 1) * words_per_split if si < n_splits - 1 else len(words)
                                            sub_text = " ".join(words[word_start:word_end])

                                            if sub_text.strip():
                                                filled_segments.append({
                                                    "speaker": "Unknown",
                                                    "gender": "Unknown",
                                                    "text": sub_text.strip(),
                                                    "start_sec": round(sub_start, 2),
                                                    "end_sec": round(sub_end, 2),
                                                    "_gap_filled": True
                                                })
                                    else:
                                        filled_segments.append({
                                            "speaker": "Unknown",
                                            "gender": "Unknown",
                                            "text": wg["text"],
                                            "start_sec": round(wg["start"], 2),
                                            "end_sec": round(wg["end"], 2),
                                            "_gap_filled": True
                                        })

                # Re-sort after adding gap-fill segments
                filled_segments.sort(key=lambda s: float(s.get("start_sec") or 0.0) if isinstance(s, dict) else 0.0)

                n_added = len(filled_segments) - len(speaker_segments)
                if n_added > 0:
                    print(f"[OK] WriterAgent [Hybrid Gap-Fill]: Added {n_added} segment(s) to fill silent gaps.")
                    speaker_segments = filled_segments

                    # Re-run anti-overlap clamp after adding new segments
                    for i in range(len(speaker_segments) - 1):
                        if speaker_segments[i].get("start_sec", 0) == speaker_segments[i+1].get("start_sec", 0):
                            speaker_segments[i+1]["start_sec"] += 0.5
                            speaker_segments[i+1]["end_sec"] = max(speaker_segments[i+1]["start_sec"] + 0.5, speaker_segments[i+1].get("end_sec", 0))
                        if speaker_segments[i].get("end_sec", 0) > speaker_segments[i+1].get("start_sec", 0):
                            speaker_segments[i]["end_sec"] = max(speaker_segments[i]["start_sec"] + 0.5, speaker_segments[i+1]["start_sec"])

            # Save Phase 1 output to state for reference
            state.speaker_transcript = speaker_segments


            # ─────────────────────────────────────────────────────────────────
            # PHASE 2: Write Myanmar narration using Phase 1 speaker transcript
            # Timestamps are COPIED from Phase 1 — no approximation
            # ─────────────────────────────────────────────────────────────────
            print("[*] WriterAgent Phase 2: Writing Myanmar narration from speaker transcript...")

            # Group consecutive lines by same speaker to reduce block count (max_blocks aware)
            grouped = self._group_speaker_segments(speaker_segments)

            # Sort grouped blocks chronologically before Phase 2 to prevent out-of-order narration
            try:
                grouped = sorted(
                    grouped,
                    key=lambda s: float(s.get("start_sec", 0)) if isinstance(s, dict) else 0
                )
            except Exception:
                pass

            # Inject per-block min/max targets so Gemini has exact numeric guidance

            for g in grouped:

                _dur = max(0.5, float(g.get("end_sec", 0)) - float(g.get("start_sec", 0)))

                g["target_min_words"] = max(1, int(_dur * 1.8))

                g["target_max_words"] = max(2, int(_dur * 4.0))

                g["target_ideal_words"] = max(1, int(_dur * 3.0))



            import json as _json
            transcript_json = _json.dumps(grouped, ensure_ascii=False, indent=2)

            phase2_prompt = (
                f"Movie Title: {state.movie_name}\n\n"
                f"Below is the complete speaker-tagged transcript extracted from the video.\n"
                f"Convert EACH entry into Myanmar dubbing narration, keeping start_sec and end_sec EXACTLY as given.\n"
                f"CRITICAL 1 (Audio Timing - BOTH Minimum AND Maximum):\n"
                f"- Each block has 'target_min_words', 'target_max_words', 'target_ideal_words' fields. YOU MUST FOLLOW THESE.\n"
                f"- Write AT LEAST target_min_words. Writing too few causes dead silence in the video. THIS IS FORBIDDEN.\n"
                f"- Write AT MOST target_max_words. Writing too many causes chipmunk-speed audio. THIS IS FORBIDDEN.\n"
                f"- Aim for target_ideal_words as your best target.\n"
                f"- For long scenes (target_ideal_words > 20): expand the dialogue naturally with emotion, emphasis, or paraphrase to FILL the time.\n"
                f"- For short scenes (target_ideal_words < 6): be ultra-concise but translate the most important meaning.\n"
                f"CRITICAL 2 (Content Priority on Short Scenes): When a scene is short and the English dialogue is long, keep the MOST IMPORTANT story beat - character reveals, emotional peaks, key plot facts. Drop filler words, NOT key content.\n"
                f"CRITICAL 3 (TTS Clarity): Ensure perfect, clear Burmese spelling and use appropriate punctuation (commas, periods) between phrases. Translate or transliterate ALL English names, loanwords, or acronyms into phonetic Burmese characters. Do NOT leave any English alphabet letters in the text.\n"
                f"CRITICAL 4: Match character visual actions on screen — write narration whose tone and emotion strictly match what the character is doing visually at that moment.\n\n"
                f"Speaker Transcript:\n{transcript_json}\n\n"
                f"Return a JSON array with fields: scene_id, speaker, narration, start_sec, end_sec, visual_cue, emotion."
            )
            phase2_raw = ask_gemini_with_video(
                file_name, PHASE2_NARRATION_SYSTEM_PROMPT, phase2_prompt,
                working_key, model=model_workhorse, temperature=0.4
            )
            parsed = self._parse_script(phase2_raw)

            if parsed and len(parsed) > 0:
                # ---------------------------------------------------------
                # PHASE 2 DROPPED BLOCK RECOVERY & TIMESTAMP MATCHING
                # ---------------------------------------------------------
                parsed_by_start = {}
                for p in parsed:
                    b_start = p.get("start_sec")
                    if b_start is not None:
                        try:
                            parsed_by_start[float(b_start)] = p
                        except (ValueError, TypeError):
                            pass

                restored_parsed = []
                # Fallback list for parsed items that had no start_sec
                unmatched_parsed = [p for p in parsed if p.get("start_sec") is None]

                for g in grouped:
                    g_start = float(g.get("start_sec", 0.0))
                    g_end = float(g.get("end_sec", g_start + 5.0))
                    
                    match = None
                    # Find matching block in parsed by start_sec (allow 2s drift)
                    for b_start, p in parsed_by_start.items():
                        if abs(b_start - g_start) < 2.0:
                            match = p
                            break
                    
                    if not match and len(unmatched_parsed) > 0:
                        match = unmatched_parsed.pop(0)

                    if match:
                        match["start_sec"] = g_start
                        match["end_sec"] = g_end
                        restored_parsed.append(match)
                    else:
                        print(f"[WARN] Gemini Phase 2 dropped block at {g_start}s. Restoring via text translation...")
                        # ---------------------------------------------------------
                        # ON-THE-FLY TRANSLATION FOR DROPPED BLOCKS
                        # ---------------------------------------------------------
                        from brain.gemini_client import call_gemini
                        fallback_prompt = (
                            "Translate the following English movie dialogue into natural, colloquial Myanmar (Burmese) dubbing narration.\n"
                            "Return ONLY the Myanmar text. Do not add quotes or explanations.\n\n"
                            f"Original Text: \"{g.get('text', '')}\""
                        )
                        try:
                            # Quick call to Gemini Flash to translate the single missing line
                            fallback_mm, _ = call_gemini(
                                "You are a Myanmar movie dubbing scriptwriter. Translate exactly as spoken.",
                                fallback_prompt,
                                working_key,
                                "gemini-3.5-flash-lite",
                                temperature=0.3
                            )
                        except Exception as e:
                            print(f"[!] Fallback translation failed: {e}")
                            fallback_mm = g.get('text', '')[:100]  # emergency fallback
                        
                        fallback_mm = fallback_mm.strip().strip('"').strip("'")
                        
                        fallback_block = {
                            "scene_id": g.get("scene_id", len(restored_parsed) + 1),
                            "speaker": g.get("speaker", "Unknown"),
                            "gender": g.get("gender", "Unknown"),
                            "narration": fallback_mm,
                            "start_sec": g_start,
                            "end_sec": g_end,
                            "visual_cue": "Restored missing block",
                            "emotion": "normal"
                        }
                        restored_parsed.append(fallback_block)

                # Ensure chronological order
                restored_parsed.sort(key=lambda x: float(x.get("start_sec") or 0.0) if isinstance(x, dict) else 0.0)
                print(f"[OK] WriterAgent Phase 2: Restored to full {len(restored_parsed)} narration blocks.")

                # Post-Phase-2 narration length validation (expand too-short, trim too-long)
                try:
                    restored_parsed = self._validate_narration_lengths(restored_parsed, working_key, model_workhorse)
                except Exception as _val_err:
                    print(f"[WARN] WriterAgent: Narration validation error (non-fatal): {_val_err}")

                return restored_parsed


        except Exception as e:
            print(f"[!] WriterAgent 2-Phase Pipeline failed: {e}")
        finally:
            if file_name and working_key:
                delete_video_file(file_name, working_key)

        return None

    def _native_video_recap_fallback(self, chapters, state, file_name, working_key, model):
        """Fallback: single-phase recap (old method) when Phase 1 extraction fails."""
        from brain.gemini_client import ask_gemini_with_video
        from brain.prompts import FULL_RECAP_SYSTEM_PROMPT

        subs_text = ""
        for ch in chapters:
            dialogue_str = "\n".join(ch.get("dialogues", []))
            if dialogue_str and "[No dialogue" not in dialogue_str:
                subs_text += f"[{ch.get('time_range', '')}] {dialogue_str}\n"

        user_prompt = (
            f"Movie Title: {state.movie_name}\n"
            f"Genre: {state.genre or 'Drama'}\n"
            f"Full Video Timeline Subtitles:\n{subs_text}\n\n"
            f"Write a continuous descriptive storytelling script in natural spoken Burmese.\n"
            f"Divide into around {len(chapters)} blocks. Output JSON array.\n"
            f'[{{"scene_id": "1", "narration": "...", "visual_cue": "..."}}]'
        )
        try:
            raw = ask_gemini_with_video(file_name, FULL_RECAP_SYSTEM_PROMPT, user_prompt, working_key, model=model)
            return self._parse_script(raw)
        except Exception as e:
            print(f"[!] Fallback also failed: {e}")
            return None

    def _align_speaker_segments_with_whisper(self, speaker_segments: list, whisper_transcript: list) -> list:
        """
        Cross-references Gemini Phase 1 speaker transcript with local Whisper STT timestamps.
        Replaces drifted Gemini video timestamps with Whisper's 100% accurate audio waveform timestamps.
        """
        from difflib import SequenceMatcher

        # BUG-H2 Fix: Early-exit when whisper transcript is empty — no point running O(n*m) loop
        if not whisper_transcript:
            return speaker_segments

        def ratio(a, b):
            return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()

        aligned = []
        for g in speaker_segments:
            g_text = g.get("text", "")
            if not g_text:
                aligned.append(g)
                continue

            best_w = None
            best_score = 0.0
            for w in whisper_transcript:
                w_text = getattr(w, "text", "") if hasattr(w, "text") else w.get("text", "") if isinstance(w, dict) else ""
                score = ratio(g_text, w_text)
                if score > best_score:
                    best_score = score
                    best_w = w

            if best_w and best_score >= 0.45:
                w_start = getattr(best_w, "start", 0.0) if hasattr(best_w, "start") else best_w.get("start", 0.0) if isinstance(best_w, dict) else 0.0
                w_end = getattr(best_w, "end", 0.0) if hasattr(best_w, "end") else best_w.get("end", 0.0) if isinstance(best_w, dict) else 0.0
                
                # Update with Whisper's exact waveform timestamps if valid
                if w_end > w_start:
                    if w_end - w_start > 6.0:
                        # Whisper chunk is too long (contains many sentences). 
                        # Proportionally interpolate the timestamp based on text position.
                        try:
                            match_idx = w_text.lower().find(g_text[:30].lower())
                            if match_idx == -1: 
                                match_idx = 0
                            
                            start_ratio = match_idx / max(len(w_text), 1)
                            end_ratio = min(1.0, (match_idx + len(g_text)) / max(len(w_text), 1))
                            
                            exact_start = w_start + (w_end - w_start) * start_ratio
                            exact_end = w_start + (w_end - w_start) * end_ratio
                            
                            g["start_sec"] = float(round(exact_start, 2))
                            g["end_sec"] = float(round(exact_end, 2))
                        except Exception:
                            pass
                    else:
                        # Short chunk — safe to overwrite entirely
                        g["start_sec"] = float(round(w_start, 2))
                        g["end_sec"] = float(round(w_end, 2))

            aligned.append(g)

        return aligned

    def _parse_speaker_transcript(self, raw: str) -> list:
        """Parse Phase 1 output: JSON array of {speaker, text, start_sec, end_sec}."""
        import json, re
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        # Try direct parse
        for open_c, close_c in [('[', ']'), ('{', '}')]:
            start = clean.find(open_c)
            end = clean.rfind(close_c)
            if start != -1 and end > start:
                try:
                    data = json.loads(clean[start:end + 1])
                    if isinstance(data, dict):
                        # BUG-H3 Fix: Check for wrapped list keys before blindly wrapping in [].
                        # e.g. {"segments": [...]} or {"items": [...]} should unwrap the inner list.
                        data = (data.get("segments") or data.get("items") or
                                data.get("data") or data.get("transcript") or [data])
                    validated = []
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        seg = {
                            "speaker": str(item.get("speaker", "Unknown")).strip(),
                            "gender": str(item.get("gender", "Unknown")).strip(),
                            "text": str(item.get("text", "")).strip(),
                            "start_sec": float(item.get("start_sec", 0.0)),
                            "end_sec": float(item.get("end_sec", 0.0)),
                        }
                        if seg["text"] and seg["end_sec"] >= seg["start_sec"]:
                            validated.append(seg)
                    if validated:
                        # --- CRITICAL FIX: ANTI-OVERLAP CLAMP ---
                        # Gemini Phase 1 sometimes hallucinates massive durations (e.g. 25s) 
                        # that swallow subsequent blocks. We strictly clamp end_sec to prevent overlap.
                        validated.sort(key=lambda x: float(x.get("start_sec") or 0.0) if isinstance(x, dict) else 0.0)
                        for i in range(len(validated) - 1):
                            if validated[i]["start_sec"] == validated[i+1]["start_sec"]:
                                validated[i+1]["start_sec"] += 0.5
                                validated[i+1]["end_sec"] = max(validated[i+1]["start_sec"] + 0.5, validated[i+1]["end_sec"])
                            if validated[i]["end_sec"] > validated[i+1]["start_sec"]:
                                # Ensure it doesn't invert if they perfectly overlap at start
                                validated[i]["end_sec"] = max(validated[i]["start_sec"] + 0.5, validated[i+1]["start_sec"])
                                
                        return validated
                except Exception:
                    pass
        return []


    def _validate_narration_lengths(self, blocks: list, api_key, model: str) -> list:
        """
        Post-Phase-2 guard: checks every block for narration length vs duration.
        Blocks that are too short (< duration * 1.5 chars) get expanded via a quick Gemini call.
        Blocks that are too long (> duration * 5.5 chars) get trimmed.
        """
        from brain.gemini_client import call_gemini
        CHARS_PER_SEC = 12.0
        too_short, too_long = [], []

        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            narration = b.get("narration", "").strip()
            if not narration:
                continue
            dur = max(0.5, float(b.get("end_sec", 0)) - float(b.get("start_sec", 0)))
            n_chars = len(narration)
            min_chars = dur * 1.5 * (CHARS_PER_SEC / 4)   # ~4.5 chars/s minimum
            max_chars = dur * 5.5 * (CHARS_PER_SEC / 4)   # ~16.5 chars/s absolute max

            if n_chars < min_chars and dur > 4.0:
                too_short.append((i, b, dur, int(dur * 3.0 * (CHARS_PER_SEC / 4))))
            elif n_chars > max_chars:
                too_long.append((i, b, dur, int(max_chars)))

        if not too_short and not too_long:
            print("[*] WriterAgent Validate: All narration lengths are within acceptable bounds.")
            return blocks

        if too_short:
            print(f"[*] WriterAgent Validate: {len(too_short)} block(s) too short — expanding...")
            for i, b, dur, target_chars in too_short:
                prompt = (
                    f"The following Myanmar (Burmese) dubbed dialogue for a {dur:.1f}s video scene is too short.\n"
                    f"Expand it naturally to approximately {target_chars} characters while keeping the same meaning and colloquial style.\n"
                    f"Add natural emotion, pauses, emphasis, or rephrase to fill the time.\n"
                    f"Output ONLY the expanded Myanmar text. No quotes, no explanations.\n\n"
                    f"Original: {b.get('narration', '')}"
                )
                try:
                    expanded, _ = call_gemini(
                        "You are a Myanmar movie dubbing writer. Expand the given text naturally.",
                        prompt, api_key, model, temperature=0.5
                    )
                    expanded = expanded.strip().strip('"').strip("'")
                    if expanded and len(expanded) > len(b.get("narration", "")):
                        blocks[i]["narration"] = expanded
                        blocks[i]["_length_expanded"] = True
                        print(f"    - Block {b.get('scene_id','?')} expanded: {len(b.get('narration',''))}c -> {len(expanded)}c")
                except Exception as e:
                    print(f"    [WARN] Expand failed for block {i}: {e}")

        if too_long:
            print(f"[*] WriterAgent Validate: {len(too_long)} block(s) too long — trimming...")
            for i, b, dur, max_chars in too_long:
                narration = b.get("narration", "")
                # Simple trim: cut at nearest sentence boundary
                trimmed = narration[:max_chars]
                last_punct = max(trimmed.rfind("။"), trimmed.rfind("!"), trimmed.rfind("?"), trimmed.rfind(","))
                if last_punct > max_chars * 0.6:
                    trimmed = trimmed[:last_punct + 1]
                blocks[i]["narration"] = trimmed.strip()
                blocks[i]["_length_trimmed"] = True
                print(f"    - Block {b.get('scene_id','?')} trimmed: {len(narration)}c -> {len(trimmed)}c")

        return blocks


    def _group_speaker_segments(self, segments: list) -> list:
        """
        Group consecutive segments by the same speaker into single blocks.

        SYNC RULE: Short segments (≤ MIN_SOLO_DUR seconds) are NEVER merged into a
        neighbouring block — they keep their own precise start/end timestamps so that
        brief lines like "Oh, thanks." or "Marry someone else?" maintain exact
        lip-sync with the character's mouth movement.
        """
        if not segments:
            return []

        # Segments shorter than this stay as solo blocks (not merged)
        MIN_SOLO_DUR = 3.0

        def _finalise(seg):
            s = float(seg.get("start_sec", 0.0) or 0.0)
            e = float(seg.get("end_sec", s + 1.0) or (s + 1.0))
            seg["start_sec"] = s
            seg["end_sec"] = e
            seg["target_dur_sec"] = round(e - s, 1)
            # Burmese average reading speed is ~2.5 to 3 syllables/words per second.
            # Limit strictly to 2.5 words per second to ensure conversational brevity and 10% shorter margins.
            seg["max_words_allowed"] = max(1, int(round(seg["target_dur_sec"] * 2.5)))
            return seg

        grouped = []
        current = dict(segments[0])

        for seg in segments[1:]:
            s_seg = float(seg.get("start_sec", 0.0) or 0.0)
            e_seg = float(seg.get("end_sec", s_seg) or s_seg)
            s_cur = float(current.get("start_sec", 0.0) or 0.0)
            e_cur = float(current.get("end_sec", s_cur) or s_cur)
            seg_dur = e_seg - s_seg
            cur_dur = e_cur - s_cur
            same_spkr = seg.get("speaker") == current.get("speaker")
            close_gap = (s_seg - e_cur) < 1.5

            # Merge only when BOTH segments are long enough and speaker matches
            if same_spkr and close_gap and seg_dur > MIN_SOLO_DUR and cur_dur > MIN_SOLO_DUR:
                current["text"] = str(current.get("text", "")) + " " + str(seg.get("text", ""))
                current["end_sec"] = e_seg
            else:
                grouped.append(_finalise(current))
                current = dict(seg)

        grouped.append(_finalise(current))

        # Remove naive max_blocks merge logic to preserve exact sync.
        # Merging across large silences forces continuous TTS over silent video parts.
        return grouped





    def _get_previous_episode_context(self, state) -> str:
        import os, re, json
        import brain.config as cfg
        match = re.search(r'(.+?)[_\s-]*((?:Episode|Ep|S\d+E|Season)\s*[-_]?)(\d+)(.*)', state.movie_name, flags=re.IGNORECASE)
        if not match:
            return ""
            
        series = match.group(1).strip('_ -')
        ep_num = int(match.group(3))
        
        if ep_num <= 1:
            return ""
            
        prev_ep_num = ep_num - 1
        
        config_data = cfg.load_config()
        output_dir_base = config_data.get("paths", {}).get("output_dir", "outputs")
        series_dir = os.path.join(output_dir_base, series)
        
        if not os.path.exists(series_dir):
            return ""
            
        prev_state_path = None
        try:
            # BUG-M9 Fix: Wrap os.listdir() in try/except — PermissionError uncaught on Windows otherwise
            for d in os.listdir(series_dir):
                d_path = os.path.join(series_dir, d)
                if os.path.isdir(d_path):
                    m = re.search(r'\d+', d)
                    if m and int(m.group()) == prev_ep_num:
                        maybe_state = os.path.join(d_path, "state.json")
                        if os.path.exists(maybe_state):
                            prev_state_path = maybe_state
                            break
        except OSError as e:
            print(f"[WARN] WriterAgent: Could not list previous episode directories: {e}")
            return ""
        
        if not prev_state_path:
            return ""
            
        print(f"[*] WriterAgent: Found previous episode memory -> {prev_state_path}")
        try:
            with open(prev_state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            gen_script = data.get("generated_script", [])
            if gen_script and len(gen_script) > 0:
                last_blocks = gen_script[-2:]
                context_text = " ".join([b.get("narration", "") for b in last_blocks])
                print(f"[*] WriterAgent: Extracted {len(last_blocks)} blocks from previous episode for continuity.")
                return context_text
        except Exception as e:
            print(f"[WARN] WriterAgent: Failed to read previous episode state: {e}")
            
        return ""

    # ─────────────────────────────────────────────────────
    # CHAPTER BUILDER — splits transcript by time
    # ─────────────────────────────────────────────────────
    def _build_chapters(self, state) -> list:
        import os, math, re
        DEFAULT_CHAPTERS = 5
        n = int(os.getenv("RECAP_CHAPTERS", str(DEFAULT_CHAPTERS)))

        segments = []
        if state.transcript:
            for seg in state.transcript:
                t = getattr(seg, "start", None)
                txt = getattr(seg, "text", "").strip()
                if txt and t is not None:
                    segments.append((float(t), txt))
        
        segments.sort(key=lambda x: x[0])

        # 1. Use SceneAgent timeline if available
        if getattr(state, "timeline", None) and len(state.timeline) > 0:
            print(f"[*] WriterAgent: Using precise SceneAgent timeline ({len(state.timeline)} chapters).")
            chapters = []
            for scene in state.timeline:
                t_start = scene.start_sec
                t_end = scene.end_sec
                dialogues = [txt for (t, txt) in segments if t_start <= t < t_end]
                dialogues = [re.sub(r'\s+', ' ', d).strip()[:200] for d in dialogues if len(d.strip()) > 4]
                
                chapters.append({
                    "chapter": scene.scene_id,
                    "t_start": t_start,
                    "time_range": f"{scene.start_time} - {scene.end_time}",
                    "dialogues": dialogues[:25]
                })
            return chapters

        # 2. Fallback to time-based mathematical chunking
        if not segments:
            duration_sec = 120.0
            if getattr(state, "duration", None):
                try:
                    parts = str(state.duration).split(":")
                    if len(parts) == 3:
                        duration_sec = int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
                except:
                    pass
            
            chapters = []
            # BUG-H1 Fix: Use DEFAULT_CHAPTERS (5) when RECAP_CHAPTERS not set.
            # Without this, chunk_size=15.0 for a 2-hour movie → 480 chunks!
            n_chapters = int(os.getenv("RECAP_CHAPTERS", "0") or "0")
            if n_chapters <= 0:
                n_chapters = DEFAULT_CHAPTERS  # cap at 5 (same as main path)
            chunk_size = duration_sec / n_chapters if duration_sec > 0 else 30.0
            n_chunks = min(n_chapters, max(1, int(math.ceil(duration_sec / chunk_size))))

            for i in range(n_chunks):
                t_start = i * chunk_size
                t_end = (i + 1) * chunk_size
                # Use HH:MM:SS format like _format_time() in scene_agent.py
                h_s = int(t_start // 3600); m_s = int((t_start % 3600) // 60); s_s = int(t_start % 60)
                h_e = int(t_end // 3600);   m_e = int((t_end % 3600) // 60);   s_e = int(t_end % 60)
                time_range = (f"{h_s:02d}:{m_s:02d}:{s_s:02d} - {h_e:02d}:{m_e:02d}:{s_e:02d}"
                              if h_s > 0 or h_e > 0
                              else f"{m_s:02d}:{s_s:02d} - {m_e:02d}:{s_e:02d}")
                chapters.append({
                    "chapter": i + 1,
                    "t_start": t_start,
                    "time_range": time_range,
                    "dialogues": ["[No dialogue available]"]
                })
            return chapters

        total_duration = segments[-1][0] if segments else 120.0
        n_chapters = int(os.getenv("RECAP_CHAPTERS", str(DEFAULT_CHAPTERS)))
        if n_chapters > 0 and total_duration > 0:
            chunk_size = total_duration / n_chapters
        else:
            chunk_size = 15.0
        n_chunks = max(1, int(math.ceil(total_duration / chunk_size)))

        chapters = []
        for i in range(n_chunks):
            t_start = i * chunk_size
            t_end   = (i + 1) * chunk_size
            dialogues = [
                txt for (t, txt) in segments
                if t_start <= t < t_end
            ]
            dialogues = [
                re.sub(r'\s+', ' ', d).strip()[:200]
                for d in dialogues
                if len(d.strip()) > 4
            ]
            if not dialogues and n > 1:
                continue

            matching_segs = [(t, txt) for (t, txt) in segments if t_start <= t < t_end]
            actual_t_start = matching_segs[0][0] if matching_segs else t_start

            mm_start = int(actual_t_start // 60)
            ss_start = int(actual_t_start % 60)
            mm_end   = int(t_end // 60)
            ss_end   = int(t_end % 60)

            chapters.append({
                "chapter":    len(chapters) + 1,
                "t_start":    actual_t_start,
                "time_range": f"{mm_start:02d}:{ss_start:02d} - {mm_end:02d}:{ss_end:02d}",
                "dialogues":  dialogues[:25],   
            })

        return chapters or [{"chapter": 1, "time_range": "Full video", "dialogues": ["[No dialogue available]"]}]



    # ─────────────────────────────────────────────────────
    # JSON PARSER
    # ─────────────────────────────────────────────────────
    def _parse_script(self, raw: str):
        """Robustly extracts a JSON array from LLM output."""
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        clean = re.sub(r',\s*([\]}])', r'\1', clean)

        # Strategy 1: Direct parse
        try:
            return self._normalise(json.loads(clean))
        except json.JSONDecodeError:
            pass

        # Strategy 2: Slice from first [ to last ]
        for open_c, close_c in [('[', ']'), ('{', '}')]:
            start = clean.find(open_c)
            end   = clean.rfind(close_c)
            if start != -1 and end > start:
                try:
                    return self._normalise(json.loads(clean[start:end + 1]))
                except json.JSONDecodeError:
                    pass

        # Strategy 3: Strip trailing extra brackets
        clean_brackets = re.sub(r'\]\s*\]+$', ']', clean)
        try:
            return self._normalise(json.loads(clean_brackets))
        except json.JSONDecodeError:
            pass

        # Strategy 4: Regex full array (greedy match from first [ to last ])
        m = re.search(r'\[.*\]', clean_brackets, re.DOTALL)
        if m:
            try:
                return self._normalise(json.loads(m.group()))
            except json.JSONDecodeError:
                pass
                
        # Strategy 5: Stack-based JSON extraction (most robust)
        start_idx = clean.find('[')
        if start_idx != -1:
            stack = 0
            for i in range(start_idx, len(clean)):
                if clean[i] == '[': stack += 1
                elif clean[i] == ']': stack -= 1
                if stack == 0:
                    try:
                        return self._normalise(json.loads(clean[start_idx:i+1]))
                    except json.JSONDecodeError:
                        break

        # Strategy 6: Plain paragraphs → blocks
        paragraphs = [p.strip() for p in raw.split('\n\n') if len(p.strip()) > 20]
        if paragraphs:
            print(f"[*] WriterAgent: Extracted {len(paragraphs)} paragraphs from plain text.")
            return [
                {
                    "scene_id":   str(i + 1),
                    "narration":  p,
                    "visual_cue": "Continue narration",
                }
                for i, p in enumerate(paragraphs)
            ]

        return None

    def _normalise(self, data) -> list:
        """Ensure the script is a list of dicts with string values.
        CRITICAL: Preserve start_sec and end_sec so video sync is never broken.
        """
        if isinstance(data, dict):
            data = [data]
        result = []
        for i, item in enumerate(data):
            if not item.get("narration", "").strip():
                continue
            block = {
                "scene_id":   str(item.get("scene_id", i + 1)),
                "narration":  str(item.get("narration", "")),
                "visual_cue": str(item.get("visual_cue", "Continue narration")),
            }
            # Preserve exact timestamps — these drive character lip-sync placement
            if "start_sec" in item:
                block["start_sec"] = float(item["start_sec"])
            if "end_sec" in item:
                block["end_sec"] = float(item["end_sec"])
            if "speaker" in item:
                block["speaker"] = str(item["speaker"])
            if "gender" in item:
                block["gender"] = str(item["gender"])
            if "emotion" in item:
                block["emotion"] = str(item["emotion"])
            result.append(block)
        return result
