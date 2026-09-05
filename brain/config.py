import json
import os

# Default configuration for the entire pipeline
DEFAULT_CONFIG = {
    "pipeline": {
        "language": "burmese",            # burmese (မြန်မာ - Thiha Voice) | english (အင်္ဂလိပ် - Guy Voice)
        "video_format": "both",            # "both" (16:9 + 9:16) | "16:9" (YouTube Landscape) | "9:16" (Facebook Reels / TikTok)
        "whisper_model": "small",         # small | base | medium | large (small is a good balance between speed and accuracy)
        "scene_threshold": 30.0,           # PySceneDetect sensitivity (lower = more scenes)
        "max_characters": 6,               # Max character names to detect
        "max_scenes_for_llm": 30,          # Scene count cap passed to LLM (context limit)
        "parallel_processing": True,       # Run STT & Scene detection in parallel (set False for Low RAM)
        "use_demucs": True                 # Vocal separation with Demucs (high accuracy)
    },
    "gemini": {
        "enabled": True,                   # Use Gemini API when writing Burmese recap scripts for natural spoken flow
        "api_keys": [],
        "model": "gemini-3.5-flash-lite",       # Primary model: gemini-3.5-flash-lite (fast, reliable 2026 production model)
        "daily_limit_per_key": 50,
        "model_limits": {
            "gemini-3.5-flash-lite": 15,
            "gemini-flash-latest": 15,
            "gemini-3.1-flash-lite": 15,
            "gemini-3.5-flash": 5,
            "gemini-3.6-flash": 5,
            "gemini-3.7-flash": 5,
            "gemini-3-flash": 5
        },
        "models": {
            "heavy": "gemini-flash-latest",
            "workhorse": "gemini-3.5-flash-lite",
            "polish": "gemini-3.1-flash-lite"
        }
    },
    "voice": {
        "enabled": True,
        "engine": "edge_tts",                 # "edge_tts" (Fast $0 Cloud TTS) | "f5_tts" (Zero-Shot Voice Cloning)
        "tts_voice_mm": "my-MM-ThihaNeural",  # Burmese voice (Thiha)
        "tts_voice_en": "en-US-GuyNeural",    # English voice (Guy)
        "tts_voice": "my-MM-ThihaNeural",     # Active default voice
        "tts_rate_mm": "+8%",
        "tts_rate_en": "+15%",
        "f5_tts": {
            "model_type": "F5-TTS",           # "F5-TTS" | "E2-TTS"
            "auto_character_cloning": True,   # Auto-extract reference audio slices for characters from Demucs vocals
            "default_ref_audio": "assets/voices/default_ref.wav",
            "default_ref_text": "",
            "speed": 1.0,
            "device": "auto"                  # "auto" | "cuda" | "cpu"
        }
    },
    "batch": {
        "movies_folder": "movies",
        "max_parallel_jobs": 1,            # Keep at 1 for CPU-only machines
        "skip_completed": True             # Skip movies with existing state.json output
    },
    "paths": {
        "output_dir": "outputs",
        "temp_dir": "temp",
        "clean_temp_after_merge": True
    },
    "copyright_protection": {
        "enabled": True,
        "mirror_video": False,
        "resize_factor": 1.02
    },
    "subtitle_blur": {
        "enabled": True,
        "region_height_pct": 0.18,
        "blur_strength": 18
    },
    "color_grading": {
        "enabled": True,
        "brightness": 0.03,
        "contrast": 1.02,
        "saturation": 1.08
    },
    "bgm": {
        "enabled": False,
        "folder": "assets/bgm",
        "volume": 0.22,
        "style": ""
    },
    "watermark": {
        "enabled": True,
        "text": "PAI AI Movie Translate",
        "opacity": 0.4,
        "margin": 30,
        "font_size": 40
    },
    "subtitle_overlay": {
        "enabled": True,
        "style_preset": "box_black",       # "box_black" | "yellow_pop" | "white_stroke" | "cyan_cyber" | "crimson_box"
        "font_name": "Myanmar Text",
        "font_size": 40,
        "bold": True,
        "border_style": 3,
        "outline_width": 3,
        "margin_bottom": 50,
        "max_chars_per_line": 28
    },
    "reels": {
        "enabled": True,
        "width": 1080,
        "height": 1920,
        "blur_background": True,
        "blur_sigma": 25,
        "hook_title_color": "&H00D7FF",
        "font_size": 52,
        "safe_zone_margin": 160
    },
    "action_narration": {
        "enabled": True,
        "min_gap_sec": 18.0,
        "max_bridge_duration_sec": 6.0
    },
    "audio_ducking": {
        "enabled": True,
        "duck_volume": 0.12,
        "ambient_volume": 0.35
    },
    "thumbnail_intro": {
        "enabled": False,                  # If True, prepends 3-second freeze-frame thumbnail intro
        "duration_sec": 3.0
    },
    "logging": {
        "level": "INFO",                   # DEBUG | INFO | WARNING
        "save_log_file": True
    }
}

