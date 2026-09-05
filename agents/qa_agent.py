import os
import json
import re
from brain.memory import MovieState
from brain.prompts import QA_SYNC_SYSTEM_PROMPT, QA_LANGUAGE_SYSTEM_PROMPT, OUTPUT_VIDEO_EXTRACT_SYSTEM_PROMPT
from brain.gemini_client import upload_video_file, ask_gemini_with_video, delete_video_file, call_gemini


class QAAgent:
    """
    Gemini-powered Quality Assurance Agent.

    Checks:
      1. OUTPUT EXTRACT — re-extracts Myanmar spoken lines + visual actions from output video -> state.output_video_transcript
      2. SYNC CHECK  — uploads final recap video -> Gemini reviews narration timing
      3. LANGUAGE QA — sends narration script blocks -> Gemini reviews colloquialism

    Outputs:
      - outputs/<project>/qa_report.json
      - outputs/<project>/qa_report.txt
    """

    def __init__(self, output_dir: str = "outputs", auto_rewrite_threshold: int = 6):
        self.output_dir = output_dir
        self.auto_rewrite_threshold = auto_rewrite_threshold

    def enforce_duration_constraints(self, state: MovieState) -> MovieState:
        """
        Runs immediately after script generation. 
        Estimates audio duration of the script based on character count.
        If a block is excessively long (causing <0.75x slow motion), it automatically calls Gemini to summarize and shorten it.
        """
        import brain.config as cfg
        from brain.gemini_client import call_gemini
        
        script_blocks = state.generated_script or []
        if not script_blocks:
            return state

        config_data = cfg.load_config()
        api_key = config_data.get("gemini", {}).get("api_keys") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return state
            
        model = config_data.get("gemini", {}).get("models", {}).get("workhorse", "gemini-3.5-flash")
        blocks_to_rewrite = []
        chars_per_sec = 9.5  # Burmese Edge-TTS reading speed (~9.5 characters/sec)
        max_stretch = 1.25  # Allows audio to be up to 1.25x target duration

        for i, block in enumerate(script_blocks):
            if not isinstance(block, dict): continue
            narration = block.get("narration", "").strip()
            if not narration: continue
            
            start = float(block.get("start_sec") or 0.0)
            end = float(block.get("end_sec") or (start + 3.0))
            target_dur = max(0.8, end - start)
            
            estimated_dur = len(narration) / chars_per_sec
            
            # If the audio is expected to exceed the target duration...
            if estimated_dur > (target_dur * max_stretch):
                target_chars = int(target_dur * chars_per_sec)
                blocks_to_rewrite.append({
                    "index": i,
                    "scene_id": block.get("scene_id", i+1),
                    "original": narration,
                    "target_chars": target_chars,
                    "target_dur": target_dur
                })
        
        if not blocks_to_rewrite:
            print("[*] QAAgent (Auto-Rewrite): All script blocks fit within acceptable timing bounds.")
            return state
            
        print(f"[*] QAAgent (Auto-Rewrite): Found {len(blocks_to_rewrite)} over-length script blocks. Calling Gemini in batches to shorten them...")
        
        system_prompt = (
            "You are a professional Myanmar dubbing scriptwriter and video editor.\n"
            "Your task: Shorten the provided Burmese dialogue blocks to fit within the target character limit.\n"
            "RULES FOR SHORTENING:\n"
            "1. PRESERVE the single most important story beat in each block (character reveals, emotional peaks, key plot facts).\n"
            "2. DROP filler words, repetitive phrases, and secondary details - NOT key content.\n"
            "3. NEVER drop: character names, emotional turning points, or plot-critical information.\n"
            "4. Keep the natural colloquial Burmese style (use particles: လေ, ပေါ့, ကွာ, ဗျာ).\n"
            "5. Output ONLY a valid JSON array of objects with: scene_id and rewritten_narration. No markdown."
        )

        BATCH_SIZE = 15
        rewritten_count = 0
        import math
        total_batches = math.ceil(len(blocks_to_rewrite) / BATCH_SIZE)

        for b_idx in range(0, len(blocks_to_rewrite), BATCH_SIZE):
            batch = blocks_to_rewrite[b_idx:b_idx + BATCH_SIZE]
            batch_num = (b_idx // BATCH_SIZE) + 1

            prompt_lines = []
            for b in batch:
                prompt_lines.append(f"Block {b['scene_id']} (Must be < {b['target_chars']} characters):\nORIGINAL: {b['original']}")
            
            user_prompt = "Rewrite the following blocks:\n\n" + "\n\n".join(prompt_lines)
            
            try:
                raw, _ = call_gemini(system_prompt, user_prompt, api_key, model=model, temperature=0.2, max_tokens=2048)
                parsed = self._parse_json(raw)
                if not parsed:
                    try:
                        import json
                        parsed = json.loads(raw)
                    except Exception:
                        pass
                
                if isinstance(parsed, dict) and "blocks" in parsed:
                    parsed = parsed["blocks"]
                    
                if isinstance(parsed, list):
                    rewrite_map = {str(item.get("scene_id")): item.get("rewritten_narration") for item in parsed if isinstance(item, dict)}
                    
                    for b in batch:
                        idx = b["index"]
                        scene_id = str(b["scene_id"])
                        if scene_id in rewrite_map and rewrite_map[scene_id]:
                            old_len = len(state.generated_script[idx]["narration"])
                            new_text = str(rewrite_map[scene_id]).strip()
                            if new_text:
                                new_len = len(new_text)
                                state.generated_script[idx]["narration"] = new_text
                                state.generated_script[idx]["qa_rewritten_for_length"] = True
                                rewritten_count += 1
            except Exception as e:
                print(f"[WARN] QAAgent (Auto-Rewrite): Batch {batch_num} failed: {e}")

        print(f"[OK] QAAgent (Auto-Rewrite): Successfully shortened {rewritten_count}/{len(blocks_to_rewrite)} over-length script blocks.")
        return state

    def review_and_rewrite_script(self, state: MovieState) -> MovieState:
        """
        Runs language quality check on narration script BEFORE voice generation (Phase 4.1c).
        Rewrites awkward or unnatural Burmese phrasing so VoiceAgent synthesizes natural audio.
        """
        import brain.config as cfg
        config_data = cfg.load_config()
        qa_cfg = config_data.get("qa", {})
        if not qa_cfg.get("enabled", False) or not qa_cfg.get("language_check", True):
            return state

        api_key = config_data.get("gemini", {}).get("api_keys") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return state

        model_workhorse = config_data.get("gemini", {}).get("models", {}).get("workhorse", "gemini-3.5-flash")
        print("[*] QAAgent: Reviewing script Burmese colloquialism before TTS synthesis...")
        lang_result = self._run_language_check(state, api_key, model_workhorse)
        if lang_result:
            rewrite_threshold = qa_cfg.get("auto_rewrite_threshold", self.auto_rewrite_threshold)
            if rewrite_threshold > 0:
                state = self._apply_rewrites(state, lang_result, rewrite_threshold)
            if not getattr(state, "qa_results", None):
                state.qa_results = {}
            state.qa_results["language"] = lang_result
        return state

    def review(self, state: MovieState, original_video_path: str, recap_video_path: str) -> MovieState:
        print("\n--- [Phase 7: QA Review --- Gemini Video Analysis] ---")

        import brain.config as cfg
        config_data = cfg.load_config()
        gemini_cfg = config_data.get("gemini", {})
        api_key = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[!] QAAgent: No Gemini API key. Skipping QA.")
            return state

        models_dict = gemini_cfg.get("models", {})
        model_heavy = models_dict.get("heavy", "gemini-3.5-flash")
        model_workhorse = models_dict.get("workhorse", "gemini-3.5-flash")
        qa_cfg = config_data.get("qa", {})
        do_sync_check = qa_cfg.get("sync_check", True)
        do_language_check = qa_cfg.get("language_check", True)

        qa_results = {"movie_name": state.movie_name, "sync": None, "language": None}

        # ── Upload output video ONCE, reuse for both extract + sync check ────
        # Avoids double-uploading the same file to Gemini File API
        recap_file_name = None
        recap_working_key = None
        if os.path.exists(recap_video_path):
            try:
                print(f"[*] QAAgent: Uploading output video to Gemini (single upload for all QA tasks)...")
                recap_file_name, recap_working_key = upload_video_file(recap_video_path, api_key)
                print(f"[OK] QAAgent: Video uploaded -> {recap_file_name}")
            except Exception as e:
                print(f"[!] QAAgent: Video upload failed: {e}")

        try:
            if recap_file_name:
                # ── Task 1: Extract Myanmar voiceover + visual action details ──
                print(f"[*] QAAgent: Extracting output video transcript & visual actions...")
                output_transcript = self._extract_output_video_transcript_with_file(
                    recap_file_name, recap_working_key, state, model_heavy
                )
                if output_transcript:
                    state.output_video_transcript = output_transcript
                    print(f"[OK] QAAgent: Extracted {len(output_transcript)} output video details into state.json")

                # ── Task 2: Sync check using the SAME uploaded file ────────────
                if do_sync_check:
                    print(f"[*] QAAgent: Running sync review on uploaded video...")
                    sync_result = self._run_sync_check_with_file(
                        recap_file_name, recap_working_key, state, model_heavy
                    )
                    if sync_result:
                        qa_results["sync"] = sync_result
                        print(f"[OK] QAAgent: Sync score = {sync_result.get('overall_sync_score', 'N/A')}/10")
        finally:
            # ── Delete video file once, after both tasks complete ─────────────
            if recap_file_name and recap_working_key:
                try:
                    delete_video_file(recap_file_name, recap_working_key)
                except Exception:
                    pass

        if do_language_check and state.generated_script:
            if getattr(state, "qa_results", None) and state.qa_results.get("language"):
                qa_results["language"] = state.qa_results["language"]
                print(f"[OK] QAAgent: Reusing pre-TTS language QA results.")
            else:
                print(f"[*] QAAgent: Reviewing Myanmar narration language quality...")
                lang_result = self._run_language_check(state, api_key, model_workhorse)
                if lang_result:
                    qa_results["language"] = lang_result
                    print(f"[OK] QAAgent: Language naturalness score = {lang_result.get('overall_language_score', 'N/A')}/10")

        project_output_dir = os.path.join(self.output_dir, state.project_dir)
        self._save_reports(qa_results, project_output_dir)

        rewrite_threshold = qa_cfg.get("auto_rewrite_threshold", self.auto_rewrite_threshold)
        if qa_results["language"] and rewrite_threshold > 0:
            state = self._apply_rewrites(state, qa_results["language"], rewrite_threshold)

        state.qa_results = qa_results
        return state

    def _run_sync_check_with_file(self, file_name, working_key, state, model):
        """Run sync check using an already-uploaded Gemini file reference."""
        try:
            script_blocks = state.generated_script or []
            script_summary = ""
            for i, block in enumerate(script_blocks):
                if isinstance(block, dict):
                    start = block.get("start_sec", "?")
                    end = block.get("end_sec", "?")
                    narration = block.get("narration", "")[:80]
                    script_summary += f"  Block {i+1}: [{start}s-{end}s] {narration}\n"

            user_prompt = (
                f"Movie: {state.movie_name}\n\n"
                f"This is a Myanmar recap video with voiceover dubbed over the original.\n\n"
                f"Expected narration schedule:\n{script_summary}\n"
                f"Watch the full video and evaluate sync accuracy per narration block. Return JSON."
            )
            raw = ask_gemini_with_video(
                file_name, QA_SYNC_SYSTEM_PROMPT, user_prompt,
                working_key, model=model, temperature=0.1
            )
            return self._parse_json(raw)
        except Exception as e:
            print(f"[!] QAAgent Sync Check failed: {e}")
            return None



    def _run_language_check(self, state, api_key, model):
        script_blocks = state.generated_script or []
        if not script_blocks:
            return None

        blocks_text = ""
        for i, block in enumerate(script_blocks):
            if isinstance(block, dict):
                scene_id = block.get("scene_id", i + 1)
                narration = block.get("narration", "")
                speaker = block.get("speaker", "")
                speaker_note = f" [{speaker}]" if speaker else ""
                start_s = float(block.get("start_sec", 0.0))
                end_s = float(block.get("end_sec", start_s + 2.0))
                duration = max(0.5, end_s - start_s)
                blocks_text += f"Block {scene_id}{speaker_note} (Duration: {duration:.1f}s, Target Syllables: ~{int(duration*4)}):\n{narration}\n\n"

        user_prompt = (
            f"Movie: {state.movie_name}\n\n"
            f"Myanmar narration script blocks:\n\n{blocks_text}"
            f"Review each block for natural colloquial Burmese. Return JSON."
        )
        try:
            raw, _ = call_gemini(
                QA_LANGUAGE_SYSTEM_PROMPT, user_prompt,
                api_key, model=model, temperature=0.1, max_tokens=8192
            )
            return self._parse_json(raw)
        except Exception as e:
            print(f"[!] QAAgent Language Check failed: {e}")
            return None

    def _apply_rewrites(self, state, lang_result, threshold):
        blocks_qa = lang_result.get("blocks", [])
        if not blocks_qa or not state.generated_script:
            return state

        rewrite_map = {}
        for qa_block in blocks_qa:
            score = float(qa_block.get("score", 10))
            rewrite = qa_block.get("suggested_rewrite")
            if score < threshold and rewrite:
                rewrite_map[str(qa_block.get("scene_id", ""))] = rewrite

        if not rewrite_map:
            print("[*] QAAgent: No blocks below threshold.")
            return state

        rewritten_count = 0
        for block in state.generated_script:
            if not isinstance(block, dict):
                continue
            sid = str(block.get("scene_id", ""))
            if sid in rewrite_map:
                old = block.get("narration", "")
                block["narration"] = rewrite_map[sid]
                block["qa_rewritten"] = True
                print(f"[QA] Block {sid} rewritten (score was below {threshold})")
                print(f"     OLD: {old[:70]}...")
                print(f"     NEW: {rewrite_map[sid][:70]}...")
                rewritten_count += 1

        if rewritten_count > 0:
            print(f"[OK] QAAgent: Applied {rewritten_count} language rewrites.")
        return state

    def _save_reports(self, qa_results, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        json_path = os.path.join(output_dir, "qa_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(qa_results, f, ensure_ascii=False, indent=2)
        print(f"[SAVED] QAAgent: {json_path}")

        txt_path = os.path.join(output_dir, "qa_report.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{'='*55}\n")
            f.write(f"QA REPORT -- {qa_results.get('movie_name', 'Unknown')}\n")
            f.write(f"{'='*55}\n\n")

            sync = qa_results.get("sync")
            if sync:
                f.write(f"SYNC ACCURACY\n")
                f.write(f"  Overall: {sync.get('overall_sync_score', 'N/A')}/10\n\n")
                for b in sync.get("blocks", []):
                    score = b.get("score", "?")
                    try:
                        icon = "OK" if float(score) >= 7 else ("WARN" if float(score) >= 5 else "BAD")
                    except Exception:
                        icon = "?"
                    f.write(f"  Block {b.get('scene_id')}: {score}/10 [{icon}] {b.get('note', '')}\n")
                    if b.get("issue"):
                        f.write(f"    Issue: {b['issue']}\n")
            else:
                f.write("SYNC ACCURACY: Skipped\n")

            f.write("\n")

            lang = qa_results.get("language")
            if lang:
                f.write(f"LANGUAGE NATURALNESS\n")
                f.write(f"  Overall: {lang.get('overall_language_score', 'N/A')}/10\n")
                f.write(f"  Summary: {lang.get('summary', '')}\n\n")
                for b in lang.get("blocks", []):
                    score = b.get("score", "?")
                    try:
                        icon = "OK" if float(score) >= 7 else ("WARN" if float(score) >= 5 else "BAD")
                    except Exception:
                        icon = "?"
                    f.write(f"  Block {b.get('scene_id')}: {score}/10 [{icon}]\n")
                    for issue in (b.get("issues") or []):
                        f.write(f"    - {issue}\n")
                    rewrite = b.get("suggested_rewrite")
                    if rewrite:
                        f.write(f"    Suggested: {rewrite[:120]}\n")
            else:
                f.write("LANGUAGE NATURALNESS: Skipped\n")

            f.write(f"\n{'='*55}\n")
        print(f"[SAVED] QAAgent: {txt_path}")

    def _parse_json(self, raw):
        if not raw:
            return None
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE).strip()
        for candidate in [clean, raw]:
            cleaned = re.sub(r',\s*([\]}])', r'\1', candidate)
            for open_c, close_c in [('{', '}'), ('[', ']')]:
                start = cleaned.find(open_c)
                end = cleaned.rfind(close_c)
                if start != -1 and end > start:
                    try:
                        data = json.loads(cleaned[start:end + 1])
                        if isinstance(data, list):
                            return {"blocks": data}
                        return data
                    except json.JSONDecodeError:
                        pass
        
        # Robust partial recovery: extract any fully-formed JSON objects {...} if the array was cut off mid-response
        try:
            object_matches = re.findall(r'\{[^{}]*\}', raw)
            if object_matches:
                recovered = []
                for m in object_matches:
                    try:
                        obj = json.loads(m)
                        if isinstance(obj, dict) and any(k in obj for k in ["scene_id", "rewritten_narration", "start_sec", "text"]):
                            recovered.append(obj)
                    except Exception:
                        pass
                if recovered:
                    return {"blocks": recovered}
        except Exception:
            pass

        print(f"[!] QAAgent: Could not parse JSON: {raw[:200]}")
        return None

    def _extract_output_video_transcript_with_file(self, file_name, working_key, state, model):
        """Extract Myanmar voiceover + visual action details using an already-uploaded Gemini file."""
        try:
            user_prompt = (
                f"Movie Title: {state.movie_name}\n\n"
                f"Watch the final dubbed Myanmar recap video completely.\n"
                f"Extract every spoken line of Myanmar narration with start_sec, end_sec, "
                f"exact Myanmar text spoken, character's visual action on screen at that moment, "
                f"and action_match_score (1-10).\n"
                f"Return JSON array."
            )
            raw = ask_gemini_with_video(
                file_name, OUTPUT_VIDEO_EXTRACT_SYSTEM_PROMPT, user_prompt,
                working_key, model=model, temperature=0.1
            )
            parsed = self._parse_json(raw)
            if parsed:
                if isinstance(parsed, dict) and "blocks" in parsed:
                    return parsed["blocks"]
                elif isinstance(parsed, list):
                    return parsed
            return None
        except Exception as e:
            print(f"[!] QAAgent Output Extraction failed: {e}")
            return None


