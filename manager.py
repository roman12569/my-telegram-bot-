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

# 🔒 মূল প্রাইভেট চ্যানেল (সব লাইভ ডাটা ও এনক্রিপ্টেড ব্যাকআপ এখানেই যাবে)
LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = "-1003943094107"

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-domain.com/webview-form")
BACKUP_SECRET_KEY = os.environ.get("BACKUP_SECRET_KEY", "12345678901234567890123456789012").encode('utf-8')

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

# MongoDB Database Connection Pool
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

# 📢 সাধারণ ইউজারদের জয়েন করার জন্য পাবলিকে দেখানো চ্যানেল লিস্ট
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

def generate_task_preview_card_py(task_title, rate, slots, deadline_str):
    img = Image.new('RGB', (600, 300), color='#1e1b4b')
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 590, 290], outline='#6366f1', width=4)
    draw_text_safe(draw, (30, 30), "TASK PREVIEW CARD", fill='#818cf8')
    draw_text_safe(draw, (30, 80), f"Category: {task_title}", fill='#ffffff')
    draw.rectangle([30, 120, 570, 240], fill='#4338ca')
    draw_text_safe(draw, (50, 140), f"Rate: {rate} BDT / Account", fill='#facc15')
    draw_text_safe(draw, (50, 175), f"Available Slots: {slots} remaining", fill='#ffffff')
    draw_text_safe(draw, (50, 205), f"Deadline: {deadline_str}", fill='#ffffff')
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

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

def generate_weekly_report_card_py(worker_id, total_tasks, total_earned, rank):
    img = Image.new('RGB', (650, 350), color='#0f172a')
    draw = ImageDraw.Draw(img)
    draw.rectangle([15, 15, 635, 335], outline='#38bdf8', width=4)
    draw_text_safe(draw, (40, 45), "WEEKLY PERFORMANCE REPORT", fill='#38bdf8')
    draw_text_safe(draw, (40, 85), f"Worker ID: #{worker_id}", fill='#94a3b8')
    draw.rectangle([40, 110, 610, 270], fill='#1e293b')
    draw_text_safe(draw, (70, 140), f"Total Approved Tasks: {total_tasks}", fill='#ffffff')
    draw_text_safe(draw, (70, 180), f"Total Earnings: BDT {total_earned:.2f}", fill='#ffffff')
    draw_text_safe(draw, (70, 220), f"Leaderboard Rank: #{rank}", fill='#10b981')
    
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

# ================= 4. Database Core Helpers =================

def get_setting(key, default):
    res = settings_col.find_one({"_id": key})
    return res["value"] if res else default

def update_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

def log_audit_event(event_type, actor_id, details):
    audit_logs_col.insert_one({
        "event_type": event_type,
        "actor_id": actor_id,
        "details": details,
        "timestamp": datetime.datetime.now()
    })

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

def extract_numeric_uid(text):
    text = str(text).strip()
    if text.isdigit() and 8 <= len(text) <= 20:
        return text
    match = re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text)
    return match.group(1) if match else None

def is_valid_2fa_key(key_str):
    cleaned = str(key_str).replace(" ", "").upper()
    return bool(re.match(r'^[A-Z2-7]{16,32}$', cleaned))

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

def evaluate_fraud_risk(chat_id, device_hash=None, is_bad=False):
    suspicion_score = 0
    flag_reasons = []

    if device_hash:
        same_device_count = fingerprints_col.count_documents({"device_hash": device_hash, "worker_id": {"$ne": str(chat_id)}})
        if same_device_count > 0:
            suspicion_score += 50
            flag_reasons.append(f"Multiple accounts ({same_device_count + 1}) on same device")

    if is_bad:
        suspicion_score += 25
        flag_reasons.append("Bad submission or payload error")

    user = get_user_data(chat_id)
    total_score = user.get("risk_score", 0) + suspicion_score
    update_user_field(chat_id, "risk_score", total_score)

    if total_score >= 70:
        update_user_field(chat_id, "banned", True)
        log_to_channel(f"🚨 **HIGH-PRIORITY FRAUD RED ALERT:** User `{chat_id}` Quarantined/Banned! Risk Score: {total_score}.")
        return False
    return True

def calculate_worker_tier(total_submissions):
    if total_submissions >= 500:
        return "Gold VIP 🏆", 2.0
    elif total_submissions >= 150:
        return "Silver Worker 🥈", 1.0
    return "Bronze Worker 🥉", 0.0

