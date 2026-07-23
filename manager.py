import os
import re
import json
import io
import base64
import random
import datetime
from datetime import timedelta
import threading
import time
import hashlib
import requests
import pyotp
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
from flask import Flask, jsonify, request, send_file, abort
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pymongo import MongoClient

# Cryptography for AES-256 Encrypted Backups
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

# ================= 1. Configuration & Credentials =================
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1aWntk0eMZt6w7GWmXs_PmckvoDT1uCCRiGUELiV4NKA")
CREDENTIALS_FILE = "credentials.json"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")

# 🔒 আপনার মূল প্রাইভেট ব্যাকআপ চ্যানেল
LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = "-1003943094107"

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-domain.com/webview-form")
BACKUP_SECRET_KEY = os.environ.get("BACKUP_SECRET_KEY", "12345678901234567890123456789012").encode('utf-8')

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

try:
    BOT_USERNAME = bot.get_me().username
except Exception:
    BOT_USERNAME = "online_bazar_manager_bot"

# MongoDB Database Connection
mongo_client = MongoClient(
    MONGO_URL,
    maxPoolSize=200,
    minPoolSize=20,
    maxIdleTimeMS=45000,
    waitQueueTimeoutMS=5000,
    connectTimeoutMS=10000
)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
custom_tasks_col = db['custom_tasks']
tickets_col = db['support_tickets']
polls_col = db['polls']
poll_votes_col = db['poll_votes']
audit_logs_col = db['audit_logs']
fingerprints_col = db['user_fingerprints']
crm_notes_col = db['worker_crm_notes']
receipts_col = db['payout_receipts']
blacklisted_payloads_col = db['blacklisted_payloads']
flash_boost_col = db['flash_boost']

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

user_states = {}

# ================= 2. PIL Graphic Canvas Generators =================

def draw_text_safe(draw, position, text, fill):
    font = ImageFont.load_default()
    draw.text(position, text, fill=fill, font=font)

def generate_worker_badge_image_py(worker_id, username, total_submissions):
    img = Image.new('RGB', (600, 320), color='#0f172a')
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 590, 310], outline='#38bdf8', width=3)
    draw_text_safe(draw, (30, 30), "VERIFIED WORKER ID BADGE", fill='#38bdf8')
    draw_text_safe(draw, (30, 80), f"Name/Username: {username}", fill='#ffffff')
    draw_text_safe(draw, (30, 120), f"Worker ID: #{worker_id}", fill='#ffffff')
    draw_text_safe(draw, (30, 160), f"Total Tasks Completed: {total_submissions}", fill='#ffffff')
    draw.rectangle([30, 220, 210, 270], fill='#10b981')
    draw_text_safe(draw, (50, 235), "VERIFIED STAFF", fill='#ffffff')
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def generate_payout_receipt_py(receipt_id, worker_id, amount, method, trx_id):
    img = Image.new('RGB', (500, 320), color='#ffffff')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 500, 60], fill='#0284c7')
    draw_text_safe(draw, (20, 20), "OFFICIAL PAYOUT RECEIPT", fill='#ffffff')
    draw_text_safe(draw, (20, 90), f"Receipt ID: {receipt_id}", fill='#334155')
    draw_text_safe(draw, (20, 120), f"Worker ID: #{worker_id}", fill='#334155')
    draw_text_safe(draw, (20, 150), f"Method: {str(method).upper()}", fill='#334155')
    draw_text_safe(draw, (20, 180), f"TrxID: {trx_id}", fill='#334155')
    draw_text_safe(draw, (20, 210), f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", fill='#334155')
    draw_text_safe(draw, (280, 250), f"PAID: {amount} BDT", fill='#16a34a')
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ================= 3. AES-256 Encryption & Security =================

def generate_payload_hash(payload_str):
    clean_str = re.sub(r'\s+', '', str(payload_str))
    return hashlib.sha256(clean_str.encode('utf-8')).hexdigest()

def is_payload_blacklisted(payload_hash):
    return blacklisted_payloads_col.find_one({"_id": payload_hash}) is not None

def add_to_payload_blacklist(payload_hash, reason="Dead Cookie/2FA"):
    blacklisted_payloads_col.update_one(
        {"_id": payload_hash},
        {"$set": {"reason": reason, "added_at": datetime.datetime.now()}},
        upsert=True
    )

def aes_encrypt(data_dict, key):
    raw = json.dumps(data_dict).encode('utf-8')
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(raw) + padder.finalize()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(iv + ct).decode('utf-8')

# ================= 4. Database & Smart Helper Functions =================

def clean_markdown_text(text):
    if not text:
        return "Worker"
    return str(text).replace("`", "").replace("*", "").replace("_", "").replace("[", "").replace("]", "")

def get_setting(key, default):
    res = settings_col.find_one({"_id": key})
    return res["value"] if res else default

def update_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

def log_to_channel(text):
    try:
        bot.send_message(LOG_CHANNEL_ID, f"📢 **SYSTEM LOG:**\n{text}")
    except Exception as e:
        print(f"[Log Error]: {e}")

def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        user = {
            "_id": chat_id,
            "first_name": "Worker",
            "balance": 0.0,
            "hold_balance": 0.0,
            "language": "bn",
            "password": get_setting("pass_rule", "20"),
            "banned": False,
            "risk_score": 0,
            "referrer_id": None,
            "last_bonus_date": None,
            "last_active": datetime.datetime.now(),
            "joined_date": datetime.datetime.now()
        }
        users_col.insert_one(user)
    return user

def update_user_field(chat_id, field, value):
    users_col.update_one({"_id": chat_id}, {"$set": {field: value}}, upsert=True)

def is_banned(chat_id):
    user = users_col.find_one({"_id": chat_id})
    return user.get("banned", False) if user else False

def check_force_join(user_id):
    if user_id == ADMIN_ID:
        return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            continue
    return True

def generate_tracking_id():
    return f"SUB-{int(datetime.datetime.now().timestamp())}-{random.randint(100,999)}"

def is_duplicate_uid(uid):
    return submissions_col.find_one({"uid": str(uid)}) is not None

# 🔥 উন্নততর UID এক্সট্র্যাক্টর (যাতে বাল্ক সাবমিশন কোনোভাবেই মিস না হয়)
def extract_numeric_uid(text):
    text = str(text).strip()
    c_user_match = re.search(r'c_user=(\d{8,20})', text)
    if c_user_match:
        return c_user_match.group(1)
    
    link_match = re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text)
    if link_match:
        return link_match.group(1)
        
    num_match = re.search(r'\b(\d{8,20})\b', text)
    if num_match:
        return num_match.group(1)
        
    return None

