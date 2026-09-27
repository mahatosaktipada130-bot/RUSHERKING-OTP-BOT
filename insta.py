import telebot
import instaloader
import re
import os
import time
import sqlite3
import secrets
from datetime import datetime, date
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

BOT_TOKEN = "8685782104:AAFD6jgtUj6eK19Xadbn55TA-3Ih4tGpE5I"
bot = telebot.TeleBot(BOT_TOKEN)

# ================= CREDIT / ADMIN SETTINGS =================
ADMIN_IDS = {8685782104}
DOWNLOAD_COST = 1
DAILY_CLAIM = 10
REFERRAL_REWARD = 10
DB_FILE = "bot_data.db"

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        credits INTEGER NOT NULL DEFAULT 10,
        referred_by INTEGER,
        referrals INTEGER NOT NULL DEFAULT 0,
        last_claim TEXT,
        joined_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        amount INTEGER NOT NULL,
        max_uses INTEGER NOT NULL DEFAULT 1,
        used_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gift_redemptions (
        code TEXT,
        user_id INTEGER,
        PRIMARY KEY(code, user_id)
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def ensure_user(tg_user, referrer_id=None):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (tg_user.id,)).fetchone()
    if row is None:
        valid_ref = None
        if referrer_id and referrer_id != tg_user.id:
            ref = conn.execute("SELECT user_id FROM users WHERE user_id=?", (referrer_id,)).fetchone()
            if ref:
                valid_ref = referrer_id
        conn.execute(
            "INSERT INTO users(user_id,username,first_name,credits,referred_by,joined_at) VALUES(?,?,?,?,?,?)",
            (tg_user.id, tg_user.username or "", tg_user.first_name or "", DAILY_CLAIM,
             valid_ref, datetime.utcnow().isoformat())
        )
        if valid_ref:
            conn.execute("UPDATE users SET credits=credits+?, referrals=referrals+1 WHERE user_id=?",
                         (REFERRAL_REWARD, valid_ref))
        conn.commit()
    else:
        conn.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                     (tg_user.username or "", tg_user.first_name or "", tg_user.id))
        conn.commit()
    conn.close()

def add_credits(user_id, amount):
    conn = db()
    conn.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def spend_credit(user_id, amount=DOWNLOAD_COST):
    conn = db()
    row = conn.execute("SELECT credits FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row or row["credits"] < amount:
        conn.close()
        return False
    conn.execute("UPDATE users SET credits=credits-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def refund_credit(user_id, amount=DOWNLOAD_COST):
    add_credits(user_id, amount)

def main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 My Profile"), KeyboardButton("🎁 Daily Claim"))
    markup.add(KeyboardButton("📥 Download Reel"), KeyboardButton("👥 Refer Friend"))
    if user_id in ADMIN_IDS:
        markup.add(KeyboardButton("🛠 Admin Panel"))
    return markup

def admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
        InlineKeyboardButton("🎁 Generate Gift Code", callback_data="admin_gift"),
        InlineKeyboardButton("➕ Add Credits", callback_data="admin_add"),
        InlineKeyboardButton("➖ Remove Credits", callback_data="admin_remove")
    )
    return markup

def show_home(chat_id, user_id):
    row = get_user(user_id)
    bot.send_message(
        chat_id,
        f"🔥 *Instagram Reel Downloader*\n\n"
        f"💳 Credits: *{row['credits']}*\n"
        f"👥 Referrals: *{row['referrals']}*\n\n"
        f"Choose an option below:",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )

init_db()

L = instaloader.Instaloader(
    save_metadata=False,
    download_comments=False,
    post_metadata_txt_pattern=""
)

# ================= DOWNLOAD FUNCTION =================
def download_reel(url):
    try:
        match = re.search(r"/reel/([^/?#]+)/?", url)
        if not match:
            return None

        shortcode = match.group(1)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

        for file in os.listdir(shortcode):
            if file.endswith(".mp4"):
                return os.path.join(shortcode, file)

    except Exception as e:
        print(f"❌ Error: {e}")
        return None

# ================= HANDLERS =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    referrer_id = None
    parts = (message.text or "").split(maxsplit=1)
    if parts and len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1][4:])
        except ValueError:
            pass

    ensure_user(message.from_user, referrer_id)
    show_home(message.chat.id, message.from_user.id)

@bot.message_handler(func=lambda msg: msg.text == "👤 My Profile")
def profile(message):
    ensure_user(message.from_user)
    row = get_user(message.from_user.id)
    bot.reply_to(
        message,
        f"👤 *My Profile*\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"💳 Credits: *{row['credits']}*\n"
        f"👥 Referrals: *{row['referrals']}*",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == "🎁 Daily Claim")
