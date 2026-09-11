import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.memory import MovieState
from agents.voice_agent import VoiceAgent
from agents.qa_agent import QAAgent


class TestLanguagePreservation(unittest.TestCase):

    def test_voice_agent_prepare_tts_text_english(self):
        """Verify English voice does not convert digits to Burmese numerals or change ellipsis to Burmese danda."""
        va = VoiceAgent(voice="en-US-GuyNeural")
        raw_text = "Room 105 has 2.5 hours remaining... VIP access only."
        clean = va._prepare_tts_text(raw_text)
        
        # Digits must remain Arabic numerals for English TTS
        self.assertIn("105", clean)
        self.assertIn("2.5", clean)
        self.assertIn("VIP", clean)
        # Burmese danda must not be injected
        self.assertNotIn("။", clean)
        self.assertNotIn("တစ်ရာ", clean)

    def test_voice_agent_prepare_tts_text_burmese(self):
        """Verify Burmese voice converts digits to Burmese words and ellipsis to danda."""
        va = VoiceAgent(voice="my-MM-ThihaNeural")
        raw_text = "အခန်း 105 မှာ 2.5 နာရီကြာ နေခဲ့တယ်..."
        clean = va._prepare_tts_text(raw_text)
        
        self.assertNotIn("105", clean)
        self.assertNotIn("...", clean)
        self.assertIn("။", clean)
        self.assertIn("ဒသမ", clean)

    def test_qa_agent_auto_rewrite_preserves_english(self):
        """Verify QAAgent does not corrupt English text with Burmese transliteration."""
        qa = QAAgent()
        state = MovieState(movie_name="test_qa_movie")
        state.language = "english"
        state.generated_script = [
            {"scene_id": "scene_1", "narration": "Agent 007 and VIP guest arrived at 100 Main Street."}
        ]
        
        # Simulate _apply_rewrites
        lang_result = {
            "blocks": [
                {"scene_id": "scene_1", "score": 4, "suggested_rewrite": "Agent 007 and VIP guest arrived at 100 Main Street safely."}
            ]
        }
        state = qa._apply_rewrites(state, lang_result, threshold=6)
        rewritten = state.generated_script[0]["narration"]
        
        self.assertIn("007", rewritten)
        self.assertIn("VIP", rewritten)
        self.assertIn("100", rewritten)
        self.assertNotIn("ဗွီအိုင်ပီ", rewritten)

    def test_qa_agent_auto_rewrite_recognizes_mm_alias(self):
        """Verify QAAgent applies Burmese transliteration when state.language is 'mm'."""
        qa = QAAgent()
        state = MovieState(movie_name="test_mm_movie")
        state.language = "mm"
        state.generated_script = [
            {"scene_id": "scene_1", "narration": "အခန်း 105 VIP ဧည့်သည် ရောက်လာပါပြီ။"}
        ]
        lang_result = {
            "blocks": [
                {"scene_id": "scene_1", "score": 4, "suggested_rewrite": "အခန်း 105 VIP ဧည့်သည် ရောက်လာပါပြီ။"}
            ]
        }
        state = qa._apply_rewrites(state, lang_result, threshold=6)
        rewritten = state.generated_script[0]["narration"]
        self.assertIn("တစ်ရာ့ငါး", rewritten)
        self.assertIn("ဗွီအိုင်ပီ", rewritten)


class TestDualScriptEngine(unittest.TestCase):

    def test_writer_agent_default_script_engine(self):
        from agents.writer_agent import WriterAgent
        writer = WriterAgent()
        self.assertEqual(writer.script_engine, "recap")

    def test_writer_agent_translate_script_engine(self):
        from agents.writer_agent import WriterAgent
        writer = WriterAgent(script_engine="translate")
        self.assertEqual(writer.script_engine, "translate")

    def test_sanitize_burmese_narration_georgian_token_leakage(self):
        from brain.burmese_utils import sanitize_burmese_narration
        # Test Georgian 'კ' leakage into 'ကလောင်'
        corrupted = "မှန်ထဲကဘီလူးက კလောင်နဲ့ လက်ကို ထိုးစိုက်တယ်။"
        cleaned = sanitize_burmese_narration(corrupted)
        self.assertNotIn("კ", cleaned)
        self.assertIn("ကလောင်", cleaned)

    def test_sanitize_burmese_narration_stray_scripts(self):
        from brain.burmese_utils import sanitize_burmese_narration
        mixed = "ဒီမစ် ရုံးခန်းထဲမှာ နေခဲ့တာပေါ့ဗျာ။ русский текст 123"
        cleaned = sanitize_burmese_narration(mixed)
        self.assertNotIn("русский", cleaned)
        self.assertIn("ဒီမစ် ရုံးခန်းထဲမှာ နေခဲ့တာပေါ့ဗျာ။", cleaned)

    def test_prompts_movie_recap_storyteller_rules(self):
        from brain.prompts import MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT, FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT
        # Recap prompt must enforce storyteller persona and conversational endings
        self.assertIn("Myanmar Movie Recap Storyteller", MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT)
        self.assertIn("...ခဲ့တာပေါ့ဗျာ", MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT)
        self.assertIn("DYNAMIC NARRATIVE TRANSITIONS", MOVIE_RECAP_STORYTELLER_SYSTEM_PROMPT)
        # Translation prompt must enforce 1:1 translation
        self.assertIn("FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT", "FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT")
        self.assertIn("STRICT 1:1 DIALOGUE TRANSLATION", FULL_MOVIE_TRANSLATION_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()

