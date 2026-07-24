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
from flask import Flask, request, abort
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
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

LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = "-1003943094107"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

try:
    BOT_USERNAME = bot.get_me().username
except Exception:
    BOT_USERNAME = "online_bazar_manager_bot"

# MongoDB Connection Pool
mongo_client = MongoClient(
    MONGO_URL,
    maxPoolSize=200,
    minPoolSize=20,
    maxIdleTimeMS=45000,
    connectTimeoutMS=10000
)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
tickets_col = db['support_tickets']
receipts_col = db['payout_receipts']
blacklisted_payloads_col = db['blacklisted_payloads']
ai_logs_col = db['ai_logs']

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

user_states = {}

# ================= 2. Sanitization, Helper & AI Functions =================

def get_bd_time():
    """Returns current Bangladesh Time (UTC+6)."""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=6)

def log_ai_report(issue_type, description, fix_action):
    """Logs Background Error Recovery quietly."""
    now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
    ai_logs_col.insert_one({"timestamp": now_str, "type": issue_type, "description": description, "action": fix_action})
    audit_msg = f"🧠 <b>[AI AUTO-FIX REPORT]</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n⏱️ <b>সময়:</b> {now_str}\n📌 <b>সমস্যা:</b> {description}\n🛠️ <b>অ্যাকশন:</b> {fix_action}"
    try: bot.send_message(ADMIN_ID, audit_msg)
    except Exception: pass

def sanitize_html(text):
    if not text: return "Worker"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_setting(key, default):
    res = settings_col.find_one({"_id": key})
    return res["value"] if res else default

def update_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        user = {
            "_id": chat_id, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0,
            "banned": False, "ban_reason": "", "custom_password": "",
            "last_bonus_date": None, "joined_date": get_bd_time(), "last_active": get_bd_time()
        }
        users_col.insert_one(user)
    return user

def update_user_field(chat_id, field, value):
    users_col.update_one({"_id": chat_id}, {"$set": {field: value}}, upsert=True)

def is_user_banned(chat_id):
    user = users_col.find_one({"_id": chat_id})
    return user.get("banned", False) if user else False

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']: return False
        except Exception: continue
    return True

def generate_tracking_id():
    return f"SUB-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"

def is_duplicate_uid(uid):
    return submissions_col.find_one({"uid": str(uid)}) is not None

def generate_payload_hash(payload_str):
    clean_str = re.sub(r'\s+', '', str(payload_str))
    return hashlib.sha256(clean_str.encode('utf-8')).hexdigest()

def is_payload_blacklisted(payload_hash):
    return blacklisted_payloads_col.find_one({"_id": payload_hash}) is not None

def add_to_payload_blacklist(payload_hash, reason="Dead Cookie/2FA"):
    blacklisted_payloads_col.update_one(
        {"_id": payload_hash},
        {"$set": {"reason": reason, "added_at": get_bd_time()}},
        upsert=True
    )

def extract_numeric_uid(text):
    text = str(text).strip()
    c_user_match = re.search(r'c_user=(\d{8,20})', text)
    if c_user_match: return c_user_match.group(1)
    link_match = re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text)
    if link_match: return link_match.group(1)
    num_match = re.search(r'\b(\d{8,20})\b', text)
    if num_match: return num_match.group(1)
    return None

def is_valid_cookies(cookie_str):
    c_str = str(cookie_str)
    return ("c_user=" in c_str) or ("datr=" in c_str) or ("xs=" in c_str) or ("sessionid=" in c_str)

def check_live_account(uid):
    try:
        clean_uid = extract_numeric_uid(uid)
        if not clean_uid: return False, "Invalid UID format"
        url = f"https://www.facebook.com/{clean_uid}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            if "content=\"no-cache\"" in res.text or "The page you requested cannot be displayed" in res.text: return False, "Checkpoint/Dead"
            return True, "Live Account"
        return False, "Suspended/Dead"
    except Exception: return True, "Assumed Live"

def check_ig_username_live(username):
    try:
        clean_user = username.replace("@", "").strip()
        url = f"https://www.instagram.com/{clean_user}/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200 and "Page Not Found" not in res.text: return True, "Live Instagram Profile"
        return False, "Dead / Suspended"
    except Exception: return True, "Assumed Live"

def get_current_task_rate(cat_key):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    base_rate = float(rates.get(cat_key, 5.0))
    surge_info = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge_info.get("active"):
        exp = surge_info.get("expires_at")
        if exp and get_bd_time() < exp: base_rate += float(surge_info.get("bonus", 0.0))
    return base_rate

def async_save_to_sheet(tab_name, row_data):
    def task():
        try:
            if not os.path.exists(CREDENTIALS_FILE): return
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(SPREADSHEET_ID)
            worksheet = sheet.worksheet(tab_name)
            worksheet.append_row(row_data)
        except Exception as e: pass
    threading.Thread(target=task, daemon=True).start()

# ================= 3. Image Badge Generators =================

