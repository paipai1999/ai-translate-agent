import os
import json
import threading
from datetime import datetime, timezone, timedelta

# BUG-M3 Fix: Use DST-aware Pacific Time via zoneinfo + tzdata (works on Windows too).
# On Windows, Python's zoneinfo requires 'tzdata' package for IANA zone names.
# We try the full stack and fall back to a fixed offset if unavailable.
_PT_ZONE = None
try:
    from zoneinfo import ZoneInfo
    _PT_ZONE = ZoneInfo("America/Los_Angeles")
except Exception:
    try:
        # tzdata package provides IANA timezone database on Windows
        from zoneinfo import ZoneInfo
        _PT_ZONE = ZoneInfo("America/Los_Angeles")
    except Exception:
        pass  # Will use fixed UTC-8 fallback below

DB_PATH = os.path.join("outputs", "api_usage_db.json")
_db_lock = threading.Lock()

def get_google_utc_date() -> str:
    """Returns current date in Pacific Time (PT) — DST-aware where possible.
    Google Gemini API resets daily limits at midnight Pacific Time.
    """
    if _PT_ZONE is not None:
        try:
            pt_time = datetime.now(_PT_ZONE)
            return pt_time.strftime("%Y-%m-%d")
        except Exception:
            pass
    # Fallback: fixed UTC-8 (PST). During PDT (summer) this is 1hr early — acceptable.
    pt_time = datetime.now(timezone.utc) - timedelta(hours=8)
    return pt_time.strftime("%Y-%m-%d")

def load_usage_db() -> dict:
    """Loads usage database. Automatically resets daily counts at 00:00 UTC."""
    os.makedirs("outputs", exist_ok=True)
    current_utc = get_google_utc_date()
    data = {"utc_date": current_utc, "keys": {}}

    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception as e:
            print(f"[WARN] Usage DB load error: {e}")

    if data.get("utc_date") != current_utc:
        data["utc_date"] = current_utc
        for k, v in data.get("keys", {}).items():
            if isinstance(v, dict):
                v["utc_date"] = current_utc
                # Migrate old format if exists
                v.pop("used_today", None)
                v.pop("status", None)
                if "models" not in v:
                    v["models"] = {}
                for m_name, m_data in v.get("models", {}).items():
                    m_data["used_today"] = 0
                    m_data["status"] = "active"
        save_usage_db(data)

    return data

def save_usage_db(data: dict):
    # BUG-M2 Fix: Atomic write via temp file + os.replace() to prevent JSON corruption on crash.
    os.makedirs("outputs", exist_ok=True)
    tmp_path = DB_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, DB_PATH)
    except Exception as e:
        print(f"[WARN] Usage DB save error: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass

def _ensure_key_model_exists(db: dict, key: str, model: str) -> tuple:
    """Ensures structure exists and returns (kdata, mdata)."""
    current_utc = get_google_utc_date()
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else key
    keys_dict = db.setdefault("keys", {})
    
    if masked not in keys_dict:
        keys_dict[masked] = {
            "masked_key": masked,
            "utc_date": current_utc,
            "models": {}
        }
    
    kdata = keys_dict[masked]
    
    # Check if key is out of date (reset)
    if kdata.get("utc_date") != current_utc:
        kdata["utc_date"] = current_utc
        for m_name, m_data in kdata.get("models", {}).items():
            m_data["used_today"] = 0
            m_data["status"] = "active"
            
    models_dict = kdata.setdefault("models", {})
    if model not in models_dict:
        models_dict[model] = {
            "used_today": 0,
            "status": "active"
        }
        
    return kdata, models_dict[model]

def reserve_model_usage(key: str, model: str, limit: int) -> bool:
    """Atomically checks limit and reserves 1 usage if under limit."""
    with _db_lock:
        db = load_usage_db()
        kdata, mdata = _ensure_key_model_exists(db, key, model)
        
        used = mdata.get("used_today", 0)
        if used >= limit:
            return False
            
        # Reserve it
        mdata["used_today"] = used + 1
        mdata["status"] = "active"
        kdata["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        save_usage_db(db)
        return True

def record_key_usage(key: str, model: str, status: str = "success"):
    """Records completion status. If error/rate-limited, refunds the reserved usage."""
    with _db_lock:
        db = load_usage_db()
        kdata, mdata = _ensure_key_model_exists(db, key, model)
        
        if status == "success":
            mdata["status"] = "active"
        else:
            # Refund the reservation on failure
            used = mdata.get("used_today", 0)
            if used > 0:
                mdata["used_today"] = used - 1
            if status == "rate_limited":
                mdata["status"] = "rate-limited (RPM)"
            else:
                mdata["status"] = status
                
        kdata["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        save_usage_db(db)

def get_key_usage(key: str) -> dict:
    """Returns usage dictionary for a specific key."""
    db = load_usage_db()
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else key
    return db.get("keys", {}).get(masked, {})
