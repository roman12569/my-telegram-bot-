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
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# ================= 1. CONFIGURATION & SETUP =================
# সিকিউরিটির জন্য Environment Variable ব্যবহার করা ভালো
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "OEB_NEXUS_bot")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=50)

mongo_client = MongoClient(MONGO_URL, maxPoolSize=200, connectTimeoutMS=10000, socketTimeoutMS=10000)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
withdrawals_col = db['withdrawals']
blacklisted_payloads_col = db['blacklisted_payloads']
ai_logs_col = db['ai_logs']

try:
    submissions_col.create_index("uid", unique=True, background=True)
except Exception as e:
    print(f"Index creation notice: {e}")

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"}
]
BD_TIMEZONE = timezone(timedelta(hours=6))

background_executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
heavy_task_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
live_check_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

class FastSettingsCache:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()
    def get(self, key, default):
        with self.lock:
            if key in self.cache: return self.cache[key]
        res = settings_col.find_one({"_id": key})
        val = res["value"] if res else default
        with self.lock: self.cache[key] = val
        return val
    def set(self, key, value):
        with self.lock: self.cache[key] = value
        try: settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)
        except Exception as e: print(f"Settings update error: {e}")

fast_settings = FastSettingsCache()
def get_setting(key, default): return fast_settings.get(key, default)
def update_setting(key, value): fast_settings.set(key, value)

class MongoDict:
    def __init__(self, collection):
        self.col = collection
        self.cache = {}
        self.lock = threading.Lock()
    def get(self, key, default=None):
        with self.lock:
            if key in self.cache: return self.cache[key]
        doc = self.col.find_one({"_id": key})
        val = doc.get("state", default) if doc else default
        with self.lock: self.cache[key] = val
        return val
    def __setitem__(self, key, value):
        with self.lock: self.cache[key] = value
        try: self.col.update_one({"_id": key}, {"$set": {"state": value}}, upsert=True)
        except Exception as e: print(f"MongoDict set error: {e}")
    def pop(self, key, default=None):
        with self.lock:
            val = self.cache.pop(key, default)
        try: self.col.delete_one({"_id": key})
        except Exception as e: print(f"MongoDict pop error: {e}")
        return val

user_states = MongoDict(db['user_states'])

def get_bd_time(): return datetime.datetime.now(BD_TIMEZONE)
def sanitize_html(text): return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if text else "User"

def get_user_data(chat_id):
    u = users_col.find_one({"_id": chat_id})
    if not u:
        u = {"_id": chat_id, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0, "banned": False, "custom_password": "", "role": "member", "virtual_wallet": 0.0, "assigned_sub_admin": None}
        try: users_col.insert_one(u)
        except Exception as e: print(f"User insert error: {e}")
    return u

def update_user_field(chat_id, field, val):
    try: users_col.update_one({"_id": chat_id}, {"$set": {field: val}}, upsert=True)
    except Exception as e: print(f"User field update error: {e}")

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            m = bot.get_chat_member(ch["username"], user_id)
            if m.status in ['left', 'kicked']: return False
        except Exception: continue
    return True

def generate_tracking_id(): return str(uuid.uuid4())[:8].upper()
def generate_withdraw_id(): return "W" + str(uuid.uuid4())[:6].upper()
def generate_payload_hash(payload): return hashlib.md5(str(payload).strip().encode('utf-8')).hexdigest()

def is_duplicate_uid(uid):
    return submissions_col.find_one({"uid": str(uid).strip()}) is not None

def is_payload_blacklisted(ph):
    return blacklisted_payloads_col.find_one({"hash": ph}) is not None

def is_valid_cookies(text):
    t = str(text)
    return "c_user" in t and "xs" in t

def extract_numeric_uid(text):
    m = re.search(r'\b\d{8,20}\b', str(text))
    return m.group(0) if m else None

def validate_strict_password(pw, rule):
    if not rule or str(rule).lower() == "none": return True
    return str(pw).strip().endswith(str(rule).strip())

def get_shift_config():
    default_conf = {"current_date": get_bd_time().strftime("%Y-%m-%d"), "deadlines": {"fb_cookie": "21:20", "fb_2fa": "21:20", "ig_cookie": "20:20", "ig_2fa": "20:20", "default": "23:59"}}
    c = get_setting("shift_config", default_conf)
    if not isinstance(c, dict) or "deadlines" not in c:
        update_setting("shift_config", default_conf)
        return default_conf
    return c

def is_submission_allowed(cat_key, now_dt):
    c = get_shift_config()
    deadlines = c.get("deadlines", {})
    dl_str = deadlines.get(cat_key, deadlines.get("default", "23:59"))
    try:
        hr, mn = map(int, dl_str.split(":"))
        dl_time = now_dt.replace(hour=hr, minute=mn, second=0, microsecond=0)
        if now_dt > dl_time:
            return False, f"⚠️ শিফট বন্ধ! (ডেডলাইন: {dl_str})"
    except Exception as e: print(f"Deadline parse error: {e}")
    return True, ""

def get_current_task_rate(cat_key):
    r = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    if cat_key in r: return float(r[cat_key])
    cc = get_setting("custom_categories", {})
    if cat_key in cc: return float(cc[cat_key].get("rate", 5.0))
    return 5.0

def check_live_account(uid):
    try:
        r = requests.get(f"https://www.facebook.com/{uid}", timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and "unauthorized" not in r.text.lower():
            return True, "Live"
    except Exception: pass
    return False, "Dead"

def check_ig_username_live(username):
    try:
        r = requests.get(f"https://www.instagram.com/{username.strip('@')}/", timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and "page not found" not in r.text.lower():
            return True, "Live"
    except Exception: pass
    return False, "Dead"

def get_active_hold_dates():
    return sorted(list(submissions_col.distinct("date_key", {"status": "Hold"})))

def send_private_backup_message(caption, file_obj=None, filename=None):
    try:
        if file_obj and filename:
            file_obj.seek(0)
            bot.send_document(BACKUP_CHANNEL_ID, file_obj, caption=caption)
        else:
            bot.send_message(BACKUP_CHANNEL_ID, caption)
    except Exception as e: print(f"Backup message error: {e}")

# ================= 2. KEYBOARDS =================
def main_bottom_keyboard(chat_id):
    role = get_user_data(chat_id).get("role", "member")
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚡ কাজ জমা সেন্টার"), KeyboardButton("🛠 হেল্পার টুলস"))
    markup.add(KeyboardButton("👤 প্রোফাইল ও ওয়ালেট"), KeyboardButton("🎁 রিওয়ার্ড ও সাপোর্ট"))
    if role in ["sub_admin", "admin"] or chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 এডমিন কন্ট্রোল সেন্টার"))
    return markup

def submit_tasks_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"),
        KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("🔙 পেছনে যান"),
        KeyboardButton("🏠 মেইন মেনু")
    )

def category_bottom_keyboard():
    r = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(f"📄 FB Cookies (৳{r.get('fb_cookie', 5.0)})"), KeyboardButton(f"🔐 FB 2FA (৳{r.get('fb_2fa', 6.0)})"))
    markup.add(KeyboardButton(f"📷 IG Cookies (৳{r.get('ig_cookie', 8.0)})"), KeyboardButton(f"🔐 IG 2FA (৳{r.get('ig_2fa', 10.0)})"))
    for k, v in get_setting("custom_categories", {}).items():
        markup.add(KeyboardButton(f"📌 {v['name']} (৳{v['rate']})"))
    markup.add(KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def helper_tools_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"),
        KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"),
        KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু")
    )

