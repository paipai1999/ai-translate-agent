import json
import os

# Default configuration for the entire pipeline
DEFAULT_CONFIG = {
    "pipeline": {
        "language": "burmese",            # burmese (မြန်မာ - Thiha Voice) | english (အင်္ဂလိပ် - Guy Voice)
        "whisper_model": "small",         # small | base | medium | large (small is a good balance between speed and accuracy)
        "scene_threshold": 30.0,           # PySceneDetect sensitivity (lower = more scenes)
        "max_characters": 6,               # Max character names to detect
        "max_scenes_for_llm": 30,          # Scene count cap passed to LLM (context limit)
        "parallel_processing": True        # Run STT & Scene detection in parallel (set False for Low RAM)
    },
    "gemini": {
        "enabled": True,                   # Use Gemini API when writing Burmese recap scripts for natural spoken flow
        "api_keys": [],
        "model": "gemini-3.5-flash",       # Primary model: gemini-3.5-flash (fast, reliable 2026 production model)
        "daily_limit_per_key": 50,
        "model_limits": {
            "gemini-3.5-flash": 50,
            "gemini-3.5-flash-lite": 50,
            "gemini-3.6-flash": 40,
            "gemini-flash-lite-latest": 50
        },
        "models": {
            "heavy": "gemini-3.5-flash",
            "workhorse": "gemini-3.5-flash",
            "polish": "gemini-3.5-flash-lite"
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
        "temp_dir": "temp"
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
        "font_name": "Myanmar Text",
        "font_size": 40,
        "bold": True,
        "border_style": 3,
        "outline_width": 3,
        "margin_bottom": 50,
        "max_chars_per_line": 28
    },
    "logging": {
        "level": "INFO",                   # DEBUG | INFO | WARNING
        "save_log_file": True
    }
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
