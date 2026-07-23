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

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

user_states = {}

# ================= 2. Sanitization & Helper Functions =================

def sanitize_html(text):
    if not text:
        return "Worker"
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
            "_id": chat_id,
            "username": "",
            "first_name": "Worker",
            "balance": 0.0,
            "hold_balance": 0.0,
            "banned": False,
            "ban_reason": "",
            "password": get_setting("pass_rule", "20"),
            "last_bonus_date": None,
            "joined_date": datetime.datetime.now(),
            "last_active": datetime.datetime.now()
        }
        users_col.insert_one(user)
    return user

def update_user_field(chat_id, field, value):
    users_col.update_one({"_id": chat_id}, {"$set": {field: value}}, upsert=True)

def is_user_banned(chat_id):
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
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            if "content=\"no-cache\"" in res.text or "The page you requested cannot be displayed" in res.text:
                return False, "Checkpoint/Dead"
            return True, "Live Account"
        return False, "Suspended/Dead"
    except Exception:
        return True, "Assumed Live"

def check_ig_username_live(username):
    try:
        clean_user = username.replace("@", "").strip()
        url = f"https://www.instagram.com/{clean_user}/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200 and "Page Not Found" not in res.text:
            return True, "Live Instagram Profile"
        return False, "Dead / Suspended"
    except Exception:
        return True, "Assumed Live"

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