def account_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("💳 Withdraw"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"),
        KeyboardButton("🏠 মেইন মেনু")
    )

def bonus_support_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"),
        KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 মেইন মেনু")
    )

def admin_bottom_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("📊 টাস্ক ও রিপোর্ট"), KeyboardButton("💳 ফাইন্যান্স ও সাব-এডমিন"),
        KeyboardButton("⚙️ সেটিংস ও শিফট"), KeyboardButton("📢 ইউজার ও প্যানেল"),
        KeyboardButton("🏠 মেইন মেনু")
    )

def admin_sub_task_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("📊 স্মার্ট ড্যাশবোর্ড"), KeyboardButton("📂 ফাইল এক্সপোর্ট"),
        KeyboardButton("🤖 অটো-ম্যাচার"), KeyboardButton("🏛️ আর্কাইভ"),
        KeyboardButton("🔙 এডমিন প্যানেল")
    )

def admin_sub_settings_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("🔑 পাসওয়ার্ড নিয়ম"),
        KeyboardButton(f"🛠 মেইনটেনেন্স: {'ON' if get_setting('maintenance_mode', False) else 'OFF'}"),
        KeyboardButton("📅 শিফট ও ডেডলাইন"), KeyboardButton("🔙 এডমিন প্যানেল")
    )

def admin_sub_finance_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("⏳ পেন্ডিং উইথড্রয়াল"), KeyboardButton("👥 সাব-এডমিন ফাইন্যান্স"),
        KeyboardButton("🔙 এডমিন প্যানেল")
    )

def admin_sub_system_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("👤 ইউজার ম্যানেজার"), KeyboardButton("📢 ব্রডকাস্ট নোটিশ"),
        KeyboardButton("🔍 ম্যানুয়াল আইডি সার্চ"), KeyboardButton("➕ কাস্টম ক্যাটাগরি"),
        KeyboardButton("🧠 AI সিটেডেল অডিট"), KeyboardButton("🔙 এডমিন প্যানেল")
    )

def cancel_keyboard(): return ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(KeyboardButton("❌ বাতিল করুন"))

# ================= 3. COMMANDS & ROUTER =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        u = get_user_data(chat_id)
        if u.get("banned", False): return bot.reply_to(message, "🔴 অ্যাকাউন্ট স্থগিত!")
        
        user_states.pop(chat_id, None)

        if not check_force_join(chat_id):
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
            markup.add(InlineKeyboardButton("✅ Verify", callback_data="verify_join"))
            return bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)

        bal, hbal = float(u.get("balance") or 0.0), float(u.get("hold_balance") or 0.0)
        card = f"❖ <b>OEB NEXUS // SECURE CORE v6.0</b>\n\n👤 Operator: {sanitize_html(message.from_user.first_name)}\n🆔 User ID: <code>#{chat_id}</code>\n\n💳 Wallet: ৳ {bal:.2f} BDT\n⏳ Escrow: ৳ {hbal:.2f} BDT\n🛡️ Status: {'👑 Global Admin' if chat_id==ADMIN_ID else 'Member'}\n\n" + "____________________________________\n\n⚡ <i>Select an option from the terminal below:</i>"
        bot.send_message(chat_id, card, reply_markup=main_bottom_keyboard(chat_id))
    except Exception as e: print(f"Start Error: {e}")

# ================= 4. CALLBACKS & ADMIN PANELS =================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call): background_executor.submit(lambda: _process_callbacks(call))

