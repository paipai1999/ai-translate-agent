import os
import re
import sys
import time

class DownloaderAgent:
    def __init__(self, output_dir: str = "movies"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def is_url(input_string: str) -> bool:
        """Check if the provided input string is a valid URL."""
        url_pattern = re.compile(
            r'^(https?://|www\.)[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(/.*)?$'
            r'|^https?://.+',  # Fix: also match short URLs like youtu.be/... and any https:// link
            re.IGNORECASE
        )
        return bool(url_pattern.match(input_string.strip()))

    @staticmethod
    def _clean_url(url: str) -> str:
        """Strips tracking parameters (?si=..., &feature=...) and formats clean canonical YouTube URL."""
        url = str(url or "").strip()
        m = re.search(r'(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})', url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
        return url

    def download_video(self, url: str) -> str:
        """Download video from URL using yt-dlp and return the local file path."""
        url = self._clean_url(url)
        print(f"[*] DownloaderAgent: URL detected -> {url}")
        print(f"[*] DownloaderAgent: Downloading video into '{self.output_dir}/'...")
        
        try:
            import yt_dlp
        except ImportError:
            raise ImportError("yt-dlp is not installed. Please run: pip install yt-dlp")

        import shutil
        ffmpeg_bin = shutil.which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE")
        if not ffmpeg_bin:
            try:
                from imageio_ffmpeg import get_ffmpeg_exe
                ffmpeg_bin = get_ffmpeg_exe()
            except Exception:
                ffmpeg_bin = None

        # Check for optional cookies.txt
        has_cookies = False
        cookie_candidates = [
            'cookies.txt',
            os.path.join('assets', 'cookies.txt'),
            '/content/cookies.txt',
            '/content/drive/MyDrive/MovieRecapOutputs/cookies.txt',
            os.path.join(self.output_dir, 'cookies.txt')
        ]
        active_cookie = None
        for c_file in cookie_candidates:
            if os.path.exists(c_file) and os.path.getsize(c_file) > 10:
                active_cookie = c_file
                has_cookies = True
                print(f"[*] DownloaderAgent: Using cookies authentication from -> {c_file}")
                break

        # Configure yt-dlp options prioritizing 1080p / 720p Full HD resolution
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'outtmpl': os.path.join(self.output_dir, '%(title)s.%(ext)s'),
            'restrictfilenames': True,  # Ensure clean filenames without weird symbols
            'noplaylist': True,
            'quiet': False,
            'no_warnings': True,
            'retries': 20,              # Retry up to 20 times on network timeout/errors
            'fragment_retries': 20,     # Retry fragmented streams up to 20 times
            'sleep_interval': 2,
            'socket_timeout': 60,       # Increase socket timeout to 60 seconds
            'http_chunk_size': 10485760,# 10MB chunk size to prevent throttling freeze
            'extractor_args': {'youtube': {'player_client': ['mweb', 'android', 'web']}}
        }
        if active_cookie:
            ydl_opts['cookiefile'] = active_cookie
        if ffmpeg_bin:
            ydl_opts['ffmpeg_location'] = ffmpeg_bin

        last_progress_time = [0]
        def _dl_progress(d):
            if d.get('status') == 'downloading':
                now = time.time()
                if now - last_progress_time[0] >= 1.5:
                    last_progress_time[0] = now
                    pct = d.get('_percent_str', '').strip()
                    speed = d.get('_speed_str', '').strip()
                    eta = d.get('_eta_str', '').strip()
                    print(f"[*] Downloading: {pct} at {speed} (ETA: {eta})")
            elif d.get('status') == 'finished':
                print("[*] Download completed. Processing video streams...")

        ydl_opts['progress_hooks'] = [_dl_progress]

        max_attempts = 3
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt == 2:
                    print("[*] DownloaderAgent: Attempting with mobile Android & iOS client fallback...")
                    ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios', 'web_embedded']}}
                elif attempt == 3:
                    print("[*] DownloaderAgent: Attempting with web-embedded multi-client fallback...")
                    ydl_opts['format'] = 'best'
                    ydl_opts['extractor_args'] = {'youtube': {'player_client': ['web_embedded', 'android', 'mweb']}}

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    print(f"[*] DownloaderAgent: Fetching video stream (Attempt {attempt}/{max_attempts})...")
                    info_dict = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info_dict)
                    
                    # If extension changed during merging, ensure we point to the existing file
                    if not os.path.exists(filename):
                        base, _ = os.path.splitext(filename)
                        for ext in ['.mp4', '.mkv', '.webm']:
                            if os.path.exists(base + ext):
                                filename = base + ext
                                break
                break # Download succeeded
            except Exception as e:
                last_error = e
                print(f"[!] DownloaderAgent Attempt {attempt} failed: {e}")
                # Clean up partial download files
                fn = locals().get('filename')
                if fn:
                    for ext in ['.part', '.ytdl', '.tmp']:
                        partial = fn + ext
                        if os.path.exists(partial):
                            try:
                                os.remove(partial)
                                print(f"[*] Downloader: Removed partial file {os.path.basename(partial)}")
                            except Exception:
                                pass
                if attempt == max_attempts:
                    if "Sign in to confirm" in str(e) or "bot" in str(e).lower():
                        raise RuntimeError(
                            f"\n❌ [YouTube Anti-Bot Challenge]\n"
                            f"YouTube has blocked unauthenticated downloads from this cloud server IP address.\n"
                            f"💡 SOLUTIONS (အလွယ်ဆုံး ဖြေရှင်းနည်း ၂ သွယ်):\n"
                            f"1. Cookies အသုံးပြုခြင်း: Chrome Extension 'Get cookies.txt LOCALLY' ဖြင့် cookies.txt ထုတ်ယူပြီး Web UI သို့မဟုတ် Google Drive (/content/drive/MyDrive/MovieRecapOutputs/cookies.txt) တွင် တင်ပေးပါ။\n"
                            f"2. ဖိုင်တိုက်ရိုက်တင်ခြင်း: ဗီဒီယိုကို မိမိစက်ထဲ ဒေါင်းလုဒ်ဆွဲပြီး Web UI ပေါ်ရှိ 'Upload Movie File' မှတစ်ဆင့် တိုက်ရိုက် တင်နိုင်ပါသည် ခင်ဗျာ။\n"
                            f"Original Error: {e}"
                        )
                    raise e
                print(f"[*] Retrying in 5 seconds with fallback client format...")
                ydl_opts['format'] = 'bestvideo+bestaudio/best' # Fallback to combined or best stream
                ydl_opts['socket_timeout'] = 120
                time.sleep(5)

        # Verify downloaded file actually exists before returning
        if not os.path.exists(filename):
            raise FileNotFoundError(
                f"[ERROR] DownloaderAgent: Download seemed to succeed but file not found: {filename}\n"
                f"Possible cause: yt-dlp merged into a different extension. Check '{self.output_dir}/' manually."
            )
        print(f"[OK] DownloaderAgent: Video downloaded successfully -> {filename}")
        return filename
