import os
import re
import json
import io
import base64
import random
import datetime
from datetime import timedelta, timezone
import threading
import concurrent.futures
import collections
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
from telebot.apihelper import ApiTelegramException
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import google.generativeai as genai

# ================= 1. Configuration & Credentials =================
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1aWntk0eMZt6w7GWmXs_PmckvoDT1uCCRiGUELiV4NKA")

# Render Secret Files & Local Path Auto-Detection for Google Credentials
CREDENTIALS_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/etc/secrets/credentials.json")
if not os.path.exists(CREDENTIALS_FILE):
    CREDENTIALS_FILE = "credentials.json"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Configure Google Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    ai_model = None

try:
    BOT_USERNAME = bot.get_me().username
except Exception:
    BOT_USERNAME = "online_bazar_manager_bot"

# MongoDB Connection Pool
mongo_client = MongoClient(
    MONGO_URL,
    maxPoolSize=300,
    minPoolSize=50,
    maxIdleTimeMS=45000,
    connectTimeoutMS=10000
)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
tickets_col = db['support_tickets']
withdrawals_col = db['withdrawals']
blacklisted_payloads_col = db['blacklisted_payloads']
ai_logs_col = db['ai_logs']
sheet_overflow_col = db['sheet_overflow_queue']

# FIXED 2: Strict Unique Indexing on UID to Prevent Race Condition Duplicates
try:
    submissions_col.create_index("track_id", unique=True, background=True)
    submissions_col.create_index("uid", unique=True, background=True)
    submissions_col.create_index("chat_id", background=True)
    submissions_col.create_index("status", background=True)
    submissions_col.create_index("date_key", background=True)
except Exception:
    pass

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

# Timezone definition for Bangladesh (UTC+6)
BD_TIMEZONE = timezone(timedelta(hours=6))

# Non-blocking Bounded Executor to Prevent Webhook Freeze
class NonBlockingBoundedExecutor:
    def __init__(self, max_workers, max_queue):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = threading.Semaphore(max_workers + max_queue)
        
    def submit(self, fn, *args, **kwargs):
        acquired = self.semaphore.acquire(blocking=False)
        if acquired:
            try:
                future = self.executor.submit(fn, *args, **kwargs)
                future.add_done_callback(lambda x: self.semaphore.release())
                return future
            except Exception:
                self.semaphore.release()
                raise
        else:
            def fallback():
                try:
                    fn(*args, **kwargs)
                except Exception:
                    pass
            threading.Thread(target=fallback, daemon=True).start()

background_executor = NonBlockingBoundedExecutor(max_workers=20, max_queue=5000)

# FIXED 1: Fully Thread-Safe LRU Cache in MongoDict
class MongoDict:
    def __init__(self, collection, max_cache_size=10000):
        self.col = collection
        self.cache = collections.OrderedDict()
        self.max_cache_size = max_cache_size
        self.lock = threading.Lock()
        
    def get(self, key, default=None):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        
        doc = self.col.find_one({"_id": key})
        if doc:
            val = doc.get("state", default)
            with self.lock:
                self._add_to_cache(key, val)
            return val
        return default

    def __setitem__(self, key, value):
        with self.lock:
            self._add_to_cache(key, value)
        background_executor.submit(self._async_save, key, value)

    def _add_to_cache(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.max_cache_size:
            self.cache.popitem(last=False)

    def _async_save(self, key, value):
        try:
            self.col.update_one({"_id": key}, {"$set": {"state": value}}, upsert=True)
        except Exception:
            pass

    def pop(self, key, default=None):
        val = default
        with self.lock:
            if key in self.cache:
                val = self.cache.pop(key)
            else:
                doc = self.col.find_one_and_delete({"_id": key})
                if doc:
                    val = doc.get("state", default)
        background_executor.submit(self._async_delete, key)
        return val

    def _async_delete(self, key):
        try:
            self.col.delete_one({"_id": key})
        except Exception:
            pass

user_states = MongoDict(db['user_states'])

# Dynamic Category Mapping Dictionary
CAT_MAP = {
    "fb_cookie": "FB Cookies",
    "fb_2fa": "FB 2FA",
    "ig_cookie": "IG Cookies",
    "ig_2fa": "IG 2FA"
}

# Dynamic Dataset for Profile Generation
BD_FIRST_NAMES = [
    "Sakib", "Tanvir", "Rahim", "Rakib", "Nayeem", "Ariful", "Mehedi", "Mahfuz", 
    "Farhan", "Ashfaq", "Sumon", "Imran", "Hasib", "Shahadat", "Rayhan", "Tasnim", 
    "Nusrat", "Riya", "Sadia", "Mim", "Farhana", "Sultana", "Anik", "Sabbir", 
    "Fahim", "Jubayer", "Naim", "Tariq", "Zubair", "Alim", "Shakil", "Mahmud"
]
BD_LAST_NAMES = [
    "Hasan", "Ahmed", "Uddin", "Islam", "Khan", "Chowdhury", "Rahman", "Hossain", 
    "Sheikh", "Mahmud", "Sarkar", "Miah", "Akter", "Siddique", "Bhuiyan", "Kabir", "Ali", "Alam"
]

USA_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", 
    "Thomas", "Charles", "Daniel", "Matthew", "Anthony", "Mark", "Steven", "Paul", 
    "Andrew", "Joshua", "Kenneth", "Kevin", "Mary", "Patricia", "Jennifer", "Linda", 
    "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Sandra"
]
USA_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", 
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", 
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris"
]

# ================= 2. Helper Functions =================

def get_bd_time():
    return datetime.datetime.now(BD_TIMEZONE)

def parse_iso_datetime(dt_val):
    if not dt_val:
        return get_bd_time()
    if isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=BD_TIMEZONE)
        return dt_val.astimezone(BD_TIMEZONE)
    if isinstance(dt_val, str):
        try:
            parsed = datetime.datetime.fromisoformat(dt_val)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=BD_TIMEZONE)
            return parsed.astimezone(BD_TIMEZONE)
        except Exception:
            return get_bd_time()
    return get_bd_time()

def safe_delete_msg(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass

def get_setting(key, default):
    res = settings_col.find_one({"_id": key})
    return res["value"] if res else default

def update_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

def get_active_surge_bonus():
    surge_info = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge_info.get("active"):
        exp = parse_iso_datetime(surge_info.get("expires_at"))
        if exp and get_bd_time() < exp:
            return float(surge_info.get("bonus", 0.0))
    return 0.0

def log_ai_report(issue_type, description, fix_action):
    now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
    ai_logs_col.insert_one({"timestamp": now_str, "type": issue_type, "description": description, "action": fix_action})
    
    audit_msg = (
        f"🧠 <b>AI AUTO-HEALING & AUDIT REPORT</b>\n\n"
        f"• <b>Time:</b> {now_str}\n"
        f"• <b>Issue:</b> {issue_type}\n\n"
        f"🔍 <b>Description:</b>\n{description[:150]}\n\n"
        f"🛠️ <b>Action Taken:</b>\n{fix_action[:150]}"
    )
    try: 
        bot.send_message(ADMIN_ID, audit_msg)
    except Exception: 
        pass

def generate_strict_ai_warning(issue, cause, solution, prevention):
    return (
        f"⚠️ <b>OEB NEXUS AI SYSTEM WARNING</b>\n\n"
        f"🔍 <b>১. সমস্যা:</b> {issue}\n"
        f"❓ <b>২. কারণ:</b> {cause}\n"
        f"🛠️ <b>৩. সমাধান:</b> {solution}\n"
        f"🛡️ <b>৪. ভবিষ্যতের প্রতিকার:</b> {prevention}"
    )

def validate_strict_password(password, rule):
    if not rule or rule.lower() == "none" or rule.strip() == "":
        return True
    return str(password).strip().endswith(rule.strip())

def ask_ai_chatbot(user_message):
    if not ai_model:
        return "আসসালামু আলাইকুম! OEB NEXUS বটে আপনাকে স্বাগতম। নিচের মেনু থেকে আপনার প্রয়োজনীয় সেবা বেছে নিন।"
    try:
        prompt = (
            f"You are an AI support assistant for a professional online earning bot 'OEB NEXUS'. "
            f"Always reply in Bengali using strict 4 points: 1. Problem, 2. Root Cause, 3. Solution, 4. Prevention. "
            f"User Query: {user_message}"
        )
        response = ai_model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return "আপনার বার্তাটি আমরা পেয়েছি। দয়া করে প্রধান মেনু থেকে আপনার কাঙ্ক্ষিত অপশনটি সিলেক্ট করুন।"

def ai_analyze_ticket_sentiment(ticket_text):
    if not ai_model:
        return "Normal", "সাধারণ সাপোর্ট বার্তা"
    try:
        prompt = (
            f"Analyze the following support ticket message and determine its priority (High or Normal) and provide a 1-line summary in Bengali. "
            f"Format as JSON with keys 'priority' and 'summary'. Message: {ticket_text}"
        )
        response = ai_model.generate_content(prompt)
        res_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(res_text)
        return data.get("priority", "Normal"), data.get("summary", "সাপোর্ট রিকোয়েস্ট")
    except Exception:
        return "Normal", "সাপোর্ট রিকোয়েস্ট"

def calculate_worker_trust_score(chat_id):
    total = submissions_col.count_documents({"chat_id": chat_id})
    appr = submissions_col.count_documents({"chat_id": chat_id, "status": "Approved"})
    if total == 0:
        return "New Worker", 100
    ratio = appr / total
    if total >= 50 and ratio >= 0.90:
        return "⭐ VIP Worker", int(ratio * 100)
    elif total >= 20 and ratio >= 0.75:
        return "🛡️ Trusted Worker", int(ratio * 100)
    else:
        return "👤 Regular Worker", int(ratio * 100)

def sanitize_html(text):
    if not text: return "Worker"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def generate_profile_data(country):
    if country == "bd":
        fn = random.choice(BD_FIRST_NAMES)
        ln = random.choice(BD_LAST_NAMES)
        flag = "🇧🇩 BANGLADESH"
    else:
        fn = random.choice(USA_FIRST_NAMES)
        ln = random.choice(USA_LAST_NAMES)
        flag = "🇺🇸 USA"

    sep = random.choice(["_", ".", ""])
    num_suffix = random.choice([str(random.randint(10, 999)), str(random.randint(1995, 2006))])
    username = f"{fn.lower()}{sep}{ln.lower()}{num_suffix}"

    year = random.randint(1995, 2006)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    dob_str = f"{day:02d}/{month:02d}/{year}"

    out = (
        f"🎲 <b>CYBER PERSONA // {flag}</b>\n\n"
        f"• <b>First Name:</b> <code>{fn}</code>\n"
        f"• <b>Last Name:</b> <code>{ln}</code>\n"
        f"• <b>Username:</b> <code>{username}</code>\n"
        f"• <b>Birth Date:</b> <code>{dob_str}</code>\n\n"
        f"💡 <i>Tap any text above to copy instantly.</i>"
    )

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔄 নতুন প্রোফাইল তৈরি করুন (Refresh)", callback_data=f"gen_prof_{country}"))
    return out, markup

def send_private_backup_message(content, doc_buf=None, doc_name=None):
    def task():
        try:
            safe_content = content
            if len(safe_content) > 3800:
                safe_content = safe_content[:3750] + "\n\n⚠️ <i>[Data Truncated for Telegram Limit]</i>"

            if doc_buf and doc_name:
                doc_buf.seek(0)
                bot.send_document(BACKUP_CHANNEL_ID, (doc_name, doc_buf), caption=safe_content)
            else:
                bot.send_message(BACKUP_CHANNEL_ID, safe_content)
        except Exception as e:
            log_ai_report("Backup Channel Error", str(e), "Check if Bot is Admin in private backup channel.")
    background_executor.submit(task)

def broadcast_password_rule_notice(new_rule):
    def task():
        all_users = list(users_col.find({"banned": False}))
        notice_text = (
            f"📢 <b>OEB NEXUS OFFICIAL NOTICE</b>\n\n"
            f"🔑 <b>আজকের নতুন পাসওয়ার্ড কোড:</b> <code>{sanitize_html(new_rule)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <b>গুরুত্বপূর্ণ নির্দেশাবলী:</b>\n"
            f"১. একাউন্ট খোলার সময় আপনার পাসওয়ার্ডের <b>'একদম শেষে'</b> বাধ্যতামূলকভাবে '<code>{sanitize_html(new_rule)}</code>' কোডটি যুক্ত করে একাউন্ট তৈরি করুন।\n"
            f"২. সঠিক নিয়ম মেনে একাউন্ট খুলে দ্রুত জমা দিন। নিয়ম ছাড়া ভুল পাসওয়ার্ড দিলে একাউন্ট সরাসরি ব্যাক/রিজেক্ট হয়ে যাবে!\n\n"
            f"⚡ দেরি না করে এখনই কাজ শুরু করুন এবং বেশি বেশি ইনকাম করুন! 🚀"
        )
        for u in all_users:
            try:
                bot.send_message(u["_id"], notice_text)
                time.sleep(0.05)
            except ApiTelegramException as e:
                if e.error_code == 429:
                    time.sleep(e.result_json.get('parameters', {}).get('retry_after', 3))
                    try: bot.send_message(u["_id"], notice_text)
                    except: pass
            except Exception:
                pass
    background_executor.submit(task)

def make_progress_bar(processed, total, length=10):
    if not total or total == 0: return "░" * length
    ratio = min(1.0, max(0.0, processed / total))
    filled = int(ratio * length)
    return "▓" * filled + "░" * (length - filled)

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

def generate_withdraw_id():
    return f"WDR-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"

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
    base_rate += get_active_surge_bonus()
    return base_rate

# --- AUTO TOKEN REFRESH & GOOGLE API RE-AUTH ENGINE ---
global_gspread_client = None
gspread_lock = threading.Lock()
sheet_write_queue = {}
sheet_queue_lock = threading.Lock()

def get_gspread_client(force_refresh=False):
    global global_gspread_client
    with gspread_lock:
        if global_gspread_client is None or force_refresh:
            try:
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds_path = "/etc/secrets/credentials.json"
                if not os.path.exists(creds_path):
                    creds_path = CREDENTIALS_FILE
                if not os.path.exists(creds_path):
                    creds_path = "credentials.json"
                
                with open(creds_path, 'r', encoding='utf-8') as f:
                    creds_dict = json.load(f)
                
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                global_gspread_client = gspread.authorize(creds)
            except Exception as e:
                print(f"[AUTH ERROR] Failed to initialize gspread client: {e}")
                raise
        return global_gspread_client

# ZERO DATA LOSS DAEMON WITH MONGODB PERSISTENT OVERFLOW QUEUE
def background_sheet_writer_daemon():
    MAX_RAM_QUEUE_SIZE = 3000
    while True:
        time.sleep(15)
        with sheet_queue_lock:
            if not sheet_write_queue:
                continue
            snapshot = sheet_write_queue.copy()
            sheet_write_queue.clear()
        
        try:
            gc = get_gspread_client(force_refresh=False)
            sheet = gc.open_by_key(SPREADSHEET_ID)
            
            overflow_docs = list(sheet_overflow_col.find().limit(500))
            if overflow_docs:
                for o_doc in overflow_docs:
                    o_tab = o_doc.get("tab_name")
                    o_rows = o_doc.get("rows", [])
                    try:
                        ws = sheet.worksheet(o_tab)
                    except gspread.exceptions.WorksheetNotFound:
                        ws = sheet.add_worksheet(title=o_tab, rows=1000, cols=10)
                    ws.append_rows(o_rows)
                    sheet_overflow_col.delete_one({"_id": o_doc["_id"]})

            for tab_name, rows in snapshot.items():
                if not rows: continue
                try:
                    worksheet = sheet.worksheet(tab_name)
                except gspread.exceptions.WorksheetNotFound:
                    cols_count = max(len(r) for r in rows) + 2
                    worksheet = sheet.add_worksheet(title=tab_name, rows=1000, cols=cols_count)
                worksheet.append_rows(rows)

        except Exception as e:
            err_str = str(e)
            log_ai_report("Google Sheet Daemon Exception", err_str, "Retrying with Auto Token Refresh & Mongo Failover...")
            
            if "401" in err_str or "invalid_grant" in err_str.lower() or "token" in err_str.lower():
                try: get_gspread_client(force_refresh=True)
                except: pass

            with sheet_queue_lock:
                for tab_name, rows in snapshot.items():
                    if tab_name not in sheet_write_queue:
                        sheet_write_queue[tab_name] = []
                    
                    sheet_write_queue[tab_name] = rows + sheet_write_queue[tab_name]
                    
                    if len(sheet_write_queue[tab_name]) > MAX_RAM_QUEUE_SIZE:
                        overflow_rows = sheet_write_queue[tab_name][MAX_RAM_QUEUE_SIZE:]
                        sheet_write_queue[tab_name] = sheet_write_queue[tab_name][:MAX_RAM_QUEUE_SIZE]
                        try:
                            sheet_overflow_col.insert_one({
                                "tab_name": tab_name,
                                "rows": overflow_rows,
                                "created_at": get_bd_time()
                            })
                        except Exception: pass

threading.Thread(target=background_sheet_writer_daemon, daemon=True).start()

def async_save_batch_to_sheet(tab_name, rows_list):
    if not rows_list: return
    with sheet_queue_lock:
        if tab_name not in sheet_write_queue:
            sheet_write_queue[tab_name] = []
        sheet_write_queue[tab_name].extend(rows_list)

def async_save_to_sheet(tab_name, row_data):
    async_save_batch_to_sheet(tab_name, [row_data])

def async_create_sheet_tab(tab_name, fields):
    def task():
        try:
            gc = get_gspread_client()
            sheet = gc.open_by_key(SPREADSHEET_ID)
            try:
                sheet.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                headers = ["Submission Time", "Track ID", "Worker ID"] + fields
                ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers)+2)
                ws.append_row(headers)
        except Exception as e:
            pass
    background_executor.submit(task)