def _process_callbacks(call):
    try:
        chat_id = call.message.chat.id
        code = call.data
        u = get_user_data(chat_id)
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False) and u.get("role") != "sub_admin": 
            bot.answer_callback_query(call.id, "🛠 মেইনটেনেন্স মোড অন রয়েছে।", show_alert=True)
            return
        
        if code == "verify_join":
            if check_force_join(chat_id):
                bot.delete_message(chat_id, call.message.message_id)
                bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল!", reply_markup=main_bottom_keyboard(chat_id))
            else:
                bot.answer_callback_query(call.id, "❌ আপনি এখনও সব চ্যানেলে জয়েন করেননি!", show_alert=True)
        elif code.startswith("w_method_"):
            method = "bKash" if "bkash" in code else "Binance"
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_ACCOUNT', 'method': method}
            bot.edit_message_text(f"📱 <b>আপনার {method} অ্যাকাউন্ট দিন:</b>", chat_id, call.message.message_id, parse_mode="HTML")
        elif code.startswith("w_appr_") and chat_id == ADMIN_ID:
            w_id = code.replace("w_appr_", "")
            w = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
            if w:
                withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Approved"}})
                bot.edit_message_text(f"✅ APPROVED\nID: {w_id}", chat_id, call.message.message_id)
                try: bot.send_message(w['chat_id'], f"🎉 <b>আপনার উইথড্র (৳{w['amount']}) এপ্রুভ হয়েছে!</b>")
                except Exception: pass
        elif code.startswith("w_rej_") and chat_id == ADMIN_ID:
            w_id = code.replace("w_rej_", "")
            w = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
            if w:
                withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Rejected"}})
                wu = get_user_data(w['chat_id'])
                if wu.get("role") == "sub_admin": users_col.update_one({"_id": w['chat_id']}, {"$inc": {"virtual_wallet": w['amount']}})
                else: users_col.update_one({"_id": w['chat_id']}, {"$inc": {"balance": w['amount']}})
                bot.edit_message_text(f"❌ REJECTED\nID: {w_id}", chat_id, call.message.message_id)
                try: bot.send_message(w['chat_id'], f"❌ উইথড্র বাতিল! ব্যালেন্স ফেরত দেওয়া হয়েছে।")
                except Exception: pass
        elif code == "user_set_custom_pass":
            p = get_setting("pass_rule", "").strip()
            user_states[chat_id] = {'step': 'AWAITING_USER_SET_PASS'}
            msg = "✏️ <b>নতুন ডিফল্ট পাসওয়ার্ড দিন:</b>\n" + (f"⚠️ শেষে <b>{sanitize_html(p)}</b> থাকা বাধ্যতামূলক!" if p and p.lower() != "none" else "")
            bot.send_message(chat_id, msg, reply_markup=cancel_keyboard())
        elif code == "user_remove_custom_pass":
            update_user_field(chat_id, "custom_password", "")
            bot.edit_message_text("🗑️ মুছে ফেলা হয়েছে!", chat_id, call.message.message_id)
        elif code == "shift_next_day" and chat_id == ADMIN_ID:
            c = get_shift_config()
            nd = (get_bd_time() + timedelta(days=1)).strftime("%Y-%m-%d")
            if c["current_date"] != get_bd_time().strftime("%Y-%m-%d"): nd = get_bd_time().strftime("%Y-%m-%d")
            c["current_date"] = nd
            update_setting("shift_config", c)
            bot.edit_message_text(f"✅ নতুন শিফট চালু: {nd}", chat_id, call.message.message_id)
        elif code.startswith("dash_dt_") and chat_id == ADMIN_ID:
            dt = code.replace("dash_dt_", "")
            out, th = f"📊 <b>BATCH // {dt}</b>\n\n", 0
            cats = ["fb_cookie", "fb_2fa", "ig_cookie", "ig_2fa"] + list(get_setting("custom_categories", {}).keys())
            for c in cats:
                hq = submissions_col.count_documents({"date_key": dt, "status": "Hold", "category_key": c})
                appr_cnt = submissions_col.count_documents({'date_key': dt, 'status': 'Approved', 'category_key': c})
                if hq > 0 or appr_cnt > 0:
                    out += f"• {c}: ⏳{hq} / ✅{appr_cnt}\n"
                    th += hq
            m = InlineKeyboardMarkup()
            if th > 0: m.add(InlineKeyboardButton("📥 ম্যাচ করুন", callback_data=f"bm_select_date_{dt}"), InlineKeyboardButton("🔒 ক্লোজ", callback_data=f"force_close_{dt}"))
            bot.send_message(ADMIN_ID, out, reply_markup=m)
        elif code.startswith("force_close_") and chat_id == ADMIN_ID:
            dt = code.replace("force_close_", "")
            stuck = list(submissions_col.find({"date_key": dt, "status": "Hold"}))
            for s in stuck:
                submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": s["chat_id"]}, {"$inc": {"hold_balance": -float(s.get("rate",0))}})
                try: bot.send_message(s["chat_id"], f"⚠️ আপনার আইডি ({s['uid']}) রিজেক্ট করা হয়েছে।")
                except Exception: pass
            bot.send_message(ADMIN_ID, f"🔒 {dt} এর {len(stuck)} টি কাজ ক্লোজ করা হয়েছে!")
        elif code.startswith("exp_select_date_") and chat_id == ADMIN_ID:
            dt = code.replace("exp_select_date_", "")
            records = list(submissions_col.find({"date_key": dt, "status": "Hold"}))
            if not records: return bot.send_message(ADMIN_ID, "📭 কোনো ডাটা নেই!")
            fn = f"Export_{dt}.csv"
            with open(fn, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["UID", "Password", "Payload", "Category"])
                for r in records: w.writerow([r.get("uid",""), r.get("password",""), r.get("payload",""), r.get("category","")])
            with open(fn, 'rb') as f: bot.send_document(ADMIN_ID, f, caption=f"📊 {dt} এক্সপোর্ট!")
            if os.path.exists(fn): os.remove(fn)
        elif code.startswith("bm_select_date_") and chat_id == ADMIN_ID:
            dt = code.replace("bm_select_date_", "")
            m = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("FB Cookies", callback_data=f"bm_cat_{dt}_fb_cookie"), InlineKeyboardButton("FB 2FA", callback_data=f"bm_cat_{dt}_fb_2fa"), InlineKeyboardButton("All", callback_data=f"bm_cat_{dt}_ALL"))
            bot.send_message(ADMIN_ID, f"🤖 কোন ক্যাটাগরির রিপোর্ট মেলাবেন?", reply_markup=m)
        elif code.startswith("bm_cat_") and chat_id == ADMIN_ID:
            parts = code.split("_")
            user_states[ADMIN_ID] = {'step': 'AWAITING_BUYER_REPORT', 'target_date': parts[2], 'target_cat': "_".join(parts[3:])}
            bot.send_message(ADMIN_ID, f"📄 বায়ার রিপোর্ট ফাইল দিন:", reply_markup=cancel_keyboard())
    except Exception as e:
        print(f"Callback Error: {e}")

# ================= 5. MAIN TEXT ROUTER, STATES & SERVER =================
@bot.message_handler(content_types=['document'])
def handle_doc(message): heavy_task_executor.submit(lambda: _process_document(message))

