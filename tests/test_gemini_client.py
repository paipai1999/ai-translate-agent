import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.gemini_client import call_gemini_vision, ask_gemini_with_video


class TestGeminiClientProtobuf(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_call_gemini_vision_camelcase_payload(self, mock_urlopen):
        """Verify call_gemini_vision formats inlineData and mimeType in camelCase for REST API v1beta."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "OK"}]}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Create dummy image
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(b"fake_image_data")
            temp_img = tf.name

        try:
            res, used_model = call_gemini_vision(
                system_prompt="Test system",
                user_text="Describe frame",
                image_path=temp_img,
                api_key="AIzaSyFakeKeyForTestOnly12345"
            )
            self.assertEqual(res, "OK")
            self.assertTrue(mock_urlopen.called)
            req = mock_urlopen.call_args[0][0]
            payload = json.loads(req.data.decode("utf-8"))

            part0 = payload["contents"][0]["parts"][0]
            # Must be camelCase inlineData and mimeType (NOT inline_data or mime_type)
            self.assertIn("inlineData", part0)
            self.assertNotIn("inline_data", part0)
            self.assertIn("mimeType", part0["inlineData"])
            self.assertNotIn("mime_type", part0["inlineData"])
            self.assertIn("data", part0["inlineData"])
        finally:
            if os.path.exists(temp_img):
                os.remove(temp_img)

    @patch("urllib.request.urlopen")
    def test_ask_gemini_with_video_camelcase_payload(self, mock_urlopen):
        """Verify ask_gemini_with_video formats fileData, mimeType, and fileUri in camelCase."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Video analysis complete"}]}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = ask_gemini_with_video(
            file_name="files/testfile123",
            system_prompt="Analyze video",
            user_text="What happens?",
            key="AIzaSyFakeKeyForTestOnly12345"
        )
        self.assertEqual(res, "Video analysis complete")
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))

        part0 = payload["contents"][0]["parts"][0]
        # Must be camelCase fileData, mimeType, and fileUri (NOT snake_case)
        self.assertIn("fileData", part0)
        self.assertNotIn("file_data", part0)
        self.assertIn("mimeType", part0["fileData"])
        self.assertNotIn("mime_type", part0["fileData"])
        self.assertIn("fileUri", part0["fileData"])
        self.assertNotIn("file_uri", part0["fileData"])


if __name__ == "__main__":
    unittest.main()