def get_active_hold_dates():
    pipeline = [
        {"$match": {"status": "Hold"}},
        {"$project": {
            "effective_date": {
                "$ifNull": [
                    "$date_key",
                    {"$cond": [
                        {"$and": [
                            {"$ne": ["$date_str", None]},
                            {"$gte": [{"$strLenCP": {"$ifNull": ["$date_str", ""]}}, 10]}
                        ]},
                        {"$substrCP": ["$date_str", 0, 10]},
                        "Legacy"
                    ]}
                ]
            }
        }},
        {"$group": {"_id": "$effective_date"}}
    ]
    results = list(submissions_col.aggregate(pipeline))
    dates = [r["_id"] for r in results if r["_id"]]
    dates.sort(reverse=True)
    return dates

def get_all_recorded_dates():
    pipeline = [
        {"$project": {
            "effective_date": {
                "$ifNull": [
                    "$date_key",
                    {"$cond": [
                        {"$and": [
                            {"$ne": ["$date_str", None]},
                            {"$gte": [{"$strLenCP": {"$ifNull": ["$date_str", ""]}}, 10]}
                        ]},
                        {"$substrCP": ["$date_str", 0, 10]},
                        "Legacy"
                    ]}
                ]
            }
        }},
        {"$group": {"_id": "$effective_date"}}
    ]
    results = list(submissions_col.aggregate(pipeline))
    dates = [r["_id"] for r in results if r["_id"]]
    dates.sort(reverse=True)
    return dates

def build_date_query(selected_date, base_status=None):
    q = {}
    if base_status: q["status"] = base_status
    if selected_date != "ALL":
        q["$or"] = [
            {"date_key": selected_date},
            {"date_str": {"$regex": f"^{selected_date}"}}
        ]
    return q

# ================= 3. Image Badge Generator =================

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

# ================= 4. UI Keyboards =================

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚡ কাজ জমা সেন্টার"), KeyboardButton("🛠 হেল্পার টুলস"))
    markup.add(KeyboardButton("👤 প্রোফাইল ও ওয়ালেট"), KeyboardButton("🎁 রিওয়ার্ড ও সাপোর্ট"))
    if chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 এডমিন কন্ট্রোল সেন্টার"))
    return markup

