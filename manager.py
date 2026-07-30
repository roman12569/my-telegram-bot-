import os
import re
import json
import io
import csv
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
import uuid
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, abort
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telebot.apihelper import ApiTelegramException
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import google.generativeai as genai

# ================= 1. CONFIGURATION & CREDENTIALS =================
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))

MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))

# Extreme Scale Optimization (Safe Limit for free server)
bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=150)

# ================= ⚡ DYNAMIC RETRY ENGINE =================
def with_rate_limit_protection(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ApiTelegramException as e:
            if e.error_code == 429:
                retry_after = int(e.result_json.get('parameters', {}).get('retry_after', 3))
                threading.Timer(retry_after + 0.5, lambda: wrapper(*args, **kwargs)).start()
            return None
        except Exception:
            return None
    return wrapper

bot.send_message = with_rate_limit_protection(bot.send_message)
bot.reply_to = with_rate_limit_protection(bot.reply_to)
bot.edit_message_text = with_rate_limit_protection(bot.edit_message_text)
bot.send_document = with_rate_limit_protection(bot.send_document)

# ================= Configure AI & Database (Fix 1: Pool Size Limits) =================
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    ai_model = None

try: BOT_USERNAME = bot.get_me().username
except Exception: BOT_USERNAME = "online_bazar_manager_bot"

# LIMIT: maxPoolSize=200 for MongoDB Free Tier Stability
mongo_client = MongoClient(
    MONGO_URL, maxPoolSize=200, minPoolSize=20, maxIdleTimeMS=45000,
    connectTimeoutMS=5000, socketTimeoutMS=5000
)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
tickets_col = db['support_tickets']
withdrawals_col = db['withdrawals']
blacklisted_payloads_col = db['blacklisted_payloads']
ai_logs_col = db['ai_logs']

try:
    submissions_col.create_index("track_id", unique=True, background=True)
    submissions_col.create_index("uid", unique=True, background=True)
    submissions_col.create_index("chat_id", background=True)
    submissions_col.create_index("status", background=True)
    submissions_col.create_index("date_key", background=True)
except Exception: pass

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"}
]

BD_TIMEZONE = timezone(timedelta(hours=6))

class GuaranteedBoundedExecutor:
    def __init__(self, max_workers, max_queue_size=10000):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = threading.Semaphore(max_queue_size)

    def submit(self, fn, *args, **kwargs):
        self.semaphore.acquire()
        try:
            future = self.executor.submit(fn, *args, **kwargs)
            future.add_done_callback(lambda x: self.semaphore.release())
            return future
        except Exception:
            self.semaphore.release()
            raise

background_executor = GuaranteedBoundedExecutor(max_workers=100, max_queue_size=10000)
heavy_task_executor = GuaranteedBoundedExecutor(max_workers=30, max_queue_size=5000)
live_check_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
cache_executor = concurrent.futures.ThreadPoolExecutor(max_workers=15)

class FastSettingsCache:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()
        self._init_cache()

    def _init_cache(self):
        try:
            for s in settings_col.find(): self.cache[s["_id"]] = s["value"]
        except Exception: pass

    def get(self, key, default):
        with self.lock:
            if key in self.cache: return self.cache[key]
        res = settings_col.find_one({"_id": key})
        val = res["value"] if res else default
        with self.lock: self.cache[key] = val
        return val

    def set(self, key, value):
        with self.lock: self.cache[key] = value
        cache_executor.submit(lambda: settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True))