# Subtitle Style Presets for ASS rendering (colors in &HAABBGGRR format)
SUBTITLE_PRESETS = {
    "box_black": {
        "id": "box_black",
        "name": "Cinema Box (Netflix Style)",
        "desc": "အမည်းရောင် Background Box ပါသော ရုပ်ရှင်ရုံသုံး စာတန်း (Contrast အကောင်းဆုံး)",
        "font_size": 40,
        "bold": True,
        "border_style": 3,
        "outline_width": 10,
        "shadow": 2,
        "primary_color": "&H00FFFFFF",   # Pure White
        "outline_color": "&H00000000",   # Black
        "back_color": "&HB0000000",      # 70% Dark Box
        "margin_bottom": 50,
        "badge_color": "#ffffff",
        "badge_bg": "rgba(0,0,0,0.8)",
    },
    "yellow_pop": {
        "id": "yellow_pop",
        "name": "TikTok / Reels Pop (Yellow & Black)",
        "desc": "ရွှေဝါရောင်စာလုံးနှင့် အမည်းရောင်အနားသတ် ထူထူ (Reels / TikTok လူကြိုက်များ)",
        "font_size": 42,
        "bold": True,
        "border_style": 1,
        "outline_width": 4,
        "shadow": 3,
        "primary_color": "&H0000D7FF",   # Vibrant Gold / Yellow
        "outline_color": "&H00000000",   # Black Outline
        "back_color": "&H80000000",
        "margin_bottom": 50,
        "badge_color": "#ffd700",
        "badge_bg": "rgba(255,215,0,0.15)",
    },
    "white_stroke": {
        "id": "white_stroke",
        "name": "Classic Movie White (Drop Shadow)",
        "desc": "အဖြူရောင်သန့်သန့်နှင့် အမည်းရောင် အနားသတ်ရိပ် (Standard Movie Subtitle)",
        "font_size": 40,
        "bold": True,
        "border_style": 1,
        "outline_width": 3.5,
        "shadow": 2.5,
        "primary_color": "&H00FFFFFF",   # Pure White
        "outline_color": "&H00000000",   # Black Outline
        "back_color": "&H90000000",
        "margin_bottom": 50,
        "badge_color": "#ffffff",
        "badge_bg": "rgba(255,255,255,0.15)",
    },
    "cyan_cyber": {
        "id": "cyan_cyber",
        "name": "Cyber Cyan (Sci-Fi & Modern)",
        "desc": "စိမ်းပြာရောင် ခေတ်မီဆန်းသစ်သော စာတန်းပုံစံ (Anime / Sci-Fi Recap)",
        "font_size": 40,
        "bold": True,
        "border_style": 1,
        "outline_width": 3.5,
        "shadow": 2.5,
        "primary_color": "&H00FFFF00",   # Bright Cyan
        "outline_color": "&H00000000",   # Black Outline
        "back_color": "&H80000000",
        "margin_bottom": 50,
        "badge_color": "#00ffff",
        "badge_bg": "rgba(0,255,255,0.15)",
    },
    "crimson_box": {
        "id": "crimson_box",
        "name": "Thriller Crimson (Dark Red Box)",
        "desc": "အနီရင့်ရောင် Background Box ပါသော စိတ်လှုပ်ရှားဖွယ် စာတန်း (Horror / Action Recap)",
        "font_size": 40,
        "bold": True,
        "border_style": 3,
        "outline_width": 10,
        "shadow": 2,
        "primary_color": "&H00FFFFFF",   # Pure White
        "outline_color": "&H00000000",
        "back_color": "&HA0151570",      # Dark Crimson Box
        "margin_bottom": 50,
        "badge_color": "#ff4d4d",
        "badge_bg": "rgba(255,77,77,0.2)",
    },
}

CONFIG_FILE = "config.json"

_config_cache = None
_config_cache_mtime = 0.0

def load_config() -> dict:
    """Loads config.json if it exists, otherwise creates it with defaults and returns defaults."""
    global _config_cache, _config_cache_mtime
    try:
        mtime = os.path.getmtime(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else 0.0
    except Exception:
        mtime = 0.0
    if _config_cache is not None and mtime == _config_cache_mtime:
        return _config_cache

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
        except Exception:
            user_config = {}
            
        merged = {**DEFAULT_CONFIG}
        for section, values in user_config.items():
            if section in merged and isinstance(merged[section], dict):
                merged[section] = {**merged[section], **values}
            else:
                merged[section] = values
        _config_cache = merged
        _config_cache_mtime = mtime
        return merged
    else:
        # First-time: write the default config file for the user
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        print(f"[*] Config: Created default config file -> {CONFIG_FILE}")
        _config_cache = DEFAULT_CONFIG
        _config_cache_mtime = mtime
        return DEFAULT_CONFIG

def get(section: str, key: str, fallback=None):
    """Convenience getter: config.get('gemini', 'model')"""
    cfg = load_config()
    return cfg.get(section, {}).get(key, fallback)

def save_config(config_data: dict) -> None:
    """Atomically save config and refresh the in-process cache."""
    global _config_cache, _config_cache_mtime
    tmp_file = CONFIG_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)
    os.replace(tmp_file, CONFIG_FILE)
    _config_cache = config_data
    _config_cache_mtime = os.path.getmtime(CONFIG_FILE)