# ================= 4. UI Keyboards (Reply & Inline) =================

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
    markup.add(KeyboardButton("📜 কাজের ইতিহাস"), KeyboardButton("📱 ইউজার-এজেন্ট"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def submit_tasks_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def category_bottom_keyboard():
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
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"))
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
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⏳ পেন্ডিং এপ্রুভাল (Manual)"), KeyboardButton("📊 টিম ও দৈনিক রিপোর্ট"))
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("📂 ফাইল এক্সপোর্ট"))
    markup.add(KeyboardButton("📢 ব্রডকাস্ট নোটিশ"), KeyboardButton("👤 ইউজার ম্যানেজার"))
    markup.add(KeyboardButton("🔙 প্রধান মেনু"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= 5. Background Daemon & Report Scheduler =================

def generate_daily_report_text(date_target=None):
    if not date_target:
        date_target = datetime.datetime.now()
    
    start_of_day = date_target.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = date_target.replace(hour=23, minute=59, second=59, microsecond=999)
    
    approved_list = list(submissions_col.find({
        "status": "Approved",
        "date_obj": {"$gte": start_of_day, "$lte": end_of_day}
    }))
    
    total_approved = len(approved_list)
    hold_count = submissions_col.count_documents({"status": "Hold", "date_obj": {"$gte": start_of_day, "$lte": end_of_day}})
    rejected_count = submissions_col.count_documents({"status": "Rejected", "date_obj": {"$gte": start_of_day, "$lte": end_of_day}})
    
    category_breakdown = {}
    total_payout = 0.0
    
    for sub in approved_list:
        cat = sub.get("category", "FB Cookies")
        rate = float(sub.get("rate", 0.0))
        total_payout += rate
        if cat not in category_breakdown:
            category_breakdown[cat] = {"count": 0, "amount": 0.0}
        category_breakdown[cat]["count"] += 1
        category_breakdown[cat]["amount"] += rate

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
    for cat, data in category_breakdown.items():
        report += f"• {cat} : {data['count']} টি (৳{data['amount']:.2f})\n"
    
    report += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return report

def escrow_daemon():
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
            print(f"Escrow Daemon Error: {e}")
        time.sleep(3600)

threading.Thread(target=escrow_daemon, daemon=True).start()

# ================= 6. Flask Webhook Server =================

flask_app = Flask(__name__)

@flask_app.route('/')
def flask_home():
    return "OEB NEXUS Production Engine Active!"

@flask_app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

# ================= 7. Core Command & Router Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if is_user_banned(chat_id):
        bot.reply_to(message, "🔴 <b>আপনার অ্যাকাউন্টটি স্থগিত (Banned) করা হয়েছে!</b>")
        return

    user = get_user_data(chat_id)
    if message.from_user.username:
        update_user_field(chat_id, "username", message.from_user.username)
    user_states.pop(chat_id, None)

    if not check_force_join(chat_id):
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
        markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
        bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)
        return

    bot.send_message(
        chat_id, 
        f"👑 <b>ONLINE EARNING BAZAR</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nস্বাগতম <b>{sanitize_html(message.from_user.first_name)}</b>! নিচের অপশন থেকে সার্ভিস নির্বাচন করুন:",
        reply_markup=main_bottom_keyboard(chat_id)
    )

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

    # --- 1-Tap Pending Approval Handlers ---
    elif code.startswith("appr_"):
        if chat_id != ADMIN_ID: return
        track_id = code.replace("appr_", "")
        sub = submissions_col.find_one({"track_id": track_id})
        if sub and sub.get("status") == "Hold":
            submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Approved"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": sub["rate"], "hold_balance": -sub["rate"]}})
            bot.edit_message_text(f"✅ <b>APPROVED</b> | Track ID: <code>{track_id}</code> | Amt: ৳{sub['rate']}", chat_id, call.message.message_id)
            try: bot.send_message(sub["chat_id"], f"🎉 আপনার সাবমিশন (<code>{track_id}</code>) এর জন্য ৳{sub['rate']:.2f} মেইন ব্যালেন্সে যুক্ত হয়েছে!")
            except Exception: pass

    elif code.startswith("rej_"):
        if chat_id != ADMIN_ID: return
        track_id = code.replace("rej_", "")
        sub = submissions_col.find_one({"track_id": track_id})
        if sub and sub.get("status") == "Hold":
            submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -sub["rate"]}})
            bot.edit_message_text(f"❌ <b>REJECTED</b> | Track ID: <code>{track_id}</code>", chat_id, call.message.message_id)
            try: bot.send_message(sub["chat_id"], f"❌ আপনার সাবমিশন (<code>{track_id}</code>) বাতিল করা হয়েছে।")
            except Exception: pass

    elif code == "appr_all_pending" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}))
        count = 0
        for sub in pending_subs:
            submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": sub["rate"], "hold_balance": -sub["rate"]}})
            count += 1
            try: bot.send_message(sub["chat_id"], f"🎉 আপনার সাবমিশন (<code>{sub['track_id']}</code>) এপ্রুভ হয়েছে!")
            except Exception: pass
        bot.send_message(ADMIN_ID, f"⚡ <b>{count} টি পেন্ডিং সাবমিশন সফলভাবে এপ্রুভ করা হয়েছে!</b>")

    # --- Worker Edit Submission Handler ---
    elif code.startswith("edit_sub_"):
        track_id = code.replace("edit_sub_", "")
        sub = submissions_col.find_one({"track_id": track_id, "chat_id": chat_id, "status": "Hold"})
        if not sub:
            bot.send_message(chat_id, "⚠️ এই কাজটির এডিট মেয়াদ শেষ হয়ে গেছে বা ইতিমধ্যেই প্রসেস করা হয়েছে।")
            return
        user_states[chat_id] = {'step': 'AWAITING_EDIT_PAYLOAD', 'track_id': track_id}
        bot.send_message(chat_id, f"✏️ <b>Track ID: {track_id}</b> এর জন্য সঠিক Cookies বা 2FA Key এখানে পেস্ট করুন:", reply_markup=cancel_keyboard())

    # --- OTP Checker Handler ---
    elif code.startswith("check_otp_"):
        email = code.replace("check_otp_", "")
        user_name, domain = email.split("@")
        try:
            res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={user_name}&domain={domain}").json()
            if not res:
                bot.send_message(chat_id, "📭 ইনবক্সে এখনো কোনো বার্তা আসেনি! ২-১ সেকেন্ড পর আবার চেষ্টা করুন।")
            else:
                msg_id = res[0]['id']
                msg_detail = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={user_name}&domain={domain}&id={msg_id}").json()
                body = msg_detail.get('textBody', '')
                otp_match = re.search(r'\b(\d{5,6})\b', body)
                otp_code = otp_match.group(1) if otp_match else "কোড পাওয়া যায়নি"
                bot.send_message(chat_id, f"✉️ <b>OTP/Message Received!</b>\n\n🔑 Code: <code>{otp_code}</code>\n\n📄 <b>Message:</b>\n{sanitize_html(body[:300])}")
        except Exception:
            bot.send_message(chat_id, "⚠️ ওটিপি চেক করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

    # --- Name Generator Handlers ---
    elif code.startswith("gen_names_"):
        cat = code.replace("gen_names_", "")
        names_db = {
            "bd_male": ["Sakib Hasan", "Tanvir Ahmed", "Rahim Uddin", "Rakibul Islam", "Nayeem Khan", "Arman Hossain", "Sabbir Rahman", "Mehedi Hasan", "Ariful Islam", "Fahim Shahriar"],
            "bd_female": ["Nusrat Jahan", "Riya Sultana", "Sadia Islam", "Farhana Akter", "Mim Chowdhury", "Tanjila Akter", "Ayesha Siddika", "Sumaiya Khan", "Sabrina Yesmin", "Priya Das"],
            "usa_male": ["James Smith", "John Johnson", "Robert Williams", "Michael Brown", "William Jones", "David Garcia", "Richard Miller", "Joseph Rodriguez", "Thomas Martinez", "Charles Hernandez"],
            "usa_female": ["Mary Smith", "Patricia Johnson", "Jennifer Williams", "Linda Brown", "Elizabeth Barbara", "Susan Miller", "Jessica Taylor", "Sarah Anderson", "Karen Thomas", "Lisa Jackson"]
        }
        selected = names_db.get(cat, names_db["bd_male"])
        out = f"👤 <b>১-ক্লিক কপি করার নাম তালিকা:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for name in selected:
            out += f"<code>{name}</code>\n"
        bot.send_message(chat_id, out)

    # --- User Agent Generator Handlers ---
    elif code.startswith("gen_ua_"):
        cat = code.replace("gen_ua_", "")
        ua_db = {
            "android": [
                "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
                "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Mobile Safari/537.36",
                "Mozilla/5.0 (Linux; Android 11; M2007J20CG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36"
            ],
            "iphone": [
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ],
            "pc": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
            ]
        }
        selected = ua_db.get(cat, ua_db["android"])
        out = "📱 <b>কপি করার জন্য User-Agent স্ট্রিং:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for ua in selected:
            out += f"<code>{ua}</code>\n\n"
        bot.send_message(chat_id, out)

    # --- Leaderboard Tab Handlers ---
    elif code.startswith("lb_"):
        tf = code.replace("lb_", "")
        now = datetime.datetime.now()
        if tf == "daily":
            query = {"date_str": {"$regex": f"^{now.strftime('%Y-%m-%d')}"}}
            title = "আজকের সেরা"
        elif tf == "weekly":
            cutoff = now - timedelta(days=7)
            query = {"date_obj": {"$gte": cutoff}}
            title = "এই সপ্তাহের সেরা"
        else:
            query = {}
            title = "সর্বকালের সেরা"

        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$worker_name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        top = list(submissions_col.aggregate(pipeline))
        out = f"🏆 <b>লিডারবোর্ড - {title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, item in enumerate(top):
            out += f"{badges[i]} <b>{sanitize_html(item['_id'])}</b> — {item['count']} টি\n"
        
        user_cnt = submissions_col.count_documents({"chat_id": chat_id})
        out += f"\n🎯 <b>আপনার মোট জমা:</b> <code>{user_cnt}</code> টি"
        
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"),
            InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"),
            InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime")
        )
        bot.edit_message_text(out, chat_id, call.message.message_id, reply_markup=markup)

    # --- Admin Surge Handlers ---
    elif code.startswith("surge_"):
        if chat_id != ADMIN_ID: return
        act = code.replace("surge_", "")
        if act == "off":
            update_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
            bot.send_message(ADMIN_ID, "🛑 <b>সার্জ বোনাস সফলভাবে বন্ধ করা হয়েছে।</b>")
        else:
            hrs = int(act)
            exp = datetime.datetime.now() + timedelta(hours=hrs)
            update_setting("surge_pricing", {"active": True, "bonus": 2.0, "expires_at": exp})
            bot.send_message(ADMIN_ID, f"⚡ <b>+৳২.০০ সার্জ বোনাস {hrs} ঘণ্টার জন্য চালু করা হয়েছে!</b>")

    # --- Admin Rate Edit Handlers ---
    elif code.startswith("rate_edit_"):
        if chat_id != ADMIN_ID: return
        cat_key = code.replace("rate_edit_", "")
        user_states[chat_id] = {'step': 'AWAITING_NEW_RATE', 'category_key': cat_key}
        bot.send_message(ADMIN_ID, f"✏️ <b>{cat_key}</b> এর নতুন মূল্য লিখুন (যেমন: 6.5):", reply_markup=cancel_keyboard())

    # --- Admin User Manager Handlers ---
    elif code == "admin_ban_user_prompt" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BAN_USER_INPUT'}
        bot.send_message(ADMIN_ID, "🚫 ব্যান করার জন্য ইউজারের <b>Telegram ID</b> বা <b>Username</b> পাঠান:", reply_markup=cancel_keyboard())

    elif code == "admin_unban_user_prompt" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_UNBAN_USER_INPUT'}
        bot.send_message(ADMIN_ID, "🟢 আনব্যান করার জন্য ইউজারের <b>Telegram ID</b> বা <b>Username</b> পাঠান:", reply_markup=cancel_keyboard())

