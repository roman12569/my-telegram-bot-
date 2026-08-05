# ==============================================================================
# OEB NEXUS - COMPLETE PREMIUM ENGINE (Bug-Fixed, Multi-Language, Premium UI)
# ==============================================================================

import os
import gc
import io
import re
import csv
import time
import random
import string
import hashlib
import threading
import collections
import concurrent.futures
from datetime import datetime, timedelta, timezone

import requests
import openpyxl
import pyotp
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

from flask import Flask
from waitress import serve

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

# ==========================================
# 1. Environment Variables & Constants
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6257034751"))
BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID", "-1003943094107"))

BD_TIMEZONE = timezone(timedelta(hours=6))

UAS = [
    "Mozilla/5.0 (Linux; Android 13; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
]

REQUIRED_CHANNELS = [
    {"name": "Online Earning Bazar™🍀", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "ONLINE EARNING METHOD", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Online Earning Shop🗂️", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

# ==========================================
# 2. Multi-Language Support (i18n)
# ==========================================
LANGS = {
    "main_menu": {"en": "🏠 <b>Main Menu</b>", "bn": "🏠 <b>মূল মেনু</b>"},
    "select_sub_type": {"en": "📦 <b>Select Submission Type:</b>", "bn": "📦 <b>সাবমিশন টাইপ নির্বাচন করুন:</b>"},
    "select_category": {"en": "📂 <b>Select Task Category:</b>", "bn": "📂 <b>টাস্ক ক্যাটাগরি নির্বাচন করুন:</b>"},
    "send_uid": {"en": "🆔 Please send the <b>numeric UID</b>:", "bn": "🆔 অনুগ্রহ করে <b>numeric UID</b> পাঠান:"},
    "send_payload": {"en": "📦 Now send the payload (Cookie/2FA data):", "bn": "📦 এখন পেলোড (Cookie/2FA data) পাঠান:"},
    "send_bulk": {"en": "📝 Send your bulk text (one task per line):", "bn": "📝 আপনার বাল্ক টেক্সট পাঠান (প্রতি লাইনে একটি টাস্ক):"},
    "send_file": {"en": "📂 Send your .xlsx or .csv file:", "bn": "📂 আপনার .xlsx বা .csv ফাইল পাঠান:"},
    "helper_tools": {"en": "🛠 <b>Helper Tools:</b>", "bn": "🛠 <b>হেল্পার টুলস:</b>"},
    "profile_wallet": {"en": "💼 <b>Profile &amp; Wallet:</b>", "bn": "💼 <b>প্রোফাইল ও ওয়ালেট:</b>"},
    "reward_support": {"en": "🎁 <b>Rewards &amp; Support:</b>", "bn": "🎁 <b>রিওয়ার্ড ও সাপোর্ট:</b>"},
    "admin_center": {"en": "⚙️ <b>Admin Control Center:</b>", "bn": "⚙️ <b>অ্যাডমিন কন্ট্রোল সেন্টার:</b>"},
    "enter_password": {"en": "🔐 Please enter your password to confirm:", "bn": "🔐 কনফার্ম করতে আপনার পাসওয়ার্ড দিন:"},
    "maintenance": {"en": "🛠 Bot is under maintenance.", "bn": "🛠 বট মেইনটেন্যান্সে আছে।"},
    "banned": {"en": "🚫 You are banned.", "bn": "🚫 আপনি ব্যান করা আছেন।"},
    "force_join": {"en": "⚠️ <b>Force Join Required!</b>\n\nPlease join:\n", "bn": "⚠️ <b>ফোর্স জয়েন আবশ্যক!</b>\n\nযোগ দিন:\n"},
    "invalid_uid": {"en": "❌ Invalid or Duplicate UID.", "bn": "❌ অবৈধ বা ডুপ্লিকেট UID।"},
    "task_saved": {"en": "✅ <b>Task Saved!</b>", "bn": "✅ <b>টাস্ক সেভ হয়েছে!</b>"},
    "set_pass_first": {"en": "❌ Set your password first.", "bn": "❌ আগে আপনার পাসওয়ার্ড সেট করুন।"},
    "my_balance": {"en": "💰 <b>Your Balances:</b>\n\n💵 Main: <code>{bal}</code> BDT\n🔒 Hold: <code>{hold}</code> BDT\n_VIRTUAL: <code>{virt}</code> BDT", "bn": "💰 <b>আপনার ব্যালেন্স:</b>\n\n💵 মূল: <code>{bal}</code> BDT\n🔒 হোল্ড: <code>{hold}</code> BDT\n_VIRTUAL: <code>{virt}</code> BDT"},
    "enter_withdraw_amt": {"en": "💸 Enter amount to withdraw:", "bn": "💸 উইথড্র করার পরিমাণ লিখুন:"},
    "bonus_claimed": {"en": "🎉 You claimed 1 BDT bonus!", "bn": "🎉 আপনি 1 BDT বোনাস পেয়েছেন!"},
    "bonus_already": {"en": "⚠️ Bonus already claimed today.", "bn": "⚠️ আজকের বোনাস ইতিমধ্যে নেওয়া হয়েছে।"},
}

def t(key, lang="en", **kwargs):
    template = LANGS.get(key, {}).get(lang, LANGS.get(key, {}).get("en", key))
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    return template

# ==========================================
# 3. Bot & Optimized MongoDB Connection
# ==========================================
bot = telebot.TeleBot(BOT_TOKEN)

mongo_client = MongoClient(MONGO_URL, maxPoolSize=20, minPoolSize=5, socketTimeoutMS=10000, connect=False)
db = mongo_client["earning_bazar_advanced"]
users_col = db["users"]
submissions_col = db["submissions"]
settings_col = db["settings"]
withdrawals_col = db["withdrawals"]
blacklisted_payloads_col = db["blacklisted_payloads"]
ai_logs_col = db["ai_logs"]

submissions_col.create_index([("track_id", 1)], unique=True, background=True)
submissions_col.create_index([("uid", 1)], background=True)
submissions_col.create_index([("date_key", 1)], background=True)
submissions_col.create_index([("status", 1)], background=True)

# ==========================================
# 4. Strict RAM Protection (Bounded Executors)
# ==========================================
class GuaranteedBoundedExecutor:
    def __init__(self, max_workers, max_queue_size=None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.max_queue_size = max_queue_size
        self.queue_semaphore = threading.Semaphore(max_queue_size) if max_queue_size else None

    def submit(self, fn, *args, **kwargs):
        if self.queue_semaphore:
            if not self.queue_semaphore.acquire(blocking=False):
                return None
        return self.executor.submit(self._task_wrapper, fn, *args, **kwargs)

    def _task_wrapper(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            if self.queue_semaphore:
                self.queue_semaphore.release()

background_executor = GuaranteedBoundedExecutor(max_workers=3, max_queue_size=100)
heavy_task_executor = GuaranteedBoundedExecutor(max_workers=2, max_queue_size=50)
live_check_executor = GuaranteedBoundedExecutor(max_workers=2, max_queue_size=100)
cache_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="CacheSync")

# ==========================================
# 5. In-Memory Caching System
# ==========================================
class FastSettingsCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self._load_initial_cache()

    def _load_initial_cache(self):
        try:
            for doc in settings_col.find():
                if 'key' in doc and 'value' in doc:
                    self.cache[doc['key']] = doc['value']
        except Exception as e:
            print(f"[Cache] Init error: {e}")

    def get(self, key, default=None):
        with self.lock:
            if key in self.cache: return self.cache[key]
        db_doc = settings_col.find_one({"key": key})
        if db_doc and 'value' in db_doc:
            val = db_doc['value']
            with self.lock:
                if key not in self.cache: self.cache[key] = val
            return val
        return default

    def set(self, key, value):
        with self.lock:
            self.cache[key] = value
        cache_executor.submit(self._async_db_update, key, value)

    def _async_db_update(self, key, value):
        try:
            settings_col.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)
        except Exception as e:
            print(f"[Cache] Async update failed: {e}")

class MongoDict:
    def __init__(self, collection, max_cache_size=2000):
        self.collection = collection
        self.max_cache_size = max_cache_size
        self.lock = threading.Lock()
        self.cache = collections.OrderedDict()

    def get(self, key, default=None):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        db_doc = self.collection.find_one({"_id": key})
        if db_doc and 'value' in db_doc:
            val = db_doc['value']
            with self.lock:
                if key in self.cache:
                    self.cache.move_to_end(key)
                    return self.cache[key]
                self.cache[key] = val
                self.cache.move_to_end(key)
                if len(self.cache) > self.max_cache_size: self.cache.popitem(last=False)
            return val
        return default

    def __setitem__(self, key, value):
        with self.lock:
            if key in self.cache: self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.max_cache_size: self.cache.popitem(last=False)
        cache_executor.submit(self._async_db_upsert, key, value)

    def pop(self, key, default=None):
        with self.lock:
            val = self.cache.pop(key, default)
        if val is not default:
            cache_executor.submit(self._async_db_delete, key)
            return val
        return default

    def _async_db_upsert(self, key, value):
        try: self.collection.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)
        except Exception as e: print(f"[MongoDict] Upsert error: {e}")

    def _async_db_delete(self, key):
        try: self.collection.delete_one({"_id": key})
        except Exception as e: print(f"[MongoDict] Delete error: {e}")

fast_settings = FastSettingsCache()
user_states = MongoDict(db['user_states'], max_cache_size=2000)

def get_setting(key, default=None): return fast_settings.get(key, default)
def update_setting(key, value): fast_settings.set(key, value)

# ==========================================
# 6. Time & Core Utilities
# ==========================================
def get_bd_time(): return datetime.now(BD_TIMEZONE)

def parse_iso_datetime(dt_val):
    if dt_val is None: return None
    try:
        dt = datetime.fromisoformat(dt_val) if isinstance(dt_val, str) else dt_val if isinstance(dt_val, datetime) else None
        if not dt: return None
        return dt.replace(tzinfo=BD_TIMEZONE) if dt.tzinfo is None else dt.astimezone(BD_TIMEZONE)
    except: return None

def sanitize_html(text):
    if not text: return "User"
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text

def generate_tracking_id(): return f"SUB-{int(get_bd_time().timestamp())}-{random.randint(100, 999)}"
def generate_withdraw_id(): return f"WDR-{int(get_bd_time().timestamp())}-{random.randint(100, 999)}"

# ==========================================
# 7. User Management & Security
# ==========================================
def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        new_user = {"_id": chat_id, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0, "banned": False, "custom_password": "", "role": "member", "virtual_wallet": 0.0, "assigned_sub_admin": None, "last_bonus_date": None, "lang": "bn"}
        try:
            users_col.insert_one(new_user)
            return new_user
        except DuplicateKeyError: return users_col.find_one({"_id": chat_id})
    return user

def update_user_field(chat_id, field, val):
    if field == "_id": return
    def _db_update():
        try: users_col.update_one({"_id": chat_id}, {"$set": {field: val}}, upsert=True)
        except Exception as e: print(f"[AsyncUpdate] {e}")
    background_executor.submit(_db_update)

def is_user_banned(chat_id):
    user = users_col.find_one({"_id": chat_id}, {"banned": 1})
    return user.get("banned", False) if user else False

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for channel in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(channel["username"], user_id)
            if member.status in ['left', 'kicked']: return False
        except: return False
    return True

def validate_strict_password(password, rule):
    if not rule or str(rule).strip().lower() == "none": return True
    if not password: return False
    return str(password).strip().endswith(str(rule).strip())

UID_PATTERN = re.compile(r'(?:c_user=|id=|profile\.php\?id=|/u/)(\d{8,20})|(?<!\d)(\d{8,20})(?!\d)')
def extract_numeric_uid(text):
    if not text: return None
    match = UID_PATTERN.search(str(text))
    return (match.group(1) or match.group(2)) if match else None

def is_duplicate_uid(uid):
    if not uid: return True
    try: return submissions_col.find_one({"uid": str(uid)}, {"_id": 1}) is not None
    except: return True

def generate_payload_hash(payload):
    if not payload: return None
    return hashlib.sha256(re.sub(r'\s+', '', str(payload)).encode('utf-8')).hexdigest()

def is_payload_blacklisted(p_hash):
    if not p_hash: return True
    try: return blacklisted_payloads_col.find_one({"_id": p_hash}) is not None
    except: return True

def is_valid_cookies(cookie_str):
    if not cookie_str: return False
    lower = str(cookie_str).lower()
    return any(tok in lower for tok in ["c_user=", "datr=", "xs=", "sessionid="])

# ==========================================
# 8. Live Checkers & Pricing
# ==========================================
def check_live_account(uid):
    clean_uid = extract_numeric_uid(uid)
    if not clean_uid: return False, "Invalid UID"
    time.sleep(random.uniform(0.5, 1.5))
    try:
        headers = {"User-Agent": random.choice(UAS), "Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Mode": "navigate"}
        res = requests.get(f"https://m.facebook.com/profile.php?id={clean_uid}", headers=headers, timeout=5.0, allow_redirects=True)
        content, res_url = res.text.lower(), (res.url or "").lower()
        if res.status_code == 403 or "login" in res_url or "checkpoint" in res_url:
            if "c_user" not in res_url and clean_uid not in res_url: return False, "Cloud Blocked"
        if res.status_code != 200: return False, "Suspended/Dead"
        if 'content="no-cache"' in content or "not found" in content: return False, "Checkpoint"
        if "profile_ring" in content or "mbasic_inline_feed_composer" in content or clean_uid in res_url: return True, "Live"
        return False, "Suspended"
    except: return False, "Network Error"

def get_active_surge_bonus():
    surge = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if surge.get("active"):
        exp_str = surge.get("expires_at")
        if exp_str:
            exp_dt = parse_iso_datetime(exp_str)
            if exp_dt and get_bd_time() < exp_dt: return float(surge.get("bonus", 0.0))
            return 0.0
        return float(surge.get("bonus", 0.0))
    return 0.0

def get_current_task_rate(cat_key):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    return float(rates.get(cat_key, 5.0)) + get_active_surge_bonus()

def get_shift_config():
    default = {"current_date": get_bd_time().strftime("%Y-%m-%d"), "deadlines": {"fb_cookie": "21:20", "fb_2fa": "21:20", "ig_cookie": "20:20", "ig_2fa": "20:20", "default": "23:59"}}
    return get_setting("shift_config", default)

def is_submission_allowed(cat_key, req_time):
    try:
        shift = get_shift_config()
        if req_time.strftime("%Y-%m-%d") != shift.get("current_date"): return False, "⚠️ আজকের শিফট এখনো চালু হয়নি!"
        deadlines = shift.get("deadlines", {})
        deadline_str = deadlines.get(cat_key, deadlines.get("default", "23:59"))
        hours, minutes = map(int, deadline_str.split(":"))
        if req_time > req_time.replace(hour=hours, minute=minutes, second=0, microsecond=0): return False, f"⚠️ ডেডলাইন {deadline_str} শেষ!"
        return True, "Allowed"
    except: return True, "Allowed"

# ==========================================
# 9. Submission Handlers
# ==========================================
def _save_submission(chat_id, uid, payload, category):
    track_id, date_key, rate = generate_tracking_id(), get_bd_time().strftime("%Y-%m-%d"), get_current_task_rate(category)
    doc = {"_id": track_id, "track_id": track_id, "uid": str(uid), "payload": payload, "category": category, "rate": rate, "status": "Hold", "date_key": date_key, "submitted_at": get_bd_time(), "user_id": chat_id}
    try:
        submissions_col.insert_one(doc)
        users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
        return track_id, rate
    except DuplicateKeyError: return None, 0.0
    except Exception as e: print(f"[Save] {e}"); return None, 0.0

def handle_single_uid(chat_id, text, lang):
    uid = extract_numeric_uid(text)
    if not uid or is_duplicate_uid(uid): return t("invalid_uid", lang)
    state_data = user_states.get(chat_id, {})
    category = state_data.get("category", "fb_cookie")
    allowed, msg = is_submission_allowed(category, get_bd_time())
    if not allowed: return msg
    state_data["state"] = "AWAITING_SINGLE_DATA"
    state_data["temp_uid"] = uid
    user_states[chat_id] = state_data
    return f"✅ UID: <code>{uid}</code>\n\n{t('send_payload', lang)}"

def handle_single_data(chat_id, payload, lang):
    state_data = user_states.get(chat_id, {})
    uid, category = state_data.get("temp_uid"), state_data.get("category", "fb_cookie")
    if not uid: return f"❌ Session expired. /start"
    global_rule, user_data = get_setting("pass_rule", ""), get_user_data(chat_id)
    if validate_strict_password(user_data.get("custom_password"), global_rule):
        track_id, rate = _save_submission(chat_id, uid, payload, category)
        if track_id:
            state_data["state"] = "AWAITING_UID"; state_data.pop("temp_uid", None); user_states[chat_id] = state_data
            return f"{t('task_saved', lang)}\n🎫 ID: <code>{track_id}</code>\n💰 Rate: {rate} BDT\n\n🔄 Next UID:"
        return "❌ Duplicate."
    else:
        state_data["state"] = "AWAITING_MANUAL_PASSWORD"; state_data["temp_payload"] = payload; user_states[chat_id] = state_data
        return t("enter_password", lang)

def handle_manual_password(chat_id, password, lang):
    state_data = user_states.get(chat_id, {})
    uid, payload, category = state_data.get("temp_uid"), state_data.get("temp_payload"), state_data.get("category", "fb_cookie")
    if not uid or not payload: return "❌ Session expired."
    if validate_strict_password(password, get_setting("pass_rule", "")):
        track_id, rate = _save_submission(chat_id, uid, payload, category)
        if track_id:
            update_user_field(chat_id, "custom_password", password)
            state_data["state"] = "AWAITING_UID"; state_data.pop("temp_uid", None); state_data.pop("temp_payload", None); user_states[chat_id] = state_data
            return f"{t('task_saved', lang)}\n🎫 ID: <code>{track_id}</code>\n💰 Rate: {rate} BDT\n🔓 Saved.\n\n🔄 Next UID:"
        return "❌ Duplicate."
    return "❌ Wrong password."

def handle_bulk_text(chat_id, text, lang):
    global_rule, user_data = get_setting("pass_rule", ""), get_user_data(chat_id)
    if not validate_strict_password(user_data.get("custom_password"), global_rule): return t("set_pass_first", lang)
    bot.send_message(chat_id, "⏳ <b>Processing bulk...</b>", parse_mode="HTML")
    def rbk():
        accepted, payout, blocked = [], 0.0, 0
        try:
            pending = []
            for line in text.strip().split('\n'):
                line = line.strip()
                if not line: continue
                uid = extract_numeric_uid(line)
                if not uid or is_duplicate_uid(uid) or is_payload_blacklisted(generate_payload_hash(line)): continue
                cat = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
                allowed, _ = is_submission_allowed(cat, get_bd_time())
                if allowed: pending.append({"uid": uid, "payload": line, "category": cat})
            if not pending: bot.send_message(chat_id, "❌ No valid tasks."); return
            def _chk(i-tem):
                il, msg = check_live_account(item["uid"]); item["is_live"] = il; item["status_msg"] = msg; return item
            for c in live_check_executor.map(_chk, pending):
                if c["is_live"]:
                    tid, rate = _save_submission(chat_id, c["uid"], c["payload"], c["category"])
                    if tid: accepted.append(c["uid"]); payout += rate
                elif c["status_msg"] == "Cloud Blocked": blocked += 1
            summary = f"✅ <b>Bulk Done!</b>\n\n📥 Accepted: {len(accepted)}\n💰 Payout: {payout:.2f} BDT\n"
            if blocked: summary += f"⚠️ Cloud Blocked: {blocked}\n"
            if accepted: summary += f"📝 First 5 IDs:\n<code>{'\n'.join(accepted[:5])}</code>"
            bot.send_message(chat_id, summary, parse_mode="HTML")
        except Exception as e: print(f"[Bulk] {e}"); bot.send_message(chat_id, "❌ Error.")
        finally: gc.collect()
    heavy_task_executor.submit(rbk)
    return None

# ==========================================
# 10. File & Auto-Matcher Processors
# ==========================================
def send_private_backup_message(content, doc_buf=None, doc_name=None):
    def task():
        try:
            safe = str(content)[:3750]
            if doc_buf and doc_name: doc_buf.seek(0); bot.send_document(BACKUP_CHANNEL_ID, doc_buf, caption=safe, parse_mode="HTML")
            else: bot.send_message(BACKUP_CHANNEL_ID, safe, parse_mode="HTML")
        except: pass
    background_executor.submit(task)

@bot.message_handler(content_types=['document'])
def handle_document(message): heavy_task_executor.submit(_process_document, message)

def _process_document(message):
    chat_id = message.chat.id
    if get_setting("maintenance_mode", False) and chat_id != ADMIN_ID: bot.send_message(chat_id, "🛠 Maintenance."); return
    if is_user_banned(chat_id): bot.send_message(chat_id, "🚫 Banned."); return
    
    state_data = user_states.get(chat_id, {})
    state = state_data.get("state")
    
    if state == "AWAITING_BUYER_REPORT" and chat_id == ADMIN_ID:
        process_buyer_report(message); return
    elif state != "AWAITING_EXCEL_FILE":
        bot.send_message(chat_id, "❌ Use menu to start file submission."); return

    global_rule, user_data = get_setting("pass_rule", ""), get_user_data(chat_id)
    if not validate_strict_password(user_data.get("custom_password"), global_rule): bot.send_message(chat_id, "❌ Invalid Password."); return
    
    bot.send_message(chat_id, "⏳ <b>Processing file...</b>", parse_mode="HTML")
    original_name = message.document.file_name or "file.xlsx"
    try:
        dw = bot.download_file(bot.get_file(message.document.file_id).file_path)
        cands = []
        if original_name.lower().endswith('.csv'):
            for row in csv.reader(dw.decode('utf-8', errors='ignore').splitlines()):
                uid, payload = None, None
                for v in row:
                    vs = str(v).strip()
                    if not uid: uid = extract_numeric_uid(vs)
                    if not payload and (is_valid_cookies(vs) or (len(vs) > 20 and not vs.isdigit())): payload = vs
                if uid and payload and not is_duplicate_uid(uid): cands.append({"uid": uid, "payload": payload})
        elif original_name.lower().endswith(('.xlsx', '.xls')):
            wb = openpyxl.load_workbook(io.BytesIO(dw), read_only=True, data_only=True)
            for row in wb.active.iter_rows(values_only=True):
                uid, payload = None, None
                for v in row:
                    if v is None: continue
                    vs = str(v).strip()
                    if not uid: uid = extract_numeric_uid(vs)
                    if not payload and (is_valid_cookies(vs) or (len(vs) > 20 and not vs.isdigit())): payload = vs
                if uid and payload and not is_duplicate_uid(uid): cands.append({"uid": uid, "payload": payload})
            wb.close()
        else: bot.send_message(chat_id, "❌ Unsupported format."); return

        valid = []
        for c in cands:
            if is_payload_blacklisted(generate_payload_hash(c["payload"])): continue
            cat = "fb_cookie" if is_valid_cookies(c["payload"]) else "fb_2fa"
            allowed, _ = is_submission_allowed(cat, get_bd_time())
            if allowed: c["category"] = cat; valid.append(c)
        
        if not valid: bot.send_message(chat_id, "❌ No valid tasks."); return
        
        def _chk(item): il, msg = check_live_account(item["uid"]); item["is_live"] = il; item["status_msg"] = msg; return item
        accepted_count, total_payout = 0, 0.0
        for c in live_check_executor.map(_chk, valid):
            if c["is_live"]:
                tid, rate = _save_submission(chat_id, c["uid"], c["payload"], c["category"])
                if tid: accepted_count += 1; total_payout += rate
                
        send_private_backup_message(f"📂 Backup | 👤 {chat_id} | ✅ {accepted_count} | 💰 {total_payout:.2f}", doc_buf=io.BytesIO(dw), doc_name=f"Backup_{original_name}")
        bot.send_message(chat_id, f"✅ <b>File Done!</b>\n\n📥 Accepted: {accepted_count}\n💰 Payout: {total_payout:.2f} BDT", parse_mode="HTML")
        state_data["state"] = "AWAITING_UID"; user_states[chat_id] = state_data
    except Exception as e: print(f"[FileProc] {e}"); bot.send_message(chat_id, "❌ Error.")
    finally: gc.collect()

def process_buyer_report(message):
    chat_id = message.chat.id
    state_data = user_states.get(chat_id, {})
    target_date, target_cat = state_data.get("target_date", "ALL"), state_data.get("target_cat", "ALL")
    state_data["state"] = "AWAITING_UID"; user_states[chat_id] = state_data
    bot.send_message(chat_id, "⏳ <b>Matching...</b>", parse_mode="HTML")
    try:
        dw = bot.download_file(bot.get_file(message.document.file_id).file_path)
        ex_uids = set()
        name = (message.document.file_name or "").lower()
        if name.endswith('.csv'):
            for row in csv.reader(dw.decode('utf-8', errors='ignore').splitlines()):
                for v in row:
                    vs = str(v).strip().replace('.0', '')
                    if vs.isdigit() and 8 <= len(vs) <= 20: ex_uids.add(vs)
        elif name.endswith(('.xlsx', '.xls')):
            wb = openpyxl.load_workbook(io.BytesIO(dw), read_only=True, data_only=True)
            for row in wb.active.iter_rows(values_only=True):
                for v in row:
                    if v is None: continue
                    vs = str(v).strip().replace('.0', '')
                    if vs.isdigit() and 8 <= len(vs) <= 20: ex_uids.add(vs)
            wb.close()
        else: bot.send_message(chat_id, "❌ Unsupported."); return

        q = {"status": "Hold"}
        if target_date != "ALL": q["date_key"] = target_date
        if target_cat != "ALL": q["category"] = target_cat
        subs = list(submissions_col.find(q))
        if not subs: bot.send_message(chat_id, "❌ No pending tasks."); return

        appr, rej, payout, notifs = 0, 0, 0.0, collections.defaultdict(list)
        for s in subs:
            uid, amt, wid = str(s.get("uid", "")), float(s.get("rate", 0.0)), s.get("user_id")
            if not wid: continue
            if uid in ex_uids:
                submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Approved"}})
                user = users_col.find_one({"_id": wid}, {"role": 1})
                role = user.get("role", "member") if user else "member"
                if role == "sub_admin": users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {"virtual_wallet": amt, "hold_balance": -amt}})
                else: users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                appr += 1; payout += amt; notifs[wid].append(f"✅ <b>Approved:</b> <code>{uid}</code> | 💰 +{amt}")
            else:
                submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {"hold_balance": -amt}})
                rej += 1; notifs[wid].append(f"❌ <b>Rejected:</b> <code>{uid}</code>")
        
        for wid, msgs in notifs.items():
            try: bot.send_message(wid, "\n".join(msgs[:15]), parse_mode="HTML"); time.sleep(0.04)
            except: pass
        bot.send_message(ADMIN_ID, f"✅ <b>Matching Done!</b>\n\n📊 Approved: {appr}\n💰 Payout: {payout:.2f}\n❌ Rejected: {rej}", parse_mode="HTML")
    except Exception as e: print(f"[Matcher] {e}"); bot.send_message(chat_id, "❌ Error.")
    finally: gc.collect()

