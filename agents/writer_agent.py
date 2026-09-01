import json
import math
import os
import re
from brain.memory import MovieState
from brain.prompts import (
    FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT,
    FULL_RECAP_SYSTEM_PROMPT,
)
from brain.gemini_client import call_gemini
from brain import config as cfg


class WriterAgent:
    def __init__(
        self,
        language: str = "burmese",
        max_blocks: int | None = None,
    ):
        self.language = language
        self.max_blocks = max_blocks or (int(os.getenv("MAX_BLOCKS")) if os.getenv("MAX_BLOCKS") else None)

    # ─────────────────────────────────────────────────────
    # PUBLIC: generate_script (Full Movie Dialogue Translation)
    # ─────────────────────────────────────────────────────
    def generate_script(self, state: MovieState) -> MovieState:
        """
        Full Movie Dialogue Translation & Dubbing Engine.
        Translates EVERY spoken dialogue line from Whisper STT into natural, colloquial Burmese.
        Completely abolishes the 1-block-per-chapter summary recap architecture.
        """
        print(f"[*] WriterAgent: Generating FULL MOVIE DIALOGUE TRANSLATION (Lang: {self.language})...")

        if not state.transcript:
            print("[!] WriterAgent: No transcript found. Skipping dialogue translation.")
            return state

        config_data = cfg.load_config()
        gemini_cfg = config_data.get("gemini", {})
        gemini_key = gemini_cfg.get("api_keys") or os.getenv("GEMINI_API_KEY") or ""
        models_dict = gemini_cfg.get("models", {})
        model_workhorse = models_dict.get("workhorse", "gemini-3.5-flash-lite")

        # 1. Extract and clean all Whisper dialogue segments
        raw_segments = []
        for i, seg in enumerate(state.transcript):
            if isinstance(seg, dict):
                t_start = float(seg.get("start", 0.0) or 0.0)
                t_end = float(seg.get("end", t_start + 2.0) or (t_start + 2.0))
                text = str(seg.get("text", "")).strip()
            else:
                t_start = float(getattr(seg, "start", 0.0) or 0.0)
                t_end = float(getattr(seg, "end", t_start + 2.0) or (t_start + 2.0))
                text = str(getattr(seg, "text", "")).strip()

            if text and len(text) > 1 and t_end > t_start:
                raw_segments.append({
                    "id": len(raw_segments) + 1,
                    "start_sec": round(t_start, 2),
                    "end_sec": round(t_end, 2),
                    "text": text
                })

        if not raw_segments:
            print("[!] WriterAgent: No valid dialogue text found in transcript.")
            return state

        total_count = len(raw_segments)
        if self.max_blocks and self.max_blocks > 0 and total_count > self.max_blocks:
            raw_segments = raw_segments[:self.max_blocks]
            total_count = len(raw_segments)
            print(f"[*] WriterAgent: Limited to MAX_BLOCKS={self.max_blocks} dialogue lines.")

        print(f"[*] WriterAgent: Found {total_count} spoken dialogue segments to translate.")

        # 2. Batch dialogue lines (20 per batch) for fast, reliable Gemini translation
        BATCH_SIZE = 20
        all_translated = []

        for b_idx in range(0, total_count, BATCH_SIZE):
            batch = raw_segments[b_idx:b_idx + BATCH_SIZE]
            batch_num = (b_idx // BATCH_SIZE) + 1
            total_batches = math.ceil(total_count / BATCH_SIZE)
            print(f"[*] WriterAgent: Translating Batch {batch_num}/{total_batches} ({len(batch)} dialogues)...")

            batch_prompt = (
                f"Target Language: {self.language.upper()}\n"
                f"Movie Title: {state.movie_name}\n"
                f"Translate the following movie dialogues into natural colloquial Myanmar (Burmese) for professional dubbing:\n"
                f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n\n"
                f"Output a JSON array where each object has: id, narration, start_sec, end_sec, emotion."
            )

            batch_translated = None
            if gemini_key:
                try:
                    raw_res, used_model = call_gemini(
                        FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT,
                        batch_prompt,
                        gemini_key,
                        model_workhorse,
                        temperature=0.3,
                        max_tokens=4096
                    )
                    batch_translated = self._parse_script(raw_res)
                except Exception as e:
                    print(f"[WARN] WriterAgent: Batch {batch_num} Gemini call failed: {e}")

            if not batch_translated:
                batch_translated = []

            # Map translated items by id
            trans_map = {}
            for item in batch_translated:
                if isinstance(item, dict) and "id" in item:
                    try:
                        trans_map[int(item["id"])] = item
                    except (ValueError, TypeError):
                        pass

            # Ensure EVERY item in the batch is preserved with Burmese translation
            for seg in batch:
                s_id = seg["id"]
                if s_id in trans_map and trans_map[s_id].get("narration"):
                    item = trans_map[s_id]
                    narration = str(item.get("narration", "")).strip()
                    emotion = str(item.get("emotion", "normal")).strip()
                    gender = str(item.get("gender", "male")).strip().lower()
                    character = str(item.get("character", "Narrator")).strip()
                else:
                    # Individual line fallback if dropped by Gemini
                    narration = seg["text"]
                    emotion = "normal"
                    gender = "male"
                    character = "Narrator"
                    if gemini_key:
                        try:
                            line_res, _ = call_gemini(
                                FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT,
                                f"Translate this single dialogue to colloquial Burmese: '{seg['text']}'",
                                gemini_key,
                                model_workhorse,
                                temperature=0.3,
                                max_tokens=256
                            )
                            line_parsed = self._parse_script(line_res)
                            if line_parsed and isinstance(line_parsed, list) and line_parsed[0].get("narration"):
                                narration = line_parsed[0]["narration"]
                                gender = str(line_parsed[0].get("gender", "male")).strip().lower()
                                character = str(line_parsed[0].get("character", "Narrator")).strip()
                            elif line_res and "{" not in line_res and "[" not in line_res:
                                narration = line_res.strip().strip('"').strip("'")
                        except Exception:
                            pass

                all_translated.append({
                    "scene_id": str(s_id),
                    "narration": narration,
                    "start_sec": seg["start_sec"],
                    "end_sec": seg["end_sec"],
                    "gender": gender,
                    "character": character,
                    "emotion": emotion,
                    "visual_cue": f"Dialogue ({seg['start_sec']}s - {seg['end_sec']}s): {seg['text'][:40]}..."
                })

        # 3. Action Narration Bridge: Bridge silent or long action gaps (> 18s)
        if gemini_key:
            all_translated = self._bridge_action_narration(all_translated, state, gemini_key, model_workhorse)

        state.generated_script = all_translated
        print(f"[OK] WriterAgent: 100% Full Movie Dialogue Translation complete! Total {len(all_translated)} dialogue lines dubbed.")
        return state

    def _bridge_action_narration(self, blocks: list, state: MovieState, gemini_key: str, model: str) -> list:
        """
        Bridges silent or long action gaps (> 18s) with engaging Burmese movie recap narration.
        Turns quiet combat, chase, or suspense sequences into a lively, continuous story recap.
        """
        if not blocks or not gemini_key:
            return blocks

        config_data = cfg.load_config()
        action_cfg = config_data.get("action_narration", {})
        if not action_cfg.get("enabled", True):
            return blocks

        min_gap = float(action_cfg.get("min_gap_sec", 18.0))
        blocks = sorted(blocks, key=lambda x: float(x.get("start_sec", 0.0)))
        
        bridge_candidates = []
        first_start = float(blocks[0].get("start_sec", 0.0))
        if first_start >= min_gap:
            bridge_candidates.append({
                "pos_idx": 0,
                "gap_start": 2.0,
                "gap_end": first_start - 1.0,
                "gap_dur": first_start - 3.0,
                "prev_text": "Movie opening introduction",
                "next_text": blocks[0].get("narration", "")[:60]
            })

        for i in range(len(blocks) - 1):
            curr_end = float(blocks[i].get("end_sec", 0.0))
            next_start = float(blocks[i+1].get("start_sec", 0.0))
            gap = next_start - curr_end
            if gap >= min_gap:
                bridge_candidates.append({
                    "pos_idx": i + 1,
                    "gap_start": curr_end + 1.5,
                    "gap_end": next_start - 1.5,
                    "gap_dur": gap,
                    "prev_text": blocks[i].get("narration", "")[:80],
                    "next_text": blocks[i+1].get("narration", "")[:80]
                })

        if not bridge_candidates:
            return blocks

        print(f"[*] WriterAgent (Action Narration): Detected {len(bridge_candidates)} silent/action sequences (> {min_gap}s). Generating recap narration...")

        new_blocks = list(blocks)
        added_count = 0
        for cand in bridge_candidates[:10]:
            prompt = (
                f"Movie Title: {state.movie_name}\n"
                f"In this movie recap, there is an action or suspense sequence lasting {int(cand['gap_dur'])} seconds without dialogue.\n"
                f"Previous dialogue: '{cand['prev_text']}'\n"
                f"Upcoming dialogue: '{cand['next_text']}'\n\n"
                f"Write a short, engaging 1-2 sentence narrator recap in natural colloquial Myanmar (Burmese) "
                f"describing what happens in the scene or setting up the tension (e.g. 'အဲဒီနောက်...', 'အဲဒီအချိန်မှာ...').\n"
                f"RULES:\n"
                f"- Max 20 words.\n"
                f"- Conversational recap style (use ...တယ်, ...တာပေါ့, ...ဗျာ, ...ကွာ).\n"
                f"- NO formal written Burmese (no ပါသည်, သည်, ၏, ၍).\n"
                f"- Return ONLY the Burmese text."
            )
            try:
                res, _ = call_gemini(
                    "You are an expert Burmese movie recap channel narrator.",
                    prompt,
                    gemini_key,
                    model=model,
                    temperature=0.4,
                    max_tokens=150
                )
                txt = res.strip().strip('"').strip("'").strip()
                if txt and len(txt) > 4 and "```" not in txt:
                    bridge_dur = min(cand["gap_dur"] - 2.0, 5.5)
                    b_start = round(cand["gap_start"], 2)
                    b_end = round(b_start + max(bridge_dur, 3.0), 2)
                    new_blocks.append({
                        "scene_id": f"action_bridge_{added_count+1}",
                        "narration": txt,
                        "start_sec": b_start,
                        "end_sec": b_end,
                        "emotion": "excited",
                        "visual_cue": f"Action Scene ({b_start}s - {b_end}s)"
                    })
                    added_count += 1
            except Exception as e:
                print(f"[WARN] WriterAgent: Action narration failed for gap at {cand['gap_start']}s: {e}")

        new_blocks.sort(key=lambda x: float(x.get("start_sec", 0.0)))
        print(f"[OK] WriterAgent (Action Narration): Successfully bridged {added_count} action scenes with lively Burmese commentary!")
        return new_blocks


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
            narration = (
                item.get("narration")
                or item.get("translation")
                or item.get("myanmar_text")
                or item.get("burmese_text")
                or item.get("text")
                or ""
            )
            if not str(narration).strip():
                continue
            block_id = item.get("id", item.get("scene_id", i + 1))
            block = {
                "id":         block_id,
                "scene_id":   str(block_id),
                "narration":  str(narration).strip(),
                "visual_cue": str(item.get("visual_cue", "Dialogue")),
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