def is_valid_cookies(cookie_str):
    c_str = str(cookie_str)
    return ("c_user=" in c_str) or ("datr=" in c_str) or ("xs=" in c_str) or ("sessionid=" in c_str)

def check_live_account(uid):
    try:
        clean_uid = extract_numeric_uid(uid)
        if not clean_uid:
            return False, "Invalid UID format"
        url = f"https://www.facebook.com/{clean_uid}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            if "content=\"no-cache\"" in response.text or "The page you requested cannot be displayed" in response.text:
                return False, "Dead / Checkpoint"
            return True, "Live Account"
        return False, "Dead / Suspended"
    except Exception:
        return True, "Assumed Live"

def calculate_worker_tier(total_submissions):
    if total_submissions >= 500:
        return "Gold VIP 🏆", 2.0
    elif total_submissions >= 150:
        return "Silver Worker 🥈", 1.0
    return "Bronze Worker 🏅", 0.0

def get_current_task_rate(cat_key):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    base_rate = float(rates.get(cat_key, 5.0))
    surge_info = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge_info.get("active"):
        exp = surge_info.get("expires_at")
        if exp and datetime.datetime.now() < exp:
            base_rate += float(surge_info.get("bonus", 0.0))
    return base_rate

def async_save_to_sheet(tab_name, row_data):
    def task():
        try:
            if not os.path.exists(CREDENTIALS_FILE):
                return
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(SPREADSHEET_ID)
            worksheet = sheet.worksheet(tab_name)
            worksheet.append_row(row_data)
        except Exception as e:
            print(f"Sheet Save Error: {e}")
    threading.Thread(target=task, daemon=True).start()

# ================= 5. Background Daemon Threads & Daily Auto-Report =================

def generate_daily_report_text():
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    approved_today = list(submissions_col.find({
        "status": "Approved",
        "date_obj": {"$gte": today_start}
    }))
    
    total_approved = len(approved_today)
    if total_approved == 0:
        return (
            f"📊 **DAILY EARNING REPORT ({datetime.datetime.now().strftime('%Y-%m-%d')})**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📭 আজ এখনো পর্যন্ত কোনো অ্যাকাউন্ট এপ্রুভ করা হয়নি।"
        )
        
    category_breakdown = {}
    total_payout = 0.0
    
    for sub in approved_today:
        cat = sub.get("category", "FB Cookies")
        rate = float(sub.get("rate", 0.0))
        total_payout += rate
        
        if cat not in category_breakdown:
            category_breakdown[cat] = {"count": 0, "amount": 0.0}
        category_breakdown[cat]["count"] += 1
        category_breakdown[cat]["amount"] += rate
        
    report = (
        f"📊 **DAILY EARNING REPORT ({datetime.datetime.now().strftime('%Y-%m-%d')})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ মোট এপ্রুভড অ্যাকাউন্ট : **{total_approved} টি**\n"
        f"💰 মোট বিতরণকৃত পেমেন্ট : **৳{total_payout:.2f}**\n\n"
        f"🛡️ **ক্যাটাগরি ভিত্তিক বিবরণ:**\n"
    )
    
    for cat, data in category_breakdown.items():
        report += f"• {cat} : {data['count']} টি (৳{data['amount']:.2f})\n"
        
    report += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    report += f"⏰ রিপোর্ট জেনারেট সময়: {datetime.datetime.now().strftime('%H:%M:%S')}"
    return report

