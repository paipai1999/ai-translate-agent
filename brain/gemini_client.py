import json
import time
import os
import urllib.request
import urllib.error
from typing import Union, List

def _mask_key(key: str) -> str:
    """Mask API key for safe logging."""
    if not key or len(key) <= 8:
        return '***'
    return key[:6] + '...' + key[-4:]

# ─────────────────────────────────────────────────────────────────────────────
# Valid Google AI Studio Gemini Models (as of 2025):
#
# 1. gemini-2.5-flash     : Primary — best quality + speed (10 RPD free tier)
# 2. gemini-2.0-flash     : Workhorse — fast + high quota (15 RPD free tier)
# 3. gemini-1.5-flash     : Fallback — stable + proven (15 RPD free tier)
# ─────────────────────────────────────────────────────────────────────────────
_FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
]

# How many seconds to wait when ALL keys are rate-limited before retrying.
# Must be >= 60 to let the per-minute quota window reset.
_RPM_WAIT_SEC = 65


def call_gemini(
    system_prompt: str,
    user_prompt: str,
    api_key: Union[str, List[str]],
    model: str = "gemini-3.5-flash-lite",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> tuple:
    """Shared Gemini API client with automatic model fallback and API key rotation.

    Returns:
        (text, used_model) tuple on success.
    Raises:
        The last exception on total failure.
    """
    api_keys = _normalize_keys(api_key)

    # Build de-duplicated model list (requested model first, then fallbacks)
    models_to_try = _build_model_list(model)

    last_err = None

    import brain.config as cfg
    from brain.tracker import reserve_model_usage
    model_limits = cfg.load_config().get("gemini", {}).get("model_limits", {})

    # Up to 3 full rotation attempts (with 65-second RPM-reset waits in between)
    for attempt in range(3):
        for m in models_to_try:
            limit = int(model_limits.get(m, 20))
            for key in api_keys:
                key = str(key).strip()
                if not key:
                    continue
                
                if not reserve_model_usage(key, m, limit):
                    continue

                url = (
                    f"https://generativelanguage.googleapis.com"
                    f"/v1beta/models/{m}:generateContent?key={key}"
                )
                payload = {
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                        "responseMimeType": "application/json",
                    },
                }

                try:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=120.0) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        _record_api_usage(key, m, "success")
                        candidates = res_data.get("candidates", [])
                        if not candidates or "content" not in candidates[0]:
                            finish_reason = candidates[0].get("finishReason", "UNKNOWN") if candidates else "NO_CANDIDATES"
                            raise Exception(f"Gemini blocked response: finishReason={finish_reason}")
                        text = candidates[0]["content"]["parts"][0]["text"]
                        return text, m

                except urllib.error.HTTPError as e:
                    last_err = e
                    err_body = ""
                    try: err_body = e.read().decode("utf-8")
                    except Exception: pass
                    
                    if e.code == 429:
                        setattr(e, "is_quota", "quota" in err_body.lower() or "exhausted" in err_body.lower())
                        if getattr(e, "is_quota", False):
                            print(f"[!] Gemini API Daily Quota Exhausted (429) on '{m}'. Trying next API key...")
                        else:
                            print(f"[!] Gemini API Rate Limit (429) hit on '{m}'. Trying next API key...")
                        _record_api_usage(key, m, "rate_limited")
                        time.sleep(1)   # tiny pause — don't hammer
                        continue        # next key, same model
                    elif e.code == 404:
                        print(
                            f"[!] Gemini API model '{m}' not available for key '{_mask_key(key)}' (404). "
                            f"Trying next key on the same model..."
                        )
                        _record_api_usage(key, m, "error_404")
                        continue        # next key, same model
                    else:
                        print(
                            f"[!] Gemini API model '{m}' returned HTTP {e.code} on key '{_mask_key(key)}'. "
                            f"Trying next key..."
                        )
                        _record_api_usage(key, m, f"error_{e.code}")
                        continue        # next key, same model

                except Exception as e:
                    last_err = e
                    _record_api_usage(key, m, "error")
                    print(f"[!] Gemini API model '{m}' failed on key '{_mask_key(key)}': {e}. Trying next key...")
                    continue        # next key, same model

        # All keys × all models exhausted for this attempt
        if attempt < 2:
            is_rate_limit = (
                isinstance(last_err, urllib.error.HTTPError)
                and last_err.code == 429
                and not getattr(last_err, "is_quota", False)
            )
            if is_rate_limit:
                print(
                    f"[!] All API keys hit Rate Limit! "
                    f"Waiting {_RPM_WAIT_SEC}s for RPM quota to reset "
                    f"(attempt {attempt + 1}/3)..."
                )
                time.sleep(_RPM_WAIT_SEC)
            else:
                break   # non-transient error or daily quota — stop retrying

    raise last_err or Exception("All Gemini API keys and models failed.")


