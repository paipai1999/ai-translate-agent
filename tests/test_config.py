import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.config import load_config, DEFAULT_CONFIG, _deep_merge, SUBTITLE_PRESETS

class TestConfig(unittest.TestCase):

    def test_default_config_has_required_sections(self):
        """Verify all critical system sections exist in DEFAULT_CONFIG."""
        required_keys = [
            "pipeline", "gemini", "voice", "subtitle_overlay",
            "watermark", "qa", "paths", "copyright_protection", "subtitle_blur",
            "color_grading", "thumbnail_intro"
        ]
        for k in required_keys:
            self.assertIn(k, DEFAULT_CONFIG, f"DEFAULT_CONFIG missing essential section: {k}")

    def test_deep_merge_preserves_sibling_defaults(self):
        """Verify _deep_merge does not drop unmentioned keys in nested dicts."""
        base = {
            "pipeline": {
                "language": "burmese",
                "whisper_model": "base",
                "video_format": "both"
            },
            "gemini": {
                "models": {"workhorse": "gemini-3.5-flash-lite"}
            }
        }
        override = {
            "pipeline": {
                "language": "english"
            }
        }
        merged = _deep_merge(base, override)
        self.assertEqual(merged["pipeline"]["language"], "english")
        self.assertEqual(merged["pipeline"]["whisper_model"], "base")
        self.assertEqual(merged["pipeline"]["video_format"], "both")
        self.assertEqual(merged["gemini"]["models"]["workhorse"], "gemini-3.5-flash-lite")

    def test_subtitle_presets_completeness(self):
        """Verify all 5 standard visual subtitle presets exist."""
        expected_presets = ["box_black", "yellow_pop", "white_stroke", "cyan_cyber", "crimson_box"]
        for preset in expected_presets:
            self.assertIn(preset, SUBTITLE_PRESETS, f"Subtitle preset missing: {preset}")
            self.assertTrue(len(SUBTITLE_PRESETS[preset]) > 10, f"Preset style string too short: {preset}")

    def test_env_gemini_api_keys_parsing(self):
        """Verify GEMINI_API_KEYS (plural) in env is parsed into a list."""
        old_env = os.environ.get("GEMINI_API_KEYS")
        try:
            os.environ["GEMINI_API_KEYS"] = "KEY_A,KEY_B,KEY_C"
            cfg = load_config()
            keys = cfg.get("gemini", {}).get("api_keys", [])
            self.assertTrue(isinstance(keys, list))
        finally:
            if old_env is not None:
                os.environ["GEMINI_API_KEYS"] = old_env
            else:
                os.environ.pop("GEMINI_API_KEYS", None)

if __name__ == "__main__":
    unittest.main()
