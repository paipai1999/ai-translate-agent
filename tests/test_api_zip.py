import unittest
import os
import zipfile
from fastapi.testclient import TestClient
from web_ui import app

class TestZipDownloadEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_dir = os.path.join("outputs", "test_zip_movie")
        os.makedirs(self.test_dir, exist_ok=True)
        # Create dummy artifacts
        with open(os.path.join(self.test_dir, "final_recap.mp4"), "wb") as f:
            f.write(b"dummy mp4 video bytes")
        with open(os.path.join(self.test_dir, "thumbnail.jpg"), "wb") as f:
            f.write(b"dummy thumbnail image bytes")
        with open(os.path.join(self.test_dir, "final_recap_script.txt"), "w", encoding="utf-8") as f:
            f.write("Dummy Burmese recap script")
        with open(os.path.join(self.test_dir, "state.json"), "w", encoding="utf-8") as f:
            f.write("{\"state\": \"internal\"}")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zip_download_success(self):
        res = self.client.get("/api/download/zip?movie=test_zip_movie")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/zip")
        self.assertIn("attachment; filename=", res.headers.get("content-disposition", ""))

        # Verify zip contents in-memory
        import io
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        names = zf.namelist()
        self.assertIn("final_recap.mp4", names)
        self.assertIn("thumbnail.jpg", names)
        self.assertIn("final_recap_script.txt", names)
        # internal state.json must be excluded
        self.assertNotIn("state.json", names)

    def test_zip_download_missing_movie(self):
        res = self.client.get("/api/download/zip?movie=nonexistent_movie_xyz")
        self.assertEqual(res.status_code, 404)

    def test_zip_download_empty_query(self):
        res = self.client.get("/api/download/zip?movie=")
        self.assertEqual(res.status_code, 400)

if __name__ == "__main__":
    unittest.main()