def daily_claim(message):
    ensure_user(message.from_user)
    today = date.today().isoformat()
    row = get_user(message.from_user.id)
    if row["last_claim"] == today:
        bot.reply_to(message, "⏳ You already claimed today's 10 credits. Come back tomorrow!",
                     reply_markup=main_menu(message.from_user.id))
        return
    conn = db()
    conn.execute("UPDATE users SET credits=credits+?, last_claim=? WHERE user_id=?",
                 (DAILY_CLAIM, today, message.from_user.id))
    conn.commit()
    conn.close()
    bot.reply_to(message, "🎉 *Daily Claim Successful!*\n\n💳 +10 credits added.",
                 parse_mode="Markdown", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda msg: msg.text == "👥 Refer Friend")
def refer_friend(message):
    ensure_user(message.from_user)
    me = bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    bot.reply_to(
        message,
        f"👥 *Refer Friend & Earn*\n\n"
        f"🎁 Get *{REFERRAL_REWARD} credits* for every new user who joins using your link.\n\n"
        f"🔗 Your referral link:\n`{link}`",
        parse_mode="Markdown", reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == "📥 Download Reel")
def download_button(message):
    bot.reply_to(message,
                 "📥 Send me the Instagram Reel URL now.\n\n"
                 f"💳 Cost: {DOWNLOAD_COST} credit per successful download.",
                 reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda msg: msg.text == "🛠 Admin Panel")
def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(message.chat.id, "🛠 *Admin Panel*\nChoose an action:", 
                     parse_mode="Markdown", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.from_user.id not in ADMIN_IDS: return
    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    credits = conn.execute("SELECT COALESCE(SUM(credits),0) c FROM users").fetchone()["c"]
    referrals = conn.execute("SELECT COALESCE(SUM(referrals),0) c FROM users").fetchone()["c"]
    conn.close()
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     f"📊 *Bot Statistics*\n\n👤 Users: {total}\n💳 Total Credits: {credits}\n👥 Referrals: {referrals}",
                     parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data in ["admin_gift","admin_add","admin_remove"])