fast_settings = FastSettingsCache()
def get_setting(key, default): return fast_settings.get(key, default)
def update_setting(key, value): fast_settings.set(key, value)

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
            with self.lock: self._add_to_cache(key, val)
            return val
        return default

    def __setitem__(self, key, value):
        with self.lock: self._add_to_cache(key, value)
        cache_executor.submit(self._async_save, key, value)

    def _add_to_cache(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.max_cache_size: self.cache.popitem(last=False)

    def _async_save(self, key, value):
        try: self.col.update_one({"_id": key}, {"$set": {"state": value}}, upsert=True)
        except Exception: pass

    def pop(self, key, default=None):
        val = default
        with self.lock:
            if key in self.cache: val = self.cache.pop(key)
            else:
                doc = self.col.find_one_and_delete({"_id": key})
                if doc: val = doc.get("state", default)
        cache_executor.submit(self._async_delete, key)
        return val

    def _async_delete(self, key):
        try: self.col.delete_one({"_id": key})
        except Exception: pass

user_states = MongoDict(db['user_states'])
CAT_MAP = {"fb_cookie": "FB Cookies", "fb_2fa": "FB 2FA", "ig_cookie": "IG Cookies", "ig_2fa": "IG 2FA"}

def get_bd_time(): return datetime.datetime.now(BD_TIMEZONE)

def safe_delete_msg(chat_id, message_id):
    background_executor.submit(lambda: _async_safe_delete(chat_id, message_id))
def _async_safe_delete(chat_id, message_id):
    try: bot.delete_message(chat_id, message_id)
    except Exception: pass

# ================= ⚡ TIME-GATING SHIFT ENGINE =================
def get_shift_config():
    default_config = {
        "current_date": get_bd_time().strftime("%Y-%m-%d"),
        "deadlines": {"fb_cookie": "21:20", "fb_2fa": "21:20", "ig_cookie": "20:20", "ig_2fa": "20:20", "default": "23:59"}
    }
    return get_setting("shift_config", default_config)

def is_submission_allowed(cat_key, request_time):
    shift = get_shift_config()
    if request_time.strftime("%Y-%m-%d") != shift["current_date"]:
        return False, f"⚠️ আজকের ({request_time.strftime('%d %B')}) কাজের শিফট এখনো চালু হয়নি। এডমিন শিফট আপডেট করা পর্যন্ত অপেক্ষা করুন।"
    deadline_str = shift["deadlines"].get(cat_key, shift["deadlines"].get("default", "23:59"))
    try:
        dead_hour, dead_min = map(int, deadline_str.split(":"))
        deadline_time = request_time.replace(hour=dead_hour, minute=dead_min, second=0, microsecond=0)
        if request_time > deadline_time:
            return False, f"⚠️ সময় শেষ! এই ক্যাটাগরির আজকের সাবমিশন ডেডলাইন ছিল রাত {deadline_str} মিনিট।"
        return True, "Allowed"
    except Exception: return True, "Allowed"

# ================= ⚡ SUB-ADMIN & USER MANAGEMENT (Fix 4: Isolation Prep) =================
def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        user = {
            "_id": chat_id, "username": "", "first_name": "Worker",
            "balance": 0.0, "hold_balance": 0.0, "banned": False, "custom_password": "",
            "joined_date": get_bd_time(), "last_active": get_bd_time(),
            "role": "member", "virtual_wallet": 0.0, "assigned_sub_admin": None
        }
        try: users_col.insert_one(user)
        except: pass
    return user

def update_user_field(chat_id, field, value):
    background_executor.submit(lambda: users_col.update_one({"_id": chat_id}, {"$set": {field: value}}, upsert=True))

def is_user_banned(chat_id):
    user = users_col.find_one({"_id": chat_id})
    return user.get("banned", False) if user else False

def sanitize_html(text):
    if not text: return "User"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ================= ⚡ ZERO-COST SERVER WIPE ENGINE =================
def generate_and_send_diary():
    now_str = get_bd_time().strftime("%Y-%m-%d")
    out = f"📓 <b>OEB NEXUS: DAILY DIARY [{now_str}]</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    pipeline = [{"$match": {"date_key": now_str}}, {"$group": {"_id": "$category", "count": {"$sum": 1}, "total_rate": {"$sum": "$rate"}}}]
    results = list(submissions_col.aggregate(pipeline))
    if not results: out += "📭 আজকে কোনো ডাটা প্রসেস হয়নি।"
    else:
        for r in results: out += f"📌 {r['_id']}: {r['count']} টি (৳{r['total_rate']:.2f})\n"
    out += "\n🧹 <i>অটো-ক্লিনআপ ইঞ্জিন এখন 'Approved' ও 'Rejected' ডাটাবেস রিমুভ করবে সার্ভার ফাস্ট রাখার জন্য। প্রাইভেট ব্যাকআপ চ্যানেলের ডাটা সুরক্ষিত থাকবে।</i>"
    try: bot.send_message(ADMIN_ID, out)
    except Exception: pass

def escrow_and_cleanup_daemon():
    while True:
        try:
            now = get_bd_time()
            if now.hour == 23 and now.minute == 55:
                generate_and_send_diary()
                time.sleep(60)
            elif now.hour == 0 and now.minute == 0:
                deleted = submissions_col.delete_many({"status": {"$in": ["Approved", "Rejected"]}})
                try: bot.send_message(ADMIN_ID, f"🧹 <b>NIGHTLY WIPE COMPLETE</b>\n{deleted.deleted_count} টি পুরোনো ডাটা মুছে সার্ভারের মেমোরি ফাঁকা করা হয়েছে।")
                except Exception: pass
                time.sleep(60)
            time.sleep(30)
        except Exception: time.sleep(60)

threading.Thread(target=escrow_and_cleanup_daemon, daemon=True).start()

# ================= ⚡ AI & UTILITY HELPERS =================
def parse_iso_datetime(dt_val):
    if not dt_val: return get_bd_time()
    if isinstance(dt_val, datetime.datetime):
        if dt_val.tzinfo is None: return dt_val.replace(tzinfo=BD_TIMEZONE)
        return dt_val.astimezone(BD_TIMEZONE)
    if isinstance(dt_val, str):
        try:
            parsed = datetime.datetime.fromisoformat(dt_val)
            if parsed.tzinfo is None: return parsed.replace(tzinfo=BD_TIMEZONE)
            return parsed.astimezone(BD_TIMEZONE)
        except Exception: return get_bd_time()
    return get_bd_time()

def get_active_surge_bonus():
    surge_info = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge_info.get("active"):
        exp = parse_iso_datetime(surge_info.get("expires_at"))
        if exp and get_bd_time() < exp: return float(surge_info.get("bonus", 0.0))
    return 0.0

def get_current_task_rate(cat_key):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    base_rate = float(rates.get(cat_key, 5.0))
    base_rate += get_active_surge_bonus()
    return base_rate

def log_ai_report(issue_type, description, fix_action):
    def task():
        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
        ai_logs_col.insert_one({"timestamp": now_str, "type": issue_type, "description": description, "action": fix_action})
        audit_msg = (
            f"🧠 <b>AI AUTO-HEALING & AUDIT REPORT</b>\n\n"
            f"• <b>Issue:</b> {issue_type}\n"
            f"🛠️ <b>Action Taken:</b>\n{fix_action[:150]}"
        )
        try: bot.send_message(ADMIN_ID, audit_msg)
        except Exception: pass
    background_executor.submit(task)

def generate_strict_ai_warning(issue, cause, solution, prevention):
    return (
        f"⚠️ <b>OEB NEXUS AI SYSTEM WARNING</b>\n\n"
        f"🔍 <b>১. সমস্যা:</b> {issue}\n"
        f"❓ <b>২. কারণ:</b> {cause}\n"
        f"🛠️ <b>৩. সমাধান:</b> {solution}\n"
        f"🛡️ <b>৪. প্রতিকার:</b> {prevention}"
    )

def validate_strict_password(password, rule):
    if not rule or rule.lower() == "none" or rule.strip() == "": return True
    return str(password).strip().endswith(rule.strip())

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

def is_duplicate_uid(uid): return submissions_col.find_one({"uid": str(uid)}) is not None
def generate_payload_hash(payload_str):
    clean_str = re.sub(r'\s+', '', str(payload_str))
    return hashlib.sha256(clean_str.encode('utf-8')).hexdigest()
def is_payload_blacklisted(payload_hash): return blacklisted_payloads_col.find_one({"_id": payload_hash}) is not None
def generate_tracking_id(): return f"SUB-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"
def generate_withdraw_id(): return f"WDR-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"
def make_progress_bar(processed, total, length=10):
    if not total or total == 0: return "░" * length
    ratio = min(1.0, max(0.0, processed / total))
    filled = int(ratio * length)
    return "▓" * filled + "░" * (length - filled)

# ================= ⚡ UI KEYBOARDS & DYNAMIC MENUS =================
def main_bottom_keyboard(chat_id):
    user = get_user_data(chat_id)
    role = user.get("role", "member")
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚡ কাজ জমা সেন্টার"), KeyboardButton("🛠 হেল্পার টুলস"))
    markup.add(KeyboardButton("👤 প্রোফাইল ও ওয়ালেট"), KeyboardButton("🎁 রিওয়ার্ড ও সাপোর্ট"))
    if role in ["sub_admin", "admin"] or chat_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 এডমিন কন্ট্রোল সেন্টার"))
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
    markup.add(KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💳 Withdraw"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def bonus_support_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 টাস্ক ও রিপোর্ট"), KeyboardButton("💳 ফাইন্যান্স ও সাব-এডমিন"))
    markup.add(KeyboardButton("⚙️ সেটিংস ও শিফট"), KeyboardButton("📢 ইউজার ও প্যানেল"))
    markup.add(KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_sub_task_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 স্মার্ট ড্যাশবোর্ড"), KeyboardButton("📂 ফাইল এক্সপোর্ট"))
    markup.add(KeyboardButton("🤖 অটো-ম্যাচার"), KeyboardButton("🏛️ আর্কাইভ"))
    markup.add(KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_finance_keyboard():
    pending_w_count = withdrawals_col.count_documents({"status": "Pending"})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(f"⏳ পেন্ডিং উইথড্রয়াল ({pending_w_count})"), KeyboardButton("👥 সাব-এডমিন ফাইন্যান্স"))
    markup.add(KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_settings_keyboard():
    m_mode = get_setting("maintenance_mode", False)
    m_btn = "🛠 মেইনটেনেন্স: 🟢 ON" if m_mode else "🛠 মেইনটেনেন্স: 🔴 OFF"
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("📅 শিফট ও ডেডলাইন"))
    markup.add(KeyboardButton("🔑 পাসওয়ার্ড নিয়ম"), KeyboardButton(m_btn))
    markup.add(KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# ================= ⚡ CORE ROUTING & WELCOME =================
def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']: return False
        except Exception: continue
    return True

@bot.message_handler(commands=['start'])
def send_welcome(message):
    background_executor.submit(lambda: _process_welcome(message))

def _process_welcome(message):
    try:
        chat_id = message.chat.id
        
        # Maintenance Shield
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
            user_data = get_user_data(chat_id)
            if user_data.get("role") != "sub_admin":
                return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

        if is_user_banned(chat_id): return bot.reply_to(message, "🔴 <b>আপনার অ্যাকাউন্টটি স্থগিত (Banned) করা হয়েছে!</b>")

        user = get_user_data(chat_id)
        if message.from_user.username: update_user_field(chat_id, "username", message.from_user.username)
        user_states.pop(chat_id, None)

        # === NEW: Sub-Admin Referral Tracker ===
        msg_parts = message.text.split()
        if len(msg_parts) > 1 and msg_parts[1].isdigit():
            ref_id = int(msg_parts[1])
            if ref_id != chat_id and not user.get("assigned_sub_admin"):
                update_user_field(chat_id, "assigned_sub_admin", ref_id)
                user["assigned_sub_admin"] = ref_id # Update local reference
        # =======================================

        if not check_force_join(chat_id):
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
            markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
            return bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)

        fname = sanitize_html(message.from_user.first_name)
        bal = float(user.get("balance") or 0.0)
        hold_bal = float(user.get("hold_balance") or 0.0)
        role = user.get("role", "member")
        
        role_display = "🟢 Active Staff"
        if role == "sub_admin": role_display = "🛡️ Sub-Admin"
        elif role == "admin" or chat_id == ADMIN_ID: role_display = "👑 Global Admin"

        welcome_card = (
            f"❖ <b>OEB NEXUS // SECURE CORE v6.0</b>\n\n"
            f"👤 <b>Operator:</b> {fname[:18]}\n"
            f"🆔 <b>User ID:</b> <code>#{chat_id}</code>\n\n"
            f"💳 <b>Wallet:</b> ৳ {bal:.2f} BDT\n"
            f"⏳ <b>Escrow:</b> ৳ {hold_bal:.2f} BDT\n"
            f"🛡 <b>Status:</b> {role_display}\n\n"
            f"────────────────────────\n"
            f"⚡ <i>Select an option from the terminal below:</i>"
        )

        bot.send_message(chat_id, welcome_card, reply_markup=main_bottom_keyboard(chat_id))
    except Exception as e: log_ai_report("Start Handler Error", str(e), "Caught gracefully.")

# ================= ⚡ IMAGE BADGE & CLOUD BACKUP =================
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
            f"১. একাউন্ট খোলার সময় আপনার পাসওয়ার্ডের <b>'একদম শেষে'</b> বাধ্যতামূলকভাবে '<code>{sanitize_html(new_rule)}</code>' কোডটি যুক্ত করে একাউন্ট তৈরি করুন।\n"
            f"২. সঠিক নিয়ম মেনে একাউন্ট খুলে দ্রুত জমা দিন। নিয়ম ছাড়া ভুল পাসওয়ার্ড দিলে একাউন্ট সরাসরি রিজেক্ট হয়ে যাবে!\n\n"
            f"⚡ দেরি না করে এখনই কাজ শুরু করুন এবং বেশি বেশি ইনকাম করুন! 🚀"
        )
        for u in all_users:
            try:
                bot.send_message(u["_id"], notice_text)
                time.sleep(0.04)
            except Exception: pass
    heavy_task_executor.submit(task)

