# 🎬 AI Movie Translate & Dubbing Agent (v2.2) — $0 Free Local & Cloud-Accelerated Pipeline

An autonomous, end-to-end AI agentic pipeline designed to automatically translate movies, short dramas, and anime clips line-by-line into natural **Colloquial Burmese** (or English), synthesize lifelike **Multi-Voice Dubbing (Male/Female)**, and produce viral, ready-to-publish videos equipped with **9:16 Facebook Reels Canvas**, **Burned Myanmar ASS Subtitles**, **Subtitle Blur Protection**, **Custom Watermark Branding**, and **High-CTR Thumbnails**.

---

## ⚡ Cloud GPU One-Click Setup (100% Free Cloud Options)

### 🥇 Option A: Google Colab (Free T4 GPU + Google Drive Sync)
👉 **[Open AI_Movie_Translate_Colab.ipynb in Google Colab](https://colab.research.google.com/github/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Colab.ipynb)**
* **Highlights:** 1-Click Web UI Dashboard, Permanent Google Drive Sync for videos/cookies/db, 60s Auto Keep-Alive Heartbeat, and Fast Socket Health-Check.

### 🥈 Option B: Kaggle Notebooks (Free Dual T4 30GB VRAM / 30h Weekly Quota)
👉 **[View AI_Movie_Translate_Kaggle.ipynb](https://github.com/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Kaggle.ipynb)**
* **Highlights:** 2x NVIDIA T4 GPUs (30GB VRAM) or P100 GPU, 30 Hours/Week Free GPU Quota, 12-Hour Continuous Sessions, Cloudflare Tunnel Web UI, and 30GB System RAM.
* **Kaggle Quickstart:**
  1. Create a new Notebook on [kaggle.com](https://www.kaggle.com).
  2. Click `File` > `Import Notebook` and upload `AI_Movie_Translate_Kaggle.ipynb` (or paste from GitHub).
  3. In right sidebar `Notebook Settings`: Set **Accelerator = GPU T4 x2** and turn **Internet = On**.
  4. Run Cell 1 to launch the Web UI Dashboard!

---

## 🌟 Key Features (v2.2)

### 🍪 1. Multi-Platform Auto Downloader (Mobile API & Anti-Bot Bypass)
* **YouTube:** Negotiates pure mobile streaming APIs (`android`, `mweb`, `android_vr`, `ios`) with automatic cookie stripping on bot challenges to 100% bypass datacenter IP blocks (`Sign in to confirm you're not a bot`).
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
* **Action Narration Bridge:** Detects non-verbal action scenes (>18s) and uses **Gemini 3.5 Flash** to synthesize engaging storyline narration so the audience never experiences silence.
* **Dynamic Audio Ducking:** Automatically lowers background ambient sound to 12% during speech and raises it back to 35% during pauses.

### 🧠 7. Google AI Studio 2026 PRO Tier & Model Auto-Rotation Chain
* **Tier Synchronization:** Pre-configured with Google AI Studio 2026 PRO quotas:
  - **Workhorse:** `gemini-3.5-flash-lite` (15 RPM) & `gemini-3.1-flash-lite` (15 RPM)
  - **Primary & SEO:** `gemini-3.5-flash` (5 RPM) & `gemini-3.7-flash` (5 RPM)
  - **High-Capacity Fallbacks:** `gemini-3.6-flash`, `gemini-3-flash`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`
* **Zero-Error Parsing:** Safe `_extract_text_from_gemini_response` multi-part and thought-block extractor preventing `KeyError: 'parts'`.

### ⏱️ 8. Process Records Time & Live Stopwatch Dashboard
* **Live Elapsed Stopwatch:** Real-time ticking stopwatch (`⏱️ 01:24`) on the Web UI dashboard during video processing.
* **Phase Timing Badges:** Real-time breakdown of seconds spent on each pipeline stage (Video Analysis, Whisper STT, Gemini Script Translation, Voiceover Generation, and Video Merge).
* **Historical Process Records:** Every completed output card permanently stores and displays its comprehensive duration table.

### 🚀 9. Dedicated GPU Cloud Acceleration & Hybrid PC Fallback
* **Google Colab Mode:** Dedicated **NVIDIA T4 GPU (16GB VRAM)** execution utilizing Whisper CUDA FP16 Tensor Cores, Demucs `-d cuda`, and FFmpeg NVENC (`h264_nvenc`) hardware encoder.
* **Kaggle Mode:** Dedicated **Dual NVIDIA T4 GPUs (30GB VRAM)** or **P100 GPU (16GB VRAM)** with 12-hour continuous sessions and Cloudflare Secure Tunnel.
* **Local PC Mode:** Intelligent auto-detection of NVIDIA CUDA, Intel QuickSync (`h264_qsv`), and AMD AMF (`h264_amf`), with zero-error fallback to CPU Multi-core.

---

## 🗂️ Project Structure

```text
ai-translate-agent/
├── agents/
│   ├── master.py              ← Pipeline orchestrator (Phases 1–7) & hardware/cancellation management
│   ├── downloader_agent.py    ← Multi-platform downloader with EJS JS solver & Netscape cookies
│   ├── video_agent.py         ← Video metadata: FPS, duration, resolution (OpenCV & FFprobe)
│   ├── audio_agent.py         ← Audio extract + Fast Whisper STT (CUDA FP16 / INT8) + Demucs GPU Isolation
│   ├── writer_agent.py        ← 1:1 Dialogue Translation (Gemini 3.5 Flash) + Gender Tagging + Action Bridge
│   ├── seo_agent.py           ← Viral Title, Description, Tags, and Hashtags generator (Gemini 3.5 Flash)
│   ├── voice_agent.py         ← Multi-Voice TTS (Thiha Male / Nilar Female) & Time Stretch
│   ├── video_merger_agent.py  ← Video Merger, Dynamic Audio Ducking, 9:16 Reels Canvas, NVENC/QSV Encoder
│   ├── thumbnail_agent.py     ← High-CTR Golden Yellow Top-Center Thumbnail Generator
│   └── qa_agent.py            ← Sync score & language naturalness QA review
│
├── brain/
│   ├── memory.py              ← Pydantic shared state (MovieState with atomic JSON persistence)
│   ├── planner.py             ← Overnight Batch Processor with auto API key rotation
│   ├── prompts.py             ← LLM prompt templates (Dialogue Translation, SEO, QA)
│   ├── config.py              ← config.json loader with Gemini 3.5 Flash defaults
│   ├── gemini_client.py       ← Gemini API client with safe multi-part parsing & 8-model fallback rotation
│   └── sqlite_store.py        ← SQLite WAL-mode local database for movie states and job logs
│
├── templates/
│   └── index.html             ← Modern Glassmorphic Web UI Dashboard with Live Timer & Controls
│
├── web_ui.py                  ← FastAPI Web Dashboard (Direct Upload, Live Timing SSE Logs, Force Stop API)
├── AI_Movie_Translate_Colab.ipynb  ← Official Google Colab One-Click Dedicated GPU Notebook
├── AI_Movie_Translate_Kaggle.ipynb ← Official Kaggle One-Click Dual T4 Dedicated GPU Notebook
├── config.json                ← Active runtime configuration (API keys, branding, models)
├── config.example.json        ← Default configuration template
├── cookies.txt                ← Netscape cookie file for YouTube, DramaBox, and ReelShort
├── main.py                    ← CLI entry point with --sub-mode and --resolution flags
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
