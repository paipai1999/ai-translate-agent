# Movie Recap AI Agent — $0 Free Local & Cloud-Accelerated Pipeline (Burmese & English)

An end-to-end AI agentic pipeline that automatically downloads videos, isolates audio, cuts out dead air, generates viral YouTube recap narration scripts (in **Colloquial Burmese** or **English**), produces lifelike voiceovers, and renders a fast-paced, highly-retaining recap video equipped with **Advanced Anti-Copyright Protection**, **Intelligent Video/Audio Time-Stretching**, and **Dual-Engine Voice Generation (Edge-TTS & F5-TTS Voice Cloning)**.

---

## 🗂️ Project Structure

```text
MovieRecapAI/
├── agents/
│   ├── master.py              ← Pipeline orchestrator (Phases 1–7) with Parallel Multi-threading
│   ├── downloader_agent.py    ← Auto-download from URL with FFmpeg merging (yt-dlp)
│   ├── video_agent.py         ← Metadata: FPS, duration, resolution (OpenCV & FFprobe)
│   ├── audio_agent.py         ← Audio extract + Fast Whisper STT (INT8 + VAD) + Demucs Vocal Isolation
│   ├── writer_agent.py        ← YouTube recap script writer (Gemini Native Video Mode + Colloquial Spoken Burmese)
│   ├── seo_agent.py           ← Viral title, description, tags, hashtags + file export
│   ├── voice_agent.py         ← Text-to-Speech & Voiceover (Edge-TTS / F5-TTS Zero-Shot Cloning)
│   ├── f5_tts_engine.py       ← Local Flow Matching (DiT) Voice Cloning & Auto Character Voice Slicer
│   ├── video_merger_agent.py  ← Video Merger: Action Stitching, Video Time-Stretching, Dynamic SFX Ducking, Anti-Copyright
│   ├── thumbnail_agent.py     ← YouTube thumbnail generation & Vision subtitle check
│   └── qa_agent.py            ← Phase 7 QA: Auto-Rewrite Over-length blocks, Sync score & Language review
│
├── brain/
│   ├── memory.py              ← Pydantic shared state (MovieState with atomic JSON persistence)
│   ├── planner.py             ← Batch Processor for overnight queue execution
│   ├── prompts.py             ← LLM prompt templates (Writer, SEO, QA, Output Extraction)
│   ├── config.py              ← config.json loader with defaults
│   ├── gemini_client.py       ← Gemini API client with auto rate-limit & video upload
│   └── sqlite_store.py        ← SQLite WAL-mode local database for movie states
│
├── templates/
│   └── index.html             ← Modern Glassmorphic Web UI Dashboard with Voice Engine Switcher
│
├── web_ui.py                  ← FastAPI/Uvicorn Web Dashboard application (supports Direct Video Upload & SSE Logs)
├── config.json                ← Configuration (API keys, voice engine, language, QA thresholds)
├── main.py                    ← CLI entry point
├── requirements.txt           ← Python package dependencies
├── assets/                    ← Custom reference audio for voice cloning and background audio
│   └── voices/                ← Custom voice actor sample files (.wav)
├── movies/                    ← Place source video files here
├── outputs/                   ← Generated scripts, JSON, MP3 voiceover, QA reports & final MP4
└── temp/                      ← Intermediate audio / frames (Auto-cleaned)
```

---

## ⚡ Google Colab One-Click Setup (Free GPU Cloud Mode)

Running on **Google Colab** provides **Free NVIDIA T4 GPU (16GB VRAM)**, **1 Gbps Google Cloud network**, and high-speed execution for Whisper STT, Demucs, and F5-TTS Voice Cloning.

You can directly open and run the included [`MovieRecapAI_Colab.ipynb`](MovieRecapAI_Colab.ipynb) notebook on Google Colab!