# ==========================================
# 11. Dynamic UI & Main Router
# ==========================================
def main_bottom_keyboard(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📦 Submit Tasks", "🛠 Helper Tools", "💼 Profile & Wallet", "🎁 Reward & Support", "🌐 Language / ভাষা")
    if chat_id == ADMIN_ID or get_user_data(chat_id).get("role") in ["admin", "sub_admin"]: kb.add("⚙️ Admin Panel")
    return kb

def cancel_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("❌ Cancel")
    return kb

def category_bottom_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    surge = get_active_surge_bonus()
    for cat, base in rates.items(): kb.add(f"🔹 {cat} ({base + surge:.1f} BDT)")
    kb.add("❌ Cancel")
    return kb

def admin_bottom_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📋 Task Mgmt", "💰 Finance", "⚙️ Settings", "🖥 System", "❌ Cancel")
    return kb

@bot.message_handler(commands=['start', 'menu'])
def cmd_start(message):
    chat_id = message.chat.id
    user_states.pop(chat_id, None)
    user = get_user_data(chat_id)
    lang = user.get("lang", "bn")
    
    if not check_force_join(chat_id):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Verify Join", callback_data="verify_join"))
        msg = t("force_join", lang)
        for ch in REQUIRED_CHANNELS: msg += f"➡️ {ch['name']}: {ch['url']}\n"
        bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=kb); return

    bot.send_message(chat_id, t("main_menu", lang), parse_mode="HTML", reply_markup=main_bottom_keyboard(chat_id))