def generate_worker_badge_image_py(worker_id, username, total_submissions):
    img = Image.new('RGB', (600, 320), color='#0f172a')
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.rectangle([10, 10, 590, 310], outline='#38bdf8', width=3)
    draw.text((30, 30), "VERIFIED WORKER ID BADGE", fill='#38bdf8', font=font)
    draw.text((30, 80), f"Name/Username: {username}", fill='#ffffff', font=font)
    draw.text((30, 120), f"Worker ID: #{worker_id}", fill='#ffffff', font=font)
    draw.text((30, 160), f"Total Tasks Completed: {total_submissions}", fill='#ffffff', font=font)
    draw.rectangle([30, 220, 210, 270], fill='#10b981')
    draw.text((50, 235), "VERIFIED STAFF", fill='#ffffff', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ================= 4. UI Keyboards (Smart Navigation) =================

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💼 টাস্ক ও টুলস"), KeyboardButton("👤 আমার অ্যাকাউন্ট"))
    markup.add(KeyboardButton("🎁 বোনাস ও সাপোর্ট"))
    if chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def tasks_and_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📋 কাজ জমা দিন"), KeyboardButton("🛠 হেল্পার টুলস"))
    markup.add(KeyboardButton("📜 কাজের ইতিহাস"), KeyboardButton("📱 ইউজার-এজেন্ট"))
    markup.add(KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def submit_tasks_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 টাস্ক মেনুতে ফিরুন"), KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def category_bottom_keyboard():
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(f"📄 FB Cookies (৳{rates['fb_cookie']})"), KeyboardButton(f"🔐 FB 2FA (৳{rates['fb_2fa']})"))
    markup.add(KeyboardButton(f"📷 IG Cookies (৳{rates['ig_cookie']})"), KeyboardButton(f"🔐 IG 2FA (৳{rates['ig_2fa']})"))
    markup.add(KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def helper_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"))
    markup.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    markup.add(KeyboardButton("👤 র্যান্ডম নাম জেনারেটর"))
    markup.add(KeyboardButton("🔙 টাস্ক মেনুতে ফিরুন"), KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💳 Withdraw"), KeyboardButton("🪪 ভেরিফাইড আইডি কার্ড"))
    markup.add(KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def bonus_support_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def admin_bottom_keyboard():
    m_mode = get_setting("maintenance_mode", False)
    m_btn = "🛠 মেইনটেনেন্স: 🟢 ON" if m_mode else "🛠 মেইনটেনেন্স: 🔴 OFF"
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⏳ পেন্ডিং এপ্রুভাল (Manual)"), KeyboardButton("📊 টিম ও দৈনিক রিপোর্ট"))
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("📂 ফাইল এক্সপোর্ট"))
    markup.add(KeyboardButton("🤖 বায়ার রিপোর্ট অটো-ম্যাচার"), KeyboardButton("📢 ব্রডকাস্ট নোটিশ"))
    markup.add(KeyboardButton("👤 ইউজার ম্যানেজার"), KeyboardButton("🧠 AI সিটেডেল অডিট"))
    markup.add(KeyboardButton(m_btn), KeyboardButton("🏠 প্রধান মেনু"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= 5. Background Daemon & Report Scheduler =================

def generate_daily_report_text(date_target=None):
    if not date_target: date_target = get_bd_time()
    
    start_of_day = date_target.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = date_target.replace(hour=23, minute=59, second=59, microsecond=999)
    
    approved_list = list(submissions_col.find({"status": "Approved", "date_obj": {"$gte": start_of_day, "$lte": end_of_day}}))
    
    total_approved = len(approved_list)
    hold_count = submissions_col.count_documents({"status": "Hold", "date_obj": {"$gte": start_of_day, "$lte": end_of_day}})
    rejected_count = submissions_col.count_documents({"status": "Rejected", "date_obj": {"$gte": start_of_day, "$lte": end_of_day}})
    
    category_breakdown = {}
    total_payout = 0.0
    
    for sub in approved_list:
        cat = sub.get("category", "FB Cookies")
        rate = float(sub.get("rate", 0.0))
        total_payout += rate
        if cat not in category_breakdown: category_breakdown[cat] = {"count": 0, "amount": 0.0}
        category_breakdown[cat]["count"] += 1; category_breakdown[cat]["amount"] += rate

    report = (
        f"📊 <b>DAILY EARNING REPORT ({date_target.strftime('%Y-%m-%d')})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 মোট সাবমিশন : <b>{total_approved + hold_count + rejected_count} টি</b>\n"
        f"✅ এপ্রুভড      : <b>{total_approved} টি</b>\n"
        f"⏳ এসক্রো হোল্ড  : <b>{hold_count} টি</b>\n"
        f"❌ রিজেক্টেড    : <b>{rejected_count} টি</b>\n"
        f"💰 বিতরণকৃত পেমেন্ট : <b>৳{total_payout:.2f}</b>\n\n"
        f"🛡️ <b>ক্যাটাগরি ভিত্তিক বিবরণ:</b>\n"
    )
    for cat, data in category_breakdown.items(): report += f"• {cat} : {data['count']} টি (৳{data['amount']:.2f})\n"
    report += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return report

def escrow_daemon():
    while True:
        try:
            cutoff_24h = get_bd_time() - timedelta(hours=24)
            pending_subs = submissions_col.find({"status": "Hold", "date_obj": {"$lte": cutoff_24h}})
            for sub in pending_subs:
                amt = float(sub.get("rate") or 0.0)
                users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
                try: bot.send_message(sub["chat_id"], f"✅ আপনার হোল্ডে থাকা ৳{amt:.2f} সফলভাবে মেইন ব্যালেন্সে যুক্ত হয়েছে।")
                except Exception: pass
        except Exception: pass
        time.sleep(3600)

threading.Thread(target=escrow_daemon, daemon=True).start()

# ================= 6. Flask Webhook Server =================

flask_app = Flask(__name__)

@flask_app.route('/')
def flask_home(): return "OEB NEXUS Production Engine Active!"

@flask_app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
        return '', 200
    abort(403)

# ================= 7. Core Command & Router Handlers (WITH SHIELDS) =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
            return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

        if is_user_banned(chat_id): return bot.reply_to(message, "🔴 <b>আপনার অ্যাকাউন্টটি স্থগিত (Banned) করা হয়েছে!</b>")

        user = get_user_data(chat_id)
        if message.from_user.username: update_user_field(chat_id, "username", message.from_user.username)
        user_states.pop(chat_id, None)

        if not check_force_join(chat_id):
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
            markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
            return bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)

        bot.send_message(chat_id, f"👑 <b>ONLINE EARNING BAZAR</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nস্বাগতম <b>{sanitize_html(message.from_user.first_name)}</b>! নিচের অপশন থেকে সার্ভিস নির্বাচন করুন:", reply_markup=main_bottom_keyboard(chat_id))
    except Exception as e: log_ai_report("Start Handler Error", str(e), "Caught gracefully.")

# --- CALLBACK ROUTER ---
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    try: _process_callbacks(call)
    except Exception as e: log_ai_report("Callback Error", f"Failed on {call.data}: {str(e)}", "Silenced to prevent crash.")

def _process_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data

    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        return bot.answer_callback_query(call.id, "🛠 বটের সার্ভার আপডেটের কাজ চলছে! দয়া করে কিছুক্ষণ পর চেষ্টা করুন.", show_alert=True)

    bot.answer_callback_query(call.id)

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        else: bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!")

    elif code == "save_pass_default":
        user = get_user_data(chat_id)
        temp_pass = user.get("temp_pending_password", "")
        if temp_pass:
            update_user_field(chat_id, "custom_password", temp_pass)
            update_user_field(chat_id, "temp_pending_password", "")
            bot.edit_message_text(f"✅ <b>সফল!</b> আপনার পাসওয়ার্ডটি ডিফল্ট হিসেবে সেভ করা হয়েছে: <code>{temp_pass}</code>", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("⚠️ কোনো পেন্ডিং পাসওয়ার্ড পাওয়া যায়নি!", chat_id, call.message.message_id)

    elif code == "appr_all_pending" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}))
        if not pending_subs: return bot.send_message(ADMIN_ID, "📭 এপ্রুভ করার মতো কোনো পেন্ডিং কাজ নেই!")
        submissions_col.update_many({"status": "Hold"}, {"$set": {"status": "Approved"}})
        for sub in pending_subs:
            amt = float(sub.get("rate") or 0.0)
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": amt, "hold_balance": -amt}})
            try: bot.send_message(sub["chat_id"], f"🎉 আপনার সাবমিশন (<code>{sub['track_id']}</code>) এপ্রুভ হয়েছে!")
            except Exception: pass
        bot.send_message(ADMIN_ID, f"⚡ <b>সফল! {len(pending_subs)} টি পেন্ডিং কাজ ১-ক্লিকে ফাস্ট এপ্রুভ করা হয়েছে।</b>")

    elif code.startswith("appr_") and not code == "appr_all_pending":
        if chat_id != ADMIN_ID: return
        track_id = code.replace("appr_", "")
        sub = submissions_col.find_one({"track_id": track_id})
        if sub and sub.get("status") == "Hold":
            amt = float(sub.get("rate") or 0.0)
            submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Approved"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": amt, "hold_balance": -amt}})
            bot.edit_message_text(f"✅ <b>APPROVED</b> | Track ID: <code>{track_id}</code> | Amt: ৳{amt}", chat_id, call.message.message_id)
            try: bot.send_message(sub["chat_id"], f"🎉 আপনার সাবমিশন (<code>{track_id}</code>) এর জন্য ৳{amt:.2f} মেইন ব্যালেন্সে যুক্ত হয়েছে!")
            except Exception: pass

    elif code.startswith("rej_"):
        if chat_id != ADMIN_ID: return
        track_id = code.replace("rej_", "")
        sub = submissions_col.find_one({"track_id": track_id})
        if sub and sub.get("status") == "Hold":
            amt = float(sub.get("rate") or 0.0)
            submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -amt}})
            bot.edit_message_text(f"❌ <b>REJECTED</b> | Track ID: <code>{track_id}</code>", chat_id, call.message.message_id)
            try: bot.send_message(sub["chat_id"], f"❌ আপনার সাবমিশন (<code>{track_id}</code>) বাতিল করা হয়েছে।")
            except Exception: pass

    elif code.startswith("exp_cat_") and chat_id == ADMIN_ID:
        cat = code.replace("exp_cat_", "")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📊 Google Sheets / CSV", callback_data=f"exp_fmt_csv_{cat}"),
            InlineKeyboardButton("📗 Excel (.xlsx)", callback_data=f"exp_fmt_xlsx_{cat}"),
            InlineKeyboardButton("📄 Text File (.txt)", callback_data=f"exp_fmt_txt_{cat}")
        )
        bot.send_message(ADMIN_ID, f"📁 <b>ক্যাটাগরি: {cat}</b>\nধাপ ২: কোন ফরম্যাটে ডাউনলোড করতে চান?", reply_markup=markup)
        
    elif code.startswith("exp_fmt_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        fmt, cat = parts[2], parts[3]
        bot.send_message(ADMIN_ID, "📁 ফাইল প্রসেস করা হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
        
        query = {"status": "Approved"}
        if cat != "ALL": query["category"] = cat
        records = list(submissions_col.find(query))
        if not records: return bot.send_message(ADMIN_ID, f"📭 {cat} ক্যাটাগরিতে কোনো ডাটা নেই!")
            
        df_data = [{"UID": r.get("uid", ""), "Password": r.get("password", ""), "Payload": r.get("payload", ""), "Category": r.get("category", "")} for r in records]
        df = pd.DataFrame(df_data)
        filename = f"Export_{cat.replace(' ', '_')}_{get_bd_time().strftime('%Y%m%d_%H%M')}"
        
        if fmt == "csv":
            buf = io.BytesIO(); df.to_csv(buf, index=False, encoding='utf-8-sig'); buf.seek(0)
            bot.send_document(ADMIN_ID, (f"{filename}.csv", buf), caption=f"📊 <b>CSV এক্সপোর্ট প্রস্তুত!</b>\nক্যাটাগরি: {cat}")
        elif fmt == "xlsx":
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Data')
            buf.seek(0); bot.send_document(ADMIN_ID, (f"{filename}.xlsx", buf), caption=f"📗 <b>Excel (.xlsx) প্রস্তুত!</b>\nক্যাটাগরি: {cat}")
        else:
            text_content = "".join([f"{i['UID']}|{i['Password']}|{i['Payload']}\n" for i in df_data])
            buf = io.BytesIO(text_content.encode('utf-8')); bot.send_document(ADMIN_ID, (f"{filename}.txt", buf), caption=f"📄 <b>Text File (.txt) প্রস্তুত!</b>\nক্যাটাগরি: {cat}")

    elif code.startswith("edit_sub_"):
        track_id = code.replace("edit_sub_", "")
        sub = submissions_col.find_one({"track_id": track_id, "chat_id": chat_id, "status": "Hold"})
        if not sub: return bot.send_message(chat_id, "⚠️ এই কাজটির এডিট মেয়াদ শেষ হয়ে গেছে বা ইতিমধ্যেই প্রসেস করা হয়েছে।")
        user_states[chat_id] = {'step': 'AWAITING_EDIT_PAYLOAD', 'track_id': track_id}
        bot.send_message(chat_id, f"✏️ <b>Track ID: {track_id}</b> এর জন্য সঠিক Cookies বা 2FA Key এখানে পেস্ট করুন:", reply_markup=cancel_keyboard())

    elif code.startswith("check_otp_"):
        email = code.replace("check_otp_", "")
        user_name, domain = email.split("@")
        try:
            res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={user_name}&domain={domain}").json()
            if not res: bot.send_message(chat_id, "📭 ইনবক্সে এখনো কোনো বার্তা আসেনি! ২-১ সেকেন্ড পর আবার চেষ্টা করুন।")
            else:
                msg_id = res[0]['id']
                msg_detail = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={user_name}&domain={domain}&id={msg_id}").json()
                body = msg_detail.get('textBody', '')
                otp_match = re.search(r'\b(\d{5,6})\b', body)
                otp_code = otp_match.group(1) if otp_match else "কোড পাওয়া যায়নি"
                bot.send_message(chat_id, f"✉️ <b>OTP/Message Received!</b>\n\n🔑 Code: <code>{otp_code}</code>\n\n📄 <b>Message:</b>\n{sanitize_html(body[:300])}")
        except Exception: bot.send_message(chat_id, "⚠️ ওটিপি চেক করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

    elif code.startswith("gen_names_"):
        cat = code.replace("gen_names_", "")
        names_db = {
            "bd_male": ["Sakib Hasan", "Tanvir Ahmed", "Rahim Uddin", "Rakibul Islam", "Nayeem Khan"],
            "bd_female": ["Nusrat Jahan", "Riya Sultana", "Sadia Islam", "Farhana Akter", "Mim Chowdhury"],
            "usa_male": ["James Smith", "John Johnson", "Robert Williams", "Michael Brown", "William Jones"],
            "usa_female": ["Mary Smith", "Patricia Johnson", "Jennifer Williams", "Linda Brown"]
        }
        selected = names_db.get(cat, names_db["bd_male"])
        out = f"👤 <b>১-ক্লিক কপি করার নাম তালিকা:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for name in selected: out += f"<code>{name}</code>\n"
        bot.send_message(chat_id, out)

    elif code.startswith("gen_ua_"):
        cat = code.replace("gen_ua_", "")
        ua_db = {
            "android": ["Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"],
            "iphone": ["Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"],
            "pc": ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"]
        }
        selected = ua_db.get(cat, ua_db["android"])
        out = "📱 <b>কপি করার জন্য User-Agent স্ট্রিং:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for ua in selected: out += f"<code>{ua}</code>\n\n"
        bot.send_message(chat_id, out)

    elif code.startswith("lb_"):
        tf = code.replace("lb_", "")
        now = get_bd_time()
        if tf == "daily": query = {"date_str": {"$regex": f"^{now.strftime('%Y-%m-%d')}"}}; title = "আজকের সেরা"
        elif tf == "weekly": query = {"date_obj": {"$gte": now - timedelta(days=7)}}; title = "এই সপ্তাহের সেরা"
        else: query = {}; title = "সর্বকালের সেরা"

        pipeline = [{"$match": query}, {"$group": {"_id": "$worker_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]
        top = list(submissions_col.aggregate(pipeline))
        out = f"🏆 <b>লিডারবোর্ড - {title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, item in enumerate(top): out += f"{badges[i]} <b>{sanitize_html(item['_id'])}</b> — {item['count']} টি\n"
        
        user_cnt = submissions_col.count_documents({"chat_id": chat_id})
        out += f"\n🎯 <b>আপনার মোট জমা:</b> <code>{user_cnt}</code> টি"
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"), InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"), InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime"))
        bot.edit_message_text(out, chat_id, call.message.message_id, reply_markup=markup)

    elif code.startswith("surge_") and chat_id == ADMIN_ID:
        act = code.replace("surge_", "")
        if act == "off":
            update_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
            bot.send_message(ADMIN_ID, "🛑 <b>সার্জ বোনাস সফলভাবে বন্ধ করা হয়েছে।</b>")
        else:
            hrs = int(act)
            update_setting("surge_pricing", {"active": True, "bonus": 2.0, "expires_at": get_bd_time() + timedelta(hours=hrs)})
            bot.send_message(ADMIN_ID, f"⚡ <b>+৳২.০০ সার্জ বোনাস {hrs} ঘণ্টার জন্য চালু করা হয়েছে!</b>")

    elif code.startswith("rate_edit_") and chat_id == ADMIN_ID:
        cat_key = code.replace("rate_edit_", "")
        user_states[chat_id] = {'step': 'AWAITING_NEW_RATE', 'category_key': cat_key}
        bot.send_message(ADMIN_ID, f"✏️ <b>{cat_key}</b> এর নতুন মূল্য লিখুন (যেমন: 6.5):", reply_markup=cancel_keyboard())

    elif code == "admin_ban_user_prompt" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BAN_USER_INPUT'}
        bot.send_message(ADMIN_ID, "🚫 ব্যান করার জন্য ইউজারের <b>Telegram ID</b> বা <b>Username</b> পাঠান:", reply_markup=cancel_keyboard())

    elif code == "admin_unban_user_prompt" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_UNBAN_USER_INPUT'}
        bot.send_message(ADMIN_ID, "🟢 আনব্যান করার জন্য ইউজারের <b>Telegram ID</b> বা <b>Username</b> পাঠান:", reply_markup=cancel_keyboard())

# --- FILE/DOCUMENT ROUTER ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try: _process_document(message)
    except Exception as e:
        log_ai_report("File Parse Error", str(e), "Caught exception gracefully.")
        bot.reply_to(message, "❌ ফাইলটি পড়তে সমস্যা হয়েছে। দয়া করে সঠিক ফরম্যাটে ফাইল দিন।", reply_markup=main_bottom_keyboard(message.chat.id))

def _process_document(message):
    chat_id = message.chat.id

    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

    if is_user_banned(chat_id): return
    state = user_states.get(chat_id)
    
    # Buyer Report Auto-Matcher
    if state and state.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = message.document.file_name.lower()
        extracted_uids = set()
        
        if filename.endswith(".csv"): extracted_uids = set(pd.read_csv(io.BytesIO(downloaded)).astype(str).values.flatten())
        elif filename.endswith(".xlsx"): extracted_uids = set(pd.read_excel(io.BytesIO(downloaded)).astype(str).values.flatten())
        else: extracted_uids = set(re.findall(r'\b\d{10,16}\b', downloaded.decode('utf-8', errors='ignore')))
            
        cleaned_uids = {u.strip() for u in extracted_uids if u.strip().isdigit()}
        pending_subs = list(submissions_col.find({"status": "Hold"}))
        appr, rej, payout = 0, 0, 0.0
        
        for sub in pending_subs:
            uid = str(sub.get("uid", "")).strip()
            amt = float(sub.get("rate") or 0.0)
            if uid in cleaned_uids:
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
                users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                appr += 1; payout += amt
                try: bot.send_message(sub["chat_id"], f"✅ বায়ার রিপোর্টে আপনার আইডি (<code>{uid}</code>) এপ্রুভ হয়েছে! ৳{amt} যোগ হয়েছে।")
                except Exception: pass
            else:
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -amt}})
                rej += 1
                try: bot.send_message(sub["chat_id"], f"❌ বায়ার রিপোর্টে আপনার আইডি (<code>{uid}</code>) রিজেক্টেড।")
                except Exception: pass
                
        return bot.send_message(ADMIN_ID, f"🤖 <b>[BUYER REPORT MATCH COMPLETE]</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📊 মোট প্রসেস: {len(pending_subs)} টি\n✅ এপ্রুভড : {appr} টি (৳{payout})\n❌ রিজেক্টেড: {rej} টি\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", reply_markup=admin_bottom_keyboard())

    # Regular Worker Excel Submission
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        user_states.pop(chat_id, None)
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        with open(file_name, 'wb') as f: f.write(bot.download_file(file_info.file_path))

        df = pd.read_csv(file_name, dtype=str) if file_name.endswith('.csv') else pd.read_excel(file_name, dtype=str)
        df = df.fillna('')
        success_count, total_earned = 0, 0.0
        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
        user = get_user_data(chat_id)
        default_pass = user.get("custom_password") or get_setting("pass_rule", "20")

        for _, row in df.iterrows():
            vals = [str(x).strip() for x in row.values]
            uid, password, payload = None, default_pass, None
            for v in vals:
                if not uid and extract_numeric_uid(v): uid = extract_numeric_uid(v)
                elif is_valid_cookies(v) or len(v) > 20: payload = v

            if uid and payload and not is_duplicate_uid(uid):
                p_hash = generate_payload_hash(payload)
                if is_payload_blacklisted(p_hash): continue
                cat_key = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                rate = float(get_current_task_rate(cat_key))
                track_id = generate_tracking_id()

                async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), uid, password, payload])
                submissions_col.insert_one({
                    "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                    "password": password, "payload": payload, "payload_hash": p_hash, "track_id": track_id,
                    "category": "FB Cookies" if "cookie" in cat_key else "FB 2FA", "category_key": cat_key,
                    "rate": rate, "status": "Hold", "date_str": now_str, "date_obj": get_bd_time()
                })
                success_count += 1; total_earned += rate
                
                # [LOG CHANNEL NOTIFICATION FIXED]
                try:
                    bot.send_message(
                        LOG_CHANNEL_ID,
                        f"📥 <b>NEW SUBMISSION (Excel)</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📌 Track: <code>{track_id}</code>\n"
                        f"👤 Worker: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                        f"🆔 UID: <code>{uid}</code>\n"
                        f"📁 Cat: <b>FB Cookies/2FA</b>\n"
                        f"💰 Rate: ৳{rate:.2f}"
                    )
                except Exception: pass

        if os.path.exists(file_name): os.remove(file_name)
        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
        return bot.reply_to(message, f"🎉 <b>ফাইল প্রসেস সম্পন্ন!</b>\n\n✅ সফল: <b>{success_count}</b> টি\n💰 আর্ন (হোল্ড): ৳{total_earned:.2f}", reply_markup=submit_tasks_keyboard())