def submit_tasks_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def category_bottom_keyboard():
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(f"📄 FB Cookies (৳{rates['fb_cookie']})"), KeyboardButton(f"🔐 FB 2FA (৳{rates['fb_2fa']})"))
    markup.add(KeyboardButton(f"📷 IG Cookies (৳{rates['ig_cookie']})"), KeyboardButton(f"🔐 IG 2FA (৳{rates['ig_2fa']})"))
    
    custom_cats = get_setting("custom_categories", {})
    bonus_amt = get_active_surge_bonus()

    for ck, ci in custom_cats.items():
        c_name = ci.get("name", "Task")
        c_rate = float(ci.get("rate", 5.0)) + bonus_amt
        markup.add(KeyboardButton(f"📌 {c_name} (৳{c_rate:.2f})"))
        
    markup.add(KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def helper_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"))
    markup.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    markup.add(KeyboardButton("👤 র্যান্ডম প্রোফাইল জেনারেটর"))
    markup.add(KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💳 Withdraw"), KeyboardButton("🪪 ভেরিফাইড আইডি কার্ড"))
    markup.add(KeyboardButton("🏠 মেইন মেনু"))
    return markup

def bonus_support_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 টাস্ক ও রিপোর্ট ম্যানেজমেন্ট"), KeyboardButton("💳 ফাইন্যান্স ও উইথড্র"))
    markup.add(KeyboardButton("⚙️ সেটিংস ও কনফিগারেশন"), KeyboardButton("📢 ইউজার ও সিস্টেম কন্ট্রোল"))
    markup.add(KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_sub_task_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 স্মার্ট ড্যাশবোর্ড ও রিপোর্ট"), KeyboardButton("📂 স্মার্ট ফাইল এক্সপোর্ট"))
    markup.add(KeyboardButton("🤖 বায়ার রিপোর্ট অটো-ম্যাচার"), KeyboardButton("🏛️ আর্কাইভ ও বন্ধ ফাইল"))
    markup.add(KeyboardButton("⏳ ম্যানুয়াল পেন্ডিং চেক"), KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_finance_keyboard():
    pending_w_count = withdrawals_col.count_documents({"status": "Pending"})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton(f"⏳ পেন্ডিং উইথড্রয়াল চেক ({pending_w_count} টি)"))
    markup.add(KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_settings_keyboard():
    m_mode = get_setting("maintenance_mode", False)
    m_btn = "🛠 মেইনটেনেন্স: 🟢 ON" if m_mode else "🛠 মেইনটেনেন্স: 🔴 OFF"
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("⚙️ কাস্টম ক্যাটাগরি প্যানেল"))
    markup.add(KeyboardButton("🔑 পাসওয়ার্ড নিয়ম সেট"), KeyboardButton(m_btn))
    markup.add(KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_system_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 ইউজার ম্যানেজার"), KeyboardButton("📢 ব্রডকাস্ট নোটিশ"))
    markup.add(KeyboardButton("🧠 AI সিটেডেল অডিট"), KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= 5. Dynamic User Control Center =================

def render_user_manager_page(admin_chat_id, message_id=None, page=1):
    users_per_page = 5
    total_u = users_col.count_documents({})
    banned_u = users_col.count_documents({"banned": True})
    active_u = total_u - banned_u

    total_pages = max(1, (total_u + users_per_page - 1) // users_per_page)
    page = max(1, min(page, total_pages))

    skip = (page - 1) * users_per_page
    user_list = list(users_col.find().sort("joined_date", -1).skip(skip).limit(users_per_page))

    out_msg = (
        f"👥 <b>USER CONTROL CENTER</b> (Page {page}/{total_pages})\n\n"
        f"• <b>Total Members:</b> {total_u}\n"
        f"• <b>Active Users:</b> {active_u}\n"
        f"• <b>Banned Users:</b> {banned_u}\n\n"
        f"────────────────────────\n\n"
    )

    markup = InlineKeyboardMarkup(row_width=1)

    for i, u in enumerate(user_list, start=skip + 1):
        u_id = u["_id"]
        raw_fname = str(u.get("first_name", "Worker"))
        fname_html = sanitize_html(raw_fname)
        uname = u.get("username", "")
        uname_str = f"(@{sanitize_html(uname)})" if uname else "(No Username)"
        is_banned = u.get("banned", False)

        st_badge = "🔴 Banned" if is_banned else "🟢 Active"
        out_msg += f"<b>{i}. {fname_html}</b> {uname_str}\n   🆔 ID: <code>{u_id}</code> | Status: <b>{st_badge}</b>\n\n"

        btn_fname = raw_fname[:10]
        btn_text = f"🔴 {btn_fname} — 🟢 আনব্যান করুন" if is_banned else f"🟢 {btn_fname} — 🚫 ব্যান করুন"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"toggle_ban_{u_id}_{page}"))

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("◀️ আগের পেজ", callback_data=f"um_page_{page - 1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("পরের পেজ ➡️", callback_data=f"um_page_{page + 1}"))

    if nav_row: markup.row(*nav_row)

    if message_id:
        try: bot.edit_message_text(out_msg, admin_chat_id, message_id, reply_markup=markup)
        except Exception: bot.send_message(admin_chat_id, out_msg, reply_markup=markup)
    else:
        bot.send_message(admin_chat_id, out_msg, reply_markup=markup)

# ================= 6. Background Daemon =================

def escrow_daemon():
    while True:
        try: time.sleep(3600)
        except Exception: pass

threading.Thread(target=escrow_daemon, daemon=True).start()

# ================= 7. Flask Webhook Server =================

flask_app = Flask(__name__)

@flask_app.route('/')
def flask_home(): return "OEB NEXUS Cyber-AI Production Engine Active!"

@flask_app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
            return '', 200
    except Exception as e:
        log_ai_report("Webhook Exception", str(e), "Handled via webhook safety wrapper.")
    abort(403)

# ================= 8. Core Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
            return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

        if is_user_banned(chat_id): return bot.reply_to(message, "🔴 <b>আপনার অ্যাকাউন্টটি স্থগিত (Banned) করা হয়েছে!</b>")

        user = get_user_data(chat_id)
        if message.from_user.username: update_user_field(chat_id, "username", message.from_user.username)
        user_states.pop(chat_id, None)

        if not check_force_join(chat_id):
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
            markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
            return bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)

        fname = sanitize_html(message.from_user.first_name)
        bal = float(user.get("balance") or 0.0)
        hold_bal = float(user.get("hold_balance") or 0.0)

        welcome_card = (
            f"❖ <b>OEB NEXUS // SECURE CORE v6.0</b>\n\n"
            f"👤 <b>Operator:</b> {fname[:18]}\n"
            f"🆔 <b>User ID:</b> <code>#{chat_id}</code>\n\n"
            f"💳 <b>Wallet:</b> ৳ {bal:.2f} BDT\n"
            f"⏳ <b>Escrow:</b> ৳ {hold_bal:.2f} BDT\n"
            f"🛡 <b>Status:</b> 🟢 Active Staff\n\n"
            f"────────────────────────\n"
            f"⚡ <i>Select an option from the terminal below:</i>"
        )

        bot.send_message(chat_id, welcome_card, reply_markup=main_bottom_keyboard(chat_id))
    except Exception as e: log_ai_report("Start Handler Error", str(e), "Caught gracefully.")

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    try: _process_callbacks(call)
    except Exception as e: log_ai_report("Callback Error", f"Failed on {call.data}: {str(e)}", "Silenced to prevent crash.")

def _process_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data

    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        try: bot.answer_callback_query(call.id, "🛠 বটের সার্ভার আপডেটের কাজ চলছে! দয়া করে কিছুক্ষণ পর চেষ্টা করুন.", show_alert=True)
        except Exception: pass
        return

    if code == "verify_join":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        else: bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!")

    elif code.startswith("w_method_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        method = code.replace("w_method_", "")
        method_name = "bKash" if method == "bkash" else "Binance Pay ID"
        
        user_states[chat_id] = {
            'step': 'AWAITING_WITHDRAW_ACCOUNT',
            'method': method_name
        }
        
        prompt = f"📱 <b>আপনার {method_name} নাম্বার/আইডিটি লিখুন:</b>" if method == "bkash" else f"🔶 <b>আপনার {method_name} টি টাইপ করুন:</b>"
        bot.edit_message_text(prompt, chat_id, call.message.message_id)

    elif code.startswith("w_appr_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        w_id = code.replace("w_appr_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Approved"}})
            bot.edit_message_text(f"✅ <b>WITHDRAWAL APPROVED</b>\nID: <code>{w_id}</code>\nWorker: <code>{w_doc['chat_id']}</code>\nAmount: ৳{w_doc['amount']:.2f}", chat_id, call.message.message_id)
            try:
                bot.send_message(w_doc['chat_id'], f"🎉 <b>আপনার উইথড্র রিকোয়েস্ট সফলভাবে এপ্রুভ হয়েছে!</b>\n💳 মেথড: {w_doc['method']}\n💰 পরিমাণ: ৳{w_doc['amount']:.2f} BDT\n\nএডমিন আপনার পেমেন্ট পাঠিয়ে দিয়েছেন। ধন্যবাদ!")
            except Exception: pass

    elif code.startswith("w_rej_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        w_id = code.replace("w_rej_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": w_doc['chat_id']}, {"$inc": {"balance": w_doc['amount']}})
            bot.edit_message_text(f"❌ <b>WITHDRAWAL REJECTED & REFUNDED</b>\nID: <code>{w_id}</code>\nWorker: <code>{w_doc['chat_id']}</code>", chat_id, call.message.message_id)
            try:
                bot.send_message(w_doc['chat_id'], f"❌ <b>আপনার উইথড্র রিকোয়েস্ট বাতিল করা হয়েছে!</b>\nআপনার কেটে নেওয়া ৳{w_doc['amount']:.2f} BDT ব্যালেন্সে ফেরত দেওয়া হয়েছে।")
            except Exception: pass

    elif code == "trigger_add_cat" and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        user_states[chat_id] = {'step': 'AWAITING_NEW_CAT_NAME'}
        bot.send_message(ADMIN_ID, "📝 <b>নতুন ক্যাটাগরির নাম লিখুন:</b>\n\nউদাহরণস্বরূপ: <code>TikTok Cookies</code> অথবা <code>FB Page Task</code>", reply_markup=cancel_keyboard())

    elif code == "save_pass_default":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        user = get_user_data(chat_id)
        temp_pass = user.get("temp_pending_password", "")
        p_rule = str(get_setting("pass_rule", "")).strip()
        
        if temp_pass:
            if p_rule and p_rule.lower() != "none" and not validate_strict_password(temp_pass, p_rule):
                bot.edit_message_text(f"❌ <b>পাসওয়ার্ড সেভ করা সম্ভব হয়নি!</b>\nপাসওয়ার্ডের একদম শেষে আজকের নিয়ম (<code>{sanitize_html(p_rule)}</code>) নেই।", chat_id, call.message.message_id)
            else:
                update_user_field(chat_id, "custom_password", temp_pass)
                update_user_field(chat_id, "temp_pending_password", "")
                bot.edit_message_text(f"✅ <b>সফল!</b> আপনার পাসওয়ার্ডটি ডিফল্ট হিসেবে সেভ করা হয়েছে: <code>{sanitize_html(temp_pass)}</code>", chat_id, call.message.message_id)
        else:
            bot.edit_message_text("⚠️ কোনো পেন্ডিং পাসওয়ার্ড পাওয়া যায়নি!", chat_id, call.message.message_id)

    elif code == "user_set_custom_pass":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        p_rule = str(get_setting("pass_rule", "")).strip()
        user_states[chat_id] = {'step': 'AWAITING_USER_SET_PASS'}
        msg = f"✏️ <b>আপনার নতুন পছন্দমতো ডিফল্ট পাসওয়ার্ডটি লিখে পাঠান:</b>\n"
        if p_rule and p_rule.lower() != "none":
            msg += f"\n⚠️ <i>মনে রাখবেন: পাসওয়ার্ডের <b>একদম শেষে</b> আজকের সিকিউরিটি কোড (<code>{sanitize_html(p_rule)}</code>) থাকা বাধ্যতামূলক!</i>"
        bot.send_message(chat_id, msg, reply_markup=cancel_keyboard())

    elif code == "user_remove_custom_pass":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        update_user_field(chat_id, "custom_password", "")
        bot.edit_message_text("🗑️ <b>আপনার সেভ করা ডিফল্ট পাসওয়ার্ড সফলভাবে মুছে ফেলা হয়েছে!</b>", chat_id, call.message.message_id)

    elif code.startswith("del_cat_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        cat_key = code.replace("del_cat_", "")
        custom_cats = get_setting("custom_categories", {})
        if cat_key in custom_cats:
            del_name = custom_cats[cat_key].get("name")
            del custom_cats[cat_key]
            update_setting("custom_categories", custom_cats)
            bot.send_message(ADMIN_ID, f"🗑️ <b>{del_name}</b> ক্যাটাগরি সফলভাবে মুছে ফেলা হয়েছে!", reply_markup=admin_bottom_keyboard())

    elif code.startswith("edit_cat_rate_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        cat_key = code.replace("edit_cat_rate_", "")
        user_states[chat_id] = {'step': 'AWAITING_CUSTOM_CAT_RATE_EDIT', 'cat_key': cat_key}
        bot.send_message(ADMIN_ID, f"✏️ <b>{cat_key}</b> এর নতুন রেট টাইপ করুন (যেমন: 12.0):", reply_markup=cancel_keyboard())

    elif code.startswith("gen_prof_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        country = code.replace("gen_prof_", "")
        msg_text, markup = generate_profile_data(country)
        try: bot.edit_message_text(msg_text, chat_id, call.message.message_id, reply_markup=markup)
        except Exception: bot.send_message(chat_id, msg_text, reply_markup=markup)

    elif code.startswith("um_page_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        target_page = int(code.replace("um_page_", ""))
        render_user_manager_page(ADMIN_ID, call.message.message_id, target_page)

    elif code.startswith("toggle_ban_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        target_uid = int(parts[2])
        target_page = int(parts[3])

        user_doc = users_col.find_one({"_id": target_uid})
        if user_doc:
            curr_ban = user_doc.get("banned", False)
            new_ban = not curr_ban
            users_col.update_one({"_id": target_uid}, {"$set": {"banned": new_ban}})
            st_text = "ব্যান (Block)" if new_ban else "আনব্যান (Unblock)"
            try: bot.answer_callback_query(call.id, f"✅ ইউজার {target_uid} সফলভাবে {st_text} করা হয়েছে!", show_alert=False)
            except Exception: pass

        render_user_manager_page(ADMIN_ID, call.message.message_id, target_page)

    elif code.startswith("dash_dt_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        selected_date = code.replace("dash_dt_", "")
        
        cats = ["fb_cookie", "fb_2fa", "ig_cookie", "ig_2fa"]
        cat_names = {"fb_cookie": "📄 FB Cookies", "fb_2fa": "🔐 FB 2FA", "ig_cookie": "📷 IG Cookies", "ig_2fa": "🔐 IG 2FA"}
        
        out = f"📊 <b>BATCH REPORT // {selected_date}</b>\n\n"
        total_date_hold = 0
        
        for c in cats:
            base_q = build_date_query(selected_date)
            hold_q = base_q.copy(); hold_q["status"] = "Hold"; hold_q["category_key"] = c
            appr_q = base_q.copy(); appr_q["status"] = "Approved"; appr_q["category_key"] = c
            rej_q = base_q.copy(); rej_q["status"] = "Rejected"; rej_q["category_key"] = c
            
            hold_c = submissions_col.count_documents(hold_q)
            appr_c = submissions_col.count_documents(appr_q)
            rej_c = submissions_col.count_documents(rej_q)
            tot = hold_c + appr_c + rej_c
            
            p_bar = make_progress_bar(appr_c + rej_c, tot, length=8)
            out += f"• <b>{cat_names[c]}</b>: [{p_bar}] (⏳{hold_c} / ✅{appr_c})\n"
            total_date_hold += hold_c

        out += f"\n────────────────────────\n📌 <b>Total Pending Hold:</b> {total_date_hold}"
        
        markup = InlineKeyboardMarkup(row_width=2)
        if total_date_hold > 0:
            markup.add(InlineKeyboardButton(f"📥 {selected_date} এর রিপোর্ট মেলান", callback_data=f"bm_select_date_{selected_date}"))
            markup.add(InlineKeyboardButton(f"📂 {selected_date} এক্সপোর্ট করুন", callback_data=f"exp_select_date_{selected_date}"))
            markup.add(InlineKeyboardButton(f"🔒 ফোর্স ক্লোজ ({selected_date})", callback_data=f"force_close_{selected_date}"))
        else:
            markup.add(InlineKeyboardButton("🔒 ব্যাচ লকড & কমপ্লিট", callback_data="none_locked"))
            
        bot.send_message(ADMIN_ID, out, reply_markup=markup)

    elif code.startswith("force_close_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        target_date = code.replace("force_close_", "")
        stuck_q = build_date_query(target_date, "Hold")
        stuck_subs = list(submissions_col.find(stuck_q))
        
        for sub in stuck_subs:
            amt = float(sub.get("rate") or 0.0)
            submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -amt}})
            try: bot.send_message(sub["chat_id"], f"⚠️ <b>{target_date}</b> এর ঝুলে থাকা আইডিটি (<code>{sub['uid']}</code>) এডমিন কর্তৃক ক্লিয়ার করে রিজেক্ট করা হয়েছে।")
            except Exception: pass
            
        bot.send_message(ADMIN_ID, f"🔒 <b>{target_date}</b> তারিখের অবশিষ্ট {len(stuck_subs)} টি ঝুলে থাকা কাজ ফোর্স ক্লোজ করা হয়েছে!")

    elif code.startswith("bm_select_date_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        target_date = code.replace("bm_select_date_", "")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📄 FB Cookies", callback_data=f"bm_cat_{target_date}_fb_cookie"),
            InlineKeyboardButton("🔐 FB 2FA", callback_data=f"bm_cat_{target_date}_fb_2fa"),
            InlineKeyboardButton("📷 IG Cookies", callback_data=f"bm_cat_{target_date}_ig_cookie"),
            InlineKeyboardButton("🔐 IG 2FA", callback_data=f"bm_cat_{target_date}_ig_2fa")
        )
        custom_cats = get_setting("custom_categories", {})
        for ck, ci in custom_cats.items():
            markup.add(InlineKeyboardButton(f"📌 {ci.get('name')}", callback_data=f"bm_cat_{target_date}_{ck}"))

        markup.add(InlineKeyboardButton("🌐 সব ক্যাটাগরি একসাথে", callback_data=f"bm_cat_{target_date}_ALL"))
        bot.send_message(ADMIN_ID, f"🤖 <b>[{target_date}]</b> তারিখের কোন ক্যাটাগরির বায়ার রিপোর্ট মেলাবেন?", reply_markup=markup)

    elif code.startswith("bm_cat_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        parts = code.split("_")
        target_date = parts[2]
        cat_key = "_".join(parts[3:])
        user_states[ADMIN_ID] = {'step': 'AWAITING_BUYER_REPORT', 'target_date': target_date, 'target_cat': cat_key}
        bot.send_message(ADMIN_ID, f"📄 <b>[{target_date} | {cat_key}]</b> এর বায়ার রিপোর্ট ফাইলটি (Excel / CSV / Text) সেন্ড করুন:", reply_markup=cancel_keyboard())

    elif code.startswith("exp_select_date_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        target_date = code.replace("exp_select_date_", "")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📄 FB Cookies", callback_data=f"exp_final_{target_date}_fb_cookie"),
            InlineKeyboardButton("🔐 FB 2FA", callback_data=f"exp_final_{target_date}_fb_2fa"),
            InlineKeyboardButton("📷 IG Cookies", callback_data=f"exp_final_{target_date}_ig_cookie"),
            InlineKeyboardButton("🔐 IG 2FA", callback_data=f"exp_final_{target_date}_ig_2fa")
        )
        custom_cats = get_setting("custom_categories", {})
        for ck, ci in custom_cats.items():
            markup.add(InlineKeyboardButton(f"📌 {ci.get('name')}", callback_data=f"exp_final_{target_date}_{ck}"))

        markup.add(InlineKeyboardButton("🌐 সব ক্যাটাগরি", callback_data=f"exp_final_{target_date}_ALL"))
        bot.send_message(ADMIN_ID, f"📂 <b>[{target_date}]</b> তারিখের কোন ক্যাটাগরির ডাটা এক্সপোর্ট করবেন?", reply_markup=markup)

    elif code.startswith("exp_final_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        parts = code.split("_")
        target_date = parts[2]
        cat_key = "_".join(parts[3:])
        
        bot.send_message(ADMIN_ID, f"⏳ <b>[{target_date}]</b> এর <code>{cat_key}</code> ডাটা এক্সপোর্ট করা হচ্ছে...")
        
        query = build_date_query(target_date, "Hold")
        if cat_key != "ALL": query["category_key"] = cat_key
        
        records = list(submissions_col.find(query))
        if not records:
            return bot.send_message(ADMIN_ID, f"📭 <b>[{target_date}]</b> এর <code>{cat_key}</code> ক্যাটাগরিতে কোনো পেন্ডিং ডাটা নেই!")
            
        df_data = [{"UID": r.get("uid", ""), "Password": r.get("password", ""), "Payload": r.get("payload", ""), "Category": r.get("category", "")} for r in records]
        df = pd.DataFrame(df_data)
        filename = f"Export_{target_date}_{cat_key}_{get_bd_time().strftime('%H%M')}"
        
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Data')
        buf.seek(0)
        bot.send_document(ADMIN_ID, (f"{filename}.xlsx", buf), caption=f"📊 <b>[{target_date}]</b> এক্সপোর্ট প্রস্তুত!\nক্যাটাগরি: <code>{cat_key}</code>\nমোট আইডি: {len(records)} টি")

    elif code == "appr_all_pending" and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
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
        try: bot.answer_callback_query(call.id)
        except Exception: pass
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
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        track_id = code.replace("rej_", "")
        sub = submissions_col.find_one({"track_id": track_id})
        if sub and sub.get("status") == "Hold":
            amt = float(sub.get("rate") or 0.0)
            submissions_col.update_one({"track_id": track_id}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -amt}})
            bot.edit_message_text(f"❌ <b>REJECTED</b> | Track ID: <code>{track_id}</code>", chat_id, call.message.message_id)
            try: bot.send_message(sub["chat_id"], f"❌ আপনার সাবমিশন (<code>{track_id}</code>) বাতিল করা হয়েছে।")
            except Exception: pass

    elif code.startswith("edit_sub_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        track_id = code.replace("edit_sub_", "")
        sub = submissions_col.find_one({"track_id": track_id, "chat_id": chat_id, "status": "Hold"})
        if not sub: return bot.send_message(chat_id, "⚠️ এই কাজটির এডিট মেয়াদ শেষ হয়ে গেছে বা ইতিমধ্যেই প্রসেস করা হয়েছে।")
        user_states[chat_id] = {'step': 'AWAITING_EDIT_PAYLOAD', 'track_id': track_id}
        bot.send_message(chat_id, f"✏️ <b>Track ID: {track_id}</b> এর জন্য সঠিক Cookies বা 2FA Key পেস্ট করুন:", reply_markup=cancel_keyboard())

    elif code.startswith("check_otp_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
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
                bot.send_message(chat_id, f"✉️ <b>OTP Received!</b>\n🔑 Code: <code>{otp_code}</code>\n\n📄 <b>Msg:</b> {sanitize_html(body[:300])}")
        except Exception: bot.send_message(chat_id, "⚠️ ওটিপি চেক করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

    elif code.startswith("lb_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        tf = code.replace("lb_", "")
        now = get_bd_time()
        if tf == "daily": query = {"date_str": {"$regex": f"^{now.strftime('%Y-%m-%d')}"}}; title = "আজকের সেরা"
        elif tf == "weekly": query = {"date_obj": {"$gte": now - timedelta(days=7)}}; title = "এই সপ্তাহের সেরা"
        else: query = {}; title = "সর্বকালের সেরা"

        pipeline = [{"$match": query}, {"$group": {"_id": "$worker_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]
        top = list(submissions_col.aggregate(pipeline))
        
        out = f"🏆 <b>LEADERBOARD // {title}</b>\n\n"
        badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, item in enumerate(top): out += f"{badges[i]} <b>{sanitize_html(item['_id'])}</b> — {item['count']} টি\n"
        
        user_cnt = submissions_col.count_documents({"chat_id": chat_id})
        out += f"\n────────────────────────\n🎯 <b>Your Submissions:</b> {user_cnt}"
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"), InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"), InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime"))
        bot.edit_message_text(out, chat_id, call.message.message_id, reply_markup=markup)

    elif code.startswith("surge_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        act = code.replace("surge_", "")
        if act == "off":
            update_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
            bot.send_message(ADMIN_ID, "🛑 <b>সার্জ বোনাস বন্ধ করা হয়েছে।</b>")
        else:
            hrs = int(act)
            exp_time = get_bd_time() + timedelta(hours=hrs)
            update_setting("surge_pricing", {"active": True, "bonus": 2.0, "expires_at": exp_time.isoformat()})
            bot.send_message(ADMIN_ID, f"⚡ <b>+৳২.০০ সার্জ বোনাস {hrs} ঘণ্টার জন্য চালু করা হয়েছে!</b>")

    elif code.startswith("rate_edit_") and chat_id == ADMIN_ID:
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        cat_key = code.replace("rate_edit_", "")
        user_states[chat_id] = {'step': 'AWAITING_NEW_RATE', 'category_key': cat_key}
        bot.send_message(ADMIN_ID, f"✏️ <b>{cat_key}</b> এর নতুন মূল্য লিখুন (যেমন: 6.5):", reply_markup=cancel_keyboard())

# --- FILE/DOCUMENT ROUTER ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    try: _process_document(message)
    except Exception as e:
        log_ai_report("File Parse Error", str(e), "Caught exception gracefully.")
        bot.reply_to(message, "❌ ফাইলটি পড়তে সমস্যা হয়েছে। দয়া করে সঠিক ফরম্যাটে ফাইল দিন.", reply_markup=main_bottom_keyboard(message.chat.id))

def _process_document(message):
    chat_id = message.chat.id

    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

    if is_user_banned(chat_id): return
    state = user_states.get(chat_id)
    
    if state and state.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
        target_date = state.get('target_date', 'ALL')
        target_cat = state.get('target_cat', 'ALL')
        user_states.pop(chat_id, None)
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = message.document.file_name.lower()
        extracted_uids = set()
        
        if filename.endswith(".csv"): 
            df_raw = pd.read_csv(io.BytesIO(downloaded), dtype=str)
            extracted_uids = set(df_raw.astype(str).values.flatten())
        elif filename.endswith(".xlsx"): 
            df_raw = pd.read_excel(io.BytesIO(downloaded), dtype=str)
            extracted_uids = set(df_raw.astype(str).values.flatten())
        else: 
            extracted_uids = set(re.findall(r'\b\d{8,20}\b', downloaded.decode('utf-8', errors='ignore')))
            
        cleaned_uids = set()
        for u in extracted_uids:
            clean_u = str(u).strip().split('.')[0]
            if clean_u.isdigit(): cleaned_uids.add(clean_u)
        
        query = build_date_query(target_date, "Hold")
        if target_cat != "ALL": query["category_key"] = target_cat
        
        pending_subs = list(submissions_col.find(query))
        if not pending_subs:
            return bot.send_message(ADMIN_ID, f"📭 <b>[{target_date} | {target_cat}]</b> এর কোনো পেন্ডিং কাজ খুঁজে পাওয়া যায়নি!", reply_markup=admin_bottom_keyboard())

        appr, rej, payout = 0, 0, 0.0
        notifications = []
        
        for sub in pending_subs:
            uid = str(sub.get("uid", "")).strip()
            amt = float(sub.get("rate") or 0.0)
            if uid in cleaned_uids:
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
                users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                appr += 1; payout += amt
                notifications.append((sub["chat_id"], f"✅ বায়ার রিপোর্টে আপনার আইডি (<code>{uid}</code>) এপ্রুভ হয়েছে! ৳{amt} যোগ হয়েছে।"))
            else:
                submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": sub["chat_id"]}, {"$inc": {"hold_balance": -amt}})
                rej += 1
                notifications.append((sub["chat_id"], f"❌ বায়ার রিপোর্টে আপনার আইডি (<code>{uid}</code>) রিজেক্টেড।"))
                
        def send_async_notifications(notification_list):
            for worker_id, text_msg in notification_list:
                try:
                    bot.send_message(worker_id, text_msg)
                    time.sleep(0.05)
                except ApiTelegramException as e:
                    if e.error_code == 429:
                        time.sleep(e.result_json.get('parameters', {}).get('retry_after', 3))
                except Exception: pass

        background_executor.submit(lambda: send_async_notifications(notifications))

        return bot.send_message(
            ADMIN_ID, 
            f"🤖 <b>[BUYER REPORT MATCH COMPLETE]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 তারিখ: <b>{target_date}</b> | 📁 ক্যাটাগরি: <b>{target_cat}</b>\n"
            f"✅ এপ্রুভড: <b>{appr} টি</b> (৳{payout:.2f}) | ❌ রিজেক্টেড: <b>{rej} টি</b>", 
            reply_markup=admin_bottom_keyboard()
        )

    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        user = get_user_data(chat_id)
        saved_pass = user.get("custom_password")
        p_rule = str(get_setting("pass_rule", "")).strip()

        password_to_use = saved_pass if (saved_pass and str(saved_pass).strip() != "" and str(saved_pass).lower() != "none") else p_rule

        if p_rule and p_rule.lower() != "none" and not validate_strict_password(password_to_use, p_rule):
            ai_warn = generate_strict_ai_warning(
                "আপনার এক্সেল ফাইলের জন্য ডিফল্ট পাসওয়ার্ডটি গ্রহণ করা হয়নি!",
                f"পাসওয়ার্ডটির (<code>{sanitize_html(password_to_use)}</code>) একদম শেষে আজকের সিকিউরিটি কোড '<code>{sanitize_html(p_rule)}</code>' অনুপস্থিত।",
                f"একাউন্ট খোলার সময়ই পাসওয়ার্ডের 'একদম শেষে' '<code>{sanitize_html(p_rule)}</code>' বসিয়ে একাউন্ট খুলুন এবং সেই পাসওয়ার্ডটি সেভ করুন। ভুল পাসওয়ার্ড দিলে একাউন্ট ব্যাক/রিজেক্ট হবে!",
                "আইডি খোলার আগেই '⚙️ পাসওয়ার্ড নিয়ম' সেকশনে গিয়ে আজকের সিকিউরিটি কোড মেনে পাসওয়ার্ড সেভ করে ফাইল আপলোড দিন."
            )
            return bot.reply_to(message, ai_warn, reply_markup=submit_tasks_keyboard())

        user_states.pop(chat_id, None)
        file_info = bot.get_file(message.document.file_id)
        orig_file_name = message.document.file_name
        
        now_time = get_bd_time()
        unique_file_name = f"user_{chat_id}_{int(now_time.timestamp())}_{orig_file_name}"
        file_downloaded_bytes = bot.download_file(file_info.file_path)
        
        with open(unique_file_name, 'wb') as f: f.write(file_downloaded_bytes)

        df = pd.read_csv(unique_file_name, dtype=str) if unique_file_name.endswith('.csv') else pd.read_excel(unique_file_name, dtype=str)
        df = df.fillna('')
        success_count, total_earned = 0, 0.0
        now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
        date_key = now_time.strftime("%Y-%m-%d")
        
        sheet_rows = []

        for _, row in df.iterrows():
            vals = [str(x).strip() for x in row.values]
            uid, password, payload = None, password_to_use, None
            for v in vals:
                if not uid and extract_numeric_uid(v): uid = extract_numeric_uid(v)
                elif is_valid_cookies(v) or len(v) > 20: payload = v

            if uid and payload and not is_duplicate_uid(uid):
                p_hash = generate_payload_hash(payload)
                if is_payload_blacklisted(p_hash): continue
                cat_key = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                cat_display = CAT_MAP.get(cat_key, "FB Cookies")
                rate = float(get_current_task_rate(cat_key))
                track_id = generate_tracking_id()

                try:
                    submissions_col.insert_one({
                        "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                        "password": password, "payload": payload, "payload_hash": p_hash, "track_id": track_id,
                        "category": cat_display, "category_key": cat_key,
                        "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
                    })
                    sheet_rows.append([now_str, track_id, str(chat_id), uid, password, payload])
                    success_count += 1; total_earned += rate
                except DuplicateKeyError:
                    continue

        if sheet_rows:
            async_save_batch_to_sheet("Cookies_Data", sheet_rows)

        backup_file_buf = io.BytesIO(file_downloaded_bytes)
        send_private_backup_message(
            f"📊 <b>[PRIVATE BACKUP - Excel Submission]</b>\n"
            f"👤 Worker ID: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
            f"📁 File: <code>{sanitize_html(orig_file_name)}</code> | 🔑 Pass: <code>{sanitize_html(password_to_use)}</code>\n"
            f"✅ Valid: <b>{success_count}</b> টি | 💰 Hold: ৳{total_earned:.2f}",
            doc_buf=backup_file_buf,
            doc_name=f"Backup_{date_key}_{orig_file_name}"
        )

        if os.path.exists(unique_file_name): os.remove(unique_file_name)
        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
        return bot.reply_to(message, f"🎉 <b>ফাইল প্রসেস সম্পন্ন!</b>\n✅ সফল: <b>{success_count}</b> টি | 💰 আর্ন (হোল্ড): ৳{total_earned:.2f}", reply_markup=submit_tasks_keyboard())

# --- MAIN TEXT ROUTER ---
@bot.message_handler(content_types=['text', 'photo', 'video', 'animation'])
def main_router(message):
    try: _process_main_router(message)
    except Exception as e: log_ai_report("Main Router Global Error", str(e), "Caught by shield to prevent crash.")

def _process_main_router(message):
    chat_id = message.chat.id
    
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

    if is_user_banned(chat_id): return
    
    text = ""
    if message.text: text = message.text.strip()
    elif message.caption: text = message.caption.strip()
    
    user = get_user_data(chat_id)

    nav_buttons = [
        "🏠 মেইন মেনু", "🏠 প্রধান মেনু", "🔙 প্রধান মেনু", "🔙 পেছনে যান", "❌ বাতিল করুন", "⚡ কাজ জমা সেন্টার", "💼 টাস্ক ও টুলস", "📋 কাজ জমা দিন", "🛠 হেল্পার টুলস", 
        "📌 সিঙ্গেল জমা", "👤 প্রোফাইল ও ওয়ালেট", "👤 আমার অ্যাকাউন্ট", "🎁 রিওয়ার্ড ও সাপোর্ট", "🎁 বোনাস ও সাপোর্ট", "👑 এডমিন কন্ট্রোল সেন্টার", "👑 এডমিন প্যানেল", "💳 Withdraw", 
        "🪪 ভেরিফাইড আইডি কার্ড", "🎁 Claim Daily Bonus", "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", 
        "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🔑 2FA কোড জেনারেটর", 
        "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "✉️ টেম্প ইমেইল", "👤 র্যান্ডম প্রোফাইল জেনারেটর", 
        "📜 কাজের ইতিহাস", "👤 ইউজার ম্যানেজার", "🤖 বায়ার রিপোর্ট অটো-ম্যাচার", 
        "🧠 AI সিটেডেল অডিট", "📢 ব্রডকাস্ট নোটিশ", "⚙️ সেট রেট ও চার্জ", "🔑 পাসওয়ার্ড নিয়ম সেট",
        "📊 স্মার্ট ড্যাশবোর্ড ও রিপোর্ট", "📂 স্মার্ট ফাইল এক্সপোর্ট", "🏛️ আর্কাইভ ও বন্ধ ফাইল", "⏳ ম্যানুয়াল পেন্ডিং চেক",
        "🔙 টাস্ক মেনুতে ফিরুন", "🔙 কাজ জমা মেনুতে ফিরুন", "➕ নতুন ক্যাটাগরি যোগ করুন", "⚙️ কাস্টম ক্যাটাগরি প্যানেল",
        "📊 টাস্ক ও রিপোর্ট ম্যানেজমেন্ট", "💳 ফাইন্যান্স ও উইথড্র", "⚙️ সেটিংস ও কনফিগারেশন", "📢 ইউজার ও সিস্টেম কন্ট্রোল", "🔙 এডমিন প্যানেল"
    ]

    current_state = user_states.get(chat_id) or {}
    if not isinstance(current_state, dict):
        current_state = {}

    if text in nav_buttons or text.startswith("🛠 মেইনটেনেন্স:") or text.startswith("⏳ পেন্ডিং উইথড্রয়াল চেক"):
        user_states.pop(chat_id, None)

    if text == "❌ বাতিল করুন":
        step = current_state.get('step')
        if step in ['AWAITING_UID', 'AWAITING_SINGLE_DATA', 'AWAITING_MANUAL_PASSWORD', 'AWAITING_BULK_TEXT', 'AWAITING_EXCEL_FILE', 'AWAITING_USER_SET_PASS', 'AWAITING_CUSTOM_FIELD']:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে 'কাজ জমা' মেনুতে ফিরে আসা হয়েছে।", reply_markup=submit_tasks_keyboard())
        elif step in ['AWAITING_2FA_GEN', 'AWAITING_BULK_FB_CHECK', 'AWAITING_BULK_IG_CHECK']:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে 'টুলস' মেনুতে ফিরে আসা হয়েছে।", reply_markup=helper_tools_keyboard())
        elif step in ['AWAITING_WITHDRAW_ACCOUNT', 'AWAITING_WITHDRAW_AMOUNT']:
            return bot.send_message(chat_id, "❌ উইথড্র প্রক্রিয়া বাতিল করা হয়েছে।", reply_markup=account_keyboard())
        elif step in ['AWAITING_BROADCAST_MSG', 'AWAITING_BUYER_REPORT', 'AWAITING_NEW_RATE', 'AWAITING_ADMIN_PASS_RULE', 'AWAITING_NEW_CAT_NAME', 'AWAITING_NEW_CAT_FIELDS', 'AWAITING_NEW_CAT_RATE', 'AWAITING_CUSTOM_CAT_RATE_EDIT']:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে এডমিন প্যানেলে ফিরে আসা হয়েছে।", reply_markup=admin_bottom_keyboard())
        elif step == 'AWAITING_SUPPORT_MSG':
            return bot.send_message(chat_id, "❌ টিকিট প্রক্রিয়া বাতিল করা হয়েছে।", reply_markup=bonus_support_keyboard())
        elif step == 'AWAITING_EDIT_PAYLOAD':
            return bot.send_message(chat_id, "❌ এডিট বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))
        else:
            return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে প্রধান মেনুতে ফিরে আসা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))

    if text in ["🏠 মেইন মেনু", "🏠 প্রধান মেনু", "🔙 প্রধান মেনু"]:
        fname = sanitize_html(message.from_user.first_name)
        bal = float(user.get("balance") or 0.0)
        hold_bal = float(user.get("hold_balance") or 0.0)

        welcome_card = (
            f"❖ <b>OEB NEXUS // SECURE CORE v6.0</b>\n\n"
            f"👤 <b>Operator:</b> {fname[:18]}\n"
            f"🆔 <b>User ID:</b> <code>#{chat_id}</code>\n\n"
            f"💳 <b>Wallet:</b> ৳ {bal:.2f} BDT\n"
            f"⏳ <b>Escrow:</b> ৳ {hold_bal:.2f} BDT\n"
            f"🛡 <b>Status:</b> 🟢 Active Staff\n\n"
            f"────────────────────────\n"
            f"⚡ <i>Select an option from the terminal below:</i>"
        )
        return bot.send_message(chat_id, welcome_card, reply_markup=main_bottom_keyboard(chat_id))

    elif text in ["⚡ কাজ জমা সেন্টার", "🔙 টাস্ক মেনুতে ফিরুন", "💼 টাস্ক ও টুলস", "🔙 পেছনে যান"]:
        return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ বেছে নিন:</b>", reply_markup=submit_tasks_keyboard())
    elif text in ["📋 কাজ জমা দিন"]: return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ বেছে নিন:</b>", reply_markup=submit_tasks_keyboard())
    
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>আপনার প্রয়োজনীয় টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
    elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard())
    
    elif text in ["👤 প্রোফাইল ও ওয়ালেট", "👤 আমার অ্যাকাউন্ট"]:
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = float(user.get("balance") or 0.0)
        hold_bal = float(user.get("hold_balance") or 0.0)
        safe_name = sanitize_html(message.from_user.first_name)
        badge_title, trust_pct = calculate_worker_trust_score(chat_id)
        
        prof_card = (
            f"👤 <b>USER PROFILE & WALLET</b>\n\n"
            f"• <b>Name:</b> {safe_name[:18]}\n"
            f"• <b>Badge:</b> {badge_title} ({trust_pct}%)\n"
            f"• <b>Tasks Done:</b> {cnt} Tasks\n\n"
            f"💳 <b>Main Wallet:</b> ৳ {bal:.2f} BDT\n"
            f"⏳ <b>Escrow Hold:</b> ৳ {hold_bal:.2f} BDT\n\n"
            f"🔗 <b>Ref Link:</b> https://t.me/{BOT_USERNAME}?start={chat_id}"
        )
        return bot.send_message(chat_id, prof_card, reply_markup=account_keyboard())

    elif text in ["🎁 রিওয়ার্ড ও সাপোর্ট", "🎁 বোনাস ও সাপোর্ট"]:
        return bot.send_message(chat_id, "🎁 <b>বোনাস ও সাপোর্ট সেন্টার:</b>", reply_markup=bonus_support_keyboard())

    elif text in ["👑 এডমিন কন্ট্রোল সেন্টার", "👑 এডমিন প্যানেল", "🔙 এডমিন প্যানেল"] and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, "👑 <b>ADMIN CONTROL CENTER</b>\nপ্রধান ক্যাটাগরি বেছে নিন:", reply_markup=admin_bottom_keyboard())

    elif text == "📊 টাস্ক ও রিপোর্ট ম্যানেজমেন্ট" and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, "📊 <b>টাস্ক ও রিপোর্ট ম্যানেজমেন্ট প্যানেল:</b>", reply_markup=admin_sub_task_keyboard())

    elif text == "💳 ফাইন্যান্স ও উইথড্র" and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, "💳 <b>ফাইন্যান্স ও উইথড্র ম্যানেজমেন্ট প্যানেল:</b>", reply_markup=admin_sub_finance_keyboard())

    elif text == "⚙️ সেটিংস ও কনফিগারেশন" and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, "⚙️ <b>সেটিংস ও কনফিগারেশন প্যানেল:</b>", reply_markup=admin_sub_settings_keyboard())

    elif text == "📢 ইউজার ও সিস্টেম কন্ট্রোল" and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, "📢 <b>ইউজার ও সিস্টেম কন্ট্রোল প্যানেল:</b>", reply_markup=admin_sub_system_keyboard())

    elif text.startswith("⏳ পেন্ডিং উইথড্রয়াল চেক") and chat_id == ADMIN_ID:
        pending_ws = list(withdrawals_col.find({"status": "Pending"}).limit(5))
        if not pending_ws:
            return bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং উইথড্র রিকোয়েস্ট নেই!", reply_markup=admin_sub_finance_keyboard())
        
        bot.send_message(ADMIN_ID, f"⏳ <b>পেন্ডিং উইথড্রয়াল লিস্ট পর্যালোচনা:</b>", reply_markup=admin_sub_finance_keyboard())
        for w in pending_ws:
            item_markup = InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("✅ Approve", callback_data=f"w_appr_{w['withdraw_id']}"),
                InlineKeyboardButton("❌ Reject & Refund", callback_data=f"w_rej_{w['withdraw_id']}")
            )
            w_msg = (
                f"💳 <b>Withdraw ID:</b> <code>{w['withdraw_id']}</code>\n"
                f"👤 <b>Worker ID:</b> <code>{w['chat_id']}</code>\n"
                f"📱 <b>Method:</b> {w['method']} ({w['account']})\n"
                f"💰 <b>Amount:</b> ৳{w['amount']:.2f} BDT\n"
                f"⏰ <b>Time:</b> {w['time']}"
            )
            bot.send_message(ADMIN_ID, w_msg, reply_markup=item_markup)
        return

    elif text == "💳 Withdraw":
        bal = float(user.get("balance") or 0.0)
        if bal < 50.0: 
            return bot.send_message(chat_id, f"⚠️ <b>সর্বনিম্ন উইথড্র ৳৫০.০০ BDT!</b>\n\n💳 আপনার বর্তমান ব্যালেন্স: <b>৳{bal:.2f} BDT</b>", reply_markup=account_keyboard())
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 বিকাশ (bKash)", callback_data="w_method_bkash"),
            InlineKeyboardButton("🔶 বাইনান্স (Binance ID)", callback_data="w_method_binance")
        )
        return bot.send_message(chat_id, f"💳 <b>উইথড্র মেথড সিলেক্ট করুন:</b>\n\n💰 আপনার উত্তোলনে যোগ্য ব্যালেন্স: <b>৳{bal:.2f} BDT</b>", reply_markup=markup)

    elif text == "⚙️ কাস্টম ক্যাটাগরি প্যানেল" and chat_id == ADMIN_ID:
        custom_cats = get_setting("custom_categories", {})
        if not custom_cats:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("➕ নতুন ক্যাটাগরি যোগ করুন", callback_data="trigger_add_cat"))
            return bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো কাস্টম ক্যাটাগরি তৈরি করা নেই!", reply_markup=markup)

        out_msg = "⚙️ <b>CUSTOM CATEGORY MANAGEMENT PANEL</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        markup = InlineKeyboardMarkup()
        for ck, ci in custom_cats.items():
            out_msg += f"📌 <b>{ci['name']}</b>\n• রেট: ৳{ci['rate']:.2f} BDT | ফিল্ডস: <code>{', '.join(ci['fields'])}</code>\n\n"
            markup.add(
                InlineKeyboardButton(f"✏️ রেট চেঞ্জ ({ci['name']})", callback_data=f"edit_cat_rate_{ck}"),
                InlineKeyboardButton(f"🗑️ ডিলিট", callback_data=f"del_cat_{ck}")
            )
        markup.add(InlineKeyboardButton("➕ নতুন ক্যাটাগরি যোগ করুন", callback_data="trigger_add_cat"))
        return bot.send_message(ADMIN_ID, out_msg, reply_markup=markup)

    elif text == "➕ নতুন ক্যাটাগরি যোগ করুন" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_NEW_CAT_NAME'}
        return bot.send_message(ADMIN_ID, "📝 <b>নতুন ক্যাটাগরির নাম লিখুন:</b>\n\nউদাহরণস্বরূপ: <code>TikTok Cookies</code> অথবা <code>FB Page Task</code>", reply_markup=cancel_keyboard())

    elif text == "📊 স্মার্ট ড্যাশবোর্ড ও রিপোর্ট" and chat_id == ADMIN_ID:
        active_dates = get_active_hold_dates()
        if not active_dates:
            return bot.send_message(ADMIN_ID, "🟢 <b>সবকটি তারিখের বায়ার রিপোর্ট প্রসেস সম্পন্ন!</b>\nবর্তমানে কোনো পেন্ডিং হোল্ড ডাটা নেই।", reply_markup=admin_sub_task_keyboard())
            
        markup = InlineKeyboardMarkup(row_width=2)
        for d in active_dates:
            hold_q = build_date_query(d, "Hold")
            hold_count = submissions_col.count_documents(hold_q)
            markup.add(InlineKeyboardButton(f"📅 {d} (⏳ {hold_count} টি)", callback_data=f"dash_dt_{d}"))
            
        return bot.send_message(ADMIN_ID, "📊 <b>[স্মার্ট তারিখ ভিত্তিক ড্যাশবোর্ড]</b>\nপেন্ডিং কাজ থাকা তারিখসমূহ সিলেক্ট করুন:", reply_markup=markup)

    elif text == "📂 স্মার্ট ফাইল এক্সপোর্ট" and chat_id == ADMIN_ID:
        active_dates = get_active_hold_dates()
        if not active_dates:
            return bot.send_message(ADMIN_ID, "📭 এক্সপোর্ট করার মতো কোনো পেন্ডিং হোল্ড ডাটা নেই!", reply_markup=admin_sub_task_keyboard())
            
        markup = InlineKeyboardMarkup(row_width=2)
        for d in active_dates:
            markup.add(InlineKeyboardButton(f"📁 তারিখ: {d}", callback_data=f"exp_select_date_{d}"))
            
        return bot.send_message(ADMIN_ID, "📂 <b>[স্মার্ট ফাইল এক্সপোর্ট]</b>\nকোন তারিখের ডাটা ডাউনলোড করতে চান?", reply_markup=markup)

    elif text == "🤖 বায়ার রিপোর্ট অটো-ম্যাচার" and chat_id == ADMIN_ID:
        active_dates = get_active_hold_dates()
        if not active_dates:
            return bot.send_message(ADMIN_ID, "📭 বায়ার রিপোর্ট মেলানোর মতো কোনো পেন্ডিং হোল্ড ডাটা নেই!", reply_markup=admin_sub_task_keyboard())
            
        markup = InlineKeyboardMarkup(row_width=2)
        for d in active_dates:
            markup.add(InlineKeyboardButton(f"🎯 {d} তারিখের রিপোর্ট মেলান", callback_data=f"bm_select_date_{d}"))
        markup.add(InlineKeyboardButton("🌐 সব তারিখ একসাথে প্রসেস করুন", callback_data="bm_select_date_ALL"))
        
        return bot.send_message(ADMIN_ID, "🤖 <b>[বায়ার রিপোর্ট অটো-ম্যাচার]</b>\nকোন তারিখের রিপোর্ট প্রসেস করবেন?", reply_markup=markup)

    elif text == "🏛️ আর্কাইভ ও বন্ধ ফাইল" and chat_id == ADMIN_ID:
        all_dates = get_all_recorded_dates()
        if not all_dates: return bot.send_message(ADMIN_ID, "📭 আর্কাইভে কোনো ডাটা পাওয়া যায়নি!", reply_markup=admin_sub_task_keyboard())
        
        markup = InlineKeyboardMarkup(row_width=2)
        for d in all_dates[:10]:
            markup.add(InlineKeyboardButton(f"🏛️ আর্কাইভ: {d}", callback_data=f"dash_dt_{d}"))
            
        return bot.send_message(ADMIN_ID, "🏛️ <b>[আর্কাইভ ও হিস্ট্রি ভল্ট]</b>\nপুরোনো যেকোনো তারিখের রিপোর্ট দেখতে বা এক্সপোর্ট করতে ক্লিক করুন:", reply_markup=markup)

    elif text == "📜 কাজের ইতিহাস":
        subs = list(submissions_col.find({"chat_id": chat_id}).sort("date_obj", -1).limit(5))
        if not subs: return bot.send_message(chat_id, "📭 আপনি এখনো কোনো কাজ জমা দেননি!", reply_markup=account_keyboard())
        out = "📜 <b>আপনার সর্বশেষ জমার ইতিহাস:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        markup = InlineKeyboardMarkup()
        for sub in subs:
            st = sub.get("status")
            st_icon = "⏳ [HOLD]" if st == "Hold" else ("✅ [APPROVED]" if st == "Approved" else "❌ [REJECTED]")
            out += f"{st_icon} <code>{sub['track_id']}</code> | <b>{sub['category']}</b> | ৳{sub['rate']}\n"
            if st == "Hold": markup.add(InlineKeyboardButton(f"✏️ এডিট {sub['track_id']}", callback_data=f"edit_sub_{sub['track_id']}"))
        return bot.send_message(chat_id, out, reply_markup=markup)

    elif text in ["👤 র্যান্ডম নাম জেনারেটর", "👤 র্যান্ডম প্রোফাইল জেনারেটর"]:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("🇧🇩 BD Profile", callback_data="gen_prof_bd"), InlineKeyboardButton("🇺🇸 USA Profile", callback_data="gen_prof_usa"))
        return bot.send_message(chat_id, "👤 <b>কোন দেশের প্রোফাইল জেনারেট করতে চান সিলেক্ট করুন:</b>", reply_markup=markup)

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
        last_bonus_dt = parse_iso_datetime(last_bonus) if last_bonus else None

        if last_bonus_dt and (now - last_bonus_dt) < datetime.timedelta(hours=24):
            return bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টার মধ্যে একবারই বোনাস নেওয়া যায়!", reply_markup=bonus_support_keyboard())
        else:
            new_bal = float(user.get("balance") or 0.0) + 2.0
            update_user_field(chat_id, "balance", new_bal)
            update_user_field(chat_id, "last_bonus_date", now.isoformat())
            return bot.send_message(chat_id, "🎉 আপনি ৳২.০০ বোনাস পেয়েছেন!", reply_markup=bonus_support_keyboard())

    elif text == "🏆 লিডারবোর্ড":
        markup = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("📅 আজকের সেরা", callback_data="lb_daily"), InlineKeyboardButton("🗓️ এই সপ্তাহের সেরা", callback_data="lb_weekly"), InlineKeyboardButton("🏆 সর্বকালের সেরা", callback_data="lb_alltime"))
        return bot.send_message(chat_id, "🏆 <b>লিডারবোর্ড ফিল্টার বেছে নিন:</b>", reply_markup=markup)

    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        return bot.send_message(chat_id, "💬 <b>আপনার বার্তাটি লিখুন:</b>", reply_markup=cancel_keyboard())

    elif text == "🪪 ভেরিফাইড আইডি কার্ড":
        safe_name = sanitize_html(message.from_user.first_name)
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        buf = generate_worker_badge_image_py(chat_id, safe_name, cnt)
        return bot.send_photo(chat_id, buf, caption="🪪 <b>আপনার ভেরিফাইড আইডি কার্ড!</b>", reply_markup=account_keyboard())

    elif text == "🔑 পাসওয়ার্ড নিয়ম সেট" and chat_id == ADMIN_ID:
        curr_rule = get_setting("pass_rule", "@21")
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_PASS_RULE'}
        return bot.send_message(chat_id, f"🔑 <b>আজকের পাসওয়ার্ড সিকিউরিটি কোড লিখুন:</b>\nবর্তমান কোড: <code>{sanitize_html(curr_rule)}</code>\n\n💡 <i>নোট: এখানে কোড সেট করার সাথে সাথে ব্যাকগ্রাউন্ড থেকে সব মেম্বারদের ইনবক্সে অটোমেটিক ব্রডকাস্ট নোটিশ চলে যাবে!</i>", reply_markup=cancel_keyboard())

    elif text.startswith("🛠 মেইনটেনেন্স:") and chat_id == ADMIN_ID:
        current_mode = get_setting("maintenance_mode", False)
        new_mode = not current_mode
        update_setting("maintenance_mode", new_mode)
        status = "চালু (ON)" if new_mode else "বন্ধ (OFF)"
        msg = f"✅ <b>মেইনটেনেন্স মোড সফলভাবে {status} করা হয়েছে!</b>"
        return bot.send_message(ADMIN_ID, msg, reply_markup=admin_sub_settings_keyboard())

    elif text == "⏳ ম্যানুয়াল পেন্ডিং চেক" and chat_id == ADMIN_ID:
        pending_subs = list(submissions_col.find({"status": "Hold"}).limit(5))
        if not pending_subs: return bot.send_message(ADMIN_ID, "📭 বর্তমানে কোনো পেন্ডিং সাবমিশন নেই!", reply_markup=admin_sub_task_keyboard())
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("⚡ Approve All Current Pending", callback_data="appr_all_pending"))
        bot.send_message(ADMIN_ID, f"⏳ <b>সর্বমোট পেন্ডিং সাবমিশন পর্যালোচনা:</b>", reply_markup=markup)
        for sub in pending_subs:
            item_markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✅ Approve", callback_data=f"appr_{sub['track_id']}"), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{sub['track_id']}"))
            bot.send_message(ADMIN_ID, f"📌 Track ID: <code>{sub['track_id']}</code>\n👤 Worker: <code>{sub['chat_id']}</code>\n🆔 UID: <code>{sub['uid']}</code>\n💰 Rate: ৳{sub['rate']}", reply_markup=item_markup)
        return

    elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
        rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
        surge = get_setting("surge_pricing", {"active": False, "bonus": 0.0})
        st_text = f"⚡ ACTIVE (+৳{surge['bonus']})" if surge.get('active') else "🔴 INACTIVE"
        
        rate_card = (
            f"⚙️ <b>RATES & SURGE CONTROL</b>\n\n"
            f"• <b>FB Cookies:</b> ৳ {rates['fb_cookie']:.2f} BDT\n"
            f"• <b>FB 2FA:</b> ৳ {rates['fb_2fa']:.2f} BDT\n"
            f"• <b>IG Cookies:</b> ৳ {rates['ig_cookie']:.2f} BDT\n"
            f"• <b>IG 2FA:</b> ৳ {rates['ig_2fa']:.2f} BDT\n\n"
            f"⚡ <b>Surge Status:</b> {st_text}"
        )
        markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✏️ FB Cookie", callback_data="rate_edit_fb_cookie"), InlineKeyboardButton("✏️ FB 2FA", callback_data="rate_edit_fb_2fa"), InlineKeyboardButton("✏️ IG Cookie", callback_data="rate_edit_ig_cookie"), InlineKeyboardButton("✏️ IG 2FA", callback_data="rate_edit_ig_2fa")).add(InlineKeyboardButton("⚡ Quick Surge (+৳২)", callback_data="surge_3"), InlineKeyboardButton("🛑 Turn OFF Surge", callback_data="surge_off"))
        return bot.send_message(ADMIN_ID, rate_card, reply_markup=markup)

    elif text == "🧠 AI সিটেডেল অডিট" and chat_id == ADMIN_ID:
        logs = list(ai_logs_col.find().sort("timestamp", -1).limit(5))
        if not logs: return bot.send_message(ADMIN_ID, "🟢 <b>AI STATUS:</b> 100% HEALTHY\nকোনো এরর বা অটো-হিলিং লগ নেই।", reply_markup=admin_sub_system_keyboard())
        msg = "🧠 <b>সাম্প্রতিক এআই অটো-হিলিং লগসমূহ:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for log in logs: msg += f"• <b>{log['timestamp']}</b>\n📌 {log['type']}\n🛠️ {log['action']}\n\n"
        return bot.send_message(ADMIN_ID, msg, reply_markup=admin_sub_system_keyboard())

    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        return bot.send_message(ADMIN_ID, "📢 <b>ব্রডকাস্ট মেসেজটি লিখুন:</b>", reply_markup=cancel_keyboard())

    elif text == "👤 ইউজার ম্যানেজার" and chat_id == ADMIN_ID:
        return render_user_manager_page(ADMIN_ID, page=1)

    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        return bot.send_message(chat_id, "📦 <b>কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        return bot.send_message(chat_id, "📊 <b>.CSV বা .XLSX ফাইলটি এখানে পাঠালুন:</b>", reply_markup=cancel_keyboard())
    elif text == "⚙️ পাসওয়ার্ড নিয়ম":
        p_rule = str(get_setting("pass_rule", "@21")).strip()
        custom_p = user.get("custom_password", "")
        
        has_p = (custom_p and str(custom_p).strip() != '' and str(custom_p).lower() != 'none')
        pass_display = f"<code>{sanitize_html(custom_p)}</code>" if has_p else "<i>কোনো ডিফল্ট পাসওয়ার্ড সেভ করা নেই</i>"
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("✏️ পাসওয়ার্ড সেট / চেঞ্জ করুন", callback_data="user_set_custom_pass"))
        if has_p: markup.add(InlineKeyboardButton("🗑️ পাসওয়ার্ড মুছে ফেলুন", callback_data="user_remove_custom_pass"))
            
        msg = (
            f"⚙️ <b>পাসওয়ার্ড নিয়মাবলী ও সেটিং:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 <b>আপনার সেভ করা পাসওয়ার্ড:</b> {pass_display}\n"
            f"📌 <b>আজকের পাসওয়ার্ড সিকিউরিটি কোড:</b> <code>{sanitize_html(p_rule)}</code>\n\n"
            f"💡 <i>নোট: একাউন্ট খোলার সময়ই পাসওয়ার্ডের <b>একদম শেষে</b> আজকের কোড '<b>{sanitize_html(p_rule)}</b>' বসিয়ে একাউন্ট খুলতে হবে। অন্যথায় ভুল পাসওয়ার্ড দিলে একাউন্ট জমা না হয়ে সরাসরি ব্যাক/রিজেক্ট হয়ে যাবে!</i>"
        )
        return bot.send_message(chat_id, msg, reply_markup=markup)

    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie"
        if "FB 2FA" in text: cat = "fb_2fa"
        elif "IG Cookies" in text: cat = "ig_cookie"
        elif "IG 2FA" in text: cat = "ig_2fa"
        
        rate = float(get_current_task_rate(cat))
        p_rule = str(get_setting("pass_rule", "@21")).strip()

        task_card = (
            f"📄 <b>TASK TERMINAL // {text[:15]}</b>\n\n"
            f"💎 <b>Current Rate:</b> ৳ {rate:.2f} BDT\n"
            f"🔑 <b>Required End-Code:</b> <code>{p_rule}</code>\n\n"
            f"────────────────────────\n"
            f"► <b>Send your UID or profile link:</b>"
        )
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        return bot.send_message(chat_id, task_card, reply_markup=cancel_keyboard())

    custom_cats = get_setting("custom_categories", {})
    bonus_amt = get_active_surge_bonus()

    matched_cat_key = None
    for ck, ci in custom_cats.items():
        c_rate = float(ci.get("rate", 5.0)) + bonus_amt
        if text == f"📌 {ci.get('name')} (৳{c_rate:.2f})":
            matched_cat_key = ck
            break

    if matched_cat_key:
        cat_info = custom_cats[matched_cat_key]
        fields = cat_info.get("fields", ["Data"])
        rate = float(cat_info.get("rate", 5.0)) + bonus_amt
        
        user_states[chat_id] = {
            'step': 'AWAITING_CUSTOM_FIELD',
            'cat_key': matched_cat_key,
            'fields': fields,
            'current_field_idx': 0,
            'collected_data': {}
        }
        
        task_card = (
            f"📌 <b>TASK TERMINAL // {cat_info['name']}</b>\n\n"
            f"💎 <b>Current Rate:</b> ৳ {rate:.2f} BDT\n\n"
            f"────────────────────────\n"
            f"► <b>{fields[0]}</b> টি দিন:"
        )
        return bot.send_message(chat_id, task_card, reply_markup=cancel_keyboard())

    # ================= DYNAMIC STATE PROCESSING =================
    state = user_states.get(chat_id)
    if not state:
        if message.text:
            ai_reply = ask_ai_chatbot(text)
            return bot.send_message(chat_id, ai_reply, reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_WITHDRAW_ACCOUNT':
        method_name = state.get('method', 'bKash')
        account_no = text.strip()
        
        safe_delete_msg(chat_id, message.message_id)

        user_states[chat_id] = {
            'step': 'AWAITING_WITHDRAW_AMOUNT',
            'method': method_name,
            'account': account_no
        }
        
        bal = float(user.get("balance") or 0.0)
        return bot.send_message(
            chat_id, 
            f"✅ <b>মেথড:</b> {method_name}\n"
            f"📌 <b>অ্যাকোউন্ট:</b> <code>{sanitize_html(account_no)}</code>\n\n"
            f"💰 <b>কত টাকা উইথড্র করতে চান লিখুন:</b>\n"
            f"(সর্বনিম্ন: ৳৫০.০০ | আপনার ব্যালেন্স: ৳{bal:.2f})", 
            reply_markup=cancel_keyboard()
        )

    elif step == 'AWAITING_WITHDRAW_AMOUNT':
        method_name = state.get('method', 'bKash')
        account_no = state.get('account', '')
        
        safe_delete_msg(chat_id, message.message_id)

        try:
            req_amount = float(text.strip())
        except ValueError:
            return bot.send_message(chat_id, "❌ <b>ভুল অ্যামাউন্ট!</b> শুধুমাত্র সংখ্যা লিখুন (যেমন: 100):", reply_markup=cancel_keyboard())

        bal = float(user.get("balance") or 0.0)

        if req_amount < 50.0:
            return bot.send_message(chat_id, "⚠️ <b>সর্বনিম্ন উইথড্র পরিমাণ ৳৫০.০০ BDT!</b>\nআবার চেষ্টা করুন:", reply_markup=cancel_keyboard())

        if req_amount > bal:
            return bot.send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nআপনার বর্তমান ব্যালেন্স: ৳{bal:.2f} BDT", reply_markup=cancel_keyboard())

        user_states.pop(chat_id, None)

        new_balance = bal - req_amount
        update_user_field(chat_id, "balance", new_balance)

        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
        withdraw_id = generate_withdraw_id()

        withdrawals_col.insert_one({
            "withdraw_id": withdraw_id,
            "chat_id": chat_id,
            "worker_name": sanitize_html(message.from_user.first_name),
            "method": method_name,
            "account": account_no,
            "amount": req_amount,
            "status": "Pending",
            "time": now_str,
            "date_obj": get_bd_time()
        })

        return bot.send_message(
            chat_id, 
            f"🎉 <b>উইথড্র রিকোয়েস্ট সফলভাবে জমা হয়েছে!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Request ID:</b> <code>{withdraw_id}</code>\n"
            f"💳 <b>মেথড:</b> {method_name}\n"
            f"📱 <b>অ্যাকাউন্ট:</b> <code>{sanitize_html(account_no)}</code>\n"
            f"💰 <b>পরিমাণ:</b> ৳{req_amount:.2f} BDT\n\n"
            f"⏳ এডমিন প্যানেল থেকে পেন্ডিং চেক করে শীঘ্রই পেমেন্ট প্রসেস করা হবে। ধন্যবাদ!", 
            reply_markup=account_keyboard()
        )

    elif step == 'AWAITING_NEW_CAT_NAME' and chat_id == ADMIN_ID:
        cat_name = text.strip()
        state['new_cat_name'] = cat_name
        state['step'] = 'AWAITING_NEW_CAT_FIELDS'
        user_states[chat_id] = state
        return bot.send_message(ADMIN_ID, f"✅ ক্যাটাগরির নাম: <b>{cat_name}</b>\n\n📋 <b>কাজের তথ্যসমূহ কমা (,) দিয়ে লিখুন:</b>\nউদাহরণ: <code>UID, Password, Cookies</code>", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_NEW_CAT_FIELDS' and chat_id == ADMIN_ID:
        raw_fields = [f.strip() for f in text.split(',') if f.strip()]
        if not raw_fields: return bot.send_message(ADMIN_ID, "❌ কমপক্ষে একটি ফিল্ডের নাম লিখুন!", reply_markup=cancel_keyboard())
        state['new_cat_fields'] = raw_fields
        state['step'] = 'AWAITING_NEW_CAT_RATE'
        user_states[chat_id] = state
        return bot.send_message(ADMIN_ID, f"✅ ফিল্ডসমূহ: <code>{', '.join(raw_fields)}</code>\n\n💰 <b>পার আইডি রেট (BDT) কত টাকা দিবেন?</b>", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_NEW_CAT_RATE' and chat_id == ADMIN_ID:
        try: rate = float(text.strip())
        except ValueError: return bot.send_message(ADMIN_ID, "❌ ভুল সংখ্যা! সঠিক রেট লিখুন (যেমন: 10.0):", reply_markup=cancel_keyboard())

        cat_name = state.get('new_cat_name')
        fields = state.get('new_cat_fields')
        user_states.pop(chat_id, None)

        cat_key = "custom_" + re.sub(r'\W+', '_', cat_name.lower())
        custom_cats = get_setting("custom_categories", {})
        custom_cats[cat_key] = {"name": cat_name, "fields": fields, "rate": rate}
        update_setting("custom_categories", custom_cats)

        async_create_sheet_tab(cat_name, fields)
        return bot.send_message(ADMIN_ID, f"🎉 <b>{cat_name}</b> সফলভাবে তৈরি ও লাইভ করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())

    elif step == 'AWAITING_CUSTOM_CAT_RATE_EDIT' and chat_id == ADMIN_ID:
        cat_key = state.get('cat_key')
        user_states.pop(chat_id, None)
        try:
            new_r = float(text.strip())
            custom_cats = get_setting("custom_categories", {})
            if cat_key in custom_cats:
                custom_cats[cat_key]["rate"] = new_r
                update_setting("custom_categories", custom_cats)
                return bot.send_message(ADMIN_ID, f"✅ <b>{custom_cats[cat_key]['name']}</b> এর রেট আপডেট করে ৳{new_r:.2f} করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())
        except Exception:
            return bot.send_message(ADMIN_ID, "❌ ভুল সংখ্যা!", reply_markup=admin_sub_settings_keyboard())

    elif step == 'AWAITING_CUSTOM_FIELD':
        safe_delete_msg(chat_id, message.message_id)

        cat_key = state.get('cat_key')
        fields = state.get('fields', [])
        idx = state.get('current_field_idx', 0)
        collected = state.get('collected_data', {})

        curr_field = fields[idx]
        collected[curr_field] = text.strip()
        idx += 1

        state['current_field_idx'] = idx
        state['collected_data'] = collected

        if idx < len(fields):
            next_field = fields[idx]
            user_states[chat_id] = state
            return bot.send_message(chat_id, f"► <b>{next_field}</b> টি লিখুন:", reply_markup=cancel_keyboard())
        else:
            user_states.pop(chat_id, None)
            custom_cats = get_setting("custom_categories", {})
            cat_info = custom_cats.get(cat_key, {})
            cat_name = cat_info.get("name", "Custom Task")
            
            bonus_amt = get_active_surge_bonus()
            rate = float(cat_info.get("rate", 5.0)) + bonus_amt

            first_val = collected.get(fields[0], "N/A")

            pass_val = "N/A"
            for k, v in collected.items():
                if k.strip().lower() in ["password", "pass", "পাসওয়ার্ড", "পাসওয়ার্ড"]:
                    pass_val = v
                    break

            p_rule = str(get_setting("pass_rule", "@21")).strip()
            if pass_val != "N/A" and p_rule and p_rule.lower() != "none":
                if not validate_strict_password(pass_val, p_rule):
                    ai_warn = generate_strict_ai_warning(
                        "আপনার কাস্টম সাবমিশনের পাসওয়ার্ডটি বাতিল করা হয়েছে!",
                        f"আপনার দেওয়া পাসওয়ার্ডটির (<code>{sanitize_html(pass_val)}</code>) একদম শেষে আজকের সিকিউরিটি কোড '<code>{sanitize_html(p_rule)}</code>' অনুপস্থিত।",
                        f"একাউন্ট খোলার সময়ই পাসওয়ার্ডের 'একদম শেষে' '<code>{sanitize_html(p_rule)}</code>' বসিয়ে একাউন্ট খুলুন এবং সেই আসল পাসওয়ার্ডটি জমা দিন। ভুল পাসওয়ার্ড দিলে একাউন্ট সরাসরি ব্যাক/রিজেক্ট হয়ে যাবে!",
                        "আইডি খোলার আগেই '⚙️ পাসওয়ার্ড নিয়ম' সেকশনে গিয়ে সিকিউরিটি কোড দেখে নিন এবং সেই অনুযায়ী একাউন্ট তৈরি করুন।"
                    )
                    return bot.send_message(chat_id, ai_warn, reply_markup=submit_tasks_keyboard())

            now_time = get_bd_time()
            now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
            date_key = now_time.strftime("%Y-%m-%d")
            track_id = generate_tracking_id()

            row_data = [now_str, track_id, str(chat_id)] + [collected.get(f, "") for f in fields]
            
            try:
                submissions_col.insert_one({
                    "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name),
                    "uid": first_val, "password": pass_val,
                    "payload": json.dumps(collected, ensure_ascii=False),
                    "track_id": track_id, "category": cat_name, "category_key": cat_key,
                    "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
                })
                async_save_to_sheet(cat_name, row_data)
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
            except DuplicateKeyError:
                return bot.send_message(chat_id, "❌ এই একাউন্টটি ইতিপূর্বেই জমা দেওয়া হয়েছে!", reply_markup=submit_tasks_keyboard())

            try:
                bot.send_message(LOG_CHANNEL_ID, f"📥 <b>NEW SUBMISSION ({cat_name})</b>\n📌 Track: <code>{track_id}</code> | 👤 Worker: <code>{chat_id}</code> | 🆔 Ref: <code>{first_val}</code> | 💰 Rate: ৳{rate:.2f}")
            except Exception: pass

            return bot.send_message(chat_id, f"🎉 <b>কাজ জমা সফল হয়েছে!</b>\n📌 ক্যাটাগরি: <b>{cat_name}</b>\n🏷️ Track ID: <code>{track_id}</code>\n💰 আর্ন (হোল্ড): ৳{rate:.2f} BDT", reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_ADMIN_PASS_RULE' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        new_rule = text.strip()
        update_setting("pass_rule", new_rule)
        broadcast_password_rule_notice(new_rule)
        return bot.send_message(ADMIN_ID, f"✅ <b>আজকের পাসওয়ার্ড সিকিউরিটি কোড সফলভাবে সেট করা হয়েছে:</b> <code>{sanitize_html(new_rule)}</code>\n\n📢 <i>সব মেম্বারদের ইনবক্সে ব্রডকাস্ট নোটিশ পাঠানো শুরু হয়েছে!</i>", reply_markup=admin_sub_settings_keyboard())

    elif step == 'AWAITING_USER_SET_PASS':
        p_rule = str(get_setting("pass_rule", "")).strip()
        new_pass = text.strip()
        
        if p_rule and p_rule.lower() != "none" and not validate_strict_password(new_pass, p_rule):
            ai_warn = generate_strict_ai_warning(
                "ডিফল্ট পাসওয়ার্ড সেভ করা সম্ভব হয়নি!",
                f"আপনার টাইপ করা পাসওয়ার্ডের (<code>{sanitize_html(new_pass)}</code>) একদম শেষে আজকের সিকিউরিটি কোড '<code>{sanitize_html(p_rule)}</code>' নেই।",
                f"পাসওয়ার্ডের একদম শেষে '<code>{sanitize_html(p_rule)}</code>' যুক্ত করে আবার পাঠান (যেমন: MyPass{sanitize_html(p_rule)})।",
                "ভবিষ্যতে একাউন্ট খোলার সময়ও নিজের পছন্দমতো পাসওয়ার্ডের একদম শেষে এই সিকিউরিটি কোডটি বসিয়ে একাউন্ট তৈরি করুন।"
            )
            return bot.send_message(chat_id, ai_warn, reply_markup=cancel_keyboard())
        
        user_states.pop(chat_id, None)
        update_user_field(chat_id, "custom_password", new_pass)
        return bot.send_message(chat_id, f"🎉 <b>সফল!</b> আপনার ডিফল্ট পাসওয়ার্ড সেভ করা হয়েছে: <code>{sanitize_html(new_pass)}</code>", reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        all_users = list(users_col.find({"banned": False}))
        bot.send_message(ADMIN_ID, f"📢 <b>{len(all_users)}</b> জন ইউজারকে মেসেজ পাঠানো শুরু হচ্ছে...", reply_markup=admin_sub_system_keyboard())
        success = 0
        for u in all_users:
            try:
                if message.photo: bot.send_photo(u["_id"], message.photo[-1].file_id, caption=text)
                elif message.video: bot.send_video(u["_id"], message.video.file_id, caption=text)
                elif message.animation: bot.send_animation(u["_id"], message.animation.file_id, caption=text)
                else: bot.send_message(u["_id"], text)
                success += 1
                time.sleep(0.05)
            except ApiTelegramException as e:
                if e.error_code == 429:
                    time.sleep(e.result_json.get('parameters', {}).get('retry_after', 3))
            except Exception: pass
        return bot.send_message(ADMIN_ID, f"✅ <b>ব্রডকাস্ট সফলভাবে {success} জনকে পাঠানো হয়েছে!</b>")

    elif step == 'AWAITING_SUPPORT_MSG':
        user_states.pop(chat_id, None)
        msg_txt = text if text else "Media/File Sent"
        ticket_id = f"TKT-{random.randint(1000,9999)}"
        priority, summary = ai_analyze_ticket_sentiment(msg_txt)
        p_badge = "🔴 [HIGH PRIORITY]" if priority == "High" else "🟢 [NORMAL]"

        admin_alert = f"🎫 <b>নতুন সাপোর্ট টিকিট: {ticket_id}</b> {p_badge}\n👤 ইউজার ID: <code>{chat_id}</code>\n🤖 এআই সামারি: <i>{summary}</i>\n\n📝 বার্তা:\n{sanitize_html(msg_txt)}"
        bot.send_message(ADMIN_ID, admin_alert)
        return bot.send_message(chat_id, "✅ আপনার বার্তাটি এডমিনের কাছে পাঠানো হয়েছে। খুব শীঘ্রই উত্তর দেওয়া হবে।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_EDIT_PAYLOAD':
        track_id = state.get('track_id')
        user_states.pop(chat_id, None)
        submissions_col.update_one({"track_id": track_id}, {"$set": {"payload": text}})
        return bot.send_message(chat_id, f"✅ <b>Track ID: {track_id}</b> এর তথ্য সফলভাবে আপডেট করা হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_NEW_RATE' and chat_id == ADMIN_ID:
        cat_key = state.get('category_key')
        user_states.pop(chat_id, None)
        try:
            val = float(text)
            rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
            rates[cat_key] = val
            update_setting("rates", rates)
            return bot.send_message(ADMIN_ID, f"✅ <b>{cat_key}</b> এর নতুন রেট ৳{val} সেভ করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())
        except Exception: return bot.send_message(ADMIN_ID, "❌ ভুল সংখ্যা ফরম্যাট!", reply_markup=admin_sub_settings_keyboard())

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
        for l in live_list: out += f"<code>{sanitize_html(l)}</code>\n"
        return bot.send_message(chat_id, out, reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_TEXT':
        saved_pass = user.get("custom_password")
        p_rule = str(get_setting("pass_rule", "@21")).strip()

        password_to_use = saved_pass if (saved_pass and str(saved_pass).strip() != "" and str(saved_pass).lower() != "none") else p_rule

        if p_rule and p_rule.lower() != "none" and not validate_strict_password(password_to_use, p_rule):
            ai_warn = generate_strict_ai_warning(
                "আপনার বাল্ক সাবমিশনের পাসওয়ার্ডটি বাতিল করা হয়েছে!",
                f"আপনার সেভ করা পাসওয়ার্ডটির (<code>{sanitize_html(password_to_use)}</code>) একদম শেষে আজকের সিকিউরিটি কোড '<code>{sanitize_html(p_rule)}</code>' অনুপস্থিত।",
                f"একাউন্ট খোলার সময়ই পাসওয়ার্ডের 'একদম শেষে' '<code>{sanitize_html(p_rule)}</code>' বসিয়ে একাউন্ট খুলুন এবং সেই পাসওয়ার্ডটি জমা দিন। ভুল পাসওয়ার্ড দিলে একাউন্ট জমা না হয়ে সরাসরি ব্যাক/রিজেক্ট হয়ে যাবে!",
                "আইডি খোলার আগেই '⚙️ পাসওয়ার্ড নিয়ম' সেকশনে গিয়ে আজকের কোডটি শেষে বসিয়ে সেভ করে নিয়ে জমা দিন."
            )
            return bot.send_message(chat_id, ai_warn, reply_markup=submit_tasks_keyboard())

        safe_delete_msg(chat_id, message.message_id) 
        user_states.pop(chat_id, None)

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        success_list, rejected_list = [], []
        sheet_rows = []
        total_earned = 0.0

        now_time = get_bd_time()
        now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
        date_key = now_time.strftime("%Y-%m-%d")

        valid_raw_payloads = []

        for line in lines:
            uid = extract_numeric_uid(line)
            if not uid:
                rejected_list.append((line[:20] + "...", "ভুল ইউআইডি / ফরম্যাট এরর"))
                continue
            if is_duplicate_uid(uid):
                rejected_list.append((uid, "ডুপ্লিকেট একাউন্ট (ইতিমধ্যে জমা দেওয়া হয়েছে)"))
                continue
            
            p_hash = generate_payload_hash(line)
            if is_payload_blacklisted(p_hash):
                rejected_list.append((uid, "ব্ল্যাকলিস্টেড বা বাতিলকৃত ডাটা"))
                continue

            cat_key = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
            cat_display = CAT_MAP.get(cat_key, "FB Cookies")
            rate = float(get_current_task_rate(cat_key))
            track_id = generate_tracking_id()

            try:
                submissions_col.insert_one({
                    "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                    "password": password_to_use, "payload": line, "payload_hash": p_hash,
                    "track_id": track_id, "category": cat_display,
                    "category_key": cat_key, "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
                })
                sheet_rows.append([now_str, track_id, str(chat_id), uid, password_to_use, line])
                valid_raw_payloads.append(line)
                success_list.append(uid); total_earned += rate
            except DuplicateKeyError:
                rejected_list.append((uid, "ডুপ্লিকেট একাউন্ট (রেস কন্ডিশন আটকানো হয়েছে)"))
                continue

            try:
                bot.send_message(LOG_CHANNEL_ID, f"📥 <b>NEW SUBMISSION (Bulk Text)</b>\n📌 Track: <code>{track_id}</code> | 👤 Worker: <code>{chat_id}</code> | 🆔 UID: <code>{uid}</code> | 💰 Rate: ৳{rate:.2f}")
            except Exception: pass

        if sheet_rows:
            async_save_batch_to_sheet("Cookies_Data", sheet_rows)

        if len(success_list) > 0:
            valid_payload_text = "\n".join(valid_raw_payloads)
            safe_raw_text = sanitize_html(valid_payload_text[:2500])
            send_private_backup_message(
                f"📦 <b>[PRIVATE BACKUP - Bulk Text Submission]</b>\n"
                f"👤 Worker ID: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                f"🔑 Pass: <code>{sanitize_html(password_to_use)}</code> | ✅ Valid: <b>{len(success_list)}</b> টি | 💰 Hold: ৳{total_earned:.2f}\n\n"
                f"📄 <b>Accepted Raw Data:</b>\n<code>{safe_raw_text}</code>"
            )

        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})

        out = f"🎉 <b>বাল্ক সাবমিশন রিপোর্ট!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        out += f"✅ <b>গৃহীত একাউন্ট:</b> {len(success_list)} টি\n"
        out += f"❌ <b>বাতিলকৃত একাউন্ট:</b> {len(rejected_list)} টি\n"
        out += f"💰 <b>আর্ন (এসক্রো হোল্ড):</b> ৳{total_earned:.2f} BDT\n\n"

        if success_list:
            out += "🟢 <b>ACCEPTED UID LIST:</b>\n"
            for s in success_list[:15]: out += f"• <code>{s}</code>\n"
            if len(success_list) > 15: out += f"<i>...এবং আরও {len(success_list)-15} টি</i>\n"

        if rejected_list:
            out += "\n🔴 <b>REJECTED DETAILS:</b>\n"
            for r_item, r_reason in rejected_list[:10]:
                out += f"• <code>{r_item}</code> — <i>{r_reason}</i>\n"
            if len(rejected_list) > 10: out += f"<i>...এবং আরও {len(rejected_list)-10} টি বাতিল</i>\n"

        return bot.send_message(chat_id, out, reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_UID':
        safe_delete_msg(chat_id, message.message_id) 

        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID!")
        cat = state.get('category', 'fb_cookie')
        state['uid'] = uid; state['step'] = 'AWAITING_SINGLE_DATA'
        prompt = "🍪 Cookies পেস্ট করুন:" if "cookie" in cat else "🔐 2FA Secret Key দিন:"
        return bot.send_message(chat_id, f"✅ Verified UID: <code>{uid}</code>\n\n{prompt}", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_SINGLE_DATA':
        safe_delete_msg(chat_id, message.message_id) 

        cat, uid = state.get('category', 'fb_cookie'), state.get('uid')
        saved_pass = user.get("custom_password")
        p_rule = str(get_setting("pass_rule", "@21")).strip()
        
        has_valid_saved_pass = False
        if saved_pass and isinstance(saved_pass, str):
            cleaned_p = saved_pass.strip()
            if cleaned_p and cleaned_p.lower() != "none" and validate_strict_password(cleaned_p, p_rule):
                has_valid_saved_pass = True

        if has_valid_saved_pass:
            now_time = get_bd_time()
            now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
            date_key = now_time.strftime("%Y-%m-%d")
            
            p_hash = generate_payload_hash(text)
            if is_payload_blacklisted(p_hash): return bot.send_message(chat_id, "❌ ব্ল্যাকলিস্টেড ডাটা!", reply_markup=submit_tasks_keyboard())
            rate = float(get_current_task_rate(cat))
            track_id = generate_tracking_id()
            cat_display = CAT_MAP.get(cat, "FB Cookies")

            try:
                submissions_col.insert_one({
                    "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                    "password": cleaned_p, "payload": text, "payload_hash": p_hash,
                    "track_id": track_id, "category": cat_display,
                    "category_key": cat, "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
                })
                async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, cleaned_p, text])
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
            except DuplicateKeyError:
                return bot.send_message(chat_id, "❌ এই UID টি ইতিপূর্বেই জমা নেওয়া হয়েছে!", reply_markup=submit_tasks_keyboard())

            safe_payload = sanitize_html(text[:2500])
            send_private_backup_message(
                f"📌 <b>[PRIVATE BACKUP - Single Task]</b>\nTrack: <code>{track_id}</code> | Worker: <code>{chat_id}</code> | UID: <code>{uid}</code>\nPass: <code>{sanitize_html(cleaned_p)}</code>\nPayload:\n<code>{safe_payload}</code>"
            )

            try:
                bot.send_message(LOG_CHANNEL_ID, f"📥 <b>NEW SUBMISSION (Single Fast-Track)</b>\n📌 Track: <code>{track_id}</code> | 👤 Worker: <code>{chat_id}</code> | 🆔 UID: <code>{uid}</code> | 💰 Rate: ৳{rate:.2f}")
            except Exception: pass

            state['step'] = 'AWAITING_UID'
            state.pop('uid', None)
            state.pop('payload', None)
            user_states[chat_id] = state

            return bot.send_message(
                chat_id, 
                f"🎉 <b>কাজ জমা সফল!</b> (Track: <code>{track_id}</code> | ৳{rate:.2f})\n\n📌 <b>{cat_display}</b>\n► পরবর্তী UID বা প্রোফাইল লিঙ্ক সেন্ড করুন:", 
                reply_markup=cancel_keyboard()
            )
        else:
            state['payload'] = text
            state['step'] = 'AWAITING_MANUAL_PASSWORD'
            
            prompt_msg = "🔑 <b>আপনার এই একাউন্টের আসল পাসওয়ার্ডটি দিন:</b>\n"
            if p_rule and p_rule.lower() != "none":
                prompt_msg += f"⚠️ <i>মনে রাখবেন: একাউন্ট খোলার সময় পাসওয়ার্ডের <b>একদম শেষে</b> অবশ্যই আজকের সিকিউরিটি কোডটি (<code>{sanitize_html(p_rule)}</code>) যুক্ত করে খুলতে হবে!</i>"
            return bot.send_message(chat_id, prompt_msg, reply_markup=cancel_keyboard())

    elif step == 'AWAITING_MANUAL_PASSWORD':
        safe_delete_msg(chat_id, message.message_id) 

        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        payload = state.get('payload')
        manual_pass = text.strip()
        p_rule = str(get_setting("pass_rule", "@21")).strip()

        if p_rule and p_rule.lower() != "none" and not validate_strict_password(manual_pass, p_rule):
            ai_warn = generate_strict_ai_warning(
                "আপনার সাবমিট করা পাসওয়ার্ডটি বাতিল করা হয়েছে এবং একাউন্ট জমা নেওয়া হয়নি!",
                f"আপনার পাসওয়ার্ডের (<code>{sanitize_html(manual_pass)}</code>) একদম শেষে আজকের সিকিউরিটি কোড '<code>{sanitize_html(p_rule)}</code>' অনুপস্থিত।",
                f"ফেসবুক একাউন্ট তৈরি করার সময়ই পাসওয়ার্ডের 'একদম শেষে' '<code>{sanitize_html(p_rule)}</code>' যুক্ত করে একাউন্ট খুলুন এবং সেই আসল পাসওয়ার্ডটি জমা দিন। সঠিক নিয়ম ছাড়া ভুল পাসওয়ার্ড দিলে একাউন্ট সরাসরি ব্যাক/রিজেক্ট হয়ে যাবে!",
                "আইডি খোলার আগেই '⚙️ পাসওয়ার্ড নিয়ম' সেকশনে গিয়ে সিকিউরিটি কোড দেখে নিন এবং সেই নিয়ম মেনে একাউন্ট তৈরি করুন।"
            )
            return bot.send_message(chat_id, ai_warn, reply_markup=cancel_keyboard())

        now_time = get_bd_time()
        now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
        date_key = now_time.strftime("%Y-%m-%d")

        p_hash = generate_payload_hash(payload)
        if is_payload_blacklisted(p_hash): return bot.send_message(chat_id, "❌ ব্ল্যাকলিস্টেড ডাটা!", reply_markup=submit_tasks_keyboard())
        rate = float(get_current_task_rate(cat))
        track_id = generate_tracking_id()
        cat_display = CAT_MAP.get(cat, "FB Cookies")

        try:
            submissions_col.insert_one({
                "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": uid,
                "password": manual_pass, "payload": payload, "payload_hash": p_hash,
                "track_id": track_id, "category": cat_display,
                "category_key": cat, "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
            })
            async_save_to_sheet("Cookies_Data" if "cookie" in cat else "2FA_Data", [now_str, track_id, str(chat_id), uid, manual_pass, payload])
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
        except DuplicateKeyError:
            return bot.send_message(chat_id, "❌ এই UID টি ইতিপূর্বেই জমা নেওয়া হয়েছে!", reply_markup=submit_tasks_keyboard())

        safe_payload = sanitize_html(payload[:2500])
        send_private_backup_message(
            f"📌 <b>[PRIVATE BACKUP - Single Manual Pass]</b>\nTrack: <code>{track_id}</code> | Worker: <code>{chat_id}</code> | UID: <code>{uid}</code>\nPass: <code>{sanitize_html(manual_pass)}</code>\nPayload:\n<code>{safe_payload}</code>"
        )

        try:
            bot.send_message(LOG_CHANNEL_ID, f"📥 <b>NEW SUBMISSION (Single Manual Pass)</b>\n📌 Track: <code>{track_id}</code> | 👤 Worker: <code>{chat_id}</code> | 🆔 UID: <code>{uid}</code> | 💰 Rate: ৳{rate:.2f}")
        except Exception: pass

        update_user_field(chat_id, "temp_pending_password", manual_pass)

        state['step'] = 'AWAITING_UID'
        state.pop('uid', None)
        state.pop('payload', None)
        user_states[chat_id] = state

        return bot.send_message(
            chat_id, 
            f"🎉 <b>কাজ জমা সফল!</b> (Track: <code>{track_id}</code> | Pass: <code>{sanitize_html(manual_pass)}</code> | ৳{rate:.2f})\n\n📌 <b>{cat_display}</b>\n► পরবর্তী UID বা প্রোফাইল লিঙ্ক সেন্ড করুন:", 
            reply_markup=cancel_keyboard()
        )

# ================= 9. Production Server Engine =================

if __name__ == "__main__":
    print("Enterprise OEB NEXUS Cyber-AI Engine Active...")
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"{render_url}/{TOKEN}")
            print(f"[WEBHOOK LIVE]: {render_url}/{TOKEN}")
        except Exception: pass
        
        try:
            from waitress import serve
            serve(flask_app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
        except ImportError:
            flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
    else:
        try: bot.remove_webhook()
        except Exception: pass
        
        def run_server():
            try:
                from waitress import serve
                serve(flask_app, host="0.0.0.0", port=10000)
            except ImportError:
                flask_app.run(host="0.0.0.0", port=10000, threaded=True)
                
        threading.Thread(target=run_server, daemon=True).start()
        bot.infinity_polling(skip_pending=True)