@bot.message_handler(content_types=['text'])
def handle_text(message): background_executor.submit(_process_main_router, message)

def _process_main_router(message):
    chat_id = message.chat.id
    text = message.text.strip()
    user = get_user_data(chat_id)
    lang = user.get("lang", "bn")
    
    if get_setting("maintenance_mode", False) and chat_id != ADMIN_ID: bot.send_message(chat_id, t("maintenance", lang)); return
    if is_user_banned(chat_id): bot.send_message(chat_id, t("banned", lang)); return

    if text in ["❌ Cancel", "/start", "/menu"]:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, t("main_menu", lang), parse_mode="HTML", reply_markup=main_bottom_keyboard(chat_id)); return

    state_data = user_states.get(chat_id)
    if state_data:
        state = state_data.get("state")
        if state == "AWAITING_UID":
            bot.send_message(chat_id, handle_single_uid(chat_id, text, lang), parse_mode="HTML"); return
        elif state == "AWAITING_SINGLE_DATA":
            bot.send_message(chat_id, handle_single_data(chat_id, text, lang), parse_mode="HTML"); return
        elif state == "AWAITING_MANUAL_PASSWORD":
            bot.send_message(chat_id, handle_manual_password(chat_id, text, lang), parse_mode="HTML"); return
        elif state == "AWAITING_BULK_TEXT":
            res = handle_bulk_text(chat_id, text, lang)
            if res: bot.send_message(chat_id, res, parse_mode="HTML"); return
        elif state == "AWAITING_2FA_GEN":
            try: bot.send_message(chat_id, f"🔐 <b>2FA:</b> <code>{pyotp.TOTP(text.replace(' ', '').upper()).now()}</code>", parse_mode="HTML")
            except: bot.send_message(chat_id, "❌ Invalid Secret.")
            user_states.pop(chat_id, None); return
        elif state == "AWAITING_ADMIN_PASS_RULE" and chat_id == ADMIN_ID:
            update_setting("pass_rule", text); bot.send_message(chat_id, f"✅ Pass rule: <code>{text}</code>", parse_mode="HTML"); user_states.pop(chat_id, None); return
        elif state == "AWAITING_BROADCAST_MSG" and chat_id == ADMIN_ID:
            cnt = 0
            for u in users_col.find({"banned": False}):
                try: bot.send_message(u["_id"], text, parse_mode="HTML"); time.sleep(0.04); cnt += 1
                except: pass
            bot.send_message(chat_id, f"✅ Broadcasted to {cnt}."); user_states.pop(chat_id, None); return
        elif state == "AWAITING_WITHDRAW_AMT":
            try:
                amt = float(text)
                if amt <= 0 or amt > user.get("balance", 0.0): raise ValueError
                w_id = generate_withdraw_id()
                withdrawals_col.insert_one({"_id": w_id, "user_id": chat_id, "amount": amt, "status": "Pending", "requested_at": get_bd_time()})
                users_col.update_one({"_id": chat_id}, {"$inc": {"balance": -amt}})
                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"w_appr_{w_id}"), types.InlineKeyboardButton("❌ Reject", callback_data=f"w_rej_{w_id}"))
                bot.send_message(ADMIN_ID, f"💸 <b>Withdraw Request</b>\n\n👤 <code>{chat_id}</code>\n💰 Amount: <code>{amt}</code> BDT\nID: <code>{w_id}</code>", parse_mode="HTML", reply_markup=kb)
                bot.send_message(chat_id, "✅ Withdrawal requested.")
            except: bot.send_message(chat_id, "❌ Invalid amount or insufficient balance.")
            user_states.pop(chat_id, None); return

    # Menu Routing
    if text == "📦 Submit Tasks":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add("📝 Single", "📋 Bulk Text", "📂 Excel/CSV", "❌ Cancel")
        bot.send_message(chat_id, t("select_sub_type", lang), parse_mode="HTML", reply_markup=kb)
    elif text == "📝 Single":
        bot.send_message(chat_id, t("select_category", lang), parse_mode="HTML", reply_markup=category_bottom_keyboard())
    elif text.startswith("🔹 "): # Category Selected
        cat_key = text.split(" (")[0].replace("🔹 ", "")
        user_states[chat_id] = {"state": "AWAITING_UID", "category": cat_key}
        bot.send_message(chat_id, t("send_uid", lang), parse_mode="HTML", reply_markup=cancel_keyboard())
    elif text == "📋 Bulk Text":
        user_states[chat_id] = {"state": "AWAITING_BULK_TEXT"}
        bot.send_message(chat_id, t("send_bulk", lang), reply_markup=cancel_keyboard())
    elif text == "📂 Excel/CSV":
        user_states[chat_id] = {"state": "AWAITING_EXCEL_FILE"}
        bot.send_message(chat_id, t("send_file", lang), reply_markup=cancel_keyboard())
    elif text == "🛠 Helper Tools":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add("📧 Temp Email", "🔐 2FA Gen", "🏆 Leaderboard", "❌ Cancel")
        bot.send_message(chat_id, t("helper_tools", lang), parse_mode="HTML", reply_markup=kb)
    elif text == "📧 Temp Email":
        email = f"{''.join(random.choices(string.ascii_lowercase+string.digits, k=8))}@1secmail.com"
        kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("📥 Check Inbox", callback_data=f"check_otp_{email}"))
        bot.send_message(chat_id, f"📧 <b>Temp Email:</b>\n<code>{email}</code>", parse_mode="HTML", reply_markup=kb)
    elif text == "🔐 2FA Gen":
        user_states[chat_id] = {"state": "AWAITING_2FA_GEN"}; bot.send_message(chat_id, "🔐 Send <b>2FA Secret</b>:", parse_mode="HTML", reply_markup=cancel_keyboard())
    elif text == "🏆 Leaderboard":
        results = list(submissions_col.aggregate([{"$group": {"_id": "$user_id", "e": {"$sum": "$rate"}}}, {"$sort": {"e": -1}}, {"$limit": 10}]))
        msg = "🏆 <b>Top 10</b>\n\n"
        for i, r in enumerate(results, 1): msg += f"{i}. <code>{r['_id']}</code> - 💰 {r['e']:.2f}\n"
        bot.send_message(chat_id, msg, parse_mode="HTML")
    elif text == "💼 Profile & Wallet":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add("💰 Balance", "💸 Withdraw", "❌ Cancel")
        bot.send_message(chat_id, t("profile_wallet", lang), parse_mode="HTML", reply_markup=kb)
    elif text == "💰 Balance":
        bot.send_message(chat_id, t("my_balance", lang, bal=user.get("balance",0), hold=user.get("hold_balance",0), virt=user.get("virtual_wallet",0)), parse_mode="HTML")
    elif text == "💸 Withdraw":
        user_states[chat_id] = {"state": "AWAITING_WITHDRAW_AMT"}; bot.send_message(chat_id, t("enter_withdraw_amt", lang), reply_markup=cancel_keyboard())
    elif text == "🎁 Reward & Support":
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add("📅 Daily Bonus", "🆘 Support", "❌ Cancel")
        bot.send_message(chat_id, t("reward_support", lang), parse_mode="HTML", reply_markup=kb)
    elif text == "📅 Daily Bonus":
        today = get_bd_time().strftime("%Y-%m-%d")
        if user.get("last_bonus_date") == today: bot.send_message(chat_id, t("bonus_already", lang))
        else: users_col.update_one({"_id": chat_id}, {"$inc": {"balance": 1.0}, "$set": {"last_bonus_date": today}}); bot.send_message(chat_id, t("bonus_claimed", lang))
    elif text == "🆘 Support": bot.send_message(chat_id, f"🆘 Admin: <code>{ADMIN_ID}</code>", parse_mode="HTML")
    elif text == "🌐 Language / ভাষা":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("🇧🇩 বাংলা", callback_data="set_lang_bn"), types.InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en"))
        bot.send_message(chat_id, "🌐 Select Language / ভাষা নির্বাচন করুন:", reply_markup=kb)
    elif text == "⚙️ Admin Panel" and (chat_id == ADMIN_ID or user.get("role") in ["admin", "sub_admin"]):
        bot.send_message(chat_id, t("admin_center", lang), parse_mode="HTML", reply_markup=admin_bottom_keyboard())
    elif text == "📋 Task Mgmt" and chat_id == ADMIN_ID:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2); kb.add("📊 Buyer Report", "🧹 Force Close", "📥 Export", "❌ Cancel")
        bot.send_message(chat_id, "📋 <b>Task Mgmt</b>", parse_mode="HTML", reply_markup=kb)
    elif text == "📊 Buyer Report" and chat_id == ADMIN_ID:
        user_states[chat_id] = {"state": "AWAITING_BUYER_REPORT", "target_date": "ALL", "target_cat": "ALL"}
        bot.send_message(chat_id, "📁 Upload Buyer Report (.csv/.xlsx):", reply_markup=cancel_keyboard())
    elif text == "🧹 Force Close" and chat_id == ADMIN_ID:
        mk = types.InlineKeyboardMarkup(row_width=2)
        for i in range(3): d = (get_bd_time() - timedelta(days=i)).strftime("%Y-%m-%d"); mk.add(types.InlineKeyboardButton(d, callback_data=f"force_close_{d}"))
        bot.send_message(chat_id, "⚠️ Select date to force close:", reply_markup=mk)
    elif text == "📥 Export" and chat_id == ADMIN_ID:
        mk = types.InlineKeyboardMarkup(row_width=2)
        for i in range(3): d = (get_bd_time() - timedelta(days=i)).strftime("%Y-%m-%d"); mk.add(types.InlineKeyboardButton(d, callback_data=f"exp_select_date_{d}"))
        bot.send_message(chat_id, "📊 Select date to export:", reply_markup=mk)
    elif text == "💰 Finance" and chat_id == ADMIN_ID:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2); kb.add("⏳ Pending Withdrawals", "❌ Cancel")
        bot.send_message(chat_id, "💰 <b>Finance</b>", parse_mode="HTML", reply_markup=kb)
    elif text == "⏳ Pending Withdrawals" and chat_id == ADMIN_ID:
        wds = withdrawals_col.find({"status": "Pending"})
        for w in wds:
            mk = types.InlineKeyboardMarkup(row_width=2)
            mk.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"w_appr_{w['_id']}"), types.InlineKeyboardButton("❌ Reject", callback_data=f"w_rej_{w['_id']}"))
            bot.send_message(chat_id, f"💸 <code>{w['user_id']}</code> requested <code>{w['amount']}</code> BDT\nID: <code>{w['_id']}</code>", parse_mode="HTML", reply_markup=mk)
    elif text == "⚙️ Settings" and chat_id == ADMIN_ID:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2); kb.add("🔑 Pass Rule", "🛠 Maintenance", "❌ Cancel")
        bot.send_message(chat_id, "⚙️ <b>Settings</b>", parse_mode="HTML", reply_markup=kb)
    elif text == "🔑 Pass Rule" and chat_id == ADMIN_ID:
        user_states[chat_id] = {"state": "AWAITING_ADMIN_PASS_RULE"}; bot.send_message(chat_id, "🔑 Send new rule (or 'none'):", reply_markup=cancel_keyboard())
    elif text == "🛠 Maintenance" and chat_id == ADMIN_ID:
        cur = get_setting("maintenance_mode", False); update_setting("maintenance_mode", not cur); bot.send_message(chat_id, f"✅ Maintenance: {not cur}")
    elif text == "🖥 System" and chat_id == ADMIN_ID:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2); kb.add("📢 Broadcast", "❌ Cancel")
        bot.send_message(chat_id, "🖥 <b>System</b>", parse_mode="HTML", reply_markup=kb)
    elif text == "📢 Broadcast" and chat_id == ADMIN_ID:
        user_states[chat_id] = {"state": "AWAITING_BROADCAST_MSG"}; bot.send_message(chat_id, "📢 Send msg:", reply_markup=cancel_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call): background_executor.submit(_process_callbacks, call)