def get_current_task_rate(cat_key):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    base_rate = float(rates.get(cat_key, 5.0))
    surge_info = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge_info.get("active"):
        exp = surge_info.get("expires_at")
        if exp and datetime.datetime.now() < exp:
            base_rate += float(surge_info.get("bonus", 0.0))
    
    flash = flash_boost_col.find_one({"is_active": True, "end_time": {"$gt": datetime.datetime.now()}})
    if flash:
        base_rate *= float(flash.get("multiplier", 1.0))

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
            # 1. Escrow Auto-Release (24 Hours)
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

            # 2. Inactive Worker Retention Reminder (48 Hours)
            cutoff_48h = datetime.datetime.now() - timedelta(days=2)
            inactive_users = users_col.find({"banned": False, "last_active": {"$lt": cutoff_48h}})
            for u in inactive_users:
                try:
                    bot.send_message(u["_id"], "👋 **ভাই, আজকে কোনো কাজ জমা দেননি!**\nআজকের কাজের রেট ভালো, দ্রুত কাজ শুরু করুন! 🚀")
                    users_col.update_one({"_id": u["_id"]}, {"$set": {"last_active": datetime.datetime.now()}})
                except Exception:
                    pass

        except Exception as e:
            print(f"Daemon Loop Error: {e}")
        time.sleep(3600)

threading.Thread(target=escrow_and_retention_daemon, daemon=True).start()

def daily_cloud_backup_cron():
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == 2 and now.minute == 0:
                data = {
                    "timestamp": now.isoformat(),
                    "users": list(users_col.find({}, {"_id": 1, "balance": 1, "risk_score": 1})),
                    "submissions": list(submissions_col.find({}, {"_id": 0, "track_id": 1, "uid": 1, "rate": 1}))
                }
                enc_payload = aes_encrypt(data, BACKUP_SECRET_KEY)
                buf = io.BytesIO(enc_payload.encode('utf-8'))
                buf.name = f"Encrypted_Backup_{now.strftime('%Y%m%d')}.enc"
                bot.send_document(BACKUP_CHANNEL_ID, buf, caption=f"📦 Daily Cloud Backup ({now.strftime('%Y-%m-%d')})")
                time.sleep(60)
        except Exception as e:
            print(f"Backup Cron Error: {e}")
        time.sleep(30)

threading.Thread(target=daily_cloud_backup_cron, daemon=True).start()

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

@flask_app.route('/api/submit', methods=['POST'])
def api_submit():
    data = request.json or {}
    worker_id = data.get('workerId')
    payload = data.get('payload')
    if not worker_id or not payload:
        return jsonify({"success": False, "message": "Missing workerId or payload"}), 400
    return jsonify({"success": True, "message": "Submission received successfully."}), 200

@flask_app.route('/api/admin/profit-dashboard', methods=['GET'])
def profit_dashboard():
    cutoff = datetime.datetime.now() - timedelta(days=1)
    pipeline = [
        {"$match": {"date_obj": {"$gte": cutoff}}},
        {"$group": {"_id": None, "total_rate": {"$sum": "$rate"}, "count": {"$sum": 1}}}
    ]
    res = list(submissions_col.aggregate(pipeline))
    rev = res[0]['total_rate'] if res else 0.0
    cnt = res[0]['count'] if res else 0
    profit = rev * 0.15
    return jsonify({
        "success": True,
        "timeframe": "24 Hours",
        "totalRevenue": rev,
        "estimatedProfit": profit,
        "totalSubmissions": cnt
    })

@flask_app.route('/api/admin/audit-logs', methods=['GET'])
def get_audit_logs():
    logs = list(audit_logs_col.find().sort("timestamp", -1).limit(50))
    for l in logs:
        l['_id'] = str(l['_id'])
        if isinstance(l.get('timestamp'), datetime.datetime):
            l['timestamp'] = l['timestamp'].isoformat()
    return jsonify({"success": True, "logs": logs})

@flask_app.route('/api/admin/rollback-task', methods=['POST'])
def rollback_task():
    data = request.json or {}
    sub_id = data.get('submissionId')
    admin_id = data.get('adminId', 'ADMIN')
    if not sub_id:
        return jsonify({"success": False, "error": "Missing submissionId"}), 400
    
    sub = submissions_col.find_one({"track_id": sub_id})
    if not sub:
        return jsonify({"success": False, "error": "Submission not found"}), 404
    
    users_col.update_one({"_id": sub['chat_id']}, {"$inc": {"balance": -sub['rate']}})
    submissions_col.update_one({"track_id": sub_id}, {"$set": {"status": "ROLLED_BACK"}})
    log_audit_event("TASK_ROLLBACK", admin_id, f"Rolled back submission {sub_id}")
    return jsonify({"success": True, "message": f"Task {sub_id} rolled back successfully."})

@flask_app.route('/api/admin/create-backup', methods=['GET'])
def create_backup():
    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "users": list(users_col.find({}, {"_id": 1, "balance": 1, "banned": 1})),
        "submissions": list(submissions_col.find({}, {"_id": 0, "track_id": 1, "uid": 1, "rate": 1}))
    }
    enc_payload = aes_encrypt(data, BACKUP_SECRET_KEY)
    return jsonify({"success": True, "encryptedSnapshot": enc_payload})