# ================= ⚡ ULTRA-FAST LIVE CHECKERS (Fix 2: IP Ban Protection) =================
UAS = [
    "Mozilla/5.0 (Linux; Android 10; SM-A505F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 11; Pixel 4a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Mobile Safari/537.36"
]

def check_live_account(uid):
    try:
        clean_uid = extract_numeric_uid(uid)
        if not clean_uid: return False, "Invalid UID format"
        
        # Jitter: Random sleep prevents request flooding and WAF blocking
        time.sleep(random.uniform(0.3, 1.2)) 
        
        url = f"https://m.facebook.com/profile.php?id={clean_uid}"
        headers = {
            "User-Agent": random.choice(UAS),
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate"
        }
        res = requests.get(url, headers=headers, timeout=5.0, allow_redirects=True)
        content = res.text.lower()
        
        if res.status_code != 200: return False, "Suspended/Dead"
        if "content=\"no-cache\"" in content or "the page you requested cannot be displayed" in content or "not found" in content or "login" in res.url:
            if "c_user" not in res.url and clean_uid not in res.url: return False, "Checkpoint/Dead"
        if "profile_ring" in content or "mbasic_inline_feed_composer" in content or clean_uid in res.url:
            return True, "Live Account"
        return False, "Suspended/Dead"
    except Exception: return False, "Dead / Timeout"

def check_ig_username_live(username):
    try:
        clean_user = username.replace("@", "").strip()
        time.sleep(random.uniform(0.2, 0.8))
        url = f"https://www.instagram.com/{clean_user}/"
        headers = {"User-Agent": random.choice(UAS)}
        res = requests.get(url, headers=headers, timeout=5.0)
        if res.status_code == 200 and "Page Not Found" not in res.text: return True, "Live IG Profile"
        return False, "Dead / Suspended"
    except Exception: return True, "Assumed Live"