def _process_callbacks(call):
    chat_id, data = call.message.chat.id, call.data
    try:
        if data == "verify_join":
            if check_force_join(chat_id): bot.answer_callback_query(call.id, "✅ Verified!"); bot.send_message(chat_id, t("main_menu", get_user_data(chat_id).get("lang","bn")), parse_mode="HTML", reply_markup=main_bottom_keyboard(chat_id))
            else: bot.answer_callback_query(call.id, "❌ Not joined!", show_alert=True)
        elif data.startswith("set_lang_"):
            lang = data.split("_")[-1]; update_user_field(chat_id, "lang", lang); bot.answer_callback_query(call.id, "✅"); bot.send_message(chat_id, t("main_menu", lang), parse_mode="HTML", reply_markup=main_bottom_keyboard(chat_id))
        elif data.startswith("w_appr_") or data.startswith("w_rej_"):
            if chat_id != ADMIN_ID: return
            w_id, is_appr = data.split("_", 2)[2], data.startswith("w_appr_")
            w = withdrawals_col.find_one({"_id": w_id})
            if not w or w.get("status") != "Pending": bot.answer_callback_query(call.id, "⚠️ Processed."); return
            amt, wid = float(w.get("amount", 0)), w.get("user_id")
            if is_appr:
                withdrawals_col.update_one({"_id": w_id}, {"$set": {"status": "Approved"}}); bot.answer_callback_query(call.id, "✅"); bot.send_message(wid, f"✅ Withdrawal of {amt} BDT approved!")
            else:
                withdrawals_col.update_one({"_id": w_id}, {"$set": {"status": "Rejected"}})
                user = get_user_data(wid)
                if user.get("role") == "sub_admin": users_col.update_one({"_id": wid}, {"$inc": {"virtual_wallet": amt}})
                else: users_col.update_one({"_id": wid}, {"$inc": {"balance": amt}})
                bot.answer_callback_query(call.id, "❌ Refunded."); bot.send_message(wid, f"❌ Withdrawal of {amt} BDT rejected. Refunded.")
        elif data.startswith("check_otp_"):
            email = data.replace("check_otp_", ""); un, dom = email.split('@')
            try:
                msgs = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={un}&domain={dom}", timeout=5).json()
                if not msgs: bot.send_message(chat_id, "📭 Empty."); return
                m_data = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={un}&domain={dom}&id={msgs[-1]['id']}", timeout=5).json()
                bot.send_message(chat_id, f"📩 <b>Body:</b>\n\n<pre>{sanitize_html(m_data.get('textBody') or m_data.get('body',''))[:3500]}</pre>", parse_mode="HTML")
            except: bot.send_message(chat_id, "❌ Fetch error.")
        elif data.startswith("force_close_") and chat_id == ADMIN_ID:
            d_str = data.replace("force_close_", ""); cnt = 0
            for s in submissions_col.find({"date_key": d_str, "status": "Hold"}):
                amt = float(s.get("rate",0)); wid = s.get("user_id")
                submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {"hold_balance": -amt}}); cnt += 1
            bot.answer_callback_query(call.id, "✅"); bot.send_message(chat_id, f"✅ Closed {cnt} tasks for {d_str}."); gc.collect()
        elif data.startswith("exp_select_date_") and chat_id == ADMIN_ID:
            d_str = data.replace("exp_select_date_", ""); buf = io.StringIO(); w = csv.writer(buf); w.writerow(["ID", "UID", "Cat", "Rate", "Status", "User"])
            for s in submissions_col.find({"date_key": d_str}): w.writerow([s.get('track_id'), s.get('uid'), s.get('category'), s.get('rate'), s.get('status'), s.get('user_id')])
            buf.seek(0); bot.answer_callback_query(call.id, "✅"); bot.send_document(chat_id, io.BytesIO(buf.getvalue().encode('utf-8')), visible_file_name=f"Report_{d_str}.csv"); gc.collect()
    except Exception as e: print(f"[CB] {e}"); bot.answer_callback_query(call.id, "❌ Error", show_alert=True)