def admin_action_prompt(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    if call.data == "admin_gift":
        msg = bot.send_message(call.message.chat.id,
            "🎁 Send gift code details like:\n`AMOUNT USES`\nExample: `50 100`",
            parse_mode="Markdown")
        bot.register_next_step_handler(msg, create_gift_code)
    elif call.data == "admin_add":
        msg = bot.send_message(call.message.chat.id,
            "➕ Send: `USER_ID AMOUNT`\nExample: `123456789 50`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, admin_add_credit)
    else:
        msg = bot.send_message(call.message.chat.id,
            "➖ Send: `USER_ID AMOUNT`\nExample: `123456789 10`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, admin_remove_credit)

def create_gift_code(message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        amount, uses = map(int, message.text.split())
        if amount <= 0 or uses <= 0: raise ValueError
        code = "GIFT-" + secrets.token_hex(4).upper()
        conn = db()
        conn.execute("INSERT INTO gift_codes(code,amount,max_uses,created_at) VALUES(?,?,?,?)",
                     (code, amount, uses, datetime.utcnow().isoformat()))
        conn.commit(); conn.close()
        bot.send_message(message.chat.id,
                         f"🎁 *Gift Code Created!*\n\n`{code}`\n💳 Amount: {amount}\n👥 Uses: {uses}",
                         parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, "❌ Format: `AMOUNT USES`", parse_mode="Markdown")

def admin_add_credit(message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid, amount = map(int, message.text.split())
        add_credits(uid, amount)
        bot.send_message(message.chat.id, f"✅ Added {amount} credits to `{uid}`.", parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, "❌ Format: `USER_ID AMOUNT`", parse_mode="Markdown")

def admin_remove_credit(message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid, amount = map(int, message.text.split())
        add_credits(uid, -abs(amount))
        bot.send_message(message.chat.id, f"✅ Removed {amount} credits from `{uid}`.", parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, "❌ Format: `USER_ID AMOUNT`", parse_mode="Markdown")

@bot.message_handler(commands=['gift'])
def redeem_gift(message):
    ensure_user(message.from_user)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        bot.reply_to(message, "🎁 Use: `/gift CODE`", parse_mode="Markdown")
        return
    code = parts[1].strip().upper()
    conn = db()
    gift = conn.execute("SELECT * FROM gift_codes WHERE code=?", (code,)).fetchone()
    if not gift:
        conn.close()
        bot.reply_to(message, "❌ Invalid gift code.")
        return
    if gift["used_count"] >= gift["max_uses"]:
        conn.close()
        bot.reply_to(message, "❌ This gift code has reached its use limit.")
        return
    used = conn.execute("SELECT 1 FROM gift_redemptions WHERE code=? AND user_id=?",
                        (code, message.from_user.id)).fetchone()
    if used:
        conn.close()
        bot.reply_to(message, "❌ You already used this gift code.")
        return
    conn.execute("INSERT INTO gift_redemptions(code,user_id) VALUES(?,?)",
                 (code, message.from_user.id))
    conn.execute("UPDATE gift_codes SET used_count=used_count+1 WHERE code=?", (code,))
    conn.execute("UPDATE users SET credits=credits+? WHERE user_id=?",
                 (gift["amount"], message.from_user.id))
    conn.commit(); conn.close()
    bot.reply_to(message, f"🎉 Gift redeemed!\n💳 +{gift['amount']} credits added.",
                 reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda msg: True)
def handle(msg):
    user_id = msg.from_user.id
    ensure_user(msg.from_user)

    url = (msg.text or "").strip()

    if "instagram.com" not in url:
        error_msg = (
            "❌ *Invalid Link*\n\n"
            "📌 Please send a valid Instagram Reel URL\n"
            "💡 Example: `https://www.instagram.com/reel/xxxxx/`"
        )
        bot.reply_to(msg, error_msg, parse_mode="Markdown")
        return

    if not spend_credit(user_id, DOWNLOAD_COST):
        bot.reply_to(msg,
                     f"❌ *Insufficient credits.*\n\n💳 Your balance: {get_user(user_id)['credits']}\n"
                     f"🎁 Use *Daily Claim* or *Refer Friend* to earn more.",
                     parse_mode="Markdown", reply_markup=main_menu(user_id))
        return

    processing_msg = bot.reply_to(
        msg,
        "⏳ *Processing Your Request...*\n\n"
        "🔍 Fetching reel information..."
    )

    time.sleep(0.5)

    bot.edit_message_text(
        "📥 *Downloading Reel...*\n\n"
        "⏬ Please wait while we fetch your video",
        msg.chat.id,
        processing_msg.message_id,
        parse_mode="Markdown"
    )

    file_path = download_reel(url)

    if file_path:
        bot.edit_message_text(
            "📤 *Uploading Video...*\n\n"
            "⬆️ Sending your reel now",
            msg.chat.id,
            processing_msg.message_id,
            parse_mode="Markdown"
        )

        try:
            with open(file_path, "rb") as vid:
                caption_text = (
                    "✅ *Download Complete!*\n\n"
                    "📹 Reel downloaded successfully\n"
                    "💫 Enjoy your video!"
                )
                bot.send_video(
                    msg.chat.id,
                    vid,
                    caption=caption_text,
                    parse_mode="Markdown"
                )

            bot.delete_message(msg.chat.id, processing_msg.message_id)

        except Exception as e:
            bot.edit_message_text(
                "❌ *Upload Failed*\n\n"
                "😕 Couldn't send the video. Please try again.",
                msg.chat.id,
                processing_msg.message_id,
                parse_mode="Markdown"
            )
            refund_credit(user_id, DOWNLOAD_COST)
            print(f"Upload error: {e}")

        finally:
            try:
                os.remove(file_path)
                match = re.search(r"/reel/([^/?#]+)/?", url)
                if match:
                    shortcode = match.group(1)
                    if os.path.exists(shortcode):
                        import shutil
                        shutil.rmtree(shortcode)
            except Exception:
                pass

    else:
        refund_credit(user_id, DOWNLOAD_COST)
        error_text = (
            "❌ *Download Failed*\n\n"
            "📋 Possible reasons:\n"
            "• Invalid or broken URL\n"
            "• Private account or reel\n"
            "• Network connection issue\n"
            "• Instagram restrictions\n\n"
            "💡 *Try these solutions:*\n"
            "• Verify the link is correct\n"
            "• Ensure reel is from public account\n"
            "• Try again after a few minutes"
        )
        bot.edit_message_text(
            error_text,
            msg.chat.id,
            processing_msg.message_id,
            parse_mode="Markdown"
        )


# ================= BOT STARTUP =================
print("╔══════════════════════════════════════╗")
print("║     🤖 INSTAGRAM REEL BOT ONLINE     ║")
print("╠══════════════════════════════════════╣")
print("║  ✅ Bot is running successfully      ║")
print("║  📡 Waiting for messages...          ║")
print("║  🟢 Service Active                   ║")
print("║  🔓 Force Subscribe: Disabled        ║")
print("╚══════════════════════════════════════╝")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except Exception as e:
        print(f"⚠️ Connection error: {e}")
        print("🔄 Restarting bot in 5 seconds...")
        time.sleep(5)