# ================= 8. Text Input Router & Dynamic Workflows =================

@bot.message_handler(content_types=['document'])
def handle_excel_document(message):
    chat_id = message.chat.id
    if is_user_banned(chat_id): return
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
                uid, password, payload = None, get_setting("pass_rule", "20"), None
                
                for v in vals:
                    if not uid and extract_numeric_uid(v):
                        uid = extract_numeric_uid(v)
                    elif is_valid_cookies(v) or len(v) > 20:
                        payload = v

                if uid and payload:
                    if is_duplicate_uid(uid): continue
                    p_hash = generate_payload_hash(payload)
                    if is_payload_blacklisted(p_hash): continue

                    cat_key = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                    rate = get_current_task_rate(cat_key)
                    track_id = generate_tracking_id()

                    async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), uid, password, payload])
                    submissions_col.insert_one({
                        "chat_id": chat_id,
                        "worker_name": sanitize_html(message.from_user.first_name),
                        "uid": uid,
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
                    success_count += 1
                    total_earned += rate

            if os.path.exists(file_name): os.remove(file_name)

            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
            user_states.pop(chat_id, None)
            bot.reply_to(message, f"🎉 <b>স্মার্ট ফাইল প্রসেস সম্পন্ন!</b>\n\n✅ সফল: <b>{success_count}</b> টি\n💰 আর্ন (এসক্রো হোল্ড): ৳{total_earned:.2f}", reply_markup=submit_tasks_keyboard())
        except Exception as e:
            bot.reply_to(message, f"❌ ফাইল পড়তে সমস্যা হয়েছে: {e}", reply_markup=submit_tasks_keyboard())

@bot.message_handler(func=lambda msg: True)
def main_router(message):
    chat_id = message.chat.id
    if is_user_banned(chat_id): return

    text = message.text.strip() if message.text else ""
    user = get_user_data(chat_id)

    nav_buttons = [
        "🔙 প্রধান মেনু", "❌ বাতিল করুন", "💼 টাস্ক ও টুলস", "📋 কাজ জমা দিন", 
        "🛠 হেল্পার টুলস", "📌 সিঙ্গেল জমা", "👤 আমার অ্যাকাউন্ট", "🎁 বোনাস ও সাপোর্ট", 
        "👑 এডমিন প্যানেল", "💳 Withdraw", "🪪 ভেরিফাইড আইডি কার্ড", "🎁 Claim Daily Bonus", 
        "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", 
        "⚙️ পাসওয়ার্ড নিয়ম", "🔑 2FA কোড জেনারেটর", "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", 
        "✉️ টেম্প ইমেইল", "👤 র্যান্ডম নাম জেনারেটর", "📜 কাজের ইতিহাস", "📱 ইউজার-এজেন্ট", "👤 ইউজার ম্যানেজার"
    ]
    if text in nav_buttons:
        user_states.pop(chat_id, None)

    if text in ["🔙 প্রধান মেনু", "❌ বাতিল করুন"]:
        bot.send_message(chat_id, "🏠 <b>প্রধান মেনু:</b>", reply_markup=main_bottom_keyboard(chat_id))
        return

    # --- Menu Navigation Routes ---
    if text == "💼 টাস্ক ও টুলস":
        bot.send_message(chat_id, "💼 <b>টাস্ক ও টুলস সেকশনে স্বাগতম:</b>", reply_markup=tasks_and_tools_keyboard())
        return

    elif text == "📋 কাজ জমা দিন":
        bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ বেছে নিন:</b>", reply_markup=submit_tasks_keyboard())
        return

    elif text == "🛠 হেল্পার টুলস":
        bot.send_message(chat_id, "🛠 <b>আপনার প্রয়োজনীয় টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
        return

    elif text == "📌 সিঙ্গেল জমা":
        bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard())
        return

    elif text == "👤 আমার অ্যাকাউন্ট":
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = user.get("balance", 0.0)
        hold_bal = user.get("hold_balance", 0.0)
        safe_name = sanitize_html(message.from_user.first_name)
        
        msg_str = (
            f"👤 <b>নাম:</b> <code>{safe_name}</code>\n"
            f"📊 <b>মোট কাজ:</b> <code>{cnt}</code> টি\n"
            f"💰 <b>মেইন ব্যালেন্স:</b> <code>৳{bal:.2f}</code>\n"
            f"⏳ <b>এসক্রো হোল্ড:</b> <code>৳{hold_bal:.2f}</code>\n"
            f"🔗 <b>রেফারেল লিঙ্ক:</b> https://t.me/{BOT_USERNAME}?start={chat_id}"
        )
        bot.send_message(chat_id, msg_str, reply_markup=account_keyboard())
        return

    elif text == "🎁 বোনাস ও সাপোর্ট":
        bot.send_message(chat_id, "🎁 <b>বোনাস ও সাপোর্ট সেন্টার:</b>", reply_markup=bonus_support_keyboard())
        return

    elif text == "👑 এডমিন প্যানেল" and chat_id == ADMIN_ID:
        bot.send_message(chat_id, "👑 <b>এডমিন প্যানেল</b>", reply_markup=admin_bottom_keyboard())
        return

    # --- Helper Tools Routes ---
    elif text == "📜 কাজের ইতিহাস":
        subs = list(submissions_col.find({"chat_id": chat_id}).sort("date_obj", -1).limit(5))
        if not subs:
            bot.send_message(chat_id, "📭 আপনি এখনো কোনো কাজ জমা দেননি!", reply_markup=tasks_and_tools_keyboard())
            return
        out = "📜 <b>আপনার সর্বশেষ জমার ইতিহাস:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        markup = InlineKeyboardMarkup()
        for sub in subs:
            st = sub.get("status")
            st_icon = "⏳ [HOLD]" if st == "Hold" else ("✅ [APPROVED]" if st == "Approved" else "❌ [REJECTED]")
            out += f"{st_icon} <code>{sub['track_id']}</code> | <b>{sub['category']}</b> | ৳{sub['rate']}\n"
            if st == "Hold":
                markup.add(InlineKeyboardButton(f"✏️ এডিট {sub['track_id']}", callback_data=f"edit_sub_{sub['track_id']}"))
        bot.send_message(chat_id, out, reply_markup=markup)
        return

    elif text == "📱 ইউজার-এজেন্ট":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("📱 Android Chrome", callback_data="gen_ua_android"),
            InlineKeyboardButton("🍎 iPhone Safari", callback_data="gen_ua_iphone"),
            InlineKeyboardButton("💻 Windows PC Chrome", callback_data="gen_ua_pc")
        )
        bot.send_message(chat_id, "📱 <b>ইউজার-এজেন্ট ক্যাটাগরি বেছে নিন:</b>", reply_markup=markup)
        return

    elif text == "👤 র্যান্ডম নাম জেনারেটর":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🇧🇩 BD Male", callback_data="gen_names_bd_male"),
            InlineKeyboardButton("🇧🇩 BD Female", callback_data="gen_names_bd_female"),
            InlineKeyboardButton("🇺🇸 USA Male", callback_data="gen_names_usa_male"),
            InlineKeyboardButton("🇺🇸 USA Female", callback_data="gen_names_usa_female")
        )
        bot.send_message(chat_id, "👤 <b>যে ক্যাটাগরির নাম চান সিলেক্ট করুন:</b>", reply_markup=markup)
        return

    elif text == "✉️ টেম্প ইমেইল":
        rand_str = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
        email = f"{rand_str}@1secmail.com"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📩 ইনবক্স / ওটিপি দেখুন", callback_data=f"check_otp_{email}"))
        bot.send_message(chat_id, f"✉️ <b>Temp Email Generated:</b>\n<code>{email}</code>\n\n<i>ওটিপি পাঠানোর পর নিচের বাটনে চাপ দিন।</i>", reply_markup=markup)
        return

    elif text == "🚀 বাল্ক FB লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
        bot.send_message(chat_id, "🔍 <b>একসাথে ফেসবুক UID গুলোর লিস্ট পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "🚀 বাল্ক IG লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_IG_CHECK'}
        bot.send_message(chat_id, "🔍 <b>একসাথে ইনস্টাগ্রাম ইউজারনেমগুলোর লিস্ট পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "🔑 <b>2FA Secret Key পাঠান:</b>", reply_markup=cancel_keyboard())
        return

    # --- Bonus & Account Routes ---
    elif text == "🎁 Claim Daily Bonus":
        last_bonus = user.get("last_bonus_date")
        now = datetime.datetime.now()
        if last_bonus and (now - last_bonus) < timedelta(hours=24):
            bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টার মধ্যে একবারই বোনাস নেওয়া যায়!", reply_markup=bonus_support_keyboard())
        else:
            update_user_field(chat_id, "balance", user.get("balance", 0.0) + 2.0)
            update_user_field(chat_id, "last_bonus_date", now)
            bot.send_message(chat_id, "🎉 আপনি ৳২.০০ বোনাস পেয়েছেন!", reply_markup=bonus_support_keyboard())
        return

    elif text == "🏆 লিডারবোর্ড":
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"),
            InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"),
            InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime")
        )
        bot.send_message(chat_id, "🏆 <b>লিডারবোর্ড ফিল্টার বেছে নিন:</b>", reply_markup=markup)
        return

    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        bot.send_message(chat_id, "💬 <b>আপনার বার্তাটি লিখুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "💳 Withdraw":
        bal = user.get("balance", 0.0)
        if bal < 50.0:
            bot.send_message(chat_id, f"⚠️ সর্বনিম্ন উইথড্র ৳৫০.০০। ব্যালেন্স: ৳{bal:.2f}", reply_markup=account_keyboard())
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নাম্বার ও পরিমাণ লিখুন (যেমন: <code>01700000000 | 100</code>):", reply_markup=cancel_keyboard())
        return

    elif text == "🪪 ভেরিফাইড আইডি কার্ড":
        safe_name = sanitize_html(message.from_user.first_name)
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        buf = generate_worker_badge_image_py(chat_id, safe_name, cnt)
        bot.send_photo(chat_id, buf, caption="🪪 <b>আপনার ভেরিফাইড আইডি কার্ড!</b>", reply_markup=account_keyboard())
        return

    # --- Admin Routes ---
    elif text == "⏳ পেন্ডিং এপ্রুভাল (Manual)" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}).limit(5))
        if not pending_subs:
            bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং সাবমিশন নেই!", reply_markup=admin_bottom_keyboard())
            return
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("⚡ Approve All Current Pending", callback_data="appr_all_pending"))
        
        bot.send_message(ADMIN_ID, f"⏳ <b>সর্বমোট পেন্ডিং সাবমিশন পর্যালোচনা:</b>", reply_markup=markup)
        for sub in pending_subs:
            item_markup = InlineKeyboardMarkup(row_width=2)
            item_markup.add(
                InlineKeyboardButton("✅ Approve", callback_data=f"appr_{sub['track_id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"rej_{sub['track_id']}")
            )
            msg = (
                f"📌 Track ID: <code>{sub['track_id']}</code>\n"
                f"👤 Worker ID: <code>{sub['chat_id']}</code>\n"
                f"🆔 UID: <code>{sub['uid']}</code>\n"
                f"💰 Rate: ৳{sub['rate']}"
            )
            bot.send_message(ADMIN_ID, msg, reply_markup=item_markup)
        return

    elif text == "📊 টিম ও দৈনিক রিপোর্ট" and chat_id == ADMIN_ID:
        report = generate_daily_report_text()
        bot.send_message(ADMIN_ID, report, reply_markup=admin_bottom_keyboard())
        return

    elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
        rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
        surge = get_setting("surge_pricing", {"active": False, "bonus": 0.0})
        st_text = f"⚡ ACTIVE (+৳{surge['bonus']})" if surge.get('active') else "🔴 INACTIVE"
        
        msg = (
            f"⚙️ <b>CURRENT RATES & SURGE DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 FB Cookie : ৳{rates['fb_cookie']}\n"
            f"🔐 FB 2FA    : ৳{rates['fb_2fa']}\n"
            f"📷 IG Cookie : ৳{rates['ig_cookie']}\n"
            f"🔐 IG 2FA    : ৳{rates['ig_2fa']}\n\n"
            f"⚡ <b>Surge Status:</b> {st_text}"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✏️ FB Cookie", callback_data="rate_edit_fb_cookie"),
            InlineKeyboardButton("✏️ FB 2FA", callback_data="rate_edit_fb_2fa"),
            InlineKeyboardButton("✏️ IG Cookie", callback_data="rate_edit_ig_cookie"),
            InlineKeyboardButton("✏️ IG 2FA", callback_data="rate_edit_ig_2fa")
        )
        markup.add(
            InlineKeyboardButton("⚡ Quick Surge (+৳২)", callback_data="surge_3"),
            InlineKeyboardButton("🛑 Turn OFF Surge", callback_data="surge_off")
        )
        bot.send_message(ADMIN_ID, msg, reply_markup=markup)
        return

    elif text == "📂 ফাইল এক্সপোর্ট" and chat_id == ADMIN_ID:
        subs = list(submissions_col.find({"status": "Approved"}))
        if not subs:
            bot.send_message(ADMIN_ID, "📭 এক্সপোর্ট করার জন্য কোনো অনুমোদিত ডাটা পাওয়া যায়নি।")
            return
        content = "\n".join([s.get("payload", "") for s in subs if s.get("payload")])
        file_name = "Approved_Export.txt"
        with open(file_name, "w", encoding="utf-8") as f: f.write(content)
        with open(file_name, "rb") as f: bot.send_document(ADMIN_ID, f, caption="📂 <b>এক্সপোর্ট ফাইল প্রস্তুত!</b>")
        if os.path.exists(file_name): os.remove(file_name)
        return

    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        bot.send_message(ADMIN_ID, "📢 <b>ব্রডকাস্ট মেসেজটি লিখুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "👤 ইউজার ম্যানেজার" and chat_id == ADMIN_ID:
        total_u = users_col.count_documents({})
        banned_u = users_col.count_documents({"banned": True})
        msg = (
            f"👥 <b>USER MANAGEMENT DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 সর্বমোট মেম্বার: <b>{total_u} জন</b>\n"
            f"🟢 এক্টিভ ইউজার   : <b>{total_u - banned_u} জন</b>\n"
            f"🔴 ব্যানড ইউজার    : <b>{banned_u} জন</b>"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🚫 ব্যান করুন", callback_data="admin_ban_user_prompt"),
            InlineKeyboardButton("🟢 আনব্যান করুন", callback_data="admin_unban_user_prompt")
        )
        bot.send_message(ADMIN_ID, msg, reply_markup=markup)
        return

    # --- Submissions & Multi-Step Handlers ---
    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        bot.send_message(chat_id, "📦 <b>কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        bot.send_message(chat_id, "📊 <b>.CSV বা .XLSX ফাইলটি এখানে পাঠালুন:</b>", reply_markup=cancel_keyboard())
        return

    elif text == "⚙️ পাসওয়ার্ড নিয়ম":
        p_rule = get_setting("pass_rule", "20")
        bot.send_message(chat_id, f"⚙️ <b>পাসওয়ার্ড নিয়মাবলী:</b>\nডিফল্ট সেভ পাসওয়ার্ড: <code>{p_rule}</code>", reply_markup=submit_tasks_keyboard())
        return

    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie"
        if "FB 2FA" in text: cat = "fb_2fa"
        elif "IG Cookies" in text: cat = "ig_cookie"
        elif "IG 2FA" in text: cat = "ig_2fa"
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        bot.send_message(chat_id, "🆔 <b>UID বা প্রোফাইল লিঙ্ক দিন:</b>", reply_markup=cancel_keyboard())
        return

    # --- Dynamic State Multi-Step Input Processing ---
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "নিচের মেনু থেকে সার্ভিস বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_EDIT_PAYLOAD':
        track_id = state.get('track_id')
        user_states.pop(chat_id, None)
        submissions_col.update_one({"track_id": track_id}, {"$set": {"payload": text}})
        bot.send_message(chat_id, f"✅ <b>Track ID: {track_id}</b> এর তথ্য সফলভাবে আপডেট করা হয়েছে!", reply_markup=tasks_and_tools_keyboard())

    elif step == 'AWAITING_NEW_RATE' and chat_id == ADMIN_ID:
        cat_key = state.get('category_key')
        user_states.pop(chat_id, None)
        try:
            val = float(text)
            rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
            rates[cat_key] = val
            update_setting("rates", rates)
            bot.send_message(ADMIN_ID, f"✅ <b>{cat_key}</b> এর নতুন রেট ৳{val} সেভ করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        except Exception:
            bot.send_message(ADMIN_ID, "❌ ভুল সংখ্যা ফরম্যাট!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_BAN_USER_INPUT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        target = text.replace("@", "").strip()
        u = users_col.find_one({"$or": [{"_id": int(target) if target.isdigit() else 0}, {"username": target}]})
        if u:
            users_col.update_one({"_id": u["_id"]}, {"$set": {"banned": True}})
            bot.send_message(ADMIN_ID, f"🚫 ইউজার <code>{u['_id']}</code> কে সফলভাবে ব্যান করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        else:
            bot.send_message(ADMIN_ID, "❌ ইউজার খুঁজে পাওয়া যায়নি!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_UNBAN_USER_INPUT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        target = text.replace("@", "").strip()
        u = users_col.find_one({"$or": [{"_id": int(target) if target.isdigit() else 0}, {"username": target}]})
        if u:
            users_col.update_one({"_id": u["_id"]}, {"$set": {"banned": False}})
            bot.send_message(ADMIN_ID, f"🟢 ইউজার <code>{u['_id']}</code> কে আনব্যান করা হয়েছে!", reply_markup=admin_bottom_keyboard())
        else:
            bot.send_message(ADMIN_ID, "❌ ইউজার খুঁজে পাওয়া যায়নি!", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_2FA_GEN':
        user_states.pop(chat_id, None)
        try:
            totp = pyotp.TOTP(text.replace(" ", "").upper())
            bot.send_message(chat_id, f"🔑 <b>2FA Code:</b> <code>{totp.now()}</code>", reply_markup=helper_tools_keyboard())
        except Exception:
            bot.send_message(chat_id, "❌ ভুল 2FA Secret Key!", reply_markup=helper_tools_keyboard())

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
        bot.send_message(chat_id, out, reply_markup=helper_tools_keyboard())

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
        bot.send_message(chat_id, out, reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_TEXT':
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        success_list, dup_list, total_earned = [], [], 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for line in lines:
            uid = extract_numeric_uid(line)
            if not uid: continue
            if is_duplicate_uid(uid):
                dup_list.append(uid)
                continue
            p_hash = generate_payload_hash(line)
            if is_payload_blacklisted(p_hash): continue

            cat_key = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
            rate = get_current_task_rate(cat_key)
            track_id = generate_tracking_id()

            async_save_to_sheet("Cookies_Data" if "cookie" in cat_key else "2FA_Data", [now_str, track_id, str(chat_id), uid, user.get("password", "20"), line])
            submissions_col.insert_one({
                "chat_id": chat_id,
                "worker_name": sanitize_html(message.from_user.first_name),
                "uid": uid,
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
            success_list.append(uid)
            total_earned += rate

        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
        user_states.pop(chat_id, None)

        out = f"🎉 <b>বাল্ক সাবমিশন সম্পন্ন!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n✅ সফল: {len(success_list)} টি\n⚠️ স্কিপড/ডুপ্লিকেট: {len(dup_list)} টি\n💰 আর্ন (এসক্রো হোল্ড): ৳{total_earned:.2f}\n\n🟢 <b>ACCEPTED UID LIST:</b>\n"
        for s in success_list: out += f"<code>{s}</code>\n"
        bot.send_message(chat_id, out, reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid):
            bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID!")
            return
        cat = state.get('category', 'fb_cookie')
        state['uid'] = uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        prompt = "🍪 Cookies পেস্ট করুন:" if "cookie" in cat else "🔐 2FA Secret Key দিন:"
        bot.send_message(chat_id, f"✅ Verified UID: <code>{uid}</code>\n\n{prompt}")

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        p_hash = generate_payload_hash(text)
        if is_payload_blacklisted(p_hash):
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "❌ ব্ল্যাকলিস্টেড ডাটা!", reply_markup=submit_tasks_keyboard())
            return

        rate = get_current_task_rate(cat)
        track_id = generate_tracking_id()

        async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, user.get("password", "20"), text])
        submissions_col.insert_one({
            "chat_id": chat_id,
            "worker_name": sanitize_html(message.from_user.first_name),
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
        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"🎉 <b>কাজ জমা সফল হয়েছে!</b>\n📌 Track ID: <code>{track_id}</code>\n💰 আর্ন (এসক্রো হোল্ড): ৳{rate:.2f}", reply_markup=submit_tasks_keyboard())

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
        except Exception as e:
            print(f"[Webhook Error]: {e}")
        port = int(os.environ.get("PORT", 10000))
        flask_app.run(host="0.0.0.0", port=port)
    else:
        try: bot.remove_webhook()
        except Exception: pass
        threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000), daemon=True).start()
        print("[LOCAL POLLING ENGINE STARTED]...")
        bot.infinity_polling(skip_pending=True)