import telebot
import instaloader
import re
import os
import time
import sqlite3
import secrets
import threading
from flask import Flask
from datetime import datetime, date
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ================= RENDER PORT FIX (FLASK WEB SERVER) =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Flask server ko background thread mein start kar rahe hain
threading.Thread(target=run_flask, daemon=True).start()
# ======================================================================

BOT_TOKEN = "8685782104:AAFD6jgtUj6eK19Xadbn55TA-3Ih4tGpE5I"
bot = telebot.TeleBot(BOT_TOKEN)

# ================= ADMIN SETTINGS =================
ADMIN_IDS = {8685782104}
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
        joined_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gift_codes (
        code TEXT PRIMARY KEY,
        amount INTEGER NOT NULL,
        max_uses INTEGER NOT NULL DEFAULT 1,
        used_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def ensure_user(tg_user):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (tg_user.id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users(user_id, username, first_name, joined_at) VALUES(?,?,?,?)",
            (tg_user.id, tg_user.username or "", tg_user.first_name or "", datetime.utcnow().isoformat())
        )
        conn.commit()
    else:
        conn.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                     (tg_user.username or "", tg_user.first_name or "", tg_user.id))
        conn.commit()
    conn.close()

def main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 My Profile"), KeyboardButton("📥 Download Reel"))
    if user_id in ADMIN_IDS:
        markup.add(KeyboardButton("🛠 Admin Panel"))
    return markup

def admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
    )
    return markup

def show_home(chat_id, user_id):
    bot.send_message(
        chat_id,
        f"🔥 *Instagram Reel Downloader*\n\n"
        f"✨ *Status:* 100% Free & Unlimited!\n\n"
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
    ensure_user(message.from_user)
    show_home(message.chat.id, message.from_user.id)

@bot.message_handler(func=lambda msg: msg.text == "👤 My Profile")
def profile(message):
    ensure_user(message.from_user)
    bot.reply_to(
        message,
        f"👤 *My Profile*\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"✨ Account Type: *Free & Unlimited*",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == "📥 Download Reel")
def download_button(message):
    bot.reply_to(message,
                 "📥 Send me the Instagram Reel URL now.\n\n"
                 "✨ *Cost:* Completely Free!",
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
    conn.close()
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id,
                     f"📊 *Bot Statistics*\n\n👤 Total Users: {total}",
                     parse_mode="Markdown")

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
print("║  🟢 Service Active (Free & Flask)    ║")
print("╚══════════════════════════════════════╝")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except Exception as e:
        print(f"⚠️ Connection error: {e}")
        print("🔄 Restarting bot in 5 seconds...")
        time.sleep(5)
