import argparse
import os
import sys
import shutil
from agents.master import MasterAgent
from agents.downloader_agent import DownloaderAgent
from brain.planner import BatchProcessor
from brain import config as cfg

# Force UTF-8 output on Windows to prevent emoji/Unicode encode errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ASCII_ART = r"""
  __  __            _        _____                       
 |  \/  |          (_)      |  __ \                      
 | \  / | _____   ___  ___  | |__) |___  ___ __ _ _ __   
 | |\/| |/ _ \ \ / / |/ _ \ |  _  // _ \/ __/ _` | '_ \  
 | |  | | (_) \ V /| |  __/ | | \ \  __/ (_| (_| | |_) | 
 |_|  |_|\___/ \_/ |_|\___| |_|  \_\___|\___\__,_| .__/  
                                                  |_|     
  100% Free Local AI Pipeline  .  Cost = $0              
"""

def setup_directories():
    for d in ["movies", "outputs", "temp", "voiceover", "assets/voices", "assets/bgm"]:
        os.makedirs(d, exist_ok=True)

def run_interactive_cleanup():
    print("\n=== 🗑️ MOVIE RECAP CLEANUP UTILITY ===")
    print("1. Delete generated outputs (outputs/ folder)")
    print("2. Delete source input videos (movies/ folder)")
    print("3. Clear temporary audio/video cache (temp/ folder)")
    print("0. Exit")
    choice = input("\nSelect an option [0-3]: ").strip()
    
    if choice == "1":
        out_dir = "outputs"
        if not os.path.exists(out_dir) or not os.listdir(out_dir):
            print("[INFO] No outputs found.")
            return
        items = sorted(os.listdir(out_dir))
        for i, name in enumerate(items, 1):
            print(f"  {i}. {name}")
        sel = input("\nEnter number to delete (or 'all' for everything, 0 to cancel): ").strip().lower()
        if sel == "all":
            confirm = input("Are you sure you want to delete ALL outputs? (y/N): ").lower()
            if confirm == "y":
                for name in items:
                    shutil.rmtree(os.path.join("outputs", name), ignore_errors=True)
                    shutil.rmtree(os.path.join("temp", name), ignore_errors=True)
                print("[OK] All outputs and associated temp files deleted!")
        elif sel.isdigit() and 1 <= int(sel) <= len(items):
            name = items[int(sel)-1]
            shutil.rmtree(os.path.join("outputs", name), ignore_errors=True)
            shutil.rmtree(os.path.join("temp", name), ignore_errors=True)
            print(f"[OK] Deleted output: {name}")
    elif choice == "2":
        mov_dir = "movies"
        if not os.path.exists(mov_dir) or not os.listdir(mov_dir):
            print("[INFO] No input videos found in movies/.")
            return
        items = sorted([f for f in os.listdir(mov_dir) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv'))])
        if not items:
            print("[INFO] No video files found in movies/.")
            return
        for i, name in enumerate(items, 1):
            print(f"  {i}. {name}")
        sel = input("\nEnter number to delete (or 'all' for everything, 0 to cancel): ").strip().lower()
        if sel == "all":
            confirm = input("Are you sure you want to delete ALL input movies? (y/N): ").lower()
            if confirm == "y":
                for name in items: os.remove(os.path.join("movies", name))
                print("[OK] All input movies deleted!")
        elif sel.isdigit() and 1 <= int(sel) <= len(items):
            name = items[int(sel)-1]
            os.remove(os.path.join("movies", name))
            print(f"[OK] Deleted input video: {name}")
    elif choice == "3":
        if os.path.exists("temp"):
            shutil.rmtree("temp", ignore_errors=True)
            os.makedirs("temp", exist_ok=True)
            print("[OK] Temporary cache cleared!")

def check_dependencies():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            ffmpeg = get_ffmpeg_exe()
        except ImportError:
            ffmpeg = None
    if not ffmpeg or not os.path.exists(ffmpeg):
        print("[CRITICAL ERROR] FFmpeg was not found. Install it or run: pip install imageio-ffmpeg")
        sys.exit(1)
    # MoviePy and the post-processing agent both honor this executable.
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg
    ffmpeg_dir = os.path.dirname(ffmpeg)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    print(f"[*] FFmpeg ready -> {ffmpeg}")

def main():
    check_dependencies()
    print(ASCII_ART)

    parser = argparse.ArgumentParser(
        description="Movie Recap AI — Free Local Pipeline",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "input_source",
        nargs="?",
        default=None,
        help="Path to video file or URL to download"
    )
    parser.add_argument(
        "-b", "--batch",
        action="store_true",
        help="Process all videos in movies/ folder sequentially"
    )
    parser.add_argument(
        "-u", "--urls",
        nargs="+",
        default=None,
        help="List of URLs to download and process in batch"
    )
    parser.add_argument(
        "-l", "--lang",
        dest="language",
        choices=["burmese", "english", "mm", "en"],
        default=None,
        help="Language for recap script and voiceover (default: burmese or config setting)"
    )
    parser.add_argument(
        "--blocks",
        type=int,
        default=None,
        help="Maximum number of narrative blocks (override config)"
    )
    parser.add_argument(
        "--subtitle",
        action="store_true",
        help="Enable subtitle blur pass in the final recap video"
    )

    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Skip Text-to-Speech voice generation step"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process movies even if output already exists (ignore skip_completed)"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Interactive cleanup menu to delete old source videos or generated outputs"
    )

    args = parser.parse_args()
    setup_directories()

    if args.clean:
        run_interactive_cleanup()
        return

    if args.no_voice:
        os.environ["VOICE_ENABLED"] = "false"

    if args.blocks is not None:
        os.environ["MAX_BLOCKS"] = str(args.blocks)

    if args.subtitle:
        os.environ["ENABLE_SUBTITLES"] = "true"



    # Single video or URL
    if args.input_source:
        src = args.input_source.strip()

        if DownloaderAgent.is_url(src):
            print(f"[URL] Detected URL - starting auto-download...")
            try:
                downloader = DownloaderAgent(output_dir="movies")
                movie_path = downloader.download_video(src)
            except Exception as e:
                print(f"[ERROR] Download failed: {e}")
                sys.exit(1)
        else:
            movie_path = src
            if not os.path.exists(movie_path):
                print(f"[ERROR] File not found: '{movie_path}'")
                print("[TIP] If this is a URL, make sure it starts with http:// or https://")
                sys.exit(1)

        try:
            master = MasterAgent(movie_path, language=args.language)
            master.run_pipeline()
        except Exception as e:
            print(f"\n[ERROR] Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Batch: movies/ folder
    elif args.batch:
        print("[BATCH] Processing all videos in movies/ folder...")
        conf = cfg.load_config()
        skip = conf.get("batch", {}).get("skip_completed", True) and not args.force
        BatchProcessor(
            movies_folder=conf.get("batch", {}).get("movies_folder", "movies"),
            skip_completed=skip,
            language=args.language
        ).process_all()

    # Batch: URL list
    elif args.urls:
        print(f"[BATCH] URL Batch Mode: {len(args.urls)} video(s) to download & process...")
        conf = cfg.load_config()
        skip = conf.get("batch", {}).get("skip_completed", True) and not args.force
        BatchProcessor(
            movies_folder=conf.get("batch", {}).get("movies_folder", "movies"),
            skip_completed=skip,
            language=args.language
        ).process_all(url_list=args.urls, local_paths=[])
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