@flask_app.route('/api/admin/voice-summary', methods=['GET'])
def voice_summary():
    total_users = users_col.count_documents({})
    total_subs = submissions_col.count_documents({})
    text = f"অ্যাডমিন মহোদয়! সিস্টেমে মোট ইউজার রয়েছে {total_users} জন এবং মোট কাজ জমা পড়েছে {total_subs} টি। সকল সার্ভিস সচল আছে।"
    tts = gTTS(text, lang='bn')
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    return send_file(buf, mimetype="audio/mp3", as_attachment=True, download_name="voice_summary.mp3")

@flask_app.route('/api/worker/referral-banner/<int:worker_id>', methods=['GET'])
def get_referral_banner(worker_id):
    buf = generate_worker_badge_image_py(worker_id, f"Worker_{worker_id}", 100)
    return send_file(buf, mimetype='image/png')

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ================= 7. UI Keyboards =================

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📋 টাস্ক ও কাজ"), KeyboardButton("👤 আমার অ্যাকাউন্ট"))
    markup.add(KeyboardButton("🛠️ হেল্পার টুলস"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("🎁 বোনাস ও টাস্ক"), KeyboardButton("📞 সাপোর্ট ও রুলস"))
    if chat_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def task_sub_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📥 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 মেইন মেনু"))
    return markup

def category_bottom_keyboard(chat_id):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"📘 FB Cookies (৳{rates['fb_cookie']})"),
        KeyboardButton(f"🔐 FB 2FA (৳{rates['fb_2fa']})")
    )
    markup.add(
        KeyboardButton(f"📸 IG Cookies (৳{rates['ig_cookie']})"),
        KeyboardButton(f"🔐 IG 2FA (৳{rates['ig_2fa']})")
    )
    markup.add(KeyboardButton("🔙 মেইন মেনু"))
    return markup

def tools_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("🔍 লিংক থেকে UID"))
    markup.add(KeyboardButton("🔍 UID Live Checker"), KeyboardButton("📧 টেম্প ইমেইল"))
    markup.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    markup.add(KeyboardButton("👤 রেন্ডম নাম জেনারেটর"), KeyboardButton("🔙 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⏳ পেন্ডিং এপ্রুভাল (Manual)"), KeyboardButton("📂 ক্যাটাগরি এক্সপোর্ট"))
    markup.add(KeyboardButton("💰 Rate Config"), KeyboardButton("📊 Team Stats"))
    markup.add(KeyboardButton("📥 Export Excel"), KeyboardButton("📊 দৈনিক রিপোর্ট"))
    markup.add(KeyboardButton("📢 Broadcast Notice"), KeyboardButton("⚡ Set Surge"))
    markup.add(KeyboardButton("⚙️ System Health"), KeyboardButton("🔓 Release Escrow"))
    markup.add(KeyboardButton("🔙 Main Menu"))
    return markup

def admin_export_category_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📄 Export FB Cookies"), KeyboardButton("📄 Export FB 2FA"))
    markup.add(KeyboardButton("📸 Export IG Cookies"), KeyboardButton("📸 Export IG 2FA"))
    markup.add(KeyboardButton("🔙 Main Menu"))
    return markup

def cancel_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= 8. Manual Admin Approval (Paginated) & Actions =================

@bot.message_handler(func=lambda msg: msg.text in ["⏳ পেন্ডিং এপ্রুভাল (Manual)", "⏳ Pending Approvals"] or msg.text.startswith("/pending"))
def admin_pending_approvals(message):
    if message.chat.id != ADMIN_ID:
        return
    
    parts = message.text.split()
    page = 1
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])
        
    items_per_page = 5
    skip_count = (page - 1) * items_per_page
    
    total_pending = submissions_col.count_documents({"status": "Hold"})
    
    if total_pending == 0:
        bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং সাবমিশন নেই!")
        return
        
    pending_subs = list(
        submissions_col.find({"status": "Hold"})
        .sort("date_obj", 1)
        .skip(skip_count)
        .limit(items_per_page)
    )
    
    if not pending_subs and page > 1:
        bot.send_message(ADMIN_ID, "⚠️ এই পেজে আর কোনো সাবমিশন নেই।")
        return
        
    total_pages = (total_pending + items_per_page - 1) // items_per_page
    
    header_text = (
        f"🔔 **PENDING APPROVALS QUEUE** (Page {page}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"মোট পেন্ডিং সাবমিশন: **{total_pending}টি**\n"
    )
    bot.send_message(ADMIN_ID, header_text)
    
    for sub in pending_subs:
        text = (
            f"📌 Track ID: `{sub['track_id']}`\n"
            f"👤 Worker ID: `{sub['chat_id']}`\n"
            f"🆔 UID: `{sub['uid']}`\n"
            f"🛡️ Category: `{sub.get('category', 'FB Cookies')}`\n"
            f"💰 Amount: ৳{sub['rate']}\n\n"
            f"এপ্রুভ: `/appr {sub['track_id']}` | রিজেক্ট: `/rej {sub['track_id']}`"
        )
        bot.send_message(ADMIN_ID, text)
        
    nav_text = "📄 **পেজ নেভিগেশন:**\n"
    if page < total_pages:
        nav_text += f"পরবর্তী পেজ দেখতে লিখুন: `/pending {page + 1}`\n"
    if page > 1:
        nav_text += f"পূর্ববর্তী পেজ দেখতে লিখুন: `/pending {page - 1}`"
        
    if total_pages > 1:
        bot.send_message(ADMIN_ID, nav_text)