def background_daily_report_scheduler():
    while True:
        now = datetime.datetime.now()
        target = now.replace(hour=23, minute=59, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
            
        sleep_seconds = (target - datetime.datetime.now()).total_seconds()
        time.sleep(sleep_seconds)
        
        try:
            report_text = f"🤖 **[AUTOMATED AUTO-REPORT]**\n\n" + generate_daily_report_text()
            bot.send_message(ADMIN_ID, report_text)
        except Exception as e:
            print(f"Daily Report Scheduler Error: {e}")
        time.sleep(60)

threading.Thread(target=background_daily_report_scheduler, daemon=True).start()

def escrow_and_retention_daemon():
    while True:
        try:
            cutoff_24h = datetime.datetime.now() - timedelta(hours=24)
            pending_subs = submissions_col.find({"status": "Hold", "date_obj": {"$lte": cutoff_24h}})
            for sub in pending_subs:
                users_col.update_one(
                    {"_id": sub["chat_id"]},
                    {"$inc": {"balance": sub["rate"], "hold_balance": -sub["rate"]}}
                )
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
                try:
                    bot.send_message(sub["chat_id"], f"✅ আপনার হোল্ডে থাকা ৳{sub['rate']:.2f} সফলভাবে মেইন ব্যালেন্সে যুক্ত হয়েছে।")
                except Exception:
                    pass

        except Exception as e:
            print(f"Daemon Loop Error: {e}")
        time.sleep(3600)

threading.Thread(target=escrow_and_retention_daemon, daemon=True).start()

# ================= 6. REST API & Webhook Server (Flask) =================

flask_app = Flask(__name__)

@flask_app.route('/')
def flask_home():
    return "Enterprise Bot Python Backend Server Running Flawlessly!"

@flask_app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ================= 7. UI Keyboards =================

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💼 টাস্ক ও টুলস"), KeyboardButton("👤 আমার অ্যাকাউন্ট"))
    markup.add(KeyboardButton("🎁 বোনাস ও সাপোর্ট"))
    if chat_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def tasks_and_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📋 কাজ জমা দিন"), KeyboardButton("🛠 হেল্পার টুলস"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def submit_tasks_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def category_bottom_keyboard(chat_id):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"📄 FB Cookies (৳{rates['fb_cookie']})"),
        KeyboardButton(f"🔐 FB 2FA (৳{rates['fb_2fa']})")
    )
    markup.add(
        KeyboardButton(f"📷 IG Cookies (৳{rates['ig_cookie']})"),
        KeyboardButton(f"🔐 IG 2FA (৳{rates['ig_2fa']})")
    )
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def helper_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("🔍 লিংক থেকে UID"))
    markup.add(KeyboardButton("🔍 UID Live Checker"), KeyboardButton("✉️ টেম্প ইমেইল"))
    markup.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    markup.add(KeyboardButton("👤 র্যান্ডম নাম জেনারেটর"), KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💳 Withdraw"), KeyboardButton("🪪 ভেরিফাইড আইডি কার্ড"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def bonus_support_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⏳ পেন্ডিং এপ্রুভাল (Manual)"), KeyboardButton("📊 টিম ও দৈনিক রিপোর্ট"))
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("📂 ফাইল এক্সপোর্ট"))
    markup.add(KeyboardButton("📢 ব্রডকাস্ট নোটিশ"), KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def admin_export_category_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📄 Export FB Cookies"), KeyboardButton("📄 Export FB 2FA"))
    markup.add(KeyboardButton("📸 Export IG Cookies"), KeyboardButton("📸 Export IG 2FA"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def cancel_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= 8. Core Telegram Router & Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if is_banned(chat_id):
        bot.reply_to(message, "🚫 Your account has been suspended.")
        return

    user = get_user_data(chat_id)
    user_states.pop(chat_id, None)

    if not check_force_join(chat_id):
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
        markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
        bot.send_message(chat_id, "🔒 **চ্যানেল ভেরিফিকেশন প্রয়োজন:**", reply_markup=markup)
        return

    bot.send_message(chat_id, "👑 **ONLINE EARNING BAZAR**\n───────────────\nস্বাগতম! নিচের অপশন থেকে নির্বাচন করুন:", reply_markup=main_bottom_keyboard(chat_id))

@bot.message_handler(commands=['appr', 'rej'])
def handle_admin_text_action(message):
    if message.chat.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, "⚠️ ফরম্যাট: `/appr TRACK_ID` বা `/rej TRACK_ID`")
        return
    action, track_id = parts[0], parts[1]
    sub = submissions_col.find_one({"track_id": track_id})
    if not sub or sub.get("status") != "Hold":
        bot.send_message(ADMIN_ID, "⚠️ সাবমিশনটি পাওয়া যায়নি বা ইতিমধ্যে প্রসেস করা হয়েছে!")
        return
    user_id = sub["chat_id"]
    rate = float(sub["rate"])
    if action == "/appr":
        submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Approved"}})
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": rate, "hold_balance": -rate}})
        bot.send_message(ADMIN_ID, f"✅ ট্র্যাকিং আইডি `{track_id}` এপ্রুভড!")
        try: bot.send_message(user_id, f"🎉 আপনার ট্র্যাকিং আইডি `{track_id}` এর জন্য ৳{rate:.2f} মেইন ব্যালেন্সে যুক্ত হয়েছে!")
        except Exception: pass
    else:
        submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Rejected"}})
        users_col.update_one({"_id": user_id}, {"$inc": {"hold_balance": -rate}})
        bot.send_message(ADMIN_ID, f"❌ ট্র্যাকিং আইডি `{track_id}` বাতিল করা হয়েছে!")
        try: bot.send_message(user_id, f"❌ আপনার ট্র্যাকিং আইডি `{track_id}` এর সাবমিশন বাতিল করা হয়েছে।")
        except Exception: pass

@bot.message_handler(content_types=['document'])
def handle_excel_document(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            file_name = message.document.file_name
            with open(file_name, 'wb') as f:
                f.write(downloaded)

            df = pd.read_csv(file_name, dtype=str) if file_name.endswith('.csv') else pd.read_excel(file_name, dtype=str)
            df = df.fillna('')
            
            success_count, total_earned = 0, 0.0
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for _, row in df.iterrows():
                vals = [str(x).strip() for x in row.values]
                if len(vals) >= 3:
                    uid, password, payload = vals[0], vals[1], vals[2]
                    clean_uid = extract_numeric_uid(uid)
                    
                    p_hash = generate_payload_hash(payload)
                    if is_payload_blacklisted(p_hash):
                        continue

                    if clean_uid and not is_duplicate_uid(clean_uid):
                        is_live, _ = check_live_account(clean_uid)
                        if not is_live:
                            add_to_payload_blacklist(p_hash, "Dead Account")
                            continue
                        cat_key = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                        rate = get_current_task_rate(cat_key)
                        track_id = generate_tracking_id()
                        
                        async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), clean_uid, password, payload])
                        submissions_col.insert_one({
                            "chat_id": chat_id,
                            "worker_name": clean_markdown_text(message.from_user.first_name),
                            "uid": clean_uid,
                            "password": password,
                            "payload": payload,
                            "payload_hash": p_hash,
                            "track_id": track_id,
                            "category": "FB Cookies" if "cookie" in cat_key else "FB 2FA",
                            "category_key": cat_key,
                            "rate": rate,
                            "status": "Hold",
                            "date_str": now_str,
                            "date_obj": datetime.datetime.now()
                        })
                        
                        try:
                            log_msg = (
                                f"📦 **EXCEL FILE BACKUP #{track_id}**\n"
                                f"⏰ সময়: {now_str}\n"
                                f"👤 Worker ID: #{chat_id}\n"
                                f"🆔 UID: `{clean_uid}`\n"
                                f"💰 Rate: ৳{rate:.2f}\n\n"
                                f"📄 Payload:\n`{payload[:100]}`..."
                            )
                            bot.send_message(LOG_CHANNEL_ID, log_msg)
                        except Exception:
                            pass

                        success_count += 1
                        total_earned += rate

            if os.path.exists(file_name):
                os.remove(file_name)

            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
            user_states.pop(chat_id, None)
            bot.reply_to(message, f"🎉 **ফাইল প্রসেস সম্পন্ন!**\n\n✅ সফল: **{success_count}** টি\n💰 আর্ন (এসক্রো হোল্ড): ৳{total_earned:.2f}", reply_markup=main_bottom_keyboard(chat_id))
        except Exception as e:
            bot.reply_to(message, f"❌ ফাইল প্রসেসিং ভুল হয়েছে: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!")

