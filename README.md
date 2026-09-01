# 🎬 AI Movie Translate & Dubbing Agent (v2.2) — $0 Free Local & Cloud-Accelerated Pipeline

An autonomous, end-to-end AI agentic pipeline designed to automatically translate movies, short dramas, and anime clips line-by-line into natural **Colloquial Burmese** (or English), synthesize lifelike **Multi-Voice Dubbing (Male/Female)**, and produce viral, ready-to-publish videos equipped with **9:16 Facebook Reels Canvas**, **Burned Myanmar ASS Subtitles**, **Subtitle Blur Protection**, **Custom Watermark Branding**, and **High-CTR Thumbnails**.

---

## ⚡ Google Colab One-Click Setup (Free Cloud GPU Mode)

Running on **Google Colab** provides **Free NVIDIA T4 GPU (16GB VRAM)**, **1 Gbps Google Cloud network**, and high-speed execution for Whisper STT, Demucs Vocal Isolation, and NVENC Hardware Acceleration with **Permanent Google Drive Storage**.

👉 **[Open AI_Movie_Translate_Colab.ipynb in Google Colab](https://colab.research.google.com/github/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Colab.ipynb)**

### ✨ Colab Highlights:
1. **⚡ 1-Click Web UI Dashboard Launcher:** Click Play (▶️) once on `🚀 Launch Web UI Dashboard`. Colab automatically provisions dependencies, installs GPU NVENC FFmpeg, starts FastAPI, and launches your private Web UI tunnel.
2. **☁️ Permanent Google Drive Sync:** Automatically backs up and restores `cookies.txt`, `config.json`, `movie_metadata.db` (job history & token usage), and `outputs/` across Colab disconnects.
3. **⚡ Colab Auto Keep-Alive Heartbeat:** Built-in JavaScript heartbeat keeps the connection active every 60 seconds, preventing idle disconnects during long movie translations.
4. **🛡️ Active Socket Health-Check (Zero 502 Errors):** Probes TCP port 5000 before publishing the Cloudflare Tunnel link, guaranteeing instant connection without Bad Gateway errors.

---

## 🌟 Key Features (v2.2)

### 🍪 1. Multi-Platform Auto Downloader (Anti-Bot Bypass)
* **YouTube:** Integrated remote EJS challenge solver + Netscape `cookies.txt` support to bypass all bot challenges (`Sign in to confirm you're not a bot`).
* **DramaBox (`dramaboxdb.com`):** Direct web & HLS streaming download with VIP authentication.
* **ReelShort (`reelshort.com`):** Direct short drama download with session cookies.
* **Local Upload:** Direct Drag & Drop upload of MP4, MKV, WebM files in the Web UI.

### 🛑 2. 1-Click Instant Force Stop Pipeline
* Emergency **`🛑 Force Stop Pipeline`** button in the Web UI to immediately cancel running jobs.
* Terminates active child subprocess trees (`ffmpeg`, `whisper`, `demucs`, `yt-dlp`) to instantly release GPU VRAM and CPU memory.

### 📝 3. Subtitle Mode Switch & Standalone SRT Export
* **🔥 Burn Subtitles (Hardsub - Default):** Burns styled Myanmar ASS subtitles (Padauk / Myanmar Text) directly into the video frame.
* **🎙️ Voiceover Only (Clean Frame):** Generates clean video with dubbed voice only (no text on video), and automatically exports standalone **`myanmar_subs.srt`** and **`myanmar_subs.ass`** subtitle files for YouTube CC / VLC player.

### ⚙️ 4. Resolution Quality Presets
* **🌟 1080p Full HD (Default / Highest Quality):** 1920x1080 (16:9 Landscape) & 1080x1920 (9:16 Vertical).
* **⚡ 720p HD (Faster Render / Smaller File):** 1280x720 (16:9 Landscape) & 720x1280 (9:16 Vertical) for 2x faster encoding.

### 📱 5. 9:16 Facebook Reels & TikTok Dual Canvas Exporter
* Exports a dedicated **1080x1920 Full HD 9:16 Vertical Video** alongside the standard 16:9 YouTube video.
* Features a high-speed silky blurred background, golden hook title at top, centered video frame, and safe-zone Myanmar subtitles.

### 👫 6. AI Multi-Voice Character Dubbing & Action Narration Bridge
* **Multi-Voice Dubbing:** Automatically assigns male characters to `my-MM-ThihaNeural` and female characters to `my-MM-NilarNeural`.
* **Action Narration Bridge:** Detects non-verbal action scenes (>18s) and uses Gemini 2.0 Flash to synthesize engaging storyline narration so the audience never experiences silence.
* **Dynamic Audio Ducking:** Automatically lowers background ambient sound to 12% during speech and raises it back to 35% during pauses.

---

## 🗂️ Project Structure

```text
ai-translate-agent/
├── agents/
│   ├── master.py              ← Pipeline orchestrator (Phases 1–7) & cancellation management
│   ├── downloader_agent.py    ← Multi-platform downloader with EJS JS solver & Netscape cookies
│   ├── video_agent.py         ← Video metadata: FPS, duration, resolution (OpenCV & FFprobe)
│   ├── audio_agent.py         ← Audio extract + Fast Whisper STT (INT8 + VAD) + Demucs Vocal Isolation
│   ├── writer_agent.py        ← 1:1 Dialogue Translation + Gender Tagging + Action Narration
│   ├── seo_agent.py           ← Viral Title, Description, Tags, and Hashtags generator
│   ├── voice_agent.py         ← Multi-Voice TTS (Thiha Male / Nilar Female) & Time Stretch
│   ├── video_merger_agent.py  ← Video Merger, Dynamic Audio Ducking, 9:16 Reels Canvas, ASS/SRT Exporter
│   ├── thumbnail_agent.py     ← High-CTR Golden Yellow Top-Center Thumbnail Generator
│   └── qa_agent.py            ← Sync score & language naturalness QA review
│
├── brain/
│   ├── memory.py              ← Pydantic shared state (MovieState with atomic JSON persistence)
│   ├── planner.py             ← Overnight Batch Processor with auto API key rotation
│   ├── prompts.py             ← LLM prompt templates (Dialogue Translation, SEO, QA)
│   ├── config.py              ← config.json loader with safe defaults
│   ├── gemini_client.py       ← Gemini API client with Gemini 2.0 Flash priority & key rotation
│   └── sqlite_store.py        ← SQLite WAL-mode local database for movie states and job logs
│
├── templates/
│   └── index.html             ← Modern Glassmorphic Web UI Dashboard with live progress & controls
│
├── web_ui.py                  ← FastAPI Web Dashboard (Direct Upload, Live SSE Logs, Force Stop API)
├── AI_Movie_Translate_Colab.ipynb ← Official Google Colab One-Click Notebook
├── config.json                ← Active runtime configuration (API keys, branding, models)
├── config.example.json        ← Default configuration template
├── cookies.txt                ← Netscape cookie file for YouTube, DramaBox, and ReelShort
├── main.py                    ← CLI entry point
├── requirements.txt           ← Python package dependencies
├── assets/                    ← Reference voice samples, cookies, and branding assets
├── movies/                    ← Place source video files here
├── outputs/                   ← Generated final videos, thumbnails, scripts, and logs
└── temp/                      ← Intermediate audio/video cache (Auto-cleaned after merge)
```

---

## 💻 Local Setup (PC)

```bash
# 1. Clone repository
git clone https://github.com/paipai1999/ai-translate-agent.git
cd ai-translate-agent

# 2. Create virtual environment & install dependencies
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt

# 3. Add your Gemini API Key in config.json (or in Web UI)
#    Get free API keys from: https://aistudio.google.com
```

---

## 🚀 Usage

### 🌐 Method 1: Web UI Dashboard (Recommended)
```bash
python web_ui.py
```
*Open your browser at: `http://localhost:5000`*

* **Direct Video Download & Upload:** Paste any YouTube, DramaBox, or ReelShort URL, or click **📁 Upload** to select a file from your computer.
* **Subtitle Mode Selector:** Choose between `🔥 Burn Subtitles (Hardsub)` and `🎙️ Voiceover Only (Clean Frame)`.
* **Resolution Quality Selector:** Choose between `🌟 1080p Full HD` and `⚡ 720p HD`.
* **9:16 Facebook Reels & TikTok:** Toggle automatic vertical video generation.
* **Overnight Batch Queue:** Paste multiple links to process sequentially overnight with automatic API key failover.
* **1-Click Force Stop:** Click `🛑 Force Stop Pipeline` at any time to immediately cancel execution.

### 💻 Method 2: Command Line (CLI)
```bash
# Run single movie recap with default settings
python main.py --input "movies/my_movie.mp4"

# Run with custom thumbnail title and 9:16 Reels export
python main.py --input "https://youtu.be/..." --thumb-title "ရွာသူလေးရဲ့ မယုံနိုင်စရာလျှို့ဝှက်ချက်"
```

---

## 📄 License
MIT License. Free for educational and commercial content creation.