# ================= ⚡ DATA QUERY HELPERS =================
def get_active_hold_dates():
    pipeline = [{"$match": {"status": "Hold"}}, {"$group": {"_id": "$date_key"}}]
    results = list(submissions_col.aggregate(pipeline))
    dates = [r["_id"] for r in results if r["_id"]]
    dates.sort(reverse=True)
    return dates

def get_all_recorded_dates():
    pipeline = [{"$group": {"_id": "$date_key"}}]
    results = list(submissions_col.aggregate(pipeline))
    dates = [r["_id"] for r in results if r["_id"]]
    dates.sort(reverse=True)
    return dates

def build_date_query(selected_date, base_status=None):
    q = {}
    if base_status: q["status"] = base_status
    if selected_date != "ALL": q["date_key"] = selected_date
    return q

# ================= ⚡ FILE & AUTO-MATCHER ROUTER (Fix 3: Zero-RAM Excel Processing) =================
@bot.message_handler(content_types=['document'])
def handle_document(message):
    heavy_task_executor.submit(lambda: _process_document(message))

def _process_document(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        user_data = get_user_data(chat_id)
        if user_data.get("role") != "sub_admin":
            return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>\nদয়া করে কিছুক্ষণ পর আবার চেষ্টা করুন।")

    if is_user_banned(chat_id): return
    state = user_states.get(chat_id)
    
    # --- ADMIN AUTO-MATCHER ENGINE (No Pandas) ---
    if state and state.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
        target_date = state.get('target_date', 'ALL')
        target_cat = state.get('target_cat', 'ALL')
        user_states.pop(chat_id, None)
        bot.reply_to(message, "⏳ <b>বায়ার রিপোর্ট স্ক্যানিং ও ম্যাচিং চলছে...</b>\nদয়া করে কিছুক্ষণ অপেক্ষা করুন।")
        
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            filename = message.document.file_name.lower()
            extracted_uids = set()
            
            # Streaming data to save RAM
            if filename.endswith(".csv"): 
                decoded_file = downloaded.decode('utf-8', errors='ignore').splitlines()
                reader = csv.reader(decoded_file)
                for row in reader:
                    for val in row:
                        if val: extracted_uids.update(re.findall(r'\b\d{8,20}\b', str(val)))
            elif filename.endswith(".xlsx"): 
                wb = load_workbook(filename=io.BytesIO(downloaded), read_only=True, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    for val in row:
                        if val: extracted_uids.update(re.findall(r'\b\d{8,20}\b', str(val)))
            else: 
                extracted_uids = set(re.findall(r'\b\d{8,20}\b', downloaded.decode('utf-8', errors='ignore')))
                
            cleaned_uids = {str(u).strip().split('.')[0] for u in extracted_uids if str(u).strip().split('.')[0].isdigit()}
            
            query = build_date_query(target_date, "Hold")
            if target_cat != "ALL": query["category_key"] = target_cat
            
            pending_subs = list(submissions_col.find(query))
            if not pending_subs:
                return bot.send_message(ADMIN_ID, f"📭 <b>[{target_date} | {target_cat}]</b> এর কোনো পেন্ডিং কাজ নেই!", reply_markup=admin_bottom_keyboard())

            appr, rej, payout = 0, 0, 0.0
            notifications = collections.defaultdict(list)
            
            for sub in pending_subs:
                uid = str(sub.get("uid", "")).strip()
                amt = float(sub.get("rate") or 0.0)
                worker_id = sub["chat_id"]
                
                if uid in cleaned_uids:
                    submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Approved"}})
                    worker_data = users_col.find_one({"_id": worker_id})
                    if worker_data and worker_data.get("role") == "sub_admin":
                        users_col.update_one({"_id": worker_id}, {"$inc": {"virtual_wallet": amt, "hold_balance": -amt}})
                    else:
                        users_col.update_one({"_id": worker_id}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                    
                    appr += 1; payout += amt
                    notifications[worker_id].append(f"✅ বায়ার রিপোর্টে আপনার আইডি ({uid}) এপ্রুভ হয়েছে! ৳{amt} যোগ হয়েছে।")
                else:
                    submissions_col.update_one({"_id": sub["_id"]}, {"$set": {"status": "Rejected"}})
                    users_col.update_one({"_id": worker_id}, {"$inc": {"hold_balance": -amt}})
                    rej += 1
                    notifications[worker_id].append(f"❌ বায়ার রিপোর্টে আপনার আইডি ({uid}) রিজেক্টেড।")
                    
            def send_async_notifications(notif_dict):
                for w_id, msgs in notif_dict.items():
                    try:
                        comb_msg = "\n".join(msgs[:15])
                        if len(msgs) > 15: comb_msg += f"\n...এবং আরও {len(msgs)-15} টি আপডেট।"
                        bot.send_message(w_id, comb_msg)
                        time.sleep(0.04)
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
        except Exception:
            return bot.send_message(chat_id, "❌ ফাইলটি রিড করা যায়নি। সঠিক ফরম্যাটের এক্সেল বা সিএসভি দিন।")

    # --- WORKER EXCEL SUBMISSION ENGINE (No Pandas) ---
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        user = get_user_data(chat_id)
        saved_pass = user.get("custom_password")
        p_rule = str(get_setting("pass_rule", "")).strip()
        password_to_use = saved_pass if (saved_pass and str(saved_pass).strip() != "" and str(saved_pass).lower() != "none") else p_rule

        if p_rule and p_rule.lower() != "none" and not validate_strict_password(password_to_use, p_rule):
            ai_warn = generate_strict_ai_warning(
                "আপনার এক্সেল ফাইলের জন্য ডিফল্ট পাসওয়ার্ডটি গ্রহণ করা হয়নি!",
                f"পাসওয়ার্ডটির (<code>{sanitize_html(password_to_use)}</code>) শেষে আজকের কোড '<code>{sanitize_html(p_rule)}</code>' নেই।",
                "একাউন্ট খোলার সময়ই পাসওয়ার্ডের শেষে কোড বসিয়ে একাউন্ট খুলুন এবং সেই পাসওয়ার্ডটি সেভ করুন।",
                "আইডি খোলার আগেই '⚙️ পাসওয়ার্ড নিয়ম' সেকশনে গিয়ে আজকের কোড মেনে পাসওয়ার্ড সেভ করুন।"
            )
            return bot.reply_to(message, ai_warn, reply_markup=submit_tasks_keyboard())

        user_states.pop(chat_id, None)
        bot.reply_to(message, "⏳ <b>এক্সেল ফাইল প্রসেসিং শুরু হয়েছে...</b>\nব্যাকগ্রাউন্ডে লাইভ চেক ও স্ক্যান শেষ হলে স্বয়ংক্রিয় নোটিফিকেশন দেওয়া হবে।", reply_markup=submit_tasks_keyboard())
        
        file_info = bot.get_file(message.document.file_id)
        orig_file_name = message.document.file_name.lower()
        now_time = get_bd_time()
        
        try:
            file_downloaded_bytes = bot.download_file(file_info.file_path)
            candidates = []

            # RAM Friendly File Reader
            if orig_file_name.endswith('.csv'):
                decoded_file = file_downloaded_bytes.decode('utf-8', errors='ignore').splitlines()
                reader = csv.reader(decoded_file)
                for row in reader:
                    uid, payload = None, None
                    for v in row:
                        val_str = str(v).strip()
                        if not uid and extract_numeric_uid(val_str): uid = extract_numeric_uid(val_str)
                        elif is_valid_cookies(val_str) or len(val_str) > 20: payload = val_str
                    if uid and payload and not is_duplicate_uid(uid):
                        candidates.append((uid, payload))
                        
            elif orig_file_name.endswith('.xlsx'):
                wb = load_workbook(filename=io.BytesIO(file_downloaded_bytes), read_only=True, data_only=True)
                ws = wb.active
                for row in ws.iter_rows(values_only=True):
                    uid, payload = None, None
                    for v in row:
                        val_str = str(v).strip() if v else ""
                        if not uid and extract_numeric_uid(val_str): uid = extract_numeric_uid(val_str)
                        elif is_valid_cookies(val_str) or len(val_str) > 20: payload = val_str
                    if uid and payload and not is_duplicate_uid(uid):
                        candidates.append((uid, payload))
            else:
                return bot.send_message(chat_id, "❌ ফাইলটি রিড করা যায়নি। সঠিক `.csv` বা `.xlsx` ফাইল দিন।")

            now_str = now_time.strftime("%Y-%m-%d %H:%M:%S")
            date_key = now_time.strftime("%Y-%m-%d")

            valid_candidates = []
            for uid, payload in candidates:
                p_hash = generate_payload_hash(payload)
                if not is_payload_blacklisted(p_hash):
                    cat_key = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                    is_allowed, _ = is_submission_allowed(cat_key, now_time)
                    if is_allowed:
                        valid_candidates.append({
                            "uid": uid, "password": password_to_use, "payload": payload,
                            "payload_hash": p_hash, "cat_key": cat_key
                        })

            def _check_cand(c):
                if c["cat_key"] in ["fb_cookie", "fb_2fa"]:
                    is_live, _ = check_live_account(c["uid"])
                    c["is_live"] = is_live
                else: c["is_live"] = True
                return c

            success_count, total_earned = 0, 0.0
            verified_candidates = list(live_check_executor.map(_check_cand, valid_candidates))

            for item in verified_candidates:
                if not item.get("is_live"): continue

                cat_display = CAT_MAP.get(item["cat_key"], "FB Cookies")
                rate = float(get_current_task_rate(item["cat_key"]))
                track_id = generate_tracking_id()

                try:
                    submissions_col.insert_one({
                        "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "uid": item["uid"],
                        "password": item["password"], "payload": item["payload"], "payload_hash": item["payload_hash"], "track_id": track_id,
                        "category": cat_display, "category_key": item["cat_key"],
                        "rate": rate, "status": "Hold", "date_key": date_key, "date_str": now_str, "date_obj": now_time
                    })
                    success_count += 1; total_earned += rate
                except DuplicateKeyError: continue

            backup_file_buf = io.BytesIO(file_downloaded_bytes)
            send_private_backup_message(
                f"📊 <b>[PRIVATE BACKUP - Excel Submission]</b>\n"
                f"👤 Worker ID: <code>{chat_id}</code> ({sanitize_html(message.from_user.first_name)})\n"
                f"📁 File: <code>{sanitize_html(message.document.file_name)}</code> | 🔑 Pass: <code>{sanitize_html(password_to_use)}</code>\n"
                f"✅ Valid Live: <b>{success_count}</b> টি | 💰 Hold: ৳{total_earned:.2f}",
                doc_buf=backup_file_buf,
                doc_name=f"Backup_{date_key}_{message.document.file_name}"
            )

            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
            bot.send_message(chat_id, f"🎉 <b>ফাইল প্রসেস সম্পন্ন!</b>\n✅ রিয়েল লাইভ অ্যাকাউন্ট গৃহীত: <b>{success_count}</b> টি | 💰 আর্ন (হোল্ড): ৳{total_earned:.2f}", reply_markup=submit_tasks_keyboard())
            
        except Exception as e:
            bot.send_message(chat_id, "❌ ফাইল প্রসেসিং এরর! ডাটা ফরম্যাট ঠিক আছে কিনা চেক করুন।")

# ================= ⚡ CORE CALLBACK HANDLERS =================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    background_executor.submit(lambda: _process_callbacks(call))

def _process_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    user = get_user_data(chat_id)

    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        if user.get("role") != "sub_admin":
            try: bot.answer_callback_query(call.id, "🛠 বটের সার্ভার আপডেটের কাজ চলছে!", show_alert=True)
            except: pass
            return

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        else: bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!")

    elif code.startswith("w_method_"):
        method_name = "bKash" if "bkash" in code else "Binance Pay ID"
        user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_ACCOUNT', 'method': method_name}
        prompt = f"📱 <b>আপনার {method_name} নাম্বার/আইডিটি লিখুন:</b>" if "bkash" in code else f"🔶 <b>আপনার {method_name} টি টাইপ করুন:</b>"
        bot.edit_message_text(prompt, chat_id, call.message.message_id)

    elif code.startswith("w_appr_") and chat_id == ADMIN_ID:
        w_id = code.replace("w_appr_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Approved"}})
            bot.edit_message_text(f"✅ <b>APPROVED</b>\nID: {w_id}\nWorker: {w_doc['chat_id']}", chat_id, call.message.message_id)
            try: bot.send_message(w_doc['chat_id'], f"🎉 <b>আপনার উইথড্র (৳{w_doc['amount']} BDT) সফলভাবে এপ্রুভ হয়েছে!</b>")
            except: pass

    elif code.startswith("w_rej_") and chat_id == ADMIN_ID:
        w_id = code.replace("w_rej_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Rejected"}})
            w_user = get_user_data(w_doc['chat_id'])
            if w_user.get("role") == "sub_admin": users_col.update_one({"_id": w_doc['chat_id']}, {"$inc": {"virtual_wallet": w_doc['amount']}})
            else: users_col.update_one({"_id": w_doc['chat_id']}, {"$inc": {"balance": w_doc['amount']}})
            bot.edit_message_text(f"❌ <b>REJECTED</b>\nID: {w_id}", chat_id, call.message.message_id)
            try: bot.send_message(w_doc['chat_id'], f"❌ <b>আপনার উইথড্র রিকোয়েস্ট বাতিল করা হয়েছে!</b> ব্যালেন্স ফেরত দেওয়া হয়েছে।")
            except: pass

    elif code == "user_set_custom_pass":
        p_rule = str(get_setting("pass_rule", "")).strip()
        user_states[chat_id] = {'step': 'AWAITING_USER_SET_PASS'}
        msg = f"✏️ <b>আপনার নতুন ডিফল্ট পাসওয়ার্ডটি লিখুন:</b>\n"
        if p_rule and p_rule.lower() != "none": msg += f"⚠️ <i>শেষে <b>{sanitize_html(p_rule)}</b> থাকা বাধ্যতামূলক!</i>"
        bot.send_message(chat_id, msg, reply_markup=cancel_keyboard())

    elif code == "user_remove_custom_pass":
        update_user_field(chat_id, "custom_password", "")
        bot.edit_message_text("🗑️ <b>ডিফল্ট পাসওয়ার্ড মুছে ফেলা হয়েছে!</b>", chat_id, call.message.message_id)

    elif code.startswith("dash_dt_") and chat_id == ADMIN_ID:
        target_date = code.replace("dash_dt_", "")
        cats = ["fb_cookie", "fb_2fa", "ig_cookie", "ig_2fa"]
        out = f"📊 <b>BATCH REPORT // {target_date}</b>\n\n"
        total_hold = 0
        for c in cats:
            hq = submissions_col.count_documents({"date_key": target_date, "status": "Hold", "category_key": c})
            aq = submissions_col.count_documents({"date_key": target_date, "status": "Approved", "category_key": c})
            out += f"• {c}: ⏳{hq} / ✅{aq}\n"
            total_hold += hq
        markup = InlineKeyboardMarkup()
        if total_hold > 0:
            markup.add(InlineKeyboardButton(f"📥 রিপোর্ট মেলান", callback_data=f"bm_select_date_{target_date}"))
            markup.add(InlineKeyboardButton(f"🔒 ফোর্স ক্লোজ", callback_data=f"force_close_{target_date}"))
        bot.send_message(ADMIN_ID, out, reply_markup=markup)

    elif code.startswith("bm_select_date_") and chat_id == ADMIN_ID:
        target_date = code.replace("bm_select_date_", "")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("📄 FB Cookies", callback_data=f"bm_cat_{target_date}_fb_cookie"), InlineKeyboardButton("🔐 FB 2FA", callback_data=f"bm_cat_{target_date}_fb_2fa"))
        markup.add(InlineKeyboardButton("🌐 সব ক্যাটাগরি একসাথে", callback_data=f"bm_cat_{target_date}_ALL"))
        bot.send_message(ADMIN_ID, f"🤖 <b>[{target_date}]</b> কোন ক্যাটাগরির বায়ার রিপোর্ট মেলাবেন?", reply_markup=markup)

    elif code.startswith("bm_cat_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        target_date, cat_key = parts[2], "_".join(parts[3:])
        user_states[ADMIN_ID] = {'step': 'AWAITING_BUYER_REPORT', 'target_date': target_date, 'target_cat': cat_key}
        bot.send_message(ADMIN_ID, f"📄 <b>[{target_date} | {cat_key}]</b> এর বায়ার রিপোর্ট (Excel/CSV) দিন:", reply_markup=cancel_keyboard())


# ================= ⚡ MAIN TEXT ROUTER =================
@bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
def main_router(message):
    if message.content_type == 'document':
        return heavy_task_executor.submit(lambda: _process_document(message))
    background_executor.submit(lambda: _process_main_router(message))

def _process_main_router(message):
    chat_id = message.chat.id
    user = get_user_data(chat_id)
    
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False) and user.get("role") != "sub_admin":
        return bot.reply_to(message, "🛠 <b>সার্ভার আপডেটের কাজ চলছে!</b>")
    if is_user_banned(chat_id): return
    
    text = message.text.strip() if message.text else ""
    current_state = user_states.get(chat_id) or {}
    
    nav_buttons = ["🏠 মেইন মেনু", "🔙 প্রধান মেনু", "❌ বাতিল করুন", "⚡ কাজ জমা সেন্টার", "🛠 হেল্পার টুলস", "📌 সিঙ্গেল জমা", "👤 প্রোফাইল ও ওয়ালেট", "🎁 রিওয়ার্ড ও সাপোর্ট", "👑 এডমিন কন্ট্রোল সেন্টার", "💳 Withdraw", "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "🔑 2FA কোড জেনারেটর", "✉️ টেম্প ইমেইল", "📊 টাস্ক ও রিপোর্ট", "💳 ফাইন্যান্স ও সাব-এডমিন", "⚙️ সেটিংস ও শিফট", "📢 ইউজার ও প্যানেল", "🔙 এডমিন প্যানেল", "⚙️ সেট রেট ও চার্জ", "🔑 পাসওয়ার্ড নিয়ম", "📢 ব্রডকাস্ট নোটিশ", "💬 এডমিন সাপোর্ট টিকিট", "🏆 লিডারবোর্ড", "🎁 Claim Daily Bonus"]

    if text in nav_buttons: user_states.pop(chat_id, None)

    if text == "❌ বাতিল করুন":
        return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করে প্রধান মেনুতে ফিরে আসা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))
    elif text == "🏠 মেইন মেনু": return send_welcome(message)
    elif text == "⚡ কাজ জমা সেন্টার": return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ বেছে নিন:</b>", reply_markup=submit_tasks_keyboard())
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>আপনার প্রয়োজনীয় টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
    elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard())
    elif text == "🎁 রিওয়ার্ড ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>বোনাস ও সাপোর্ট সেন্টার:</b>", reply_markup=bonus_support_keyboard())
    
    elif text in ["👤 প্রোফাইল ও ওয়ালেট"]:
        cnt = submissions_col.count_documents({"chat_id": chat_id})
        bal = float(user.get("balance") or 0.0)
        v_bal = float(user.get("virtual_wallet") or 0.0)
        role = user.get("role", "member")
        prof_card = f"👤 <b>USER PROFILE</b>\n• <b>Role:</b> {role.upper()}\n• <b>Tasks Done:</b> {cnt}\n"
        if role == "sub_admin": prof_card += f"💳 <b>Virtual Wallet:</b> ৳ {v_bal:.2f}\n"
        else: prof_card += f"💳 <b>Main Wallet:</b> ৳ {bal:.2f}\n"
        prof_card += f"🔗 <b>Ref Link:</b> https://t.me/{BOT_USERNAME}?start={chat_id}"
        return bot.send_message(chat_id, prof_card, reply_markup=account_keyboard())

    elif text in ["👑 এডমিন কন্ট্রোল সেন্টার"] and (chat_id == ADMIN_ID or user.get("role") in ["admin", "sub_admin"]):
        return bot.send_message(chat_id, "👑 <b>ADMIN CONTROL CENTER</b>", reply_markup=admin_bottom_keyboard())
    
    # Admin Advanced Routing
    elif text == "📊 টাস্ক ও রিপোর্ট" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "📊 <b>টাস্ক ও রিপোর্ট প্যানেল:</b>", reply_markup=admin_sub_task_keyboard())
    elif text == "⚙️ সেটিংস ও শিফট" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "⚙️ <b>সেটিংস ও শিফট প্যানেল:</b>", reply_markup=admin_sub_settings_keyboard())
    elif text == "💳 ফাইন্যান্স ও সাব-এডমিন" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "💳 <b>ফাইন্যান্স প্যানেল:</b>", reply_markup=admin_sub_finance_keyboard())
    
    elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_NEW_RATE'}
        return bot.send_message(chat_id, "✏️ <b>FB Cookies এর নতুন রেট লিখুন:</b>", reply_markup=cancel_keyboard())
        
    elif text == "🔑 পাসওয়ার্ড নিয়ম" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_ADMIN_PASS_RULE'}
        return bot.send_message(chat_id, f"🔑 <b>নতুন সিকিউরিটি কোড লিখুন:</b> (যেমন: @21)", reply_markup=cancel_keyboard())

    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        return bot.send_message(chat_id, "📢 <b>সকল মেম্বারদের জন্য মেসেজটি লিখুন:</b>", reply_markup=cancel_keyboard())

    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
        return bot.send_message(chat_id, "💬 <b>আপনার মেসেজ বা সমস্যাটি বিস্তারিত লিখুন:</b>", reply_markup=cancel_keyboard())

    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        return bot.send_message(chat_id, "🔑 <b>2FA Secret Key টি দিন:</b>", reply_markup=cancel_keyboard())

    elif text == "🚀 বাল্ক FB লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
        return bot.send_message(chat_id, "🔍 <b>একসাথে ফেসবুক UID গুলোর লিস্ট পেস্ট করুন:</b>", reply_markup=cancel_keyboard())

    elif text == "💳 Withdraw":
        bal = float(user.get("virtual_wallet") if user.get("role") == "sub_admin" else user.get("balance") or 0.0)
        if bal < 50.0: return bot.send_message(chat_id, f"⚠️ <b>সর্বনিম্ন উইথড্র ৳৫০.০০ BDT!</b> (আপনার আছে ৳{bal:.2f})", reply_markup=account_keyboard())
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📱 বিকাশ (bKash)", callback_data="w_method_bkash"), InlineKeyboardButton("🔶 বাইনান্স", callback_data="w_method_binance"))
        return bot.send_message(chat_id, "💳 <b>উইথড্র মেথড সিলেক্ট করুন:</b>", reply_markup=markup)

    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        return bot.send_message(chat_id, "📦 <b>কুকিজ বা ২এফএ ডেটা লাইন বাই লাইন পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    
    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie" if "Cookies" in text else "fb_2fa"
        p_rule = str(get_setting("pass_rule", "@21")).strip()
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        return bot.send_message(chat_id, f"📄 <b>TASK: {text[:15]}</b>\n🔑 End-Code: <code>{p_rule}</code>\n► <b>UID সেন্ড করুন:</b>", reply_markup=cancel_keyboard())

# ================= ⚡ DYNAMIC STATE PROCESSING =================
    state = user_states.get(chat_id)
    if not state: return
    step = state.get('step')

    # ADMIN STATES
    if step == 'AWAITING_NEW_RATE' and chat_id == ADMIN_ID:
        try:
            val = float(text)
            rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
            rates["fb_cookie"] = val
            update_setting("rates", rates)
            user_states.pop(chat_id, None)
            return bot.send_message(chat_id, f"✅ রেট আপডেট করে ৳{val} করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())
        except: return bot.send_message(chat_id, "❌ সংখ্যা দিন!")

    elif step == 'AWAITING_ADMIN_PASS_RULE' and chat_id == ADMIN_ID:
        update_setting("pass_rule", text)
        user_states.pop(chat_id, None)
        broadcast_password_rule_notice(text)
        return bot.send_message(chat_id, f"✅ পাসওয়ার্ড কোড <b>{text}</b> সেট করা হয়েছে এবং সবাইকে ব্রডকাস্ট করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())

    elif step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        all_users = list(users_col.find({"banned": False}))
        bot.send_message(ADMIN_ID, f"📢 ব্রডকাস্ট পাঠানো শুরু হচ্ছে...", reply_markup=admin_sub_system_keyboard())
        def run_bdcast():
            for u in all_users:
                try: bot.send_message(u["_id"], text); time.sleep(0.05)
                except: pass
        heavy_task_executor.submit(run_bdcast)
        return

    # USER STATES
    elif step == 'AWAITING_SUPPORT_MSG':
        user_states.pop(chat_id, None)
        ticket_id = f"TKT-{random.randint(1000,9999)}"
        bot.send_message(ADMIN_ID, f"🎫 <b>টিকিট {ticket_id}</b>\n👤 ID: <code>{chat_id}</code>\n📝 বার্তা:\n{sanitize_html(text)}")
        return bot.send_message(chat_id, "✅ আপনার বার্তা এডমিনের কাছে পাঠানো হয়েছে।", reply_markup=bonus_support_keyboard())

    elif step == 'AWAITING_2FA_GEN':
        user_states.pop(chat_id, None)
        try:
            totp = pyotp.TOTP(text.replace(" ", "").upper())
            return bot.send_message(chat_id, f"🔑 <b>Code:</b> <code>{totp.now()}</code>", reply_markup=helper_tools_keyboard())
        except: return bot.send_message(chat_id, "❌ ভুল 2FA Key!", reply_markup=helper_tools_keyboard())

    elif step == 'AWAITING_BULK_FB_CHECK':
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "⏳ ব্যাকগ্রাউন্ডে চেক করা হচ্ছে...", reply_markup=helper_tools_keyboard())
        def run_fb_check():
            uids = [extract_numeric_uid(l) for l in text.split("\n") if extract_numeric_uid(l)][:50]
            results = list(live_check_executor.map(check_live_account, uids))
            live_list = [uid for uid, (is_live, _) in zip(uids, results) if is_live]
            out = f"📊 <b>BULK FB CHECK</b>\nTotal: {len(uids)}\n🟢 Live: {len(live_list)}\n\n" + "\n".join(live_list)
            bot.send_message(chat_id, out[:4000])
        heavy_task_executor.submit(run_fb_check)
        return

    elif step == 'AWAITING_WITHDRAW_ACCOUNT':
        method_name = state.get('method', 'bKash')
        user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_AMOUNT', 'method': method_name, 'account': text.strip()}
        bal = float(user.get("virtual_wallet") if user.get("role") == "sub_admin" else user.get("balance") or 0.0)
        return bot.send_message(chat_id, f"✅ অ্যাকাউন্ট: {text.strip()}\n💰 কত টাকা উইথড্র করবেন? (ব্যালেন্স: ৳{bal:.2f})", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_WITHDRAW_AMOUNT':
        try: req_amount = float(text.strip())
        except: return bot.send_message(chat_id, "❌ সংখ্যা লিখুন:", reply_markup=cancel_keyboard())
        bal_field = "virtual_wallet" if user.get("role") == "sub_admin" else "balance"
        bal = float(user.get(bal_field) or 0.0)
        if req_amount < 50.0 or req_amount > bal: return bot.send_message(chat_id, "❌ ব্যালেন্স এরর!", reply_markup=cancel_keyboard())
        user_states.pop(chat_id, None)
        update_user_field(chat_id, bal_field, bal - req_amount)
        withdraw_id = generate_withdraw_id()
        withdrawals_col.insert_one({"withdraw_id": withdraw_id, "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "method": state['method'], "account": state['account'], "amount": req_amount, "status": "Pending", "time": get_bd_time().strftime("%Y-%m-%d %H:%M:%S")})
        return bot.send_message(chat_id, f"🎉 <b>রিকোয়েস্ট জমা হয়েছে! (ID: {withdraw_id})</b>", reply_markup=account_keyboard())

    elif step == 'AWAITING_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID!")
        cat = state.get('category', 'fb_cookie')
        is_allowed, allow_msg = is_submission_allowed(cat, get_bd_time())
        if not is_allowed: return bot.send_message(chat_id, allow_msg, reply_markup=submit_tasks_keyboard())
        state['uid'] = uid; state['step'] = 'AWAITING_SINGLE_DATA'
        user_states[chat_id] = state
        bot.send_message(chat_id, f"✅ Verified UID: <code>{uid}</code>\n► এবার ডাটা/কুকিজ দিন:", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_SINGLE_DATA':
        cat, uid = state.get('category'), state.get('uid')
        p_rule = str(get_setting("pass_rule", "@21")).strip()
        saved_pass = user.get("custom_password")
        if saved_pass and validate_strict_password(saved_pass, p_rule):
            now_time = get_bd_time()
            rate = float(get_current_task_rate(cat))
            track_id = generate_tracking_id()
            try:
                submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": saved_pass, "payload": text, "payload_hash": generate_payload_hash(text), "track_id": track_id, "category_key": cat, "rate": rate, "status": "Hold", "date_key": now_time.strftime("%Y-%m-%d"), "date_str": now_time.strftime("%Y-%m-%d %H:%M:%S")})
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
                send_private_backup_message(f"📌 [BACKUP] Track: {track_id} | UID: {uid}\nPass: {saved_pass}\nData: {text[:2500]}")
            except: return bot.send_message(chat_id, "❌ ডুপ্লিকেট UID!")
            state['step'] = 'AWAITING_UID'
            user_states[chat_id] = state
            return bot.send_message(chat_id, f"🎉 <b>জমা সফল!</b> (৳{rate:.2f})\n► পরবর্তী UID সেন্ড করুন:", reply_markup=cancel_keyboard())
        else:
            state['payload'] = text; state['step'] = 'AWAITING_MANUAL_PASSWORD'
            user_states[chat_id] = state
            return bot.send_message(chat_id, "🔑 <b>এই একাউন্টের আসল পাসওয়ার্ডটি দিন:</b>", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_MANUAL_PASSWORD':
        cat, uid, payload = state.get('category'), state.get('uid'), state.get('payload')
        manual_pass = text.strip()
        p_rule = str(get_setting("pass_rule", "@21")).strip()
        if p_rule and p_rule.lower() != "none" and not validate_strict_password(manual_pass, p_rule):
            return bot.send_message(chat_id, "⚠️ পাসওয়ার্ডের শেষে আজকের নিয়ম নেই। বাতিল করা হয়েছে।", reply_markup=cancel_keyboard())
        now_time = get_bd_time()
        rate = float(get_current_task_rate(cat))
        track_id = generate_tracking_id()
        try:
            submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": manual_pass, "payload": payload, "payload_hash": generate_payload_hash(payload), "track_id": track_id, "category_key": cat, "rate": rate, "status": "Hold", "date_key": now_time.strftime("%Y-%m-%d"), "date_str": now_time.strftime("%Y-%m-%d %H:%M:%S")})
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
            update_user_field(chat_id, "temp_pending_password", manual_pass)
            send_private_backup_message(f"📌 [BACKUP] Track: {track_id} | UID: {uid}\nPass: {manual_pass}")
        except: return bot.send_message(chat_id, "❌ ডুপ্লিকেট UID!")
        state['step'] = 'AWAITING_UID'
        user_states[chat_id] = state
        return bot.send_message(chat_id, f"🎉 <b>জমা সফল!</b> (৳{rate:.2f})\n► পরবর্তী UID সেন্ড করুন:", reply_markup=cancel_keyboard())


# ================= 10. FLASK SERVER & PRODUCTION LAUNCH =================
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

if __name__ == "__main__":
    print("Enterprise OEB NEXUS Cyber-AI Engine Active...")
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    
    if render_url:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"{render_url}/{TOKEN}")
            print(f"[WEBHOOK LIVE]: {render_url}/{TOKEN}")
        except: pass
        try:
            from waitress import serve
            serve(flask_app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threads=200)
        except ImportError:
            flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
    else:
        try: bot.remove_webhook()
        except: pass
        def run_server():
            try:
                from waitress import serve
                serve(flask_app, host="0.0.0.0", port=10000, threads=200)
            except ImportError:
                flask_app.run(host="0.0.0.0", port=10000, threaded=True)
        threading.Thread(target=run_server, daemon=True).start()
        bot.infinity_polling(skip_pending=True)