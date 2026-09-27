import telebot
import yt_dlp
import re
import os
import time
import sqlite3
import threading
from flask import Flask
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ================= RENDER PORT FIX (FLASK WEB SERVER) =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()
# ======================================================================

BOT_TOKEN = "8685782104:AAFD6jgtUj6eK19Xadbn55TA-3Ih4tGpE5I"
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

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
    conn.commit()
    conn.close()

def ensure_user(tg_user):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (tg_user.id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users(user_id, username, first_name, joined_at) VALUES(?,?,?,?)",
            (tg_user.id, tg_user.username or "", tg_user.first_name or "", datetime.utcnow().isoformat())
        )
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
    markup.add(InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"))
    return markup

init_db()

# ================= LIGHTNING FAST DOWNLOAD USING YT-DLP =================
def download_reel(url):
    output_template = "reel_%(id)s.%(ext)s"
    ydl_opts = {
        'outtmpl': output_template,
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename):
                return filename
    except Exception as e:
        print(f"❌ yt-dlp Error: {e}")
    return None

# ================= HANDLERS =================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    ensure_user(message.from_user)
    bot.send_message(
        message.chat.id,
        "🔥 *Instagram Reel Downloader*\n\n✨ *Status:* Lightning Fast & 100% Free!",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == "👤 My Profile")
def profile(message):
    ensure_user(message.from_user)
    bot.reply_to(
        message,
        f"👤 *My Profile*\n\n🆔 ID: `{message.from_user.id}`\n✨ Account Type: *Free & Unlimited*",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == "📥 Download Reel")
def download_button(message):
    bot.reply_to(message, "📥 Send me the Instagram Reel URL now.", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda msg: msg.text == "🛠 Admin Panel")
def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS: return
    bot.send_message(message.chat.id, "🛠 *Admin Panel*:", parse_mode="Markdown", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.from_user.id not in ADMIN_IDS: return
    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    conn.close()
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"📊 *Bot Statistics*\n\n👤 Total Users: {total}", parse_mode="Markdown")

def process_reel_background(message, url):
    processing_msg = bot.reply_to(message, "⚡ *Downloading at Lightning Speed...*", parse_mode="Markdown")
    
    file_path = download_reel(url)

    if file_path and os.path.exists(file_path):
        try:
            bot.edit_message_text("📤 *Sending Video...*", message.chat.id, processing_msg.message_id, parse_mode="Markdown")
            with open(file_path, "rb") as vid:
                bot.send_video(message.chat.id, vid, caption="✅ *Downloaded Successfully!*", parse_mode="Markdown")
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except Exception as e:
            bot.edit_message_text("❌ *Upload Failed!*", message.chat.id, processing_msg.message_id, parse_mode="Markdown")
            print(f"Upload error: {e}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
    else:
        bot.edit_message_text("❌ *Download Failed.*\nMake sure the link is public and correct.", message.chat.id, processing_msg.message_id, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: True)
def handle(msg):
    ensure_user(msg.from_user)
    url = (msg.text or "").strip()

    if "instagram.com" not in url:
        bot.reply_to(msg, "❌ Please send a valid Instagram Reel URL.", parse_mode="Markdown")
        return

    threading.Thread(target=process_reel_background, args=(msg, url)).start()

# ================= BOT STARTUP =================
print("╔══════════════════════════════════════╗")
print("║     🤖 INSTAGRAM REEL BOT ONLINE     ║")
print("╠══════════════════════════════════════╣")
print("║  🚀 Speed: Lightning Fast (yt-dlp)   ║")
print("║  🟢 Service Active (Free & Flask)    ║")
print("╚══════════════════════════════════════╝")
bot.infinity_polling(timeout=60, long_polling_timeout=30)