def _process_document(message):
    try:
        chat_id = message.chat.id
        u = get_user_data(chat_id)
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False) and u.get("role") != "sub_admin": return
        if u.get("banned", False): return
        st = user_states.get(chat_id)

        if st and st.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
            td, tc = st.get('target_date', 'ALL'), st.get('target_cat', 'ALL')
            user_states.pop(chat_id, None)
            bot.reply_to(message, "⏳ ম্যাচিং চলছে...")
            try:
                fi = bot.get_file(message.document.file_id)
                dw = bot.download_file(fi.file_path)
                fn = message.document.file_name.lower()
                ex_uids = set()
                if fn.endswith(".csv"):
                    for r in csv.reader(dw.decode('utf-8', 'ignore').splitlines()):
                        for v in r:
                            if v: ex_uids.update(re.findall(r'\b\d{8,20}\b', str(v)))
                elif fn.endswith(".xlsx"):
                    ws = load_workbook(filename=io.BytesIO(dw), read_only=True, data_only=True).active
                    for row in ws.iter_rows(values_only=True):
                        for v in row:
                            if v: ex_uids.update(re.findall(r'\b\d{8,20}\b', str(v)))
                else: ex_uids = set(re.findall(r'\b\d{8,20}\b', dw.decode('utf-8', 'ignore')))
                
                c_uids = {str(u).strip().split('.')[0] for u in ex_uids if str(u).strip().split('.')[0].isdigit()}
                q = {"status": "Hold"}
                if td != "ALL": q["date_key"] = td
                if tc != "ALL": q["category_key"] = tc
                
                subs = list(submissions_col.find(q))
                if not subs: return bot.send_message(ADMIN_ID, "📭 পেন্ডিং কাজ নেই!", reply_markup=admin_bottom_keyboard())

                appr, rej, payout, notifs = 0, 0, 0.0, collections.defaultdict(list)
                for s in subs:
                    uid, amt, wid = str(s.get("uid","")).strip(), float(s.get("rate",0.0)), s["chat_id"]
                    if uid in c_uids:
                        submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Approved"}})
                        wu = users_col.find_one({"_id": wid}) or {}
                        if wu.get("role") == "sub_admin": users_col.update_one({"_id": wid}, {"$inc": {"virtual_wallet": amt, "hold_balance": -amt}})
                        else: users_col.update_one({"_id": wid}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                        appr += 1; payout += amt
                        notifs[wid].append(f"✅ এপ্রুভ ({uid}) ৳{amt}")
                    else:
                        submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Rejected"}})
                        users_col.update_one({"_id": wid}, {"$inc": {"hold_balance": -amt}})
                        rej += 1
                        notifs[wid].append(f"❌ রিজেক্ট ({uid})")
                        
                for wid, msgs in notifs.items():
                    try: bot.send_message(wid, "\n".join(msgs[:15]) + (f"\n...আরও {len(msgs)-15} টি" if len(msgs)>15 else "")); time.sleep(0.04)
                    except Exception: pass
                bot.send_message(ADMIN_ID, f"🤖 <b>MATCH COMPLETE</b>\n✅ এপ্রুভড: {appr} (৳{payout:.2f})\n❌ রিজেক্টেড: {rej}", reply_markup=admin_bottom_keyboard())
            except Exception as e: 
                print(f"Buyer report process error: {e}")
                bot.send_message(chat_id, "❌ ফাইল রিড করা যায়নি।")

        elif st and st.get('step') == 'AWAITING_EXCEL_FILE':
            pr = str(get_setting("pass_rule", "")).strip()
            sp = u.get("custom_password")
            pw = sp if (sp and str(sp).lower()!="none") else pr
            if pr and pr.lower()!="none" and not validate_strict_password(pw, pr):
                return bot.reply_to(message, "⚠️ পাসওয়ার্ড নিয়ম মানা হয়নি!", reply_markup=submit_tasks_keyboard())
            user_states.pop(chat_id, None)
            bot.reply_to(message, "⏳ ফাইল প্রসেস হচ্ছে...", reply_markup=submit_tasks_keyboard())
            
            try:
                fi = bot.get_file(message.document.file_id)
                dw = bot.download_file(fi.file_path)
                fn = message.document.file_name.lower()
                cands = []
                if fn.endswith('.csv'):
                    for r in csv.reader(dw.decode('utf-8', 'ignore').splitlines()):
                        uid, pl = None, None
                        for v in r:
                            vs = str(v).strip()
                            if not uid and extract_numeric_uid(vs): uid = extract_numeric_uid(vs)
                            elif is_valid_cookies(vs) or len(vs)>20: pl = vs
                        if uid and pl and not is_duplicate_uid(uid): cands.append((uid, pl))
                elif fn.endswith('.xlsx'):
                    ws = load_workbook(filename=io.BytesIO(dw), read_only=True, data_only=True).active
                    for r in ws.iter_rows(values_only=True):
                        uid, pl = None, None
                        for v in r:
                            vs = str(v).strip() if v else ""
                            if not uid and extract_numeric_uid(vs): uid = extract_numeric_uid(vs)
                            elif is_valid_cookies(vs) or len(vs)>20: pl = vs
                        if uid and pl and not is_duplicate_uid(uid): cands.append((uid, pl))
                else: return bot.send_message(chat_id, "❌ সঠিক .csv বা .xlsx দিন।")

                now = get_bd_time()
                v_cands = []
                for uid, pl in cands:
                    ph = generate_payload_hash(pl)
                    if not is_payload_blacklisted(ph):
                        ck = "fb_cookie" if is_valid_cookies(pl) else "fb_2fa"
                        ia, _ = is_submission_allowed(ck, now)
                        if ia: v_cands.append({"uid":uid, "password":pw, "payload":pl, "payload_hash":ph, "cat_key":ck})

                def _chk(c):
                    c["is_live"] = check_live_account(c["uid"])[0] if c["cat_key"] in ["fb_cookie","fb_2fa"] else True
                    return c

                sc, te = 0, 0.0
                for it in live_check_executor.map(_chk, v_cands):
                    if not it.get("is_live"): continue
                    r = get_current_task_rate(it["cat_key"])
                    try:
                        submissions_col.insert_one({"chat_id": chat_id, "uid": it["uid"], "password": it["password"], "payload": it["payload"], "payload_hash": it["payload_hash"], "track_id": generate_tracking_id(), "category_key": it["cat_key"], "rate": r, "status": "Hold", "date_key": now.strftime("%Y-%m-%d"), "date_str": now.strftime("%Y-%m-%d %H:%M:%S")})
                        sc += 1; te += r
                    except DuplicateKeyError: pass

                send_private_backup_message(f"📊 [EXCEL] Worker: {chat_id}\nPass: {pw}\nValid: {sc} | Hold: ৳{te:.2f}", io.BytesIO(dw), f"Backup_{now.strftime('%Y-%m-%d')}_{fn}")
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": te}})
                bot.send_message(chat_id, f"🎉 <b>প্রসেস সম্পন্ন!</b>\n✅ গৃহীত: {sc} | 💰 ৳{te:.2f}", reply_markup=submit_tasks_keyboard())
            except Exception as e:
                print(f"Excel processing error: {e}")
                bot.send_message(chat_id, "❌ ফাইল প্রসেসিং এরর!")
    except Exception as e:
        print(f"Document handler error: {e}")

@bot.message_handler(content_types=['text', 'photo', 'video', 'animation'])
def main_router(message): background_executor.submit(lambda: _process_main_router(message))

def _process_main_router(message):
    try:
        chat_id = message.chat.id
        u = get_user_data(chat_id)
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False) and u.get("role") != "sub_admin": 
            return bot.send_message(chat_id, "🛠 <b>বোটটি বর্তমানে মেইনটেনেন্স মোডে রয়েছে।</b>")
        if u.get("banned", False): return
        text = message.text.strip() if message.text else ""
        
        nb = ["🏠 মেইন মেনু", "🔙 প্রধান মেনু", "❌ বাতিল করুন", "⚡ কাজ জমা সেন্টার", "🛠 হেল্পার টুলস", "📌 সিঙ্গেল জমা", "👤 প্রোফাইল ও ওয়ালেট", "🎁 রিওয়ার্ড ও সাপোর্ট", "👑 এডমিন কন্ট্রোল সেন্টার", "💳 Withdraw", "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "🔑 2FA কোড জেনারেটর", "✉️ টেম্প ইমেইল", "📊 টাস্ক ও রিপোর্ট", "💳 ফাইন্যান্স ও সাব-এডমিন", "⚙️ সেটিংস ও শিফট", "📢 ইউজার ও প্যানেল", "🔙 এডমিন প্যানেল", "⚙️ সেট রেট ও চার্জ", "🔑 পাসওয়ার্ড নিয়ম", "📢 ব্রডকাস্ট নোটিশ", "💬 এডমিন সাপোর্ট টিকিট", "🏆 লিডারবোর্ড", "🎁 Claim Daily Bonus", "🔙 পেছনে যান", "🔙 কাজ জমা মেনুতে ফিরুন", "📅 শিফট ও ডেডলাইন", "📊 স্মার্ট ড্যাশবোর্ড", "📂 ফাইল এক্সপোর্ট", "🤖 অটো-ম্যাচার", "🏛️ আর্কাইভ", "⏳ পেন্ডিং উইথড্রয়াল", "👤 ইউজার ম্যানেজার", "🧠 AI সিটেডেল অডিট", "👥 সাব-এডমিন ফাইন্যান্স", "🔍 ম্যানুয়াল আইডি সার্চ", "➕ কাস্টম ক্যাটাগরি"]
        if text in nb: 
            user_states.pop(chat_id, None)

        # Basic Nav
        if text == "❌ বাতিল করুন": return bot.send_message(chat_id, "❌ বাতিল করা হলো।", reply_markup=main_bottom_keyboard(chat_id))
        elif text in ["🏠 মেইন মেনু", "🔙 প্রধান মেনু"]: return send_welcome(message)
        elif text in ["🔙 পেছনে যান", "🔙 কাজ জমা মেনুতে ফিরুন"]: return bot.send_message(chat_id, "🔙 পেছনে ফেরা হলো:", reply_markup=submit_tasks_keyboard())
        elif text == "🔙 এডমিন প্যানেল": return bot.send_message(chat_id, "👑 <b>এডমিন প্যানেল:</b>", reply_markup=admin_bottom_keyboard())
        elif text == "⚡ কাজ জমা সেন্টার": return bot.send_message(chat_id, "📋 <b>কাজ জমা:</b>", reply_markup=submit_tasks_keyboard())
        elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>টুলস:</b>", reply_markup=helper_tools_keyboard())
        elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি:</b>", reply_markup=category_bottom_keyboard())
        elif text == "🎁 রিওয়ার্ড ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>সাপোর্ট:</b>", reply_markup=bonus_support_keyboard())
        
        elif text == "👤 প্রোফাইল ও ওয়ালেট":
            r = u.get("role", "member")
            pc = f"👤 <b>PROFILE</b>\n• <b>Role:</b> {r.upper()}\n• <b>Tasks:</b> {submissions_col.count_documents({'chat_id': chat_id})}\n"
            if r == "sub_admin": pc += f"💳 <b>Virtual Wallet:</b> ৳ {float(u.get('virtual_wallet') or 0.0):.2f}\n"
            else: pc += f"💳 <b>Main Wallet:</b> ৳ {float(u.get('balance') or 0.0):.2f}\n"
            pc += f"🔗 <b>Ref Link:</b> https://t.me/{BOT_USERNAME}?start={chat_id}"
            return bot.send_message(chat_id, pc, reply_markup=account_keyboard())

        # Admin Panels
        elif text == "👑 এডমিন কন্ট্রোল সেন্টার" and (chat_id == ADMIN_ID or u.get("role") in ["admin", "sub_admin"]): return bot.send_message(chat_id, "👑 <b>ADMIN CONTROL</b>", reply_markup=admin_bottom_keyboard())
        elif text == "📊 টাস্ক ও রিপোর্ট" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "📊 <b>টাস্ক প্যানেল:</b>", reply_markup=admin_sub_task_keyboard())
        elif text == "⚙️ সেটিংস ও শিফট" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "⚙️ <b>সেটিংস:</b>", reply_markup=admin_sub_settings_keyboard())
        elif text == "💳 ফাইন্যান্স ও সাব-এডমিন" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "💳 <b>ফাইন্যান্স:</b>", reply_markup=admin_sub_finance_keyboard())
        elif text == "📢 ইউজার ও প্যানেল" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "📢 <b>সিস্টেম কন্ট্রোল:</b>", reply_markup=admin_sub_system_keyboard())
        
        elif text == "📅 শিফট ও ডেডলাইন" and chat_id == ADMIN_ID:
            c = get_shift_config()
            m = InlineKeyboardMarkup().add(InlineKeyboardButton("📅 Start Next Day Shift", callback_data="shift_next_day"))
            return bot.send_message(chat_id, f"📅 <b>Shift:</b> {c['current_date']}\n" + "".join([f"• {k}: {v}\n" for k,v in c['deadlines'].items()]), reply_markup=m)
        elif text == "📊 স্মার্ট ড্যাশবোর্ড" and chat_id == ADMIN_ID:
            ad = get_active_hold_dates()
            if not ad: return bot.send_message(ADMIN_ID, "🟢 সব ক্লিয়ার!")
            m = InlineKeyboardMarkup(row_width=2)
            for d in ad: m.add(InlineKeyboardButton(f"📅 {d}", callback_data=f"dash_dt_{d}"))
            return bot.send_message(ADMIN_ID, "📊 <b>স্মার্ট ড্যাশবোর্ড</b>", reply_markup=m)
        elif text == "📂 ফাইল এক্সপোর্ট" and chat_id == ADMIN_ID:
            ad = get_active_hold_dates()
            m = InlineKeyboardMarkup(row_width=2)
            for d in ad: m.add(InlineKeyboardButton(f"📁 {d}", callback_data=f"exp_select_date_{d}"))
            return bot.send_message(ADMIN_ID, "📂 <b>ফাইল এক্সপোর্ট</b>", reply_markup=m) if ad else bot.send_message(ADMIN_ID, "📭 ডাটা নেই!")
        elif text == "🤖 অটো-ম্যাচার" and chat_id == ADMIN_ID:
            ad = get_active_hold_dates()
            m = InlineKeyboardMarkup(row_width=2)
            for d in ad: m.add(InlineKeyboardButton(f"🎯 {d}", callback_data=f"bm_select_date_{d}"))
            return bot.send_message(ADMIN_ID, "🤖 <b>অটো-ম্যাচার</b>", reply_markup=m) if ad else bot.send_message(ADMIN_ID, "📭 ডাটা নেই!")
        elif text.startswith("⏳ পেন্ডিং উইথড্রয়াল") and chat_id == ADMIN_ID:
            pws = list(withdrawals_col.find({"status": "Pending"}).limit(5))
            if not pws: return bot.send_message(ADMIN_ID, "📭 পেন্ডিং নেই!")
            for w in pws:
                m = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✅ Approve", callback_data=f"w_appr_{w['withdraw_id']}"), InlineKeyboardButton("❌ Reject", callback_data=f"w_rej_{w['withdraw_id']}"))
                bot.send_message(ADMIN_ID, f"💳 ID: {w['withdraw_id']}\n💰 ৳{w['amount']:.2f}", reply_markup=m)
            return
        elif text.startswith("🛠 মেইনটেনেন্স:") and chat_id == ADMIN_ID:
            update_setting("maintenance_mode", not get_setting("maintenance_mode", False))
            return bot.send_message(ADMIN_ID, "✅ মেইনটেনেন্স আপডেট করা হয়েছে!", reply_markup=admin_sub_settings_keyboard())
        elif text == "⚙️ সেট রেট ও চার্জ" and chat_id == ADMIN_ID:
            user_states[chat_id] = {'step': 'AWAITING_NEW_RATE'}
            return bot.send_message(chat_id, "✏️ <b>FB Cookies এর রেট লিখুন:</b>", reply_markup=cancel_keyboard())
        elif text == "🔑 পাসওয়ার্ড নিয়ম" and chat_id == ADMIN_ID:
            user_states[chat_id] = {'step': 'AWAITING_ADMIN_PASS_RULE'}
            return bot.send_message(chat_id, f"🔑 <b>নতুন সিকিউরিটি কোড লিখুন:</b> (@21)", reply_markup=cancel_keyboard())
        elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
            user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
            return bot.send_message(chat_id, "📢 <b>মেসেজ লিখুন:</b>", reply_markup=cancel_keyboard())
        elif text == "👤 ইউজার ম্যানেজার" and chat_id == ADMIN_ID:
            return bot.send_message(ADMIN_ID, f"👥 <b>Total Users:</b> {users_col.count_documents({})}\n🟢 <b>Active:</b> {users_col.count_documents({'banned': False})}")
        elif text == "🧠 AI সিটেডেল অডিট" and chat_id == ADMIN_ID:
            logs = list(ai_logs_col.find().sort("timestamp", -1).limit(5))
            return bot.send_message(ADMIN_ID, "🧠 <b>AI LOGS</b>\n" + "".join([f"• {l.get('timestamp','N/A')}: {l.get('type','N/A')}\n" for l in logs]) if logs else "🟢 HEALTHY")
        
        # SEARCH & CUSTOM CAT
        elif text == "🔍 ম্যানুয়াল আইডি সার্চ" and chat_id == ADMIN_ID:
            user_states[chat_id] = {'step': 'AWAITING_UID_SEARCH'}
            return bot.send_message(chat_id, "🔍 <b>যে আইডিটি (UID) খুঁজতে চান, সেটি লিখে পাঠান:</b>", reply_markup=cancel_keyboard())
        elif text == "➕ কাস্টম ক্যাটাগরি" and chat_id == ADMIN_ID:
            user_states[chat_id] = {'step': 'AWAITING_NEW_CAT_NAME'}
            return bot.send_message(chat_id, "➕ <b>নতুন ক্যাটাগরির নাম লিখুন (যেমন: TikTok):</b>", reply_markup=cancel_keyboard())

        # User Utilities
        elif text == "💬 এডমিন সাপোর্ট টিকিট":
            user_states[chat_id] = {'step': 'AWAITING_SUPPORT_MSG'}
            return bot.send_message(chat_id, "💬 <b>বিস্তারিত লিখুন:</b>", reply_markup=cancel_keyboard())
        elif text == "🎁 Claim Daily Bonus":
            lb = u.get("last_bonus_date")
            if lb and (get_bd_time() - datetime.datetime.fromisoformat(lb)) < timedelta(hours=24): return bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টায় একবার!")
            update_user_field(chat_id, "balance", float(u.get("balance") or 0.0) + 2.0)
            update_user_field(chat_id, "last_bonus_date", get_bd_time().isoformat())
            return bot.send_message(chat_id, "🎉 ৳২.০০ বোনাস!")
        elif text == "🏆 লিডারবোর্ড":
            top = list(submissions_col.aggregate([{"$group": {"_id": "$worker_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]))
            bdg = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            return bot.send_message(chat_id, "🏆 <b>LEADERBOARD</b>\n\n" + "".join([f"{bdg[i]} {item['_id']} — {item['count']}\n" for i, item in enumerate(top)]))
        elif text == "✉️ টেম্প ইমেইল":
            em = f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}@1secmail.com"
            m = InlineKeyboardMarkup().add(InlineKeyboardButton("📩 ইনবক্স", callback_data=f"check_otp_{em}"))
            return bot.send_message(chat_id, f"✉️ <b>Temp Email:</b> <code>{em}</code>", reply_markup=m)
        elif text == "🔑 2FA কোড জেনারেটর":
            user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
            return bot.send_message(chat_id, "🔑 <b>2FA Secret Key দিন:</b>", reply_markup=cancel_keyboard())
        elif text == "🚀 বাল্ক FB লাইভ চেকার":
            user_states[chat_id] = {'step': 'AWAITING_BULK_FB_CHECK'}
            return bot.send_message(chat_id, "🔍 <b>FB UIDs পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        elif text == "🚀 বাল্ক IG লাইভ চেকার":
            user_states[chat_id] = {'step': 'AWAITING_BULK_IG_CHECK'}
            return bot.send_message(chat_id, "🔍 <b>IG Users পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        elif text == "💳 Withdraw":
            b = float(u.get("virtual_wallet") if u.get("role") == "sub_admin" else u.get("balance") or 0.0)
            if b < 50.0: return bot.send_message(chat_id, f"⚠️ <b>সর্বনিম্ন ৳৫০!</b> (আছে ৳{b:.2f})", reply_markup=account_keyboard())
            m = InlineKeyboardMarkup().add(InlineKeyboardButton("বিকাশ", callback_data="w_method_bkash"), InlineKeyboardButton("বাইনান্স", callback_data="w_method_binance"))
            return bot.send_message(chat_id, f"💳 <b>মেথড সিলেক্ট করুন:</b>", reply_markup=m)
        elif text == "📦 বাল্ক জমা (Text)":
            user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
            return bot.send_message(chat_id, "📦 <b>কুকিজ পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
        elif text == "📊 এক্সেল ফাইল জমা":
            user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
            return bot.send_message(chat_id, "📊 <b>ফাইল পাঠান:</b>", reply_markup=cancel_keyboard())
        elif text == "⚙️ পাসওয়ার্ড নিয়ম":
            user_states[chat_id] = {'step': 'AWAITING_USER_SET_PASS'}
            return bot.send_message(chat_id, "✏️ <b>আপনার নিজস্ব ফিক্সড পাসওয়ার্ড বা শেষ অংশটি দিন:</b>", reply_markup=cancel_keyboard())
        elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]) or text.startswith("📌"):
            c = "fb_cookie" 
            if "FB 2FA" in text: c = "fb_2fa"
            elif "IG Cookies" in text: c = "ig_cookie"
            elif "IG 2FA" in text: c = "ig_2fa"
            else:
                for k, v in get_setting("custom_categories", {}).items():
                    if v["name"] in text: c = k; break
            user_states[chat_id] = {'step': 'AWAITING_UID', 'category': c}
            return bot.send_message(chat_id, f"📄 <b>TASK: {text[:20]}</b>\n► <b>UID বা আইডি সেন্ড করুন:</b>", reply_markup=cancel_keyboard())

        # State Processing
        st = user_states.get(chat_id)
        if not st: return
        sp = st.get('step')

        # ADMIN STATES
        if sp == 'AWAITING_NEW_RATE' and chat_id == ADMIN_ID:
            try:
                r = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
                r["fb_cookie"] = float(text)
                update_setting("rates", r)
                user_states.pop(chat_id, None)
                return bot.send_message(chat_id, f"✅ রেট আপডেট!", reply_markup=admin_sub_settings_keyboard())
            except Exception: return bot.send_message(chat_id, "❌ সংখ্যা দিন!")
        elif sp == 'AWAITING_ADMIN_PASS_RULE' and chat_id == ADMIN_ID:
            update_setting("pass_rule", text)
            user_states.pop(chat_id, None)
            return bot.send_message(chat_id, f"✅ কোড <b>{text}</b> সেট!", reply_markup=admin_sub_settings_keyboard())
        elif sp == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
            user_states.pop(chat_id, None)
            bot.send_message(ADMIN_ID, f"📢 ব্রডকাস্ট পাঠানো হচ্ছে...", reply_markup=admin_sub_system_keyboard())
            def rb():
                for us in list(users_col.find({"banned": False})):
                    try: bot.send_message(us["_id"], text); time.sleep(0.05)
                    except Exception: pass
            heavy_task_executor.submit(rb)
            return
            
        elif sp == 'AWAITING_UID_SEARCH' and chat_id == ADMIN_ID:
            s_uid = extract_numeric_uid(text) or text.strip()
            doc = submissions_col.find_one({"uid": s_uid})
            if not doc: return bot.send_message(chat_id, f"❌ <b>{s_uid}</b> পাওয়া যায়নি!", reply_markup=admin_sub_system_keyboard())
            out = (f"🔍 <b>SEARCH RESULT</b>\n👤 <b>Worker:</b> <code>{doc.get('chat_id')}</code>\n🆔 <b>UID:</b> <code>{doc.get('uid')}</code>\n🔑 <b>Pass:</b> <code>{doc.get('password')}</code>\n📁 <b>Cat:</b> {doc.get('category_key')}\n📅 <b>Date:</b> {doc.get('date_str')}\n🛡️ <b>Status:</b> {doc.get('status')}\n\n📝 <b>Data:</b>\n<code>{sanitize_html(doc.get('payload','')[:500])}</code>")
            user_states.pop(chat_id, None)
            return bot.send_message(chat_id, out, reply_markup=admin_sub_system_keyboard())
        elif sp == 'AWAITING_NEW_CAT_NAME' and chat_id == ADMIN_ID:
            c_name = text.strip()
            user_states[chat_id] = {'step': 'AWAITING_NEW_CAT_RATE', 'c_name': c_name, 'c_key': c_name.lower().replace(" ", "_")}
            return bot.send_message(chat_id, f"💰 <b>'{c_name}'</b> এর রেট কত টাকা হবে? (যেমন: 5.5)", reply_markup=cancel_keyboard())
        elif sp == 'AWAITING_NEW_CAT_RATE' and chat_id == ADMIN_ID:
            try:
                rate = float(text.strip())
                c_cats = get_setting("custom_categories", {})
                c_cats[st['c_key']] = {"name": st['c_name'], "rate": rate}
                update_setting("custom_categories", c_cats)
                user_states.pop(chat_id, None)
                return bot.send_message(chat_id, f"✅ <b>সফল!</b> '{st['c_name']}' (৳{rate}) যুক্ত হয়েছে।", reply_markup=admin_sub_system_keyboard())
            except Exception: return bot.send_message(chat_id, "❌ সংখ্যা দিন!", reply_markup=cancel_keyboard())

        # USER STATES
        elif sp == 'AWAITING_USER_SET_PASS':
            update_user_field(chat_id, "custom_password", text.strip())
            user_states.pop(chat_id, None)
            return bot.send_message(chat_id, f"✅ আপনার পাসওয়ার্ড <code>{sanitize_html(text.strip())}</code> সেভ করা হয়েছে!", reply_markup=account_keyboard())
        elif sp == 'AWAITING_SUPPORT_MSG':
            user_states.pop(chat_id, None)
            bot.send_message(ADMIN_ID, f"🎫 <b>টিকিট</b>\n👤 <code>{chat_id}</code>\n📝 {sanitize_html(text)}")
            return bot.send_message(chat_id, "✅ পাঠানো হয়েছে।", reply_markup=bonus_support_keyboard())
        elif sp == 'AWAITING_2FA_GEN':
            user_states.pop(chat_id, None)
            try: 
                secret = text.replace(' ', '').upper()
                totp = pyotp.TOTP(secret)
                return bot.send_message(chat_id, f"🔑 <b>Code:</b> <code>{totp.now()}</code>", reply_markup=helper_tools_keyboard())
            except Exception: 
                return bot.send_message(chat_id, "❌ ভুল বা অকার্যকর Key!", reply_markup=helper_tools_keyboard())
        elif sp == 'AWAITING_BULK_FB_CHECK':
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "⏳ চেক করা হচ্ছে...", reply_markup=helper_tools_keyboard())
            def rc():
                uids = [extract_numeric_uid(l) for l in text.split("\n") if extract_numeric_uid(l)][:50]
                ls = [uid for uid, (il, _) in zip(uids, list(live_check_executor.map(check_live_account, uids))) if il]
                bot.send_message(chat_id, f"📊 <b>FB CHECK</b>\nLive: {len(ls)}\n" + "\n".join(ls)[:3500])
            heavy_task_executor.submit(rc)
            return
        elif sp == 'AWAITING_BULK_IG_CHECK':
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "⏳ চেক করা হচ্ছে...", reply_markup=helper_tools_keyboard())
            def ri():
                us = [l.strip() for l in text.split("\n") if l.strip()][:50]
                ls = [u for u, (il, _) in zip(us, list(live_check_executor.map(check_ig_username_live, us))) if il]
                bot.send_message(chat_id, f"📊 <b>IG CHECK</b>\nLive: {len(ls)}\n" + "\n".join(ls)[:3500])
            heavy_task_executor.submit(ri)
            return
        elif sp == 'AWAITING_WITHDRAW_ACCOUNT':
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_AMOUNT', 'method': st['method'], 'account': text.strip()}
            return bot.send_message(chat_id, f"✅ অ্যাকাউন্ট: {text.strip()}\n💰 কত টাকা?", reply_markup=cancel_keyboard())
        elif sp == 'AWAITING_WITHDRAW_AMOUNT':
            try: ra = float(text.strip())
            except Exception: return bot.send_message(chat_id, "❌ সংখ্যা লিখুন:", reply_markup=cancel_keyboard())
            bf = "virtual_wallet" if u.get("role") == "sub_admin" else "balance"
            bal = float(u.get(bf) or 0.0)
            if ra < 50.0 or ra > bal: return bot.send_message(chat_id, "❌ ব্যালেন্স এরর!", reply_markup=cancel_keyboard())
            user_states.pop(chat_id, None)
            update_user_field(chat_id, bf, bal - ra)
            wid = generate_withdraw_id()
            withdrawals_col.insert_one({"withdraw_id": wid, "chat_id": chat_id, "worker_name": sanitize_html(message.from_user.first_name), "method": st['method'], "account": st['account'], "amount": ra, "status": "Pending", "time": get_bd_time().strftime("%Y-%m-%d %H:%M:%S")})
            return bot.send_message(chat_id, f"🎉 <b>রিকোয়েস্ট জমা! (ID: {wid})</b>", reply_markup=account_keyboard())
        elif sp == 'AWAITING_BULK_TEXT':
            pr = str(get_setting("pass_rule", "")).strip()
            spw = u.get("custom_password")
            pw = spw if (spw and str(spw).lower()!="none") else pr
            if pr and pr.lower()!="none" and not validate_strict_password(pw, pr): return bot.send_message(chat_id, "⚠️ নিয়ম মানা হয়নি!", reply_markup=submit_tasks_keyboard())
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "⏳ প্রসেস হচ্ছে...", reply_markup=submit_tasks_keyboard())
            def rbk():
                ls = [l.strip() for l in text.split("\n") if l.strip()]
                pis = []
                for l in ls:
                    uid = extract_numeric_uid(l) or (l.split()[0] if len(l)>5 else None)
                    if uid and not is_duplicate_uid(uid):
                        ck = "fb_cookie" if is_valid_cookies(l) else "fb_2fa"
                        if is_submission_allowed(ck, get_bd_time())[0] and not is_payload_blacklisted(generate_payload_hash(l)): pis.append({"uid":uid, "line":l, "ph":generate_payload_hash(l), "ck":ck})
                def _chk(i):
                    i["il"] = check_live_account(i["uid"])[0] if i["ck"] in ["fb_cookie","fb_2fa"] else True
                    return i
                cis = list(live_check_executor.map(_chk, pis))
                sc, te, now = 0, 0.0, get_bd_time()
                for i in cis:
                    if i.get("il"):
                        r = get_current_task_rate(i["ck"])
                        try:
                            submissions_col.insert_one({"chat_id": chat_id, "uid": i["uid"], "password": pw, "payload": i["line"], "payload_hash": i["ph"], "track_id": generate_tracking_id(), "category_key": i["ck"], "rate": r, "status": "Hold", "date_key": now.strftime("%Y-%m-%d"), "date_str": now.strftime("%Y-%m-%d %H:%M:%S")})
                            sc += 1; te += r
                        except DuplicateKeyError: pass
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": te}})
                bot.send_message(chat_id, f"🎉 <b>বাল্ক সাবমিশন!</b>\n✅ গৃহীত: {sc}\n💰 ৳{te:.2f}")
            heavy_task_executor.submit(rbk)
            return
        elif sp == 'AWAITING_UID':
            uid = extract_numeric_uid(text) or text.strip()
            if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ ভুল/ডুপ্লিকেট আইডি!")
            c = st.get('category', 'fb_cookie')
            ia, am = is_submission_allowed(c, get_bd_time())
            if not ia: return bot.send_message(chat_id, am, reply_markup=submit_tasks_keyboard())
            st['uid'] = uid; st['step'] = 'AWAITING_SINGLE_DATA'
            user_states[chat_id] = st
            return bot.send_message(chat_id, f"✅ UID: <code>{uid}</code>\n► ডাটা দিন:", reply_markup=cancel_keyboard())
        elif sp == 'AWAITING_SINGLE_DATA':
            c, uid = st.get('category'), st.get('uid')
            pr = str(get_setting("pass_rule", "")).strip()
            spw = u.get("custom_password")
            if spw and validate_strict_password(spw, pr):
                now = get_bd_time()
                r = get_current_task_rate(c)
                try:
                    submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": spw, "payload": text, "payload_hash": generate_payload_hash(text), "track_id": generate_tracking_id(), "category_key": c, "rate": r, "status": "Hold", "date_key": now.strftime("%Y-%m-%d"), "date_str": now.strftime("%Y-%m-%d %H:%M:%S")})
                    users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": r}})
                except Exception: return bot.send_message(chat_id, "❌ ডুপ্লিকেট!")
                st['step'] = 'AWAITING_UID'
                user_states[chat_id] = st
                return bot.send_message(chat_id, f"🎉 <b>জমা সফল!</b> (৳{r:.2f})\n► পরবর্তী আইডি দিন:", reply_markup=cancel_keyboard())
            else:
                st['payload'] = text; st['step'] = 'AWAITING_MANUAL_PASSWORD'
                user_states[chat_id] = st
                return bot.send_message(chat_id, "🔑 <b>পাসওয়ার্ডটি দিন:</b>", reply_markup=cancel_keyboard())
        elif sp == 'AWAITING_MANUAL_PASSWORD':
            c, uid, pl = st.get('category'), st.get('uid'), st.get('payload')
            mp = text.strip()
            pr = str(get_setting("pass_rule", "")).strip()
            if pr and pr.lower() != "none" and not validate_strict_password(mp, pr): return bot.send_message(chat_id, "⚠️ নিয়ম মানা হয়নি!", reply_markup=cancel_keyboard())
            now = get_bd_time()
            r = get_current_task_rate(c)
            try:
                submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": mp, "payload": pl, "payload_hash": generate_payload_hash(pl), "track_id": generate_tracking_id(), "category_key": c, "rate": r, "status": "Hold", "date_key": now.strftime("%Y-%m-%d"), "date_str": now.strftime("%Y-%m-%d %H:%M:%S")})
                users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": r}})
                update_user_field(chat_id, "temp_pending_password", mp)
            except Exception: return bot.send_message(chat_id, "❌ ডুপ্লিকেট!")
            st['step'] = 'AWAITING_UID'
            user_states[chat_id] = st
            return bot.send_message(chat_id, f"🎉 <b>জমা সফল!</b> (৳{r:.2f})\n► পরবর্তী আইডি দিন:", reply_markup=cancel_keyboard())
    except Exception as e:
        print(f"Main Router Error: {e}")

# ================= 6. FLASK & POLLING SERVER =================
flask_app = Flask(__name__)
@flask_app.route('/')
def flask_home(): return "OEB NEXUS Production Engine Active (Polling Mode)!"

if __name__ == "__main__":
    print("OEB NEXUS Enterprise Engine Starting (Polling Mode)...")
    def run_web():
        port = int(os.environ.get("PORT", 10000))
        flask_app.run(host="0.0.0.0", port=port)
        
    threading.Thread(target=run_web, daemon=True).start()
    
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e: print(f"Webhook remove notice: {e}")
    
    bot.infinity_polling(skip_pending=True)