# ─────────────────────────────────────────────────────────────────────────────
# Vision (multimodal) variant
# ─────────────────────────────────────────────────────────────────────────────
def call_gemini_vision(
    system_prompt: str,
    user_text: str,
    image_path: str,
    api_key: Union[str, List[str]],
    model: str = "gemini-3.5-flash-lite",
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> tuple:
    """Multimodal Gemini Vision call: sends a frame image + text for grounded narration."""
    import base64

    api_keys = _normalize_keys(api_key)
    models_to_try = _build_model_list(model)

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    import brain.config as cfg
    from brain.tracker import reserve_model_usage
    model_limits = cfg.load_config().get("gemini", {}).get("model_limits", {})

    last_err = None

    for attempt in range(3):
        for m in models_to_try:
            limit = int(model_limits.get(m, 20))
            for key in api_keys:
                key = str(key).strip()
                if not key:
                    continue
                
                if not reserve_model_usage(key, m, limit):
                    continue

                url = (
                    f"https://generativelanguage.googleapis.com"
                    f"/v1beta/models/{m}:generateContent?key={key}"
                )
                payload = {
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"inline_data": {"mime_type": "image/jpeg" if image_path.lower().endswith(('.jpg', '.jpeg')) else "image/png" if image_path.lower().endswith('.png') else "image/webp" if image_path.lower().endswith('.webp') else "image/jpeg", "data": img_b64}},
                            {"text": user_text},
                        ],
                    }],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                        "responseMimeType": "application/json",
                    },
                }

                try:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=120.0) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        _record_api_usage(key, m, "success")
                        candidates = res_data.get("candidates", [])
                        if not candidates or "content" not in candidates[0]:
                            finish_reason = candidates[0].get("finishReason", "UNKNOWN") if candidates else "NO_CANDIDATES"
                            raise Exception(f"Gemini blocked response: finishReason={finish_reason}")
                        text = candidates[0]["content"]["parts"][0]["text"]
                        return text, m

                except urllib.error.HTTPError as e:
                    last_err = e
                    err_code = e.code
                    err_body = ""
                    try: err_body = e.read().decode("utf-8")
                    except Exception: pass

                    if err_code == 429:
                        setattr(e, "is_quota", "quota" in err_body.lower() or "exhausted" in err_body.lower())
                        if getattr(e, "is_quota", False):
                            print(f"[WARN] Vision Model '{m}' Daily Quota Exhausted (429) on key '{_mask_key(key)}'. Retrying next key...")
                        else:
                            print(f"[WARN] Vision Model '{m}' rate-limited (429). Retrying next key...")
                        _record_api_usage(key, m, "rate_limited")
                        time.sleep(1)
                        continue
                    elif err_code == 404:
                        print(f"[WARN] Vision Model '{m}' 404 Not Found on key '{_mask_key(key)}'. Trying next key on the same model...")
                        _record_api_usage(key, m, "error_404")
                        continue
                    else:
                        print(f"[WARN] Vision Model '{m}' returned HTTP {err_code}: {err_body[:200]} -- trying next key...")
                        _record_api_usage(key, m, f"error_{err_code}")
                        continue

                except Exception as e:
                    last_err = e
                    print(f"[WARN] Vision Model '{m}' failed on key '{_mask_key(key)}': {e}. Trying next key...")
                    continue

        if attempt < 2:
            is_rate_limit = (
                isinstance(last_err, urllib.error.HTTPError)
                and last_err.code == 429
                and not getattr(last_err, "is_quota", False)
            )
            if is_rate_limit:
                print(
                    f"[!] VisionAPI: All keys rate-limited. "
                    f"Waiting {_RPM_WAIT_SEC}s (attempt {attempt + 1}/3)..."
                )
                time.sleep(_RPM_WAIT_SEC)
            else:
                break

    raise last_err or Exception("All Gemini Vision API calls failed.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_keys(api_key: Union[str, List[str]]) -> List[str]:
    if isinstance(api_key, str):
        return [k.strip() for k in api_key.split(",")] if "," in api_key else [api_key]
    return [str(k).strip() for k in api_key if k]


def _build_model_list(requested_model: str) -> List[str]:
    """De-duplicated list: requested model first, then standard fallbacks."""
    seen = set()
    result = []
    for m in [requested_model] + _FALLBACK_MODELS:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _record_api_usage(key: str, model: str, status: str):
    """Tracks API usage per key using brain.tracker (Google Official UTC Reset Time)."""
    try:
        from brain.tracker import record_key_usage
        record_key_usage(key, model, status)
    except Exception as e:
        print(f"[WARN] Failed to record API usage: {e}")

# ------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------
# Video File API (For Hybrid Architecture)
# ------------------------------------------------------------------------------------------------
def upload_video_file(video_path: str, api_key) -> tuple:
    # Use brain.gemini_client imports indirectly or rely on locals
    import brain.gemini_client as gc
    api_keys = gc._normalize_keys(api_key)
    file_size = os.path.getsize(video_path)
    mime_type = "video/mp4"
    
    for key in api_keys:
        start_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={key}"
        start_headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json"
        }
        start_payload = json.dumps({"file": {"display_name": os.path.basename(video_path)}}).encode("utf-8")
        
        req1 = urllib.request.Request(start_url, data=start_payload, headers=start_headers, method="POST")
        try:
            with urllib.request.urlopen(req1) as res1:
                upload_url = res1.headers.get("X-Goog-Upload-URL")
        except Exception as e:
            print(f"[WARN] Upload start failed for key {gc._mask_key(key)}: {e}")
            continue
            
        if not upload_url:
            continue
            
        print(f"[*] Gemini API: Uploading {os.path.basename(video_path)} via REST (Streaming to prevent memory exhaustion)...")
        upload_headers = {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "upload, finalize",
            "X-Goog-Upload-Offset": "0",
            "Content-Length": str(file_size)
        }
        
        try:
            with open(video_path, "rb") as f:
                req2 = urllib.request.Request(upload_url, data=f, headers=upload_headers, method="POST")
                with urllib.request.urlopen(req2, timeout=600) as res2:
                    res_data = json.loads(res2.read().decode("utf-8"))
                    file_name = res_data.get("file", {}).get("name")
        except Exception as e:
            print(f"[WARN] Upload finalization failed: {e}")
            continue
            
        if not file_name:
            continue
            
        print(f"[*] Gemini API: Waiting for video processing ({file_name})...")
        max_poll_attempts = 120  # Max 10 minutes (120 * 5s)
        for _ in range(max_poll_attempts):
            time.sleep(5)
            check_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={key}"
            try:
                req_check = urllib.request.Request(check_url, method="GET")
                with urllib.request.urlopen(req_check, timeout=15) as r:
                    info = json.loads(r.read().decode("utf-8"))
                    state = info.get("state")
                    if state == "ACTIVE":
                        print(f"[OK] Gemini API: Video '{file_name}' is ACTIVE and ready!")
                        return file_name, key
                    elif state == "FAILED":
                        # BUG-L5 Fix: break here instead of raising — the raise was caught by
                        # 'except Exception' below and caused it to keep polling for 10 more minutes.
                        print(f"[WARN] Video processing FAILED on Google servers for {file_name}. Trying next API key.")
                        break
            except Exception as e:
                print(f"[WARN] Check status failed: {e}")
                
    raise Exception("All Gemini API keys failed to upload the video.")