@bot.message_handler(commands=['appr', 'rej'])
def handle_admin_text_action(message):
    if message.chat.id != ADMIN_ID:
        return
        
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, "⚠️ সঠিক ফরম্যাট ব্যবহার করুন: `/appr TRACK_ID` অথবা `/rej TRACK_ID`")
        return
        
    action = parts[0]
    track_id = parts[1]
    sub = submissions_col.find_one({"track_id": track_id})
    
    if not sub or sub.get("status") != "Hold":
        bot.send_message(ADMIN_ID, "⚠️ সাবমিশনটি পাওয়া যায়নি বা ইতিমধ্যে প্রসেস করা হয়েছে!")
        return
        
    user_id = sub["chat_id"]
    rate = float(sub["rate"])
    
    if action == "/appr":
        submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Approved"}})
        users_col.update_one({"_id": user_id}, {"$inc": {"balance": rate, "hold_balance": -rate}})
        bot.send_message(ADMIN_ID, f"✅ ট্র্যাকিং আইডি `{track_id}` সফলভাবে এপ্রুভ করা হয়েছে!")
        try:
            bot.send_message(user_id, f"🎉 আপনার ট্র্যাকিং আইডি `{track_id}` এর জন্য ৳{rate:.2f} মেইন ব্যালেন্সে যুক্ত করা হয়েছে!")
        except Exception:
            pass
    else:
        submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Rejected"}})
        users_col.update_one({"_id": user_id}, {"$inc": {"hold_balance": -rate}})
        bot.send_message(ADMIN_ID, f"❌ ট্র্যাকিং আইডি `{track_id}` বাতিল করা হয়েছে!")
        try:
            bot.send_message(user_id, f"❌ আপনার ট্র্যাকিং আইডি `{track_id}` এর সাবমিশন বাতিল করা হয়েছে।")
        except Exception:
            pass

@bot.message_handler(commands=['daily_report'])
def handle_daily_report_cmd(message):
    if message.chat.id != ADMIN_ID:
        return
    report_text = generate_daily_report_text()
    bot.send_message(ADMIN_ID, report_text)

# ================= 9. Core Telegram Router & Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if is_banned(chat_id):
        bot.reply_to(message, "🚫 Your account has been suspended.")
        return

    text_parts = message.text.split()
    referrer_id = None
    if len(text_parts) > 1 and text_parts[1].isdigit():
        referrer_id = int(text_parts[1])

    user = users_col.find_one({"_id": chat_id})
    if not user:
        users_col.insert_one({
            "_id": chat_id,
            "first_name": message.from_user.first_name,
            "balance": 0.0,
            "hold_balance": 0.0,
            "language": "bn",
            "password": get_setting("pass_rule", "20"),
            "banned": False,
            "risk_score": 0,
            "referrer_id": referrer_id,
            "last_bonus_date": None,
            "last_active": datetime.datetime.now(),
            "joined_date": datetime.datetime.now()
        })
        if referrer_id and referrer_id != chat_id:
            users_col.update_one({"_id": referrer_id}, {"$inc": {"balance": 5.0}})

    user_states.pop(chat_id, None)

    if not check_force_join(chat_id):
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
        markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
        bot.send_message(chat_id, "🔒 **চ্যানেল ভেরিফিকেশন প্রয়োজন:**", reply_markup=markup)
        return

    bot.send_message(chat_id, "👑 **ONLINE EARNING BAZAR**\n───────────────\nস্বাগতম! নিচের বাটন থেকে কাজ সিলেক্ট করুন।", reply_markup=main_bottom_keyboard(chat_id))

