import os
import glob
import json
from typing import List
from agents.master import MasterAgent
from agents.downloader_agent import DownloaderAgent
from brain.memory import MovieState  # Fix: was missing — caused NameError in _is_completed()
import brain.config as cfg

class BatchProcessor:
    def __init__(
        self,
        movies_folder: str = "movies",
        skip_completed: bool = True,
        language: str = None,
        subtitle_mode: str = "burn",
        resolution: str = "1080p",
        tts_engine: str = None,
        custom_thumb_title: str = None,
        watermark_enabled: bool = None,
        watermark_text: str = None,
        watermark_opacity: float = None,
        tts_voice: str = None,
        video_format: str = None,
        subtitle_style: str = None,
        thumbnail_intro: bool = None,
        source_language: str = "auto",
    ):
        self.movies_folder = movies_folder
        self.skip_completed = skip_completed
        self.language = language
        self.source_language = source_language or "auto"
        self.subtitle_mode = subtitle_mode
        self.subtitle_style = subtitle_style
        self.resolution = resolution or "1080p"
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.video_format = video_format
        self.custom_thumb_title = custom_thumb_title
        self.watermark_enabled = watermark_enabled
        self.watermark_text = watermark_text
        self.watermark_opacity = watermark_opacity
        self.thumbnail_intro = thumbnail_intro
        self.supported_extensions = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
        self.results = []

    def _is_completed(self, movie_path: str) -> bool:
        """Check if this movie already has a completed output state.json."""
        try:
            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            project_dir = MovieState(movie_name=movie_name).project_dir
            output_dir = cfg.load_config().get("paths", {}).get("output_dir", "outputs")
            state_file = os.path.join(output_dir, project_dir, "state.json")
            if not os.path.exists(state_file):
                return False
            # Verify the state file is valid JSON and pipeline reached 100%
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("progress", 0)) >= 100
        except Exception:
            return False  # If anything fails, re-process this movie

    def _collect_movies(self) -> List[str]:
        """Collect all supported video files from the movies folder."""
        movie_files = []
        for ext in self.supported_extensions:
            pattern = os.path.join(self.movies_folder, f"*{ext}")
            movie_files.extend(glob.glob(pattern))
        return sorted(movie_files)

    def process_all(self, url_list: List[str] = None, local_paths: List[str] = None):
        """
        Process all movies in the movies/ folder (batch mode).
        Optionally also download and process a list of URLs first.
        """
        # Step 1: Download from URLs if provided
        downloaded_paths = []
        if url_list:
            print(f"\n[URL] Batch Mode: Downloading {len(url_list)} video(s) from URLs...")
            downloader = DownloaderAgent(output_dir=self.movies_folder)
            for idx, url in enumerate(url_list, 1):
                print(f"\n[{idx}/{len(url_list)}] Downloading: {url}")
                try:
                    downloaded_path = downloader.download_video(url)
                    downloaded_paths.append(downloaded_path)
                    print(f"[OK] Downloaded: {downloaded_path}")
                except Exception as e:
                    print(f"[ERROR] Download failed for {url}: {e}")
                    self.results.append({"url": url, "status": "DOWNLOAD_FAILED", "error": str(e)})

        # Step 2: Collect all local movies
        if local_paths is not None:
            movies = list(dict.fromkeys([*local_paths, *downloaded_paths]))
        else:
            movies = self._collect_movies()
        if not movies:
            print(f"[!] BatchProcessor: No video files found in '{self.movies_folder}/'")
            return

        total = len(movies)
        print(f"\n[VIDEO] Batch Mode: Found {total} video file(s) to process in '{self.movies_folder}/'")

        # Step 3: Process each movie sequentially
        for idx, movie_path in enumerate(movies, 1):
            if os.environ.get("CURRENT_JOB_CANCELLED") == "1":
                print(f"\n🛑 [STOP] Batch processing cancelled by user at item {idx}/{total}.")
                break

            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            print(f"\n{'='*55}")
            print(f"[{idx}/{total}] Processing: {movie_name}")
            print(f"{'='*55}")

            # Skip already-completed jobs
            if self.skip_completed and self._is_completed(movie_path):
                print(f"[SKIP] Skipping '{movie_name}' - already completed (outputs/{movie_name}/state.json exists).")
                self.results.append({"movie": movie_name, "status": "SKIPPED"})
                continue

            try:
                master = MasterAgent(
                    movie_path,
                    language=self.language,
                    subtitle_mode=self.subtitle_mode,
                    resolution=self.resolution,
                    tts_engine=self.tts_engine,
                    tts_voice=self.tts_voice,
                    custom_thumb_title=self.custom_thumb_title,
                    watermark_enabled=self.watermark_enabled,
                    watermark_text=self.watermark_text,
                    watermark_opacity=self.watermark_opacity,
                    video_format=self.video_format,
                    subtitle_style=self.subtitle_style,
                    thumbnail_intro=self.thumbnail_intro,
                    source_language=self.source_language,
                )
                master.run_pipeline()
                self.results.append({"movie": movie_name, "status": "SUCCESS"})
                print(f"[OK] [{idx}/{total}] Completed: {movie_name}")
            except Exception as e:
                print(f"[ERROR] [{idx}/{total}] FAILED: {movie_name} - Error: {e}")
                self.results.append({"movie": movie_name, "status": "FAILED", "error": str(e)})

        # Step 4: Print batch summary
        self._print_summary()

    def _print_summary(self):
        """Print a final summary report of the batch run."""
        success = [r for r in self.results if r.get("status") == "SUCCESS"]
        failed  = [r for r in self.results if r.get("status") == "FAILED"]
        skipped = [r for r in self.results if r.get("status") == "SKIPPED"]

        print(f"\n{'='*55}")
        print(f"[STATS] BATCH PROCESSING SUMMARY")
        print(f"{'='*55}")
        print(f"  [OK] Completed : {len(success)}")
        print(f"  [SKIP] Skipped   : {len(skipped)}")
        print(f"  [ERROR] Failed    : {len(failed)}")
        if failed:
            print(f"\n  Failed jobs:")
            for r in failed:
                name = r.get('movie') or r.get('url') or 'Unknown'
                print(f"    - {name}: {r.get('error','Unknown error')}")
        print(f"{'='*55}")

        # Save summary to JSON
        summary_path = os.path.join("outputs", "batch_summary.json")
        os.makedirs("outputs", exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4)
        print(f"[SAVED] Batch summary saved -> {summary_path}")