Or open a new notebook on [colab.research.google.com](https://colab.research.google.com), set **Runtime > Change runtime type > T4 GPU**, and run the following cells:

### Cell 1: Clone Repository & Install Dependencies
```python
!git clone https://github.com/paipai1999/ai-translate-agent.git recap_app
%cd recap_app

!apt-get update -qq && apt-get install -y ffmpeg fonts-sil-padauk fonts-noto-cjk fonts-noto-core
!pip install -r requirements.txt
```

### Cell 2: Configure Gemini API Key
```python
import json

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

# Paste your Gemini API key from https://aistudio.google.com
config["gemini"]["api_keys"] = ["YOUR_GEMINI_API_KEY_HERE"]
config["pipeline"]["language"] = "burmese"

with open("config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4)

print("✅ Configuration Ready!")
```

### Cell 3: Run via CLI or Web UI Dashboard
```python
# Option A: Run a single YouTube video or direct file
!python main.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" -l burmese -e edge_tts

# Option B: Run Web UI Dashboard accessible from your browser
!wget -q -nc https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x cloudflared-linux-amd64
import subprocess, time
subprocess.Popen(["python", "web_ui.py"])
time.sleep(3)
!./cloudflared-linux-amd64 tunnel --url http://127.0.0.1:5000
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

# 3. Add your Gemini API Key in config.json
#    Get free API keys from: https://aistudio.google.com
```

---

## 🚀 Usage

### 🌐 Method 1: Web UI Dashboard (Recommended)
```bash
python web_ui.py
```
*Open your browser at: `http://localhost:5000`*

* **Direct Voice Engine Selector:** Switch seamlessly between `⚡ Edge TTS (Fast $0 Cloud Neural)` and `🧬 F5-TTS (Zero-Shot Voice Cloning)` directly on the UI.
* **Direct Video Upload & URL Download:** Paste any YouTube, DramaBox, or direct video URL, or click **📁 Upload** to select a file from your computer.
* **Overnight Batch Queue:** Paste multiple links to process sequentially overnight with automatic API key failover and cache cleanup.
* **Live SSE Progress Streaming:** Watch real-time log outputs, timeline status, and active rendering percentage.

---

### 💻 Method 2: Command Line Interface (CLI)

```bash
# Run a single video file or YouTube URL
python main.py "movies/sample.mp4"
python main.py "https://www.youtube.com/watch?v=5VRSIZwxJso"

# Process all videos in movies/ folder sequentially (Batch Mode)
python main.py --batch

# Select language explicitly (Burmese or English)
python main.py "movies/sample.mp4" --lang burmese

# Enable Subtitle Blur pass explicitly
python main.py "movies/sample.mp4" --subtitle

# Interactive Mass Cleanup Utility (Clean old outputs, movies, or cache)
python main.py --clean
```

---

## 🎙️ Dual Voiceover Engines

| Feature | ⚡ Microsoft Edge TTS | 🧬 F5-TTS Voice Cloning |
| :--- | :---: | :---: |
| **Type** | Cloud Neural Speech Synthesis | Local Flow Matching (DiT) Diffusion |
| **Best For** | 🇲🇲 **Myanmar (Burmese)** & English | 🇬🇧 English & Global Multilingual |
| **Cost** | 🟢 **$0 (100% Free)** | 🟢 **$0 (Open-Source)** |
| **Hardware Load** | ⚡ **0% CPU/GPU Load** | 🖥️ GPU / CPU Accelerated |
| **Voice Models** | `my-MM-ThihaNeural`, `my-MM-NilarNeural`, `en-US-GuyNeural` | Auto Character Cloned Vocals / Custom WAV |

---

## 📦 Output Files

After processing `movies/my_movie.mp4`, outputs appear in `outputs/my_movie/`:

* `final_recap.mp4` — **FINAL RENDERED VIDEO** (Action-stitched, AI Voiceover, SFX Ducking, Anti-Copyright Protection).
* `thumbnail.jpg` — High-CTR YouTube Thumbnail image.
* `seo_metadata.json` — Viral YouTube Title, Description, Tags, and Hashtags.
* `final_recap_script.txt` — Full human-readable narration script with timestamps.
* `qa_report.txt` — Detailed QA sync and language quality score.
* `voiceover/` — Individual MP3 audio narration clips per scene.
* `state.json` — Comprehensive pipeline state and execution metadata.

---

## 🧠 7-Phase Agentic Architecture

```text
Input (Video File or URL)
  │
  ▼ Phase 1: VideoAgent          (OpenCV/FFprobe — FPS, Resolution, Duration Analysis)
  ▼ Phase 2: AudioAgent          (Demucs Vocal Separation + Faster-Whisper INT8 VAD STT)
  ▼ Phase 3: SceneAgent          (PySceneDetect — Visual scene cut detection & chapter clustering)
  ▼ Phase 4: WriterAgent & SEO   (Gemini 3.5 Native Video Mode + Colloquial Burmese Script + SEO Tags)
  ▼ Phase 5: VoiceAgent          (Edge-TTS Neural Voice / F5-TTS Flow Matching Voice Cloning)
  ▼ Phase 6: VideoMergerAgent    (Action Stitching, Dynamic Video Speed Stretch, SFX Ducking, Anti-Copyright)
  ▼ Phase 7: QAAgent             (Duration enforcement, Sync analysis, and Auto-Rewrite loop)
  │
  ▼ outputs/my_movie/final_recap.mp4 & thumbnail.jpg
```

---

## 🛡️ Key Features & Resilience

1. **Native Video Understanding (`gemini-3.5-flash-lite` / `gemini-3.6-flash`):** Understands visual narrative context directly from video frames without relying solely on audio dialogue.
2. **True Action-Stitching (Zero Dead Air):** Automatically trims silent intervals and stitches key action scenes with 0.2s cinematic transitions.
3. **Audio-Video Time Stretching:** Maintains 100% natural human speech pitch while subtly adjusting video speed (`0.85x`–`1.2x`) for frame-accurate synchronization.
4. **Demucs SFX Isolation & Ducking:** Separates clean background SFX and ducks audio volume to 15% when the narrator speaks.
5. **Anti-Copyright Defense Suite:** Multi-layer protection including horizontal mirroring, dynamic shifting film grain (`noise=alls=2:allf=t`), vignette borders, and pixel color grading.
6. **VisionAI Subtitle Blurring:** Uses Gemini Vision to detect hardcoded foreign subtitles and applies dynamic bounding-box blur.
7. **Colloquial Burmese Optimization:** Generates natural spoken Burmese (`လေ၊ ပေါ့၊ ဟယ်၊ ဗျာ`) with automated Burmese number-to-word transliteration.

---

## ⚠️ Disclaimer

This tool is designed for educational, research, fair-use commentary, and transformative analysis purposes. Ensure compliance with local copyright regulations and platform policies when publishing AI-assisted video content.