# ==========================================
# 12. Nightly Daemon & Final Exec
# ==========================================
last_report_date, last_wipe_date = None, None
def escrow_and_cleanup_daemon():
    global last_report_date, last_wipe_date
    while True:
        try:
            time.sleep(30); now = get_bd_time(); today_str = now.strftime("%Y-%m-%d")
            if now.hour == 23 and now.minute == 55 and last_report_date != now.date():
                last_report_date = now.date()
                res = list(submissions_col.aggregate([{"$match": {"date_key": today_str}}, {"$group": {"_id": "$category", "c": {"$sum": 1}, "r": {"$sum": {"$ifNull": ["$rate", 0]}}}}]))
                msg = f"📊 <b>Dairy - {today_str}</b>\n\n"
                for r in res: msg += f"▪️ <b>{r['_id']}</b>: {r['c']} | 💰 {r['r']:.2f}\n"
                if ADMIN_ID: bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
            if now.hour == 0 and now.minute == 0 and last_wipe_date != now.date():
                last_wipe_date = now.date(); y_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                dc = submissions_col.delete_many({"date_key": y_str, "status": {"$in": ["Approved", "Rejected"]}}).deleted_count
                if ADMIN_ID: bot.send_message(ADMIN_ID, f"🧹 <b>Cleanup</b>: {y_str}\n🗑 Deleted: {dc}", parse_mode="HTML")
        except: time.sleep(60)

threading.Thread(target=escrow_and_cleanup_daemon, daemon=True).start()

app = Flask(__name__)
@app.route('/')
def home(): return "OEB NEXUS Active"

if __name__ == "__main__":
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=10000), daemon=True).start()
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)