# --- MAIN TEXT ROUTER ---
@bot.message_handler(content_types=['text', 'photo', 'video', 'animation'])
def main_router(message):
    try: _process_main_router(message)
    except Exception as e: log_ai_report("Main Router Global Error", str(e), "Caught by shield to prevent crash.")

def _process_main_router(message):
    chat_id = message.chat.id
    
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

    if is_user_banned(chat_id): return
    
    text = ""
    if message.text: text = message.text.strip()
    elif message.caption: text = message.caption.strip()
    
    user = get_user_data(chat_id)

    nav_buttons = [
        "🏠 প্রধান মেনু", "🔙 প্রধান মেনু", "❌ বাতিল করুন", "💼 টাস্ক ও টুলস", "📋 কাজ জমা দিন", "🛠 হেল্পার টুলস", 
        "📌 সিঙ্গেল জমা", "👤 আমার অ্যাকাউন্ট", "🎁 বোনাস ও সাপোর্ট", "👑 এডমিন প্যানেল", "💳 Withdraw", 
        "🪪 ভেরিফাইড আইডি কার্ড", "🎁 Claim Daily Bonus", "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", 
        "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🔑 2FA কোড জেনারেটর", 
        "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "✉️ টেম্প ইমেইল", "👤 র্যান্ডম নাম জেনারেটর", 
        "📜 কাজের ইতিহাস", "📱 ইউজার-এজেন্ট", "👤 ইউজার ম্যানেজার", "🤖 বায়ার রিপোর্ট অটো-ম্যাচার", 
        "🧠 AI সিটেডেল অডিট", "📂 ফাইল এক্সপোর্ট", "📢 ব্রডকাস্ট নোটিশ", "⚙️ সেট রেট ও চার্জ", 
        "📊 টিম ও দৈনিক রিপোর্ট", "⏳ পেন্ডিং এপ্রুভাল (Manual)", 
        "🔙 টাস্ক মেনুতে ফিরুন", "🔙 কাজ জমা মেনুতে ফিরুন"
    ]

    current_state = user_states.get(chat_id, {}).copy()

    if text in nav_buttons or text.startswith("🛠 মেইনটেনেন্স:"):
        user_states.pop(chat_id, None)

    if text == "❌ বাতিল করুন":
        step = current_state.get('step')
        if step in ['AWAITING_UID', 'AWAITING_SINGLE_DATA', 'AWAITING_MANUAL_PASSWORD', 'AWAITING_BULK_TEXT', 'AWAITING_EXCEL_FILE']:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে কাজ জমা মেনুতে ফিরে আসা হয়েছে।", reply_markup=submit_tasks_keyboard())
        elif step in ['AWAITING_2FA_GEN', 'AWAITING_BULK_FB_CHECK', 'AWAITING_BULK_IG_CHECK']:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে টুলস মেনুতে ফিরে আসা হয়েছে।", reply_markup=helper_tools_keyboard())
        elif step == 'AWAITING_WITHDRAW_DETAILS':
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করা হয়েছে।", reply_markup=account_keyboard())
        elif step == 'AWAITING_EDIT_PAYLOAD':
            return bot.send_message(chat_id, "❌ এডিট বাতিল করা হয়েছে।", reply_markup=tasks_and_tools_keyboard())
        else:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে প্রধান মেনুতে ফিরে আসা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))

    # NLP Interceptor
    if chat_id == ADMIN_ID and text not in nav_buttons and not text.startswith("/") and not text.startswith("🛠 মেইনটেনেন্স:"):
        if "রেট" in text or "ব্রডকাস্ট" in text or "টাকা" in text:
            numbers = re.findall(r'\d+\.?\d*', text)
            if numbers and "রেট" in text:
                new_rate = float(numbers[0])
                rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
                if "ফেসবুক কুকিজ" in text or "fb cookie" in text.lower(): rates["fb_cookie"] = new_rate
                elif "ফেসবুক ২এফএ" in text or "fb 2fa" in text.lower(): rates["fb_2fa"] = new_rate
                elif "ইনস্টাগ্রাম কুকিজ" in text or "ig cookie" in text.lower(): rates["ig_cookie"] = new_rate
                elif "ইনস্টাগ্রাম ২এফএ" in text or "ig 2fa" in text.lower(): rates["ig_2fa"] = new_rate
                update_setting("rates", rates)
                log_ai_report("Admin Natural Language Command", text, f"Updated rates to {new_rate}")
                return bot.send_message(ADMIN_ID, f"🤖 <b>[AI COMMAND EXECUTED]</b>\nরেট সফলভাবে আপডেট করা হয়েছে ৳{new_rate}।", reply_markup=admin_bottom_keyboard())

    # --- Static Navigations ---
    if text in ["🏠 প্রধান মেনু", "🔙 প্রধান মেনু"]: return bot.send_message(chat_id, "🏠 <b>প্রধান মেনু:</b>", reply_markup=main_bottom_keyboard(chat_id))
    elif text in ["🔙 টাস্ক মেনুতে ফিরুন", "💼 টাস্ক ও টুলস"]: return bot.send_message(chat_id, "💼 <b>টাস্ক ও টুলস সেকশনে স্বাগতম:</b>", reply_markup=tasks_and_tools_keyboard())
    elif text in ["🔙 কাজ জমা মেনুতে ফিরুন", "📋 কাজ জমা দিন"]: return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ বেছে নিন:</b>", reply_markup=submit_tasks_keyboard())
    
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>আপনার প্রয়োজনীয় টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
    elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard())
    
    elif text == "👤 আমার অ্যাকাউন্ট":
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = float(user.get("balance") or 0.0)
        hold_bal = float(user.get("hold_balance") or 0.0)
        safe_name = sanitize_html(message.from_user.first_name)
        msg_str = f"👤 <b>নাম:</b> <code>{safe_name}</code>\n📊 <b>মোট কাজ:</b> <code>{cnt}</code> টি\n💰 <b>মেইন ব্যালেন্স:</b> <code>৳{bal:.2f}</code>\n⏳ <b>এসক্রো হোল্ড:</b> <code>৳{hold_bal:.2f}</code>\n🔗 <b>রেফারেল লিঙ্ক:</b> https://t.me/{BOT_USERNAME}?start={chat_id}"
        return bot.send_message(chat_id, msg_str, reply_markup=account_keyboard())
    elif text == "🎁 বোনাস ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>বোনাস ও সাপোর্ট সেন্টার:</b>", reply_markup=bonus_support_keyboard())
    elif text == "👑 এডমিন প্যানেল" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "👑 <b>এডমিন প্যানেল</b>\nসবকটি ফিচার ও এআই সার্ভিস চালু রয়েছে।", reply_markup=admin_bottom_keyboard())

    # --- Worker Helpers & Tools ---
    elif text == "📜 কাজের ইতিহাস":
        subs = list(submissions_col.find({"chat_id": chat_id}).sort("date_obj", -1).limit(5))
        if not subs: return bot.send_message(chat_id, "📭 আপনি এখনো কোনো কাজ জমা দেননি!", reply_markup=tasks_and_tools_keyboard())
        out = "📜 <b>আপনার সর্বশেষ জমার ইতিহাস:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        markup = InlineKeyboardMarkup()
        for sub in subs:
            st = sub.get("status")
            st_icon = "⏳ [HOLD]" if st == "Hold" else ("✅ [APPROVED]" if st == "Approved" else "❌ [REJECTED]")
            out += f"{st_icon} <code>{sub['track_id']}</code> | <b>{sub['category']}</b> | ৳{sub['rate']}\n"
            if st == "Hold": markup.add(InlineKeyboardButton(f"✏️ এডিট {sub['track_id']}", callback_data=f"edit_sub_{sub['track_id']}"))
        return bot.send_message(chat_id, out, reply_markup=markup)

    elif text == "📱 ইউজার-এজেন্ট":
        markup = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("📱 Android Chrome", callback_data="gen_ua_android"), InlineKeyboardButton("🍎 iPhone Safari", callback_data="gen_ua_iphone"), InlineKeyboardButton("💻 Windows PC Chrome", callback_data="gen_ua_pc"))
        return bot.send_message(chat_id, "📱 <b>ইউজার-এজেন্ট ক্যাটাগরি বেছে নিন:</b>", reply_markup=markup)

    elif text == "👤 র্যান্ডম নাম জেনারেটর":
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("🇧🇩 BD Male", callback_data="gen_names_bd_male"), InlineKeyboardButton("🇧🇩 BD Female", callback_data="gen_names_bd_female"), InlineKeyboardButton("🇺🇸 USA Male", callback_data="gen_names_usa_male"), InlineKeyboardButton("🇺🇸 USA Female", callback_data="gen_names_usa_female"))
        return bot.send_message(chat_id, "👤 <b>যে ক্যাটাগরির নাম চান সিলেক্ট করুন:</b>", reply_markup=markup)

    elif text == "✉️ টেম্প ইমেইল":
        email = f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}@1secmail.com"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📩 ইনবক্স / ওটিপি দেখুন", callback_data=f"check_otp_{email}"))
        return bot.send_message(chat_id, f"✉️ <b>Temp Email Generated:</b>\n<code>{email}</code>\n\n<i>ওটিপি পাঠানোর পর নিচের বাটনে চাপ দিন।</i>", reply_markup=markup)

    elif text == "🚀 বাল্ক FB লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
        return bot.send_message(chat_id, "🔍 <b>একসাথে ফেসবুক UID গুলোর লিস্ট পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "🚀 বাল্ক IG লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_IG_CHECK'}
        return bot.send_message(chat_id, "🔍 <b>একসাথে ইনস্টাগ্রাম ইউজারনেমগুলোর লিস্ট পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        return bot.send_message(chat_id, "🔑 <b>2FA Secret Key পাঠান:</b>", reply_markup=cancel_keyboard())

    elif text == "🎁 Claim Daily Bonus":
        last_bonus = user.get("last_bonus_date")
        now = get_bd_time()
        
        if isinstance(last_bonus, str):
            try: last_bonus = datetime.datetime.fromisoformat(last_bonus)
            except Exception: last_bonus = None
            
        if last_bonus: last_bonus = last_bonus.replace(tzinfo=None)
        now_naive = now.replace(tzinfo=None)

        if last_bonus and (now_naive - last_bonus) < datetime.timedelta(hours=24):
            return bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টার মধ্যে একবারই বোনাস নেওয়া যায়!", reply_markup=bonus_support_keyboard())
        else:
            new_bal = float(user.get("balance") or 0.0) + 2.0
            update_user_field(chat_id, "balance", new_bal)
            update_user_field(chat_id, "last_bonus_date", now)
            return bot.send_message(chat_id, "🎉 আপনি ৳২.০০ বোনাস পেয়েছেন!", reply_markup=bonus_support_keyboard())

    elif text == "🏆 লিডারবোর্ড":
        markup = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"), InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"), InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime"))
        return bot.send_message(chat_id, "🏆 <b>লিডারবোর্ড ফিল্টার বেছে নিন:</b>", reply_markup=markup)

    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        return bot.send_message(chat_id, "💬 <b>আপনার বার্তাটি লিখুন:</b>", reply_markup=cancel_keyboard())

    elif text == "💳 Withdraw":
        bal = float(user.get("balance") or 0.0)
        if bal < 50.0: return bot.send_message(chat_id, f"⚠️ সর্বনিম্ন উইথড্র ৳৫০.০০। ব্যালেন্স: ৳{bal:.2f}", reply_markup=account_keyboard())
        user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
        return bot.send_message(chat_id, "💳 বিকাশ/নগদ নাম্বার ও পরিমাণ লিখুন (যেমন: <code>01700000000 | 100</code>):", reply_markup=cancel_keyboard())

    elif text == "🪪 ভেরিফাইড আইডি কার্ড":
        safe_name = sanitize_html(message.from_user.first_name)
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        buf = generate_worker_badge_image_py(chat_id, safe_name, cnt)
        return bot.send_photo(chat_id, buf, caption="🪪 <b>আপনার ভেরিফাইড আইডি কার্ড!</b>", reply_markup=account_keyboard())

    # --- Admin Routes ---
    elif text.startswith("🛠 মেইনটেনেন্স:") and chat_id == ADMIN_ID:
        current_mode = get_setting("maintenance_mode", False)
        new_mode = not current_mode
        update_setting("maintenance_mode", new_mode)
        status = "চালু (ON)" if new_mode else "বন্ধ (OFF)"
        msg = f"✅ <b>মেইনটেনেন্স মোড সফলভাবে {status} করা হয়েছে!</b>\n\nএখন থেকে {'সাধারণ মেম্বাররা বটের কোনো কাজ করতে পারবে না' if new_mode else 'সবাই আবার বটের সার্ভিস ব্যবহার করতে পারবে'}।"
        return bot.send_message(ADMIN_ID, msg, reply_markup=admin_bottom_keyboard())

    elif text == "⏳ পেন্ডিং এপ্রুভাল (Manual)" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}).limit(5))
        if not pending_subs: return bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং সাবমিশন নেই!", reply_markup=admin_bottom_keyboard())
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("⚡ Approve All Current Pending", callback_data="appr_all_pending"))
        bot.send_message(ADMIN_ID, f"⏳ <b>সর্বমোট পেন্ডিং সাবমিশন পর্যালোচনা:</b>", reply_markup=markup)
        for sub in pending_subs:
            item_markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✅ Approve", callback_data=f"appr_{sub['track_id']}"), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{sub['track_id']}"))
            bot.send_message(ADMIN_ID, f"📌 Track ID: <code>{sub['track_id']}</code>\n👤 Worker: <code>{sub['chat_id']}</code>\n🆔 UID: <code>{sub['uid']}</code>\n💰 Rate: ৳{sub['rate']}", reply_markup=item_markup)
        return

    elif text == "📊 টিম ও দৈনিক রিপোর্ট" and chat_id == ADMIN_ID:
        report = generate_daily_report_text()
        return bot.send_message(ADMIN_ID, report, reply_markup=admin_bottom_keyboard())

    elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
        rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
        surge = get_setting("surge_pricing", {"active": False, "bonus": 0.0})
        st_text = f"⚡ ACTIVE (+৳{surge['bonus']})" if surge.get('active') else "🔴 INACTIVE"
        msg = f"⚙️ <b>CURRENT RATES & SURGE DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📄 FB Cookie : ৳{rates['fb_cookie']}\n🔐 FB 2FA    : ৳{rates['fb_2fa']}\n📷 IG Cookie : ৳{rates['ig_cookie']}\n🔐 IG 2FA    : ৳{rates['ig_2fa']}\n\n⚡ <b>Surge Status:</b> {st_text}"
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✏️ FB Cookie", callback_data="rate_edit_fb_cookie"), InlineKeyboardButton("✏️ FB 2FA", callback_data="rate_edit_fb_2fa"), InlineKeyboardButton("✏️ IG Cookie", callback_data="rate_edit_ig_cookie"), InlineKeyboardButton("✏️ IG 2FA", callback_data="rate_edit_ig_2fa")).add(InlineKeyboardButton("⚡ Quick Surge (+৳২)", callback_data="surge_3"), InlineKeyboardButton("🛑 Turn OFF Surge", callback_data="surge_off"))
        return bot.send_message(ADMIN_ID, msg, reply_markup=markup)

    elif text == "📂 ফাইল এক্সপোর্ট" and chat_id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("📄 FB Cookies", callback_data="exp_cat_FB Cookies"), InlineKeyboardButton("🔐 FB 2FA", callback_data="exp_cat_FB 2FA"), InlineKeyboardButton("📷 IG Cookies", callback_data="exp_cat_IG Cookies"), InlineKeyboardButton("🔐 IG 2FA", callback_data="exp_cat_IG 2FA"), InlineKeyboardButton("🌐 সব ক্যাটাগরি", callback_data="exp_cat_ALL"))
        return bot.send_message(ADMIN_ID, "📁 <b>[ফাইল এক্সপোর্ট সেন্টার]</b>\nধাপ ১: কোন ক্যাটাগরির ডাটা এক্সপোর্ট করবেন?", reply_markup=markup)

    elif text == "🤖 বায়ার রিপোর্ট অটো-ম্যাচার" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BUYER_REPORT'}
        return bot.send_message(ADMIN_ID, "🤖 <b>বায়ার রিপোর্ট অটো-ম্যাচার</b>\nবায়ার আপনাকে যে এক্সেল (.xlsx), সিএসভি (.csv) বা টেক্সট ফাইলটি দিয়েছে, তা এখানে সেন্ড করুন:", reply_markup=cancel_keyboard())

    elif text == "🧠 AI সিটেডেল অডিট" and chat_id == ADMIN_ID:
        logs = list(ai_logs_col.find().sort("timestamp", -1).limit(5))
        if not logs: return bot.send_message(ADMIN_ID, "🟢 <b>AI STATUS:</b> 100% HEALTHY\nকোনো এরর বা অটো-হিলিং লগ নেই।", reply_markup=admin_bottom_keyboard())
        msg = "🧠 <b>Recent AI Auto-Healing Logs:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for log in logs: msg += f"• <b>{log['timestamp']}</b>\n📌 {log['description']}\n🛠️ {log['action']}\n\n"
        return bot.send_message(ADMIN_ID, msg, reply_markup=admin_bottom_keyboard())

    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        return bot.send_message(ADMIN_ID, "📢 <b>ব্রডকাস্ট মেসেজটি লিখুন (ছবি বা ভিডিও যুক্ত করতে পারেন):</b>", reply_markup=cancel_keyboard())

    elif text == "👤 ইউজার ম্যানেজার" and chat_id == ADMIN_ID:
        total_u = users_col.count_documents({})
        banned_u = users_col.count_documents({"banned": True})
        msg = f"👥 <b>USER MANAGEMENT DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📊 সর্বমোট মেম্বার: <b>{total_u} জন</b>\n🟢 এক্টিভ ইউজার   : <b>{total_u - banned_u} জন</b>\n🔴 ব্যানড ইউজার    : <b>{banned_u} জন</b>"
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("🚫 ব্যান করুন", callback_data="admin_ban_user_prompt"), InlineKeyboardButton("🟢 আনব্যান করুন", callback_data="admin_unban_user_prompt"))
        return bot.send_message(ADMIN_ID, msg, reply_markup=markup)

    # --- Job Submission ---
    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        return bot.send_message(chat_id, "📦 <b>কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        return bot.send_message(chat_id, "📊 <b>.CSV বা .XLSX ফাইলটি এখানে পাঠালুন:</b>", reply_markup=cancel_keyboard())
    elif text == "⚙️ পাসওয়ার্ড নিয়ম":
        p_rule = get_setting("pass_rule", "20")
        custom_p = user.get("custom_password", "")
        return bot.send_message(chat_id, f"⚙️ <b>পাসওয়ার্ড নিয়মাবলী ও সেটিং:</b>\nআপনার সেভ করা পাসওয়ার্ড: {f'<code>{custom_p}</code>' if custom_p else '<i>কোনো ডিফল্ট পাসওয়ার্ড সেভ করা নেই</i>'}\n<i>(সিস্টেম অটো রুল: {p_rule})</i>", reply_markup=submit_tasks_keyboard())
    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie"
        if "FB 2FA" in text: cat = "fb_2fa"
        elif "IG Cookies" in text: cat = "ig_cookie"
        elif "IG 2FA" in text: cat = "ig_2fa"
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        return bot.send_message(chat_id, "🆔 <b>UID বা প্রোফাইল লিঙ্ক দিন:</b>", reply_markup=cancel_keyboard())

    # ================= DYNAMIC STATE PROCESSING =================
    state = user_states.get(chat_id)
    if not state:
        if message.text: return bot.send_message(chat_id, "নিচের মেনু থেকে সার্ভিস বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        all_users = list(users_col.find({"banned": False}))
        bot.send_message(ADMIN_ID, f"📢 <b>{len(all_users)}</b> জন ইউজারকে মেসেজ পাঠানো শুরু হচ্ছে...", reply_markup=admin_bottom_keyboard())
        success = 0
        for u in all_users:
            try:
                if message.photo: bot.send_photo(u["_id"], message.photo[-1].file_id, caption=text)
                elif message.video: bot.send_video(u["_id"], message.video.file_id, caption=text)
                elif message.animation: bot.send_animation(u["_id"], message.animation.file_id, caption=text)
                else: bot.send_message(u["_id"], text)
                success += 1
            except Exception: pass
        return bot.send_message(ADMIN_ID, f"✅ <b>ব্রডকাস্ট সফলভাবে {success} জনকে পাঠানো হয়েছে!</b>")

    elif step == 'AWAITING_SUPPORT_MSG':
        user_states.pop(chat_id, None)
        msg_txt = text if text else "Media/File Sent"
        ticket_id = f"TKT-{random.randint(1000,9999)}"
        bot.send_message(ADMIN_ID, f"🎫 <b>New Support Ticket: {ticket_id}</b>\n👤 User: <code>{chat_id}</code>\n📝 Message:\n{msg_txt}")
        return bot.send_message(chat_id, "✅ আপনার মেসেজ এডমিনের কাছে পাঠানো হয়েছে। খুব শীঘ্রই উত্তর দেওয়া হবে।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_WITHDRAW_DETAILS':
        user_states.pop(chat_id, None)
        bal = float(user.get("balance") or 0.0)
        try:
            bot.send_message(ADMIN_ID, f"💸 <b>Withdraw Request!</b>\n👤 User: <code>{chat_id}</code>\n💰 Current Bal: ৳{bal:.2f}\n📝 Details:\n{text}")
            bot.send_message(chat_id, "✅ আপনার উইথড্র রিকোয়েস্ট এডমিনের কাছে পাঠানো হয়েছে!", reply_markup=account_keyboard())
        except Exception: pass
        return

    elif step == 'AWAITING_EDIT_PAYLOAD':
        track_id = state.get('track_id')
        user_states.pop(chat_id, None)
        submissions_col.update_one({"track_id": track_id}, {"$set": {"payload": text}})
        return bot.send_message(chat_id, f"✅ <b>Track ID: {track_id}</b> এর তথ্য সফলভাবে আপডেট করা হয়েছে!", reply_markup=tasks_and_tools_keyboard())

    elif step == 'AWAITING_NEW_RATE' and chat_id == ADMIN_ID:
        cat_key = state.get('category_key')
        user_states.pop(chat_id, None)
        try:
            val = float(text)
            rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
            rates[cat_key] = val
            update_setting("rates", rates)
            return bot.send_message(ADMIN_ID, f"✅ <b>{cat_key}</b> এর নতুন রেট ৳{val} সেভ করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        except Exception: return bot.send_message(ADMIN_ID, "❌ ভুল সংখ্যা ফরম্যাট!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_BAN_USER_INPUT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        target = text.replace("@", "").strip()
        u = users_col.find_one({"$or": [{"_id": int(target) if target.isdigit() else 0}, {"username": target}]})
        if u:
            users_col.update_one({"_id": u["_id"]}, {"$set": {"banned": True}})
            return bot.send_message(ADMIN_ID, f"🚫 ইউজার <code>{u['_id']}</code> কে সফলভাবে ব্যান করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        return bot.send_message(ADMIN_ID, "❌ ইউজার খুঁজে পাওয়া যায়নি!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_UNBAN_USER_INPUT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        target = text.replace("@", "").strip()
        u = users_col.find_one({"$or": [{"_id": int(target) if target.isdigit() else 0}, {"username": target}]})
        if u:
            users_col.update_one({"_id": u["_id"]}, {"$set": {"banned": False}})
            return bot.send_message(ADMIN_ID, f"🟢 ইউজার <code>{u['_id']}</code> কে আনব্যান করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        return bot.send_message(ADMIN_ID, "❌ ইউজার খুঁজে পাওয়া যায়নি!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_2FA_GEN':
        user_states.pop(chat_id, None)
        try:
            totp = pyotp.TOTP(text.replace(" ", "").upper())
            return bot.send_message(chat_id, f"🔑 <b>2FA Code:</b> <code>{totp.now()}</code>", reply_markup=helper_tools_keyboard())
        except Exception: return bot.send_message(chat_id, "❌ ভুল 2FA Secret Key!", reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_FB_CHECK':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        live_list, dead_list = [], []
        for line in lines[:20]:
            uid = extract_numeric_uid(line)
            if uid:
                is_live, _ = check_live_account(uid)
                if is_live: live_list.append(uid)
                else: dead_list.append(uid)
        out = f"📊 <b>FACEBOOK BULK CHECK REPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n• মোট চেক: {len(lines)} টি\n🟢 <b>Live:</b> {len(live_list)} টি\n🔴 <b>Dead:</b> {len(dead_list)} টি\n\n🟢 <b>LIVE LIST:</b>\n"
        for l in live_list: out += f"<code>{l}</code>\n"
        return bot.send_message(chat_id, out, reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_IG_CHECK':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        live_list, dead_list = [], []
        for line in lines[:20]:
            is_live, _ = check_ig_username_live(line)
            if is_live: live_list.append(line)
            else: dead_list.append(line)
        out = f"📊 <b>INSTAGRAM BULK CHECK REPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n• মোট চেক: {len(lines)} টি\n🟢 <b>Live:</b> {len(live_list)} টি\n🔴 <b>Dead:</b> {len(dead_list)} টি\n\n🟢 <b>LIVE LIST:</b>\n"
        for l in live_list: out += f"<code>{l}</code>\n"
        return bot.send_message(chat_id, out, reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_TEXT':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        success_list, dup_list, total_earned = [], [], 0.0
        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
        password_to_use = user.get("custom_password") or get_setting("pass_rule", "20")

        for line in lines:
            uid = extract_numeric_uid(line)
            if not uid: continue
            if is_duplicate_uid(uid):
                dup_list.append(uid)
                continue
            p_hash = generate_payload_hash(line)
            if is_payload_blacklisted(p_hash): continue
            cat_key = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
            rate = float(get_current_task_rate(cat_key))
            track_id = generate_tracking_id()

            async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), uid, password_to_use, line])
            submissions_col.insert_one({
                "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                "password": password_to_use, "payload": line, "payload_hash": p_hash,
                "track_id": track_id, "category": "FB Cookies" if "cookie" in cat_key else "FB 2FA",
                "category_key": cat_key, "rate": rate, "status": "Hold", "date_str": now_str, "date_obj": get_bd_time()
            })
            success_list.append(uid); total_earned += rate
            
            # [LOG CHANNEL NOTIFICATION FIXED]
            try:
                bot.send_message(
                    LOG_CHANNEL_ID,
                    f"📥 <b>NEW SUBMISSION (Bulk Text)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 Track: <code>{track_id}</code>\n"
                    f"👤 Worker: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                    f"🆔 UID: <code>{uid}</code>\n"
                    f"📁 Cat: <b>{cat_key}</b>\n"
                    f"💰 Rate: ৳{rate:.2f}"
                )
            except Exception: pass

        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
        out = f"🎉 <b>বাল্ক সাবমিশন সম্পন্ন!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n✅ সফল: {len(success_list)} টি\n⚠️ স্কিপড/ডুপ্লিকেট: {len(dup_list)} টি\n💰 আর্ন (এসক্রো হোল্ড): ৳{total_earned:.2f}\n\n🟢 <b>ACCEPTED UID LIST:</b>\n"
        for s in success_list: out += f"<code>{s}</code>\n"
        return bot.send_message(chat_id, out, reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID!")
        cat = state.get('category', 'fb_cookie')
        state['uid'] = uid; state['step'] = 'AWAITING_SINGLE_DATA'
        prompt = "🍪 Cookies পেস্ট করুন:" if "cookie" in cat else "🔐 2FA Secret Key দিন:"
        return bot.send_message(chat_id, f"✅ Verified UID: <code>{uid}</code>\n\n{prompt}")

    elif step == 'AWAITING_SINGLE_DATA':
        cat, uid = state.get('category', 'fb_cookie'), state.get('uid')
        saved_pass = user.get("custom_password", "")

        if saved_pass:
            # Fast-track: Password already saved, process immediately
            user_states.pop(chat_id, None)
            now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
            p_hash = generate_payload_hash(text)
            if is_payload_blacklisted(p_hash): return bot.send_message(chat_id, "❌ ব্ল্যাকলিস্টেড ডাটা!", reply_markup=submit_tasks_keyboard())
            rate = float(get_current_task_rate(cat))
            track_id = generate_tracking_id()

            async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, saved_pass, text])
            submissions_col.insert_one({
                "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                "password": saved_pass, "payload": text, "payload_hash": p_hash,
                "track_id": track_id, "category": "FB Cookies" if "cookie" in cat else "FB 2FA",
                "category_key": cat, "rate": rate, "status": "Hold", "date_str": now_str, "date_obj": get_bd_time()
            })
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
            
            # [LOG CHANNEL NOTIFICATION FIXED]
            try:
                bot.send_message(
                    LOG_CHANNEL_ID,
                    f"📥 <b>NEW SUBMISSION (Single Fast-Track)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 Track: <code>{track_id}</code>\n"
                    f"👤 Worker: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                    f"🆔 UID: <code>{uid}</code>\n"
                    f"📁 Cat: <b>{cat}</b>\n"
                    f"💰 Rate: ৳{rate:.2f}"
                )
            except Exception: pass

            return bot.send_message(chat_id, f"🎉 <b>কাজ জমা সফল হয়েছে!</b>\n📌 Track ID: <code>{track_id}</code>\n💰 আর্ন (এসক্রো হোল্ড): ৳{rate:.2f}", reply_markup=submit_tasks_keyboard())
        else:
            # Prompt for manual password
            state['payload'] = text
            state['step'] = 'AWAITING_MANUAL_PASSWORD'
            return bot.send_message(chat_id, "🔑 <b>আপনার পাসওয়ার্ড দিন:</b>\n<i>(যেহেতু আপনার কোনো ডিফল্ট পাসওয়ার্ড সেভ করা নেই)</i>", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_MANUAL_PASSWORD':
        user_states.pop(chat_id, None)
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        payload = state.get('payload')
        manual_pass = text.strip()
        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")

        p_hash = generate_payload_hash(payload)
        if is_payload_blacklisted(p_hash): return bot.send_message(chat_id, "❌ ব্ল্যাকলিস্টেড ডাটা!", reply_markup=submit_tasks_keyboard())
        rate = float(get_current_task_rate(cat))
        track_id = generate_tracking_id()

        async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, manual_pass, payload])
        submissions_col.insert_one({
            "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
            "password": manual_pass, "payload": payload, "payload_hash": p_hash,
            "track_id": track_id, "category": "FB Cookies" if "cookie" in cat else "FB 2FA",
            "category_key": cat, "rate": rate, "status": "Hold", "date_str": now_str, "date_obj": get_bd_time()
        })
        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})

        # [LOG CHANNEL NOTIFICATION FIXED]
        try:
            bot.send_message(
                LOG_CHANNEL_ID,
                f"📥 <b>NEW SUBMISSION (Single Manual Pass)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Track: <code>{track_id}</code>\n"
                f"👤 Worker: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                f"🆔 UID: <code>{uid}</code>\n"
                f"📁 Cat: <b>{cat}</b>\n"
                f"💰 Rate: ৳{rate:.2f}"
            )
        except Exception: pass

        update_user_field(chat_id, "temp_pending_password", manual_pass)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💾 এই পাসওয়ার্ডটি ডিফল্ট হিসেবে সেভ করুন", callback_data="save_pass_default"))

        return bot.send_message(chat_id, f"🎉 <b>কাজ জমা সফল হয়েছে!</b>\n📌 Track ID: <code>{track_id}</code>\n🔑 পাসওয়ার্ড: <code>{manual_pass}</code>\n💰 আর্ন (এসক্রো হোল্ড): ৳{rate:.2f}", reply_markup=markup)

# ================= 9. Production Server Engine =================

if __name__ == "__main__":
    print("Zero-Bug Enterprise OEB NEXUS Engine Active...")
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"{render_url}/{TOKEN}")
            print(f"[WEBHOOK LIVE]: {render_url}/{TOKEN}")
        except Exception: pass
        flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    else:
        try: bot.remove_webhook()
        except Exception: pass
        threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000), daemon=True).start()
        bot.infinity_polling(skip_pending=True)