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


if __name__ == "__main__":
    unittest.main()