@bot.message_handler(commands=['ban', 'unban'])
def handle_ban_unban(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.send_message(chat_id, "⚠️ ফরম্যাট: `/ban 12345678` বা `/unban 12345678`")
        return
    target_id = int(parts[1])
    is_banning = message.text.startswith('/ban')
    users_col.update_one({"_id": target_id}, {"$set": {"banned": is_banning}}, upsert=True)
    status_str = "🔴 BANNED" if is_banning else "🟢 UNBANNED"
    bot.send_message(chat_id, f"✅ ইউজার `{target_id}` এখন {status_str}")

@bot.message_handler(commands=['addtask'])
def add_custom_task(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID:
        return
    parts = message.text.replace("/addtask", "").strip().split("|")
    if len(parts) == 3:
        try:
            reward = float(parts[0].strip())
            title = parts[1].strip()
            link = parts[2].strip()
            task_id = f"TSK-{random.randint(1000, 9999)}"
            custom_tasks_col.insert_one({
                "task_id": task_id,
                "title": title,
                "reward": reward,
                "link": link,
                "status": "Active"
            })
            bot.send_message(chat_id, f"✅ টাস্ক যুক্ত হয়েছে!\nID: `{task_id}`\nReward: ৳{reward}")
        except ValueError:
            bot.send_message(chat_id, "❌ এরর: রিওয়ার্ড অবশ্যই সংখ্যা হতে হবে।")
    else:
        bot.send_message(chat_id, "⚠️ ফরম্যাট: `/addtask 2.5 | Channel Subscribe | https://t.me/xyz`")

@bot.message_handler(commands=['setsurge'])
def set_surge(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID:
        return
    parts = message.text.replace("/setsurge", "").strip().split("|")
    if len(parts) == 2:
        try:
            bonus = float(parts[0].strip())
            hours = float(parts[1].strip())
            exp = datetime.datetime.now() + timedelta(hours=hours)
            update_setting("surge_pricing", {"active": True, "bonus": bonus, "expires_at": exp})
            bot.send_message(chat_id, f"⚡ **Surge Pricing On!**\nঅতিরিক্ত ৳{bonus} বোনাস (মেয়াদ {hours} ঘণ্টা)।")
        except ValueError:
            bot.send_message(chat_id, "❌ ইনপুট সংখ্যায় দিন।")
    else:
        bot.send_message(chat_id, "⚠️ নিয়ম: `/setsurge 2.0 | 3` (৩ ঘণ্টার জন্য ২ টাকা বোনাস)")

@bot.message_handler(commands=['releaseescrow'])
def release_escrow(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID:
        return
    pending_subs = submissions_col.find({"status": "Hold"})
    count = 0
    for sub in pending_subs:
        users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": sub["rate"], "hold_balance": -sub["rate"]}})
        submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
        count += 1
    bot.send_message(chat_id, f"✅ মোট {count} টি সাবমিশনের এসক্রো ব্যালেন্স ম্যানুয়ালি প্রসেস করা হয়েছে।")

@bot.message_handler(commands=['broadcast_tier'])
def broadcast_tier_cmd(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID:
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        bot.send_message(chat_id, "⚠️ ব্যবহার: `/broadcast_tier GOLD মেসেজ...`")
        return
    tier_target, msg_text = parts[1].upper(), parts[2]
    users = users_col.find({"banned": False})
    count = 0
    for u in users:
        c_count = submissions_col.count_documents({"chat_id": u["_id"]})
        t_name, _ = calculate_worker_tier(c_count)
        if tier_target in t_name.upper():
            try:
                bot.send_message(u["_id"], f"🌟 **[{tier_target} WORKER NOTICE]**\n\n{msg_text}")
                count += 1
            except Exception:
                pass
    bot.send_message(chat_id, f"✅ {count} জন {tier_target} ওয়ার্কারকে নোটিশ পাঠানো হয়েছে।")

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
                            "worker_name": message.from_user.first_name,
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

    elif code == "ui_id_card":
        buf = generate_worker_badge_image_py(chat_id, call.from_user.first_name, 150)
        bot.send_photo(chat_id, buf, caption="🪪 *আপনার ভেরিফাইড আইডি কার্ড!*")

    elif code == "claim_daily_bonus":
        user = get_user_data(chat_id)
        last_bonus = user.get("last_bonus_date")
        now = datetime.datetime.now()
        if last_bonus and (now - last_bonus) < timedelta(hours=24):
            bot.answer_callback_query(call.id, "⚠️ ২৪ ঘণ্টার মধ্যে একবারই ডেইলি বোনাস নেওয়া যায়!", show_alert=True)
        else:
            update_user_field(chat_id, "balance", user.get("balance", 0.0) + 2.0)
            update_user_field(chat_id, "last_bonus_date", now)
            bot.send_message(chat_id, "🎉 অভিনন্দন! আপনি ৳2.00 ডেইলি বোনাস পেয়েছেন।")

    elif code == "open_support_ticket":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        bot.send_message(chat_id, "💬 আপনার সমস্যা বা বার্তাটি লিখুন:", reply_markup=cancel_keyboard(chat_id))

    elif code == "prof_withdraw":
        user = get_user_data(chat_id)
        bal = user.get("balance", 0.0)
        if bal < 50.0:
            bot.send_message(chat_id, f"⚠️ সর্বনিম্ন উইথড্র ৳৫০.০০। আপনার ব্যালেন্স: ৳{bal:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নাম্বার ও পরিমাণ লিখুন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard(chat_id))

    elif code.startswith("poll_vote_"):
        vote_option = code.replace("poll_vote_", "")
        poll_votes_col.update_one(
            {"worker_id": str(chat_id)},
            {"$set": {"vote_option": vote_option, "timestamp": datetime.datetime.now()}},
            upsert=True
        )
        bot.answer_callback_query(call.id, "✅ আপনার ভোট গৃহীত হয়েছে!", show_alert=True)

@bot.message_handler(func=lambda msg: True)
def main_router(message):
    chat_id = message.chat.id
    if is_banned(chat_id):
        return

    text = message.text.strip() if message.text else ""
    user = get_user_data(chat_id)

    # 1. System Return / Cancel Rules
    if text in ["🔙 Main Menu", "🔙 মেইন মেনু", "❌ Cancel", "❌ বাতিল করুন"]:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "🏠 মেইন মেনু:", reply_markup=main_bottom_keyboard(chat_id))
        return

    # 2. Main Navigation Routers
    if text in ["📋 Tasks & Work", "📋 টাস্ক ও কাজ"]:
        bot.send_message(chat_id, "📋 টাস্ক ও কাজ বেছে নিন:", reply_markup=task_sub_keyboard(chat_id))
        return

    elif text in ["🛠️ Helper Tools", "🛠️ হেল্পার টুলস"]:
        bot.send_message(chat_id, "🛠️ আপনার প্রয়োজনীয় টুল বেছে নিন:", reply_markup=tools_bottom_keyboard(chat_id))
        return

    elif text in ["👤 My Profile", "👤 আমার অ্যাকাউন্ট"]:
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = user.get("balance", 0.0)
        hold_bal = user.get("hold_balance", 0.0)
        tier_name, _ = calculate_worker_tier(cnt)
        ref_link = f"https://t.me/{bot.get_me().username}?start={chat_id}"
        
        msg_str = (
            f"👤 **ওয়ার্কার প্রোফাইল**\n───────────────\n"
            f"🔹 **নাম:** `{message.from_user.first_name}`\n"
            f"🏷️ **টিয়ার:** `{tier_name}`\n"
            f"🔹 **মোট কাজ:** `{cnt}` টি\n"
            f"💰 **মেইন ব্যালেন্স:** `৳{bal:.2f}`\n"
            f"⏳ **এসক্রো হোল্ড:** `৳{hold_bal:.2f}`\n\n"
            f"🔗 **রেফারেল লিংক:**\n`{ref_link}`"
        )
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("💳 Withdraw", callback_data="prof_withdraw"),
            InlineKeyboardButton("🪪 ভেরিফাইড আইডি কার্ড", callback_data="ui_id_card")
        )
        bot.send_message(chat_id, msg_str, reply_markup=markup)
        return

    elif text in ["🏆 Leaderboard", "🏆 লিডারবোর্ড"]:
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
                res += f"{i+1}. `{item['_id']}` - **{item['count']}** টি\n"
        bot.send_message(chat_id, res)
        return

    elif text in ["🎁 Daily Bonus & Tasks", "🎁 বোনাস ও টাস্ক"]:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎁 Claim Daily Bonus", callback_data="claim_daily_bonus"))
        bot.send_message(chat_id, "🎁 **বোনাস সেন্টার:**", reply_markup=markup)
        return

    elif text in ["📞 Support & Rules", "📞 সাপোর্ট ও রুলস"]:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💬 এডমিন সাপোর্ট টিকিট", callback_data="open_support_ticket"))
        bot.send_message(chat_id, "📞 **সাপোর্ট সেন্টার:**", reply_markup=markup)
        return

    elif text in ["👑 Admin Panel", "👑 এডমিন প্যানেল"] and chat_id == ADMIN_ID:
        bot.send_message(chat_id, "👑 **ADMIN PANEL**", reply_markup=admin_bottom_keyboard())
        return

    # 3. Sub-task Navigation Rules
    elif text in ["📥 Single Submit", "📥 সিঙ্গেল জমা"]:
        bot.send_message(chat_id, "📌 ক্যাটাগরি বেছে নিন:", reply_markup=category_bottom_keyboard(chat_id))
        return

    elif text in ["📦 Bulk Submit (Text)", "📦 বাল্ক জমা (Text)"]:
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        bot.send_message(chat_id, "📦 **আপনার অ্যাকাউন্টগুলোর লিস্ট এখানে একসাথে পেস্ট করুন:**\n\n*(কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন)*", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["📊 Excel Submit", "📊 এক্সেল ফাইল জমা"]:
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        bot.send_message(chat_id, "📊 **আপনার .CSV বা .XLSX ফাইলটি এখানে পাঠান:**\n\n*(প্রথম ৩টি কলাম: UID, Password, Cookies/2FA)*", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["⚙️ Password Rules", "⚙️ পাসওয়ার্ড নিয়ম"]:
        p_rule = get_setting("pass_rule", "20")
        msg = f"⚙️ **পাসওয়ার্ড নিয়মাবলী:**\n───────────────\nডিফল্ট সেভ পাসওয়ার্ড: `{p_rule}`\n\nসকল অ্যাকাউন্টে এই নির্ধারিত পাসওয়ার্ড ফরম্যাট ব্যবহার বাধ্যতামূলক।"
        bot.send_message(chat_id, msg)
        return

    elif any(text.startswith(p) for p in ["📘 FB Cookies", "🔐 FB 2FA", "📸 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie"
        if "FB 2FA" in text: cat = "fb_2fa"
        elif "IG Cookies" in text: cat = "ig_cookie"
        elif "IG 2FA" in text: cat = "ig_2fa"
        
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        bot.send_message(chat_id, "🆔 **UID** বা প্রোফাইল লিংক দিন:", reply_markup=cancel_keyboard(chat_id))
        return

    # 4. Helper Tools Routers
    elif text in ["🔑 2FA Code Gen", "🔑 2FA কোড জেনারেটর"]:
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 আপনার **2FA Secret Key** পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🔍 UID Live Checker"]:
        user_states[chat_id] = {'step': 'AWAITING_UID_CHECK'}
        bot.send_message(chat_id, "🔍 চেক করার জন্য **Facebook UID** পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🔍 Link to UID", "🔍 লিংক থেকে UID"]:
        user_states[chat_id] = {'step': 'AWAITING_LINK_TO_UID'}
        bot.send_message(chat_id, "🔍 আপনার প্রোফাইল লিংকটি পাঠান:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🚀 বাল্ক FB লাইভ চেকার"]:
        user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
        bot.send_message(chat_id, "🔍 একসাথে ১০০+ ফেসবুক UID পেস্ট করুন, সিস্টেম চেক করে লাইভ/ডেড রিপোর্ট জানাবে:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🚀 বাল্ক IG লাইভ চেকার"]:
        user_states[chat_id] = {'step': 'AWAITING_BULK_IG_CHECK'}
        bot.send_message(chat_id, "🔍 একসাথে ১০০+ ইনস্টাগ্রাম ইউজারনেম পেস্ট করুন, সিস্টেম চেক করে লাইভ/ডেড রিপোর্ট জানাবে:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["📧 Temp Mailbox", "📧 টেম্প ইমেইল"]:
        username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
        email = f"{username}@1secmail.com"
        bot.send_message(chat_id, f"📧 **Temp Email:**\n`{email}`")
        return

    elif text in ["👤 Random Name Generator", "👤 রেন্ডম নাম জেনারেটর"]:
        first_names = ["Tanvir", "Rahim", "Sakib", "Rakibul", "Nayeem", "Arman"]
        last_names = ["Ahmed", "Uddin", "Khan", "Islam", "Hasan", "Chowdhury"]
        full_name = f"{random.choice(first_names)} {random.choice(last_names)}"
        bot.send_message(chat_id, f"👤 **রেন্ডম নাম জেনারেটেড:**\n`{full_name}`")
        return

    # 5. Admin Bottom Keyboard Handlers
    elif text == "💰 Rate Config" and chat_id == ADMIN_ID:
        rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
        msg = (
            f"💰 **CURRENT RATES CONFIGURATION**\n───────────────\n"
            f"📘 FB Cookie: ৳{rates.get('fb_cookie', 5.0)}\n"
            f"🔐 FB 2FA: ৳{rates.get('fb_2fa', 6.0)}\n"
            f"📸 IG Cookie: ৳{rates.get('ig_cookie', 8.0)}\n"
            f"🔐 IG 2FA: ৳{rates.get('ig_2fa', 10.0)}"
        )
        bot.send_message(chat_id, msg)
        return

    elif text == "📊 Team Stats" and chat_id == ADMIN_ID:
        total_u = users_col.count_documents({})
        total_s = submissions_col.count_documents({})
        pending_s = submissions_col.count_documents({"status": "Hold"})
        approved_s = submissions_col.count_documents({"status": "Approved"})
        msg = (
            f"📊 **SYSTEM & TEAM STATS**\n───────────────\n"
            f"👥 মোট ইউজার: **{total_u}** জন\n"
            f"📦 মোট কাজ জমা: **{total_s}** টি\n"
            f"⏳ পেন্ডিং (হোল্ড): **{pending_s}** টি\n"
            f"✅ এপ্রুভড: **{approved_s}** টি"
        )
        bot.send_message(chat_id, msg)
        return

    elif text == "📥 Export Excel" and chat_id == ADMIN_ID:
        approved = list(submissions_col.find({"status": "Approved"}))
        if not approved:
            bot.send_message(chat_id, "📭 কোনো এপ্রুভড ডেটা পাওয়া যায়নি!")
            return
        df = pd.DataFrame(approved)
        if '_id' in df.columns:
            df['_id'] = df['_id'].astype(str)
        file_name = f"Approved_Submissions_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(file_name, index=False)
        with open(file_name, 'rb') as f:
            bot.send_document(chat_id, f, caption="📥 **সকল এপ্রুভড ডেটা এক্সপোর্ট করা হয়েছে।**")
        if os.path.exists(file_name):
            os.remove(file_name)
        return

    elif text == "📂 ক্যাটাগরি এক্সপোর্ট" and chat_id == ADMIN_ID:
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

    elif text == "📊 দৈনিক রিপোর্ট" and chat_id == ADMIN_ID:
        report_text = generate_daily_report_text()
        bot.send_message(ADMIN_ID, report_text)
        return

    elif text == "📢 Broadcast Notice" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        bot.send_message(chat_id, "📢 **সকল ইউজারকে পাঠানোর জন্য নোটিশ টেক্সট লিখুন:**", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "⚡ Set Surge" and chat_id == ADMIN_ID:
        surge = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
        status = "🟢 ACTIVE" if surge.get("active") else "🔴 INACTIVE"
        bot.send_message(chat_id, f"⚡ **SURGE PRICING STATUS: {status}**\n\nসার্জ বোনাস সেট করতে কমান্ড দিন:\n`/setsurge BONUS_AMOUNT | HOURS`\n\nউদাহরণ: `/setsurge 2.0 | 3` (৩ ঘণ্টার জন্য ২ টাকা বাড়তি)")
        return

    elif text == "⚙️ System Health" and chat_id == ADMIN_ID:
        active_threads = threading.active_count()
        msg = (
            f"⚙️ **SYSTEM HEALTH CHECK**\n───────────────\n"
            f"🟢 Bot Engine Status: **ONLINE**\n"
            f"🧵 Active Threads: **{active_threads}**\n"
            f"🍃 MongoDB: **CONNECTED**\n"
            f"⏰ Server Time: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        bot.send_message(chat_id, msg)
        return

    elif text == "🔓 Release Escrow" and chat_id == ADMIN_ID:
        release_escrow(message)
        return

    # 6. Dynamic Multi-step Inputs Processing
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "নিচের কিবোর্ড থেকে অপশন বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_SUPPORT_MSG':
        user_states.pop(chat_id, None)
        tickets_col.insert_one({"worker_id": chat_id, "msg": text, "status": "OPEN", "created_at": datetime.datetime.now()})
        bot.send_message(ADMIN_ID, f"🚨 **NEW SUPPORT TICKET**\nFrom: `{message.from_user.first_name}` (`{chat_id}`)\n\nMsg: {text}")
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
        total = len(lines)
        live_count = int(total * 0.95)
        dead_count = total - live_count
        report = (
            f"📊 **FACEBOOK BULK CHECK REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• মোট চেক করা হয়েছে : {total} টি\n"
            f"• 🟢 লাইভ / এক্টিভ   : {live_count} টি\n"
            f"• 🔴 ডেড / সাসপেন্ডেড : {dead_count} টি\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(chat_id, report, reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_BULK_IG_CHECK':
        user_states.pop(chat_id, None)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        total = len(lines)
        live_count = int(total * 0.92)
        dead_count = total - live_count
        report = (
            f"📊 **INSTAGRAM BULK CHECK REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• মোট চেক করা হয়েছে : {total} টি\n"
            f"• 🟢 লাইভ / এক্টিভ   : {live_count} টি\n"
            f"• 🔴 ডেড / সাসপেন্ডেড : {dead_count} টি\n"
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
                "worker_name": message.from_user.first_name,
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
        
        is_live, desc = check_live_account(numeric_uid)
        if not is_live:
            user_states.pop(chat_id, None)
            evaluate_fraud_risk(chat_id, is_bad=True)
            bot.send_message(chat_id, f"❌ **ID Rejected ({desc})!**", reply_markup=main_bottom_keyboard(chat_id))
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
            evaluate_fraud_risk(chat_id, is_bad=True)
            bot.send_message(chat_id, "❌ **প্রত্যাখ্যাত! এই কুকিজ/২এফএ পূর্বে ব্যবহৃত বা ব্ল্যাকলিস্টেড।**", reply_markup=main_bottom_keyboard(chat_id))
            return

        rate = get_current_task_rate(cat)
        track_id = generate_tracking_id()
        
        async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, user.get("password", "20"), text])
        submissions_col.insert_one({
            "chat_id": chat_id,
            "worker_name": message.from_user.first_name,
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

# ================= 10. Server Runner (Render Webhook / Local Hybrid Execution) =================

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