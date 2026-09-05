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

### 🎨 4. Subtitle Style Presets (Interactive Visual Studio)
Choose from 5 professionally designed subtitle styles with real-time live preview in the Web UI:
* **🎬 Cinema Box (Netflix Style - `box_black`):** White text over dark translucent box (maximum readability & contrast for movie recaps).
* **⚡ TikTok / Reels Yellow (`yellow_pop`):** High-energy gold/yellow text with bold black border and drop shadow (ideal for viral shorts).
* **⚪ Classic White Stroke (`white_stroke`):** Crisp white text with black outline (clean YouTube classic aesthetic).
* **💎 Cyber Cyan Neon (`cyan_cyber`):** Glowing cyan font with deep blue outline (perfect for Sci-Fi, Cyberpunk & Tech movies).
* **🩸 Thriller Crimson Box (`crimson_box`):** White text over dark crimson red box (high suspense for Horror, Mystery & Thrillers).

### ⚙️ 5. Resolution Quality Presets
* **🌟 1080p Full HD (Default / Highest Quality):** 1920x1080 (16:9 Landscape) & 1080x1920 (9:16 Vertical).
* **⚡ 720p HD (Faster Render / Smaller File):** 1280x720 (16:9 Landscape) & 720x1280 (9:16 Vertical) for 2x faster encoding.

### 📱 6. Multi-Format Video Output (16:9 Landscape, 9:16 Vertical Reels, or Both)
* **🌟 Both (16:9 + 9:16 - Default):** Generates both YouTube 16:9 and Facebook/TikTok 9:16 vertical videos in a single run.
* **🖥️ 16:9 Landscape Only:** Focuses exclusively on standard YouTube widescreen output.
* **📱 9:16 Vertical Only:** Produces high-speed Facebook Reels, TikTok & YouTube Shorts with dynamic bokeh video background, top hook title, and safe-zone Myanmar subtitles.

### 👫 6. AI Multi-Voice Character Dubbing & Action Narration Bridge
* **Multi-Voice Dubbing:** Automatically assigns male characters to `my-MM-ThihaNeural` and female characters to `my-MM-NilarNeural`.
* **Action Narration Bridge:** Detects non-verbal action scenes (>18s) and uses **Gemini 3.5 Flash** to synthesize engaging storyline narration so the audience never experiences silence.
* **Dynamic Audio Ducking:** Automatically lowers background ambient sound to 12% during speech and raises it back to 35% during pauses.

### 🧠 7. Google AI Studio 2026 PRO Tier & Model Auto-Rotation Chain
* **Tier Synchronization:** Pre-configured with Google AI Studio 2026 PRO quotas:
  - **Workhorse:** `gemini-3.5-flash-lite` (15 RPM) & `gemini-3.1-flash-lite` (15 RPM)
  - **Fastest Cloud:** `gemini-flash-latest` (Dynamic auto-routed to newest stable engine)
  - **Primary & Fallbacks:** `gemini-3.5-flash` (5 RPM), `gemini-3.7-flash` (5 RPM), `gemini-3.6-flash`, `gemini-3-flash`
* **Zero-Error Parsing:** Safe `_extract_text_from_gemini_response` multi-part and thought-block extractor preventing `KeyError: 'parts'`.

### ⏱️ 8. Process Records Time & Live Stopwatch Dashboard
* **Live Elapsed Stopwatch:** Real-time ticking stopwatch (`⏱️ 01:24`) on the Web UI dashboard during video processing.
* **Phase Timing Badges:** Real-time breakdown of seconds spent on each pipeline stage (Video Analysis, Whisper STT, Gemini Script Translation, Voiceover Generation, and Video Merge).
* **Historical Process Records:** Every completed output card permanently stores and displays its comprehensive duration table.

### 🚀 9. Dedicated GPU Cloud Acceleration & Hybrid PC Fallback
* **Google Colab Mode:** Dedicated **NVIDIA T4 GPU (16GB VRAM)** execution utilizing Whisper CUDA FP16 Tensor Cores, Demucs `-d cuda`, and FFmpeg NVENC (`h264_nvenc`) hardware encoder.
* **Kaggle Mode:** Dedicated **Dual NVIDIA T4 GPUs (30GB VRAM)** or **P100 GPU (16GB VRAM)** with 12-hour continuous sessions and Cloudflare Secure Tunnel.
* **Local PC Mode:** Intelligent auto-detection of NVIDIA CUDA, Intel QuickSync (`h264_qsv`), and AMD AMF (`h264_amf`), with zero-error fallback to CPU Multi-core.

### 🖼️ 10. Optional 3-Second Thumbnail Intro & Smart Audio Ducking
* **Toggleable Thumbnail Intro:** Control whether a 3-second thumbnail freeze-frame appears at video start via Web UI checkbox, `config.json` (`"thumbnail_intro": {"enabled": false, "duration_sec": 3.0}`), or CLI flags (`--thumbnail-intro` / `--no-thumbnail-intro`). When enabled, ASS subtitles are dynamically shifted to preserve flawless subtitle-to-voice synchronization.
* **Zero Dead Silence Audio Ducking:** Preserves movie ambient background SFX, BGM, and foley sound effects even when Demucs is bypassed (`--skip-demucs`), automatically ducking original audio down to 15% volume under the AI Burmese voiceover.

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
* **Video Format Selector:** Choose between `🌟 Both (16:9 + 9:16)`, `🖥️ 16:9 Landscape`, and `📱 9:16 Vertical Reels`.
* **Subtitle Style Presets:** Choose from 5 presets (`box_black`, `yellow_pop`, `white_stroke`, `cyan_cyber`, `crimson_box`) with live preview canvas.
* **Subtitle Mode Selector:** Choose between `🔥 Burn Subtitles (Hardsub)` and `🎙️ Voiceover Only (Clean Frame)`.
* **Resolution Quality Selector:** Choose between `🌟 1080p Full HD` and `⚡ 720p HD`.
* **Overnight Batch Queue:** Process multiple files/links sequentially overnight with automatic API key failover.
* **1-Click Force Stop:** Click `🛑 Force Stop Pipeline` at any time to immediately cancel execution.

### 💻 Method 2: Command Line (CLI)
```bash
# Run single movie recap with default settings
python main.py --input "movies/my_movie.mp4"

# Run with TikTok/Reels yellow subtitles and 9:16 vertical format
python main.py --input "movies/my_movie.mp4" --format 9:16 --sub-style yellow_pop

# Run batch processing with Netflix cinema box subtitles
python main.py --batch --sub-style box_black --format both
```

---

## 📄 License
MIT License. Free for educational and commercial content creation.