@bot.message_handler(func=lambda msg: True)
def main_router(message):
    chat_id = message.chat.id
    if is_banned(chat_id):
        return

    text = message.text.strip() if message.text else ""
    user = get_user_data(chat_id)

    # 🔥 ১. যেকোনো নেভিগেশন বাটনে চাপলে স্বয়ংক্রিয়ভাবে আগের স্টেট ক্লিয়ার হবে
    nav_buttons = [
        "🔙 প্রধান মেনু", "🔙 Main Menu", "❌ Cancel", "❌ বাতিল করুন",
        "💼 টাস্ক ও টুলস", "📋 কাজ জমা দিন", "🛠 হেল্পার টুলস", "📌 সিঙ্গেল জমা",
        "👤 আমার অ্যাকাউন্ট", "🎁 বোনাস ও সাপোর্ট", "👑 এডমিন প্যানেল",
        "💳 Withdraw", "🪪 ভেরিফাইড আইডি কার্ড", "🎁 Claim Daily Bonus",
        "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", "📦 বাল্ক জমা (Text)",
        "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🔑 2FA কোড জেনারেটর",
        "🔍 UID Live Checker", "🔍 লিংক থেকে UID", "🚀 বাল্ক FB লাইভ চেকার",
        "🚀 বাল্ক IG লাইভ চেকার", "✉️ টেম্প ইমেইল", "👤 র্যান্ডম নাম জেনারেটর"
    ]
    
    if text in nav_buttons:
        user_states.pop(chat_id, None)

    # 2. প্রধান মেনুতে ফেরা
    if text in ["🔙 প্রধান মেনু", "🔙 Main Menu", "❌ Cancel", "❌ বাতিল করুন"]:
        bot.send_message(chat_id, "🏠 প্রধান মেনু:", reply_markup=main_bottom_keyboard(chat_id))
        return

    # 3. মূল ক্যাটাগরি মেনু হ্যান্ডলার
    if text == "💼 টাস্ক ও টুলস":
        bot.send_message(chat_id, "💼 **টাস্ক ও টুলস** সেকশনে স্বাগতম:", reply_markup=tasks_and_tools_keyboard())
        return

    elif text == "📋 কাজ জমা দিন":
        bot.send_message(chat_id, "📋 **কাজ জমা দেওয়ার ধরণ বেছে নিন:**", reply_markup=submit_tasks_keyboard())
        return

    elif text == "🛠 হেল্পার টুলস":
        bot.send_message(chat_id, "🛠 **আপনার প্রয়োজনীয় টুল বেছে নিন:**", reply_markup=helper_tools_keyboard())
        return

    elif text == "📌 সিঙ্গেল জমা":
        bot.send_message(chat_id, "📌 **ক্যাটাগরি বেছে নিন:**", reply_markup=category_bottom_keyboard(chat_id))
        return

    elif text == "👤 আমার অ্যাকাউন্ট":
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = user.get("balance", 0.0)
        hold_bal = user.get("hold_balance", 0.0)
        tier_name, _ = calculate_worker_tier(cnt)
        safe_name = clean_markdown_text(message.from_user.first_name)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        
        msg_str = (
            f"👤 **নাম:** `{safe_name}`\n"
            f"🎖 **টিয়ার:** `{tier_name}`\n"
            f"📊 **মোট কাজ:** `{cnt}` টি\n"
            f"💰 **মেইন ব্যালেন্স:** `৳{bal:.2f}` | **এসক্রো হোল্ড:** `৳{hold_bal:.2f}`\n"
            f"🔗 **রেফারেল লিঙ্ক:** {ref_link}"
        )
        bot.send_message(chat_id, msg_str, reply_markup=account_keyboard(), disable_web_page_preview=True)
        return

    elif text == "🎁 বোনাস ও সাপোর্ট":
        bot.send_message(chat_id, "🎁 **বোনাস ও সাপোর্ট সেন্টার:**", reply_markup=bonus_support_keyboard())
        return

    elif text == "👑 এডমিন প্যানেল" and chat_id == ADMIN_ID:
        bot.send_message(chat_id, "👑 **এডমিন প্যানেল**", reply_markup=admin_bottom_keyboard())
        return

    # 4. সার্ভিসসমূহ
    elif text == "💳 Withdraw":
        bal = user.get("balance", 0.0)
        if bal < 50.0:
            bot.send_message(chat_id, f"⚠️ সর্বনিম্ন উইথড্র ৳৫০.০০। আপনার বর্তমান ব্যালেন্স: ৳{bal:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নাম্বার ও পরিমাণ লিখুন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🪪 ভেরিফাইড আইডি কার্ড":
        safe_name = clean_markdown_text(message.from_user.first_name)
        buf = generate_worker_badge_image_py(chat_id, safe_name, 150)
        bot.send_photo(chat_id, buf, caption="🪪 *আপনার ভেরিফাইড আইডি কার্ড!*")
        return

    elif text == "🎁 Claim Daily Bonus":
        last_bonus = user.get("last_bonus_date")
        now = datetime.datetime.now()
        if last_bonus and (now - last_bonus) < timedelta(hours=24):
            bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টার মধ্যে একবারই ডেইলি বোনাস নেওয়া যায়!")
        else:
            update_user_field(chat_id, "balance", user.get("balance", 0.0) + 2.0)
            update_user_field(chat_id, "last_bonus_date", now)
            bot.send_message(chat_id, "🎉 অভিনন্দন! আপনি ৳2.00 ডেইলি বোনাস পেয়েছেন।")
        return

    elif text == "🏆 লিডারবোর্ড":
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        pipeline = [
            {"$match": {"date_str": {"$regex": f"^{today}"}}},
            {"$group": {"_id": "$worker_name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        top = list(submissions_col.aggregate(pipeline))
        res = "🏆 **আজকের টপ ৫ ওয়ার্কার**\n───────────────\n"
        if not top:
            res += "আজ এখনো কাজ জমা পড়েনি।"
        else:
            for i, item in enumerate(top):
                safe_worker = clean_markdown_text(item['_id'])
                res += f"{i+1}. `{safe_worker}` - **{item['count']}** টি\n"
        bot.send_message(chat_id, res)
        return

    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        bot.send_message(chat_id, "💬 আপনার সমস্যা বা বার্তাটি লিখুন:", reply_markup=cancel_keyboard(chat_id))
        return

    # 5. টাস্ক ও হেল্পার টুলস হ্যান্ডলার
    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        bot.send_message(chat_id, "📦 **আপনার অ্যাকাউন্টগুলোর লিস্ট এখানে একসাথে পেস্ট করুন:**\n\n*(কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন)*", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        bot.send_message(chat_id, "📊 **আপনার .CSV বা .XLSX ফাইলটি এখানে পাঠান:**\n\n*(প্রথম ৩টি কলাম: UID, Password, Cookies/2FA)*", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "⚙️ পাসওয়ার্ড নিয়ম":
        p_rule = get_setting("pass_rule", "20")
        msg = f"⚙️ **পাসওয়ার্ড নিয়মাবলী:**\n───────────────\nডিফল্ট সেভ পাসওয়ার্ড: `{p_rule}`\n\nসকল অ্যাকাউন্টে এই নির্ধারিত পাসওয়ার্ড ফরম্যাট ব্যবহার বাধ্যতামূলক।"
        bot.send_message(chat_id, msg)
        return

    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie"
        if "FB 2FA" in text: cat = "fb_2fa"
        elif "IG Cookies" in text: cat = "ig_cookie"
        elif "IG 2FA" in text: cat = "ig_2fa"
        
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        bot.send_message(chat_id, "🆔 **UID** বা প্রোফাইল লিংক দিন:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 আপনার **2FA Secret Key** পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🔍 UID Live Checker":
        user_states[chat_id] = {'step': 'AWAITING_UID_CHECK'}
        bot.send_message(chat_id, "🔍 চেক করার জন্য **Facebook UID** পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🔍 লিংক থেকে UID":
        user_states[chat_id] = {'step': 'AWAITING_LINK_TO_UID'}
        bot.send_message(chat_id, "🔍 আপনার প্রোফাইল লিংকটি পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🚀 বাল্ক FB লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
        bot.send_message(chat_id, "🔍 একসাথে ফেসবুক UID গুলোর লিস্ট পেস্ট করুন:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "🚀 বাল্ক IG লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_IG_CHECK'}
        bot.send_message(chat_id, "🔍 একসাথে ইনস্টাগ্রাম ইউজারনেমগুলোর লিস্ট পেস্ট করুন:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "✉️ টেম্প ইমেইল":
        username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
        email = f"{username}@1secmail.com"
        bot.send_message(chat_id, f"✉️ **Temp Email:**\n`{email}`")
        return

    elif text == "👤 র্যান্ডম নাম জেনারেটর":
        first_names = ["Tanvir", "Rahim", "Sakib", "Rakibul", "Nayeem", "Arman"]
        last_names = ["Ahmed", "Uddin", "Khan", "Islam", "Hasan", "Chowdhury"]
        full_name = f"{random.choice(first_names)} {random.choice(last_names)}"
        bot.send_message(chat_id, f"👤 **রেন্ডম নাম জেনারেটেড:**\n`{full_name}`")
        return

    # 6. এডমিন প্যানেল
    elif text == "⏳ পেন্ডিং এপ্রুভাল (Manual)" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}).limit(5))
        if not pending_subs:
            bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং সাবমিশন নেই!")
            return
        for sub in pending_subs:
            text_msg = (
                f"📌 Track ID: `{sub['track_id']}`\n"
                f"👤 Worker ID: `{sub['chat_id']}`\n"
                f"🆔 UID: `{sub['uid']}`\n"
                f"💰 Amount: ৳{sub['rate']}\n\n"
                f"এপ্রুভ: `/appr {sub['track_id']}` | রিজেক্ট: `/rej {sub['track_id']}`"
            )
            bot.send_message(ADMIN_ID, text_msg)
        return

    elif text == "📊 টিম ও দৈনিক রিপোর্ট" and chat_id == ADMIN_ID:
        report_text = generate_daily_report_text()
        bot.send_message(ADMIN_ID, report_text)
        return

    elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
        rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
        msg = (
            f"⚙️ **CURRENT RATES CONFIGURATION**\n───────────────\n"
            f"📄 FB Cookie: ৳{rates.get('fb_cookie', 5.0)}\n"
            f"🔐 FB 2FA: ৳{rates.get('fb_2fa', 6.0)}\n"
            f"📷 IG Cookie: ৳{rates.get('ig_cookie', 8.0)}\n"
            f"🔐 IG 2FA: ৳{rates.get('ig_2fa', 10.0)}\n\n"
            f"সার্জ সেট করতে কমান্ড দিন: `/setsurge 2.0 | 3`"
        )
        bot.send_message(chat_id, msg)
        return

    elif text == "📂 ফাইল এক্সপোর্ট" and chat_id == ADMIN_ID:
        bot.send_message(chat_id, "📥 **SELECT CATEGORY TO EXPORT:**", reply_markup=admin_export_category_keyboard())
        return

    elif text in ["📄 Export FB Cookies", "📄 Export FB 2FA", "📸 Export IG Cookies", "📸 Export IG 2FA"] and chat_id == ADMIN_ID:
        cat_map = {
            "📄 Export FB Cookies": "fb_cookie",
            "📄 Export FB 2FA": "fb_2fa",
            "📸 Export IG Cookies": "ig_cookie",
            "📸 Export IG 2FA": "ig_2fa"
        }
        target_cat = cat_map.get(text)
        subs = list(submissions_col.find({"status": "Approved"}))
        subs = [s for s in subs if s.get("category_key") == target_cat or target_cat.replace('_', ' ') in str(s.get("category", "")).lower()]

        if not subs:
            bot.send_message(ADMIN_ID, f"📭 এই ক্যাটাগরিতে কোনো অনুমোদিত ডাটা নেই!")
            return
            
        file_content = "\n".join([s.get("payload", "") for s in subs if s.get("payload")])
        file_name = f"{text.replace(' ', '_')}_Export.txt"
        
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        with open(file_name, "rb") as f:
            bot.send_document(ADMIN_ID, f, caption=f"📥 **{text}** এর এক্সপোর্ট ফাইল।")
        if os.path.exists(file_name):
            os.remove(file_name)
        return

    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        bot.send_message(chat_id, "📢 **সকল ইউজারকে পাঠানোর জন্য নোটিশ টেক্সট লিখুন:**", reply_markup=cancel_keyboard(chat_id))
        return

    # 7. ডাইনামিক মাল্টি-স্টেপ ডাটা ইনপুট
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "নিচের কিবোর্ড থেকে অপশন বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_SUPPORT_MSG':
        user_states.pop(chat_id, None)
        tickets_col.insert_one({"worker_id": chat_id, "msg": text, "status": "OPEN", "created_at": datetime.datetime.now()})
        bot.send_message(ADMIN_ID, f"🚨 **NEW SUPPORT TICKET**\nFrom: `{clean_markdown_text(message.from_user.first_name)}` (`{chat_id}`)\n\nMsg: {text}")
        bot.send_message(chat_id, "✅ আপনার সাপোর্ট টিকিট এডমিনের কাছে পাঠানো হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_WITHDRAW_DETAILS':
        parts = [p.strip() for p in text.split("|")]
        bal = user.get("balance", 0.0)
        if len(parts) == 2 and parts[1].replace(".", "", 1).isdigit():
            num, amt = parts[0], float(parts[1])
            if 50.0 <= amt <= bal:
                update_user_field(chat_id, "balance", bal - amt)
                user_states.pop(chat_id, None)
                
                receipt_id = f"RCP-{random.randint(100000, 999999)}"
                receipts_col.insert_one({"receipt_id": receipt_id, "worker_id": chat_id, "amount": amt, "method": "Bkash/Nagad", "trx_id": num, "created_at": datetime.datetime.now()})
                
                buf = generate_payout_receipt_py(receipt_id, chat_id, amt, "Bkash/Nagad", num)
                bot.send_photo(chat_id, buf, caption=f"✅ **উইথড্র রিকোয়েস্ট সফল!**\nপরিমাণ: ৳{amt:.2f}")
                bot.send_message(ADMIN_ID, f"🔔 **WITHDRAW REQUEST:**\nUser: `{chat_id}`\nPhone: `{num}`\nAmt: ৳{amt:.2f}\nReceipt: {receipt_id}")
            else:
                bot.send_message(chat_id, f"❌ ভুল অ্যামাউন্ট! ব্যালেন্স: ৳{bal:.2f}")
        else:
            bot.send_message(chat_id, "❌ ফরম্যাট ভুল! সঠিক উদাহরণ: `01700000000 | 100`")

    elif step == 'AWAITING_2FA_GEN':
        user_states.pop(chat_id, None)
        clean_key = text.replace(" ", "").upper()
        try:
            totp = pyotp.TOTP(clean_key)
            code = totp.now()
            bot.send_message(chat_id, f"🔑 **আপনার ২এফএ লাইভ কোড:** `{code}`\n\n*(কোডটি প্রতি ৩০ সেকেন্ডে পরিবর্তন হয়)*", reply_markup=main_bottom_keyboard(chat_id))
        except Exception:
            bot.send_message(chat_id, "❌ **ভুল 2FA Secret Key!** দয়া করে সঠিক Base32 সিক্রেট কী প্রদান করুন।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_UID_CHECK':
        user_states.pop(chat_id, None)
        clean_uid = extract_numeric_uid(text)
        if not clean_uid:
            bot.send_message(chat_id, "❌ **ভুল UID ফরম্যাট!**", reply_markup=main_bottom_keyboard(chat_id))
            return
        is_live, desc = check_live_account(clean_uid)
        status_icon = "🟢" if is_live else "🔴"
        bot.send_message(chat_id, f"📊 **UID Live Check Result:**\n\n🆔 UID: `{clean_uid}`\nStatus: {status_icon} **{desc}**", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_BULK_FB_CHECK':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        live_count = 0
        dead_count = 0
        for line in lines[:20]:
            uid = extract_numeric_uid(line)
            if uid:
                is_live, _ = check_live_account(uid)
                if is_live: live_count += 1
                else: dead_count += 1
            else: dead_count += 1
        report = (
            f"📊 **FACEBOOK BULK CHECK REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• মোট চেক করা হয়েছে : {len(lines)} টি\n"
            f"• 🟢 লাইভ / এক্টিভ   : {live_count} টি\n"
            f"• 🔴 ডেড / সাসপেন্ডেড : {dead_count} টি\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(chat_id, report, reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_BULK_IG_CHECK':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        report = (
            f"📊 **INSTAGRAM BULK CHECK REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• মোট চেক করা হয়েছে : {len(lines)} টি\n"
            f"• 🟢 লাইভ / এক্টিভ   : {len(lines)} টি\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(chat_id, report, reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_LINK_TO_UID':
        user_states.pop(chat_id, None)
        clean_uid = extract_numeric_uid(text)
        if clean_uid:
            bot.send_message(chat_id, f"✅ **এক্সট্র্যাক্ট করা UID:** `{clean_uid}`", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ লিংক থেকে কোনো UID পাওয়া যায়নি!", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        users = users_col.find({"banned": False})
        sent_count = 0
        for u in users:
            try:
                bot.send_message(u["_id"], f"📢 **[ANNOUNCEMENT]**\n\n{text}")
                sent_count += 1
            except Exception:
                pass
        bot.send_message(ADMIN_ID, f"✅ মোট **{sent_count}** জন ইউজারকে নোটিশ পাঠানো হয়েছে।", reply_markup=admin_bottom_keyboard())

    # 🔥 বাল্ক সাবমিশন ইঞ্জিন (সম্পূর্ণ ফিক্সড)
    elif step == 'AWAITING_BULK_TEXT':
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            bot.send_message(chat_id, "❌ কোনো ডেটা পাওয়া যায়নি!", reply_markup=main_bottom_keyboard(chat_id))
            user_states.pop(chat_id, None)
            return

        success_count, duplicate_count, total_earned = 0, 0, 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for line in lines:
            numeric_uid = extract_numeric_uid(line)
            if not numeric_uid:
                continue

            if is_duplicate_uid(numeric_uid):
                duplicate_count += 1
                continue

            p_hash = generate_payload_hash(line)
            if is_payload_blacklisted(p_hash):
                continue

            cat_key = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
            if "sessionid=" in line:
                cat_key = "ig_cookie"

            rate = get_current_task_rate(cat_key)
            track_id = generate_tracking_id()

            async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), numeric_uid, user.get("password", "20"), line])
            submissions_col.insert_one({
                "chat_id": chat_id,
                "worker_name": clean_markdown_text(message.from_user.first_name),
                "uid": numeric_uid,
                "password": user.get("password", "20"),
                "payload": line,
                "payload_hash": p_hash,
                "track_id": track_id,
                "category": "FB Cookies" if "cookie" in cat_key else "FB 2FA",
                "category_key": cat_key,
                "rate": rate,
                "status": "Hold",
                "date_str": now_str,
                "date_obj": datetime.datetime.now()
            })
            
            try:
                log_msg = (
                    f"📦 **LIVE BULK BACKUP #{track_id}**\n"
                    f"⏰ সময়: {now_str}\n"
                    f"👤 Worker ID: #{chat_id}\n"
                    f"🆔 UID: `{numeric_uid}`\n"
                    f"💰 Rate: ৳{rate:.2f}\n\n"
                    f"📄 Payload:\n`{line[:100]}`..."
                )
                bot.send_message(LOG_CHANNEL_ID, log_msg)
            except Exception:
                pass

            success_count += 1
            total_earned += rate

        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}, "$set": {"last_active": datetime.datetime.now()}})
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"🎉 **বাল্ক সাবমিশন সম্পন্ন!**\n\n✅ সফল: **{success_count}** টি\n⚠️ ডুপ্লিকেট/স্কিপড: **{duplicate_count}** টি\n💰 অর্জিত (হোল্ড): ৳{total_earned:.2f}", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID! সঠিক UID দিন:")
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        prompt = "🍪 **Cookies** পেস্ট করুন:" if "cookie" in cat else "🔐 **2FA Secret Key** দিন:"
        bot.send_message(chat_id, f"✅ Live UID Verified: `{numeric_uid}`\n\n{prompt}")

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        p_hash = generate_payload_hash(text)
        if is_payload_blacklisted(p_hash):
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "❌ **প্রত্যাখ্যাত! এই কুকিজ/২এফএ পূর্বে ব্যবহৃত বা ব্ল্যাকলিস্টেড।**", reply_markup=main_bottom_keyboard(chat_id))
            return

        rate = get_current_task_rate(cat)
        track_id = generate_tracking_id()
        
        async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, user.get("password", "20"), text])
        submissions_col.insert_one({
            "chat_id": chat_id,
            "worker_name": clean_markdown_text(message.from_user.first_name),
            "uid": uid,
            "password": user.get("password", "20"),
            "payload": text,
            "payload_hash": p_hash,
            "track_id": track_id,
            "category": "FB Cookies" if "cookie" in cat else "FB 2FA",
            "category_key": cat,
            "rate": rate,
            "status": "Hold",
            "date_str": now_str,
            "date_obj": datetime.datetime.now()
        })

        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}, "$set": {"last_active": datetime.datetime.now()}})
        user_states.pop(chat_id, None)
        
        bot.send_message(chat_id, f"🎉 **কাজ জমা সফল হয়েছে!**\n📌 Track ID: `{track_id}`\n💰 আর্ন (এসক্রো হোল্ড): ৳{rate:.2f}\n\n*নোট: ২৪ ঘণ্টা পর টেস্ট শেষে টাকা মেইন ব্যালেন্সে যুক্ত হবে।*", reply_markup=main_bottom_keyboard(chat_id))

# ================= 9. Server Runner =================

if __name__ == "__main__":
    print("Zero-Bug Enterprise Production Python Bot Engine Active with 100% Feature Parity...")
    
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        try:
            bot.remove_webhook()
            time.sleep(1)
            webhook_url = f"{render_url}/{TOKEN}"
            bot.set_webhook(url=webhook_url)
            print(f"[WEBHOOK SET SUCCESS]: {webhook_url}")
        except Exception as e:
            print(f"[Webhook Error]: {e}")
            
        port = int(os.environ.get("PORT", 10000))
        flask_app.run(host="0.0.0.0", port=port)
    else:
        try:
            bot.remove_webhook()
        except Exception:
            pass
        threading.Thread(target=run_flask, daemon=True).start()
        print("[LOCAL POLLING ENGINE STARTED]...")
        bot.infinity_polling(skip_pending=True)