def ask_gemini_with_video(file_name: str, system_prompt: str, user_text: str, key: str, model: str = "gemini-3.5-flash-lite", temperature: float = 0.3) -> str:
    models_to_try = _build_model_list(model)
    last_err = None
    
    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{
                "role": "user",
                "parts": [
                    {"file_data": {"mime_type": "video/mp4", "file_uri": f"https://generativelanguage.googleapis.com/v1beta/{file_name}"}},
                    {"text": user_text},
                ],
            }],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        print(f"[*] Gemini API: Sending prompt and video '{file_name}' to {m}...")
        
        max_retries = 3
        success = False
        
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=600.0) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if not candidates or "content" not in candidates[0]:
                        raise Exception(f"Gemini blocked response")
                    return candidates[0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in [503, 500, 429]:
                    if attempt < max_retries - 1:
                        wait_sec = (attempt + 1) * 10
                        print(f"[WARN] {m} returned {e.code}. Retrying in {wait_sec}s...")
                        time.sleep(wait_sec)
                        continue
                    else:
                        print(f"[WARN] {m} failed after {max_retries} attempts with HTTP {e.code}. Falling back to next model...")
                        break # break inner retry loop, continue to next model
                else:
                    print(f"[WARN] {m} returned HTTP {e.code}. Falling back to next model...")
                    break
            except Exception as e:
                last_err = e
                print(f"[WARN] {m} failed: {e}. Falling back to next model...")
                break
                
    raise Exception(f"All models failed for Video API. Last error: {last_err}")

def delete_video_file(file_name: str, key: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={key}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        urllib.request.urlopen(req)
        print(f"[OK] Gemini API: Deleted video '{file_name}'.")
    except Exception as e:
        print(f"[WARN] Failed to delete video file {file_name}: {e}")
