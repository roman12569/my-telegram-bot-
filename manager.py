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
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))

bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=50)

mongo_client = MongoClient(MONGO_URL, maxPoolSize=50, connectTimeoutMS=10000, socketTimeoutMS=10000)
db = mongo_client['earning_bazar_advanced']

users_col = db['users']
submissions_col = db['submissions']
settings_col = db['settings']
withdrawals_col = db['withdrawals']
blacklisted_payloads_col = db['blacklisted_payloads']
ai_logs_col = db['ai_logs']

try:
    submissions_col.create_index("uid", unique=True, background=True)
except: pass

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
        except: pass

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
        except: pass
    def pop(self, key, default=None):
        with self.lock:
            val = self.cache.pop(key, default)
        try: self.col.delete_one({"_id": key})
        except: pass
        return val

user_states = MongoDict(db['user_states'])

def get_bd_time(): return datetime.datetime.now(BD_TIMEZONE)
def sanitize_html(text): return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if text else "User"

def get_user_data(chat_id):
    u = users_col.find_one({"_id": chat_id})
    if not u:
        u = {"_id": chat_id, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0, "banned": False, "custom_password": "", "role": "member", "virtual_wallet": 0.0, "assigned_sub_admin": None}
        try: users_col.insert_one(u)
        except: pass
    return u

def update_user_field(chat_id, field, val):
    try: users_col.update_one({"_id": chat_id}, {"$set": {field: val}}, upsert=True)
    except: pass

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            m = bot.get_chat_member(ch["username"], user_id)
            if m.status in ['left', 'kicked']: return False
        except: continue
    return True

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
        KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু")
    )

def category_bottom_keyboard():
    r = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0})
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton(f"📄 FB Cookies (৳{r.get('fb_cookie', 5.0)})"), 
        KeyboardButton(f"🔐 FB 2FA (৳{r.get('fb_2fa', 6.0)})"),
        KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 মেইন মেনু")
    )

def helper_tools_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"),
        KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু")
    )

def account_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("💳 Withdraw"), KeyboardButton("🏠 মেইন মেনু")
    )

def bonus_support_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"),
        KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 মেইন মেনু")
    )

def admin_bottom_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
        KeyboardButton("📊 ইউজার স্ট্যাটাস"), KeyboardButton("📢 ব্রডকাস্ট নোটিশ"),
        KeyboardButton("🏠 মেইন মেনু")
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
        card = f"❖ <b>OEB NEXUS // v6.0 (Stable)</b>\n\n👤 Operator: {sanitize_html(message.from_user.first_name)}\n🆔 ID: <code>#{chat_id}</code>\n\n💳 Wallet: ৳ {bal:.2f}\n⏳ Escrow: ৳ {hbal:.2f}\n\n⚡ <i>Select an option:</i>"
        bot.send_message(chat_id, card, reply_markup=main_bottom_keyboard(chat_id))
    except Exception as e: print(f"Start Error: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "verify_join":
        if check_force_join(call.message.chat.id):
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "✅ ভেরিফিকেশন সফল!", reply_markup=main_bottom_keyboard(call.message.chat.id))

@bot.message_handler(content_types=['text'])
def main_router(message):
    chat_id = message.chat.id
    u = get_user_data(chat_id)
    if u.get("banned", False): return
    text = message.text.strip() if message.text else ""
    
    if text == "❌ বাতিল করুন": return bot.send_message(chat_id, "❌ বাতিল করা হলো।", reply_markup=main_bottom_keyboard(chat_id))
    elif text in ["🏠 মেইন মেনু", "🔙 প্রধান মেনু"]: return send_welcome(message)
    elif text in ["🔙 পেছনে যান", "🔙 কাজ জমা মেনুতে ফিরুন"]: return bot.send_message(chat_id, "🔙 পেছনে ফেরা হলো:", reply_markup=submit_tasks_keyboard())
    elif text == "⚡ কাজ জমা সেন্টার": return bot.send_message(chat_id, "📋 <b>কাজ জমা:</b>", reply_markup=submit_tasks_keyboard())
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>টুলস:</b>", reply_markup=helper_tools_keyboard())
    elif text == "📌 সিঙ্গেল জমা":
        user_states[chat_id] = {'step': 'AWAITING_UID'}
        return bot.send_message(chat_id, "📄 <b>UID বা আইডি সেন্ড করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "👤 প্রোফাইল ও ওয়ালেট":
        pc = f"👤 <b>PROFILE</b>\n• <b>Tasks:</b> {submissions_col.count_documents({'chat_id': chat_id})}\n💳 <b>Main Wallet:</b> ৳ {float(u.get('balance') or 0.0):.2f}"
        return bot.send_message(chat_id, pc, reply_markup=account_keyboard())
    elif text == "🎁 রিওয়ার্ড ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>সাপোর্ট:</b>", reply_markup=bonus_support_keyboard())
    elif text == "👑 এডমিন কন্ট্রোল সেন্টার" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "👑 <b>ADMIN CONTROL</b>", reply_markup=admin_bottom_keyboard())
    elif text == "📊 ইউজার স্ট্যাটাস" and chat_id == ADMIN_ID:
        return bot.send_message(ADMIN_ID, f"👥 <b>Total Users:</b> {users_col.count_documents({})}")
    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_SUPPORT'}
        return bot.send_message(chat_id, "💬 <b>আপনার সমস্যা বিস্তারিত লিখুন:</b>", reply_markup=cancel_keyboard())

    # State processing
    st = user_states.get(chat_id)
    if not st: return
    sp = st.get('step')

    if sp == 'AWAITING_SUPPORT':
        user_states.pop(chat_id, None)
        bot.send_message(ADMIN_ID, f"🎫 <b>Support Ticket</b>\n👤 <code>{chat_id}</code>\n📝 {sanitize_html(text)}")
        return bot.send_message(chat_id, "✅ আপনার মেসেজ এডমিনের কাছে পাঠানো হয়েছে।", reply_markup=bonus_support_keyboard())
    elif sp == 'AWAITING_UID':
        st['uid'] = text.strip()
        st['step'] = 'AWAITING_DATA'
        user_states[chat_id] = st
        return bot.send_message(chat_id, "🔑 <b>এবার কুকিজ বা পাসওয়ার্ড দিন:</b>", reply_markup=cancel_keyboard())
    elif sp == 'AWAITING_DATA':
        uid = st.get('uid')
        user_states.pop(chat_id, None)
        try:
            submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "payload": text, "status": "Hold", "date_str": get_bd_time().strftime("%Y-%m-%d %H:%M:%S")})
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": 5.0, "balance": 5.0}})
        except: pass
        return bot.send_message(chat_id, "🎉 <b>সফলভাবে জমা হয়েছে! (৳৫.০০ যোগ হয়েছে)</b>", reply_markup=main_bottom_keyboard(chat_id))

# ================= 4. SIMPLE FLASK & POLLING =================
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "OEB NEXUS Running Smoothly!"

if __name__ == "__main__":
    print("OEB NEXUS Bot Started via Polling...")
    def run_web():
        flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    threading.Thread(target=run_web, daemon=True).start()
    
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)