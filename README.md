# AI Movie Translate & Dubbing Agent (v2.2) — $0 Free Local & Cloud-Accelerated Pipeline

An end-to-end autonomous AI agentic pipeline that transcribes video audio line-by-line, generates natural **1:1 Spoken Dialogue Translations** (in **Colloquial Burmese** or **English**), synthesizes lifelike voiceovers, and renders a fully dubbed video equipped with **Advanced Anti-Copyright Protection**, **Burned Myanmar ASS Subtitles**, **Dynamic High-CTR Thumbnails**, **Custom Watermark Branding**, and **Dual-Engine Voiceover (Edge-TTS & F5-TTS Voice Cloning)**.

---

## ⚡ Google Colab One-Click Setup (Free GPU Cloud Mode)

Running on **Google Colab** provides **Free NVIDIA T4 GPU (16GB VRAM)**, **1 Gbps Google Cloud network**, and high-speed execution for Whisper STT, Demucs, and F5-TTS Voice Cloning with **Zero Google Drive dependency** (100% high-speed NVMe local SSD).

👉 **[Open AI_Movie_Translate_Colab.ipynb in Google Colab](https://colab.research.google.com/github/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Colab.ipynb)**

### ✨ Colab Highlights:
1. **⚡ 1-Click All-in-One Translation Runner:** Paste your YouTube / DramaBox URL, enter your Gemini API Key, and press Play (▶️) once. The entire pipeline runs autonomously to produce the final dubbed video!
2. **⚡ Colab Auto Keep-Alive Heartbeat:** Built-in background heartbeat prevents Colab idle session disconnects during long movie translations.
3. **🌐 Interactive Web UI with Cloudflare Tunnel:** Run Step 4 (Option B) to launch the Glassmorphic Web Dashboard with an automatic browser tab pop-up!
4. **🎬 In-Notebook Media Player:** Watch the rendered video, review the high-CTR thumbnail, and inspect translated Burmese dialogues directly inside Colab.

---

## 🗂️ Project Structure

```text
ai-translate-agent/
├── agents/
│   ├── master.py              ← Pipeline orchestrator (Phases 1–7) with Auto-Temp Cleanup
│   ├── downloader_agent.py    ← Video downloader with retry & fallback formats (yt-dlp)
│   ├── video_agent.py         ← Metadata: FPS, duration, resolution (OpenCV & FFprobe)
│   ├── audio_agent.py         ← Audio extract + Fast Whisper STT (INT8 + VAD) + Demucs Vocal Isolation
│   ├── writer_agent.py        ← 1:1 Full Spoken Dialogue Translation (Colloquial Burmese & English)
│   ├── seo_agent.py           ← Viral title, description, tags, hashtags + file export
│   ├── voice_agent.py         ← Text-to-Speech (Edge-TTS Cloud Neural / F5-TTS Zero-Shot Cloning)
│   ├── f5_tts_engine.py       ← Local Flow-Matching Voice Cloning with SoundFile Windows patch
│   ├── video_merger_agent.py  ← Video Merger: High-Contrast ASS Subtitles, Subtitle Blur, Watermark Overlay
│   ├── thumbnail_agent.py     ← High-CTR Golden Yellow Top-Center Thumbnail Generator with Vision Check
│   └── qa_agent.py            ← Phase 7 QA: Auto-Rewrite Over-length blocks, Sync score & Language review
│
├── brain/
│   ├── memory.py              ← Pydantic shared state (MovieState with atomic JSON persistence)
│   ├── planner.py             ← Batch Processor with branding & custom thumbnail support
│   ├── prompts.py             ← LLM prompt templates (Dialogue Translation, SEO, QA)
│   ├── config.py              ← config.json loader with safe defaults
│   ├── gemini_client.py       ← Gemini API client with Gemini 2.0 Flash priority & key rotation
│   └── sqlite_store.py        ← SQLite WAL-mode local database for movie states
│
├── templates/
│   └── index.html             ← Modern Glassmorphic Web UI Dashboard with Branding & Thumbnail controls
│
├── web_ui.py                  ← FastAPI Web Dashboard (Direct Upload, Live SSE Logs, Branding API)
├── config.json                ← Active runtime configuration (API keys, branding, models)
├── config.example.json        ← Default configuration template
├── main.py                    ← CLI entry point with --thumb-title and --watermark-text flags
├── requirements.txt           ← Python package dependencies
├── assets/                    ← Reference voice samples and branding assets
│   └── voices/default_ref.wav ← Bundled reference voice sample for F5-TTS zero-shot cloning
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
python main.py "https://www.youtube.com/watch?v=5VRSIZwxJso"

# Custom Thumbnail Title & Watermark Branding
python main.py "movies/sample.mp4" --thumb-title "သေမင်းတမန်" --watermark-text "PAI Channel"

# Disable Watermark
python main.py "movies/sample.mp4" --no-watermark

# Process all videos in movies/ folder sequentially (Batch Mode)
python main.py --batch

# Select voice engine (edge_tts or f5_tts)
python main.py "movies/sample.mp4" -e f5_tts

# Select language explicitly (Burmese or English)
python main.py "movies/sample.mp4" --lang burmese

# Enable Subtitle Blur pass explicitly
python main.py "movies/sample.mp4" --subtitle

# Interactive Mass Cleanup Utility
python main.py --clean
```

---

## 🎙️ Dual Voiceover Engines

| Feature | ⚡ Microsoft Edge TTS | 🧬 F5-TTS Zero-Shot Cloning |
| :--- | :---: | :---: |
| **Type** | Cloud Neural Speech Synthesis | Local Flow-Matching (DiT) Diffusion |
| **Best For** | 🇲🇲 **Myanmar (Burmese)** & English | 🇬🇧 Character Voice Cloning & Multilingual |
| **Cost** | 🟢 **$0 (100% Free)** | 🟢 **$0 (Open-Source)** |
| **Hardware Load** | ⚡ **Instant (~1s per line, 0% GPU load)** | 🖥️ GPU Accelerated (~2s on Colab T4) |
| **Voice Models** | `my-MM-ThihaNeural`, `my-MM-NilarNeural`, `en-US-GuyNeural` | Zero-Shot Cloned from Reference Audio / Actor Vocals |
| **Windows Support** | Built-in Async Client | 🛡️ Native SoundFile Patch (No DLL crashes) |

---

## 📦 Output Files

After processing `movies/my_movie.mp4`, outputs appear in `outputs/my_movie/`:

* `final_recap.mp4` — **FINAL FULLY DUBBED VIDEO** (Action-stitched, 1:1 Dialogue Dubbing, Burned ASS Subtitles, Watermark, Anti-Copyright Protection).
* `thumbnail.jpg` — High-CTR YouTube Thumbnail image (Golden Yellow, Top-Center, 1080p).
* `seo_metadata.json` — Viral YouTube Title, Description, Tags, and Hashtags.
* `final_recap_script.txt` — Full line-by-line translated Burmese dialogue script with timestamps.
* `qa_report.txt` — Detailed QA sync and language quality score.
* `voiceover/` — Individual MP3 audio dialogue clips per scene.
* `state.json` — Comprehensive pipeline state and execution metadata.

---

## 🧠 7-Phase Autonomous Architecture

```text
Input (Video File or URL)
  │
  ▼ Phase 1: VideoAgent          (OpenCV/FFprobe — FPS, Resolution, Duration Analysis)
  ▼ Phase 2: AudioAgent          (Demucs Vocal Separation + Faster-Whisper INT8 VAD STT)
  ▼ Phase 3: SceneAgent          (PySceneDetect — Visual scene cut detection & chapter clustering)
  ▼ Phase 4: WriterAgent & SEO   (1:1 Full Spoken Dialogue Translation + Colloquial Burmese + SEO Tags)
  ▼ Phase 5: VoiceAgent          (Edge-TTS Neural Voice / F5-TTS Zero-Shot Character Voice Cloning)
  ▼ Phase 6: VideoMergerAgent    (Action Stitching, High-Contrast ASS Subtitles, Subtitle Blur, Watermark)
  ▼ Phase 7: QAAgent & Cleanup   (Sync validation, Auto-Temp Cleanup to save disk space)
  │
  ▼ outputs/my_movie/final_recap.mp4 & thumbnail.jpg
```

---

## 🛡️ Key Features & Resilience

1. **1:1 Full Spoken Dialogue Translation:** Completely abolishes the 1-block-per-chapter summary recap architecture. Every spoken line from Whisper STT is translated into colloquial spoken Burmese (`လေ၊ ပေါ့၊ ဟယ်၊ ဗျာ`).
2. **High-CTR YouTube Thumbnail Generator:** Auto-extracts the sharpest, brightest keyframe using OpenCV Laplacian variance + HSV brightness, renders vibrant golden-yellow titles at Top-Center with deep black shadows.
3. **Custom Branding & Watermark Overlay:** Supports transparent PNG watermarks with customizable opacity, position, and text.
4. **High-Contrast Burned Subtitles:** Burns Myanmar Unicode ASS subtitles with a 70% deep dark box background (`&HB0000000`), 10px padding, and 2px shadow for maximum readability on bright movie scenes. Automatically shifts subtitle timestamps by +3.0s to sync with the thumbnail intro.
5. **Gemini 2.0 Flash Priority & Multi-Key Failover:** Primary model set to Gemini 2.0 Flash with automatic failover across 6 backup models and key rotation.
6. **Anti-Copyright Defense Suite:** Multi-layer protection including horizontal mirroring, dynamic shifting film grain (`noise=alls=2:allf=t`), vignette borders, and color grading.
7. **Auto-Temp Disk Optimizer:** Automatically cleans up intermediate audio/video chunks in `temp/` after the final video is successfully created.

---

## ⚠️ Disclaimer

This tool is designed for educational, research, fair-use commentary, and transformative translation purposes. Ensure compliance with local copyright regulations and platform policies when publishing AI-assisted video content.

