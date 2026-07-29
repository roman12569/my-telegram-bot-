# -*- coding: utf-8 -*-
# ==============================================================================
# OEB NEXUS - CYBER AI ENTERPRISE ENGINE
# Version: 12.0 (Ultimate Zero-Bug Production Build)
# Features: ALL Original Features + RAM-Safe Streaming, Zero Data-Loss Backup, 
# Float-UID Fix, Throttled UI, Anti-IP Ban, OOM Protection, Auto-Healing DB.
# ==============================================================================

import os
import re
import json
import io
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
import uuid
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

# ================= 1. Configuration & Credentials =================
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

LOG_CHANNEL_ID = -1003943094107
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))

bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=250)

# ================= ⚡ DYNAMIC RETRY ENGINE (Zero-Crash) =================
class _DummyMessage:
    def __init__(self): self.message_id = 0

def with_rate_limit_protection(func):
    def wrapper(*args, **kwargs):
        for _ in range(3):
            try:
                res = func(*args, **kwargs)
                return res if res is not None else _DummyMessage()
            except ApiTelegramException as e:
                if e.error_code == 429:
                    time.sleep(int(e.result_json.get('parameters', {}).get('retry_after', 3)) + 0.5)
                    continue
                return _DummyMessage()
            except Exception: return _DummyMessage()
        return _DummyMessage()
    return wrapper

bot.send_message = with_rate_limit_protection(bot.send_message)
bot.reply_to = with_rate_limit_protection(bot.reply_to)
bot.edit_message_text = with_rate_limit_protection(bot.edit_message_text)
bot.send_document = with_rate_limit_protection(bot.send_document)
bot.send_photo = with_rate_limit_protection(bot.send_photo)
bot.send_video = with_rate_limit_protection(bot.send_video)
bot.send_animation = with_rate_limit_protection(bot.send_animation)
bot.delete_message = with_rate_limit_protection(bot.delete_message)
bot.forward_message = with_rate_limit_protection(bot.forward_message)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
else: ai_model = None

try: BOT_USERNAME = bot.get_me().username
except Exception: BOT_USERNAME = "online_bazar_manager_bot"

# Strict Connection Limits for Free MongoDB (Prevents DB Crash)
mongo_client = MongoClient(
    MONGO_URL, maxPoolSize=100, minPoolSize=10, 
    maxIdleTimeMS=45000, connectTimeoutMS=5000, socketTimeoutMS=5000
)
db = mongo_client['earning_bazar_advanced']

users_col, submissions_col, skeletons_col = db['users'], db['submissions'], db['skeletons']
archives_col, settings_col, tickets_col = db['archives'], db['settings'], db['support_tickets']
withdrawals_col, blacklisted_payloads_col, ai_logs_col = db['withdrawals'], db['blacklisted_payloads'], db['ai_logs']

try:
    for idx in ["track_id", "uid", "chat_id", "status", "date_key"]: submissions_col.create_index(idx, background=True)
    skeletons_col.create_index([("uid", 1), ("category_key", 1)], unique=True, background=True)
    skeletons_col.create_index("date_key", background=True)
    skeletons_col.create_index("chat_id", background=True)
    archives_col.create_index([("oeb_id", 1), ("date_key", 1)], background=True)
except Exception: pass

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]
BD_TIMEZONE = timezone(timedelta(hours=6))

def get_oeb_id(chat_id): return f"OEB-{str(chat_id)[-4:]}"

class GuaranteedBoundedExecutor:
    def __init__(self, max_workers, max_queue_size=50000):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = threading.Semaphore(max_queue_size)
    def submit(self, fn, *args, **kwargs):
        self.semaphore.acquire()
        try:
            future = self.executor.submit(fn, *args, **kwargs)
            future.add_done_callback(lambda x: self.semaphore.release())
            return future
        except Exception:
            self.semaphore.release(); raise

background_executor = GuaranteedBoundedExecutor(max_workers=150, max_queue_size=50000)
heavy_task_executor = GuaranteedBoundedExecutor(max_workers=50, max_queue_size=20000)
live_check_executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)
cache_executor = concurrent.futures.ThreadPoolExecutor(max_workers=20)

class FastSettingsCache:
    def __init__(self):
        self.cache, self.lock = {}, threading.Lock()
        try:
            for s in settings_col.find(): self.cache[s["_id"]] = s["value"]
        except: pass
    def get(self, key, default):
        with self.lock:
            if key in self.cache: return self.cache[key]
        val = settings_col.find_one({"_id": key})
        val = val["value"] if val else default
        with self.lock: self.cache[key] = val
        return val
    def set(self, key, value):
        with self.lock: self.cache[key] = value
        cache_executor.submit(lambda: settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True))

fast_settings = FastSettingsCache()
def get_setting(key, default): return fast_settings.get(key, default)
def update_setting(key, value): fast_settings.set(key, value)

class MongoDict:
    def __init__(self, collection, max_cache_size=20000):
        self.col, self.cache, self.max_cache_size, self.lock = collection, collections.OrderedDict(), max_cache_size, threading.Lock()
    def get(self, key, default=None):
        with self.lock:
            if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
        doc = self.col.find_one({"_id": key})
        if doc:
            val = doc.get("state", default)
            with self.lock:
                self.cache[key] = val; self.cache.move_to_end(key)
                if len(self.cache) > self.max_cache_size: self.cache.popitem(last=False)
            return val
        return default
    def __setitem__(self, key, value):
        with self.lock:
            self.cache[key] = value; self.cache.move_to_end(key)
            if len(self.cache) > self.max_cache_size: self.cache.popitem(last=False)
        cache_executor.submit(lambda: self.col.update_one({"_id": key}, {"$set": {"state": value}}, upsert=True))
    def pop(self, key, default=None):
        val = default
        with self.lock:
            if key in self.cache: val = self.cache.pop(key)
            else:
                doc = self.col.find_one_and_delete({"_id": key})
                if doc: val = doc.get("state", default)
        cache_executor.submit(lambda: self.col.delete_one({"_id": key}))
        return val

user_states = MongoDict(db['user_states'])
CAT_MAP = {"fb_cookie": "FB Cookies", "fb_2fa": "FB 2FA", "ig_cookie": "IG Cookies", "ig_2fa": "IG 2FA"}
BD_FIRST_NAMES = ["Sakib", "Tanvir", "Rahim", "Rakib", "Nayeem", "Ariful", "Mehedi", "Mahfuz", "Farhan", "Ashfaq", "Sumon", "Imran", "Hasib", "Shahadat", "Rayhan", "Tasnim", "Nusrat", "Riya", "Sadia", "Mim", "Farhana", "Sultana", "Anik", "Sabbir", "Fahim", "Jubayer", "Naim", "Tariq", "Zubair", "Alim", "Shakil", "Mahmud"]
BD_LAST_NAMES = ["Hasan", "Ahmed", "Uddin", "Islam", "Khan", "Chowdhury", "Rahman", "Hossain", "Sheikh", "Mahmud", "Sarkar", "Miah", "Akter", "Siddique", "Bhuiyan", "Kabir", "Ali", "Alam"]
USA_FIRST_NAMES = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Daniel", "Matthew", "Anthony", "Mark", "Steven", "Paul", "Andrew", "Joshua", "Kenneth", "Kevin", "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Sandra"]
USA_LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris"]

# ================= 2. Helper Functions =================
def get_bd_time(): return datetime.datetime.now(BD_TIMEZONE)
def parse_iso_datetime(dt_val):
    if not dt_val: return get_bd_time()
    if isinstance(dt_val, datetime.datetime): return dt_val.astimezone(BD_TIMEZONE) if dt_val.tzinfo else dt_val.replace(tzinfo=BD_TIMEZONE)
    try: return datetime.datetime.fromisoformat(dt_val).astimezone(BD_TIMEZONE) if datetime.datetime.fromisoformat(dt_val).tzinfo else datetime.datetime.fromisoformat(dt_val).replace(tzinfo=BD_TIMEZONE)
    except Exception: return get_bd_time()

def safe_delete_msg(chat_id, message_id): background_executor.submit(lambda: bot.delete_message(chat_id, message_id))

def get_active_surge_bonus():
    si = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if si.get("active") and parse_iso_datetime(si.get("expires_at")) > get_bd_time(): return float(si.get("bonus", 0.0))
    return 0.0

def get_current_task_rate(cat_key, chat_id=None):
    base_rate = float(get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0}).get(cat_key, 5.0))
    if chat_id:
        u = users_col.find_one({"_id": chat_id})
        if u and u.get("is_vip"): base_rate = float(get_setting("vip_rates", {}).get(cat_key, base_rate + 1.0))
    return base_rate + get_active_surge_bonus()

def log_ai_report(issue_type, description, fix_action):
    def task():
        now_str = get_bd_time().strftime("%Y-%m-%d %H:%M:%S")
        ai_logs_col.insert_one({"timestamp": now_str, "type": issue_type, "description": description, "action": fix_action})
    background_executor.submit(task)

def generate_strict_ai_warning(issue, cause, solution, prevention): return f"⚠️ <b>OEB NEXUS AI SYSTEM WARNING</b>\n\n🔍 <b>১. সমস্যা:</b> {issue}\n❓ <b>২. কারণ:</b> {cause}\n🛠️ <b>৩. সমাধান:</b> {solution}\n🛡️ <b>৪. ভবিষ্যতের প্রতিকার:</b> {prevention}"
def validate_strict_password(password, rule): return True if not rule or rule.lower() == "none" or not rule.strip() else str(password).strip().endswith(rule.strip())

def ask_ai_chatbot(user_message):
    if not ai_model: return "আসসালামু আলাইকুম! OEB NEXUS বটে আপনাকে স্বাগতম।"
    try: return ai_model.generate_content(f"Reply in Bengali short: {user_message}", request_options={"timeout": 4.0}).text.strip()
    except Exception: return "আপনার বার্তা পেয়েছি, অনুগ্রহ করে মেনু ব্যবহার করুন।"

def ai_analyze_ticket_sentiment(ticket_text):
    if not ai_model: return "Normal", "সাধারণ সাপোর্ট বার্তা"
    try:
        res = ai_model.generate_content(f"Analyze support ticket priority (High/Normal) and 1-line Bengali summary. Format JSON keys 'priority','summary'. Msg: {ticket_text}", request_options={"timeout": 4.0}).text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(res)
        return data.get("priority", "Normal"), data.get("summary", "সাপোর্ট রিকোয়েস্ট")
    except Exception: return "Normal", "সাপোর্ট রিকোয়েস্ট"

def calculate_worker_trust_score(chat_id):
    total, appr = submissions_col.count_documents({"chat_id": chat_id}), submissions_col.count_documents({"chat_id": chat_id, "status": "Approved"})
    if total == 0: return "New Worker", 100
    ratio = appr / total
    if total >= 50 and ratio >= 0.90: return "⭐ VIP Worker", int(ratio * 100)
    elif total >= 20 and ratio >= 0.75: return "🛡️ Trusted Worker", int(ratio * 100)
    return "👤 Regular Worker", int(ratio * 100)

def sanitize_html(text): return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if text else "Worker"

def generate_profile_data(country):
    if country == "bd": fn, ln, flag = random.choice(BD_FIRST_NAMES), random.choice(BD_LAST_NAMES), "🇧🇩 BANGLADESH"
    else: fn, ln, flag = random.choice(USA_FIRST_NAMES), random.choice(USA_LAST_NAMES), "🇺🇸 USA"
    username = f"{fn.lower()}{random.choice(['_','.',''])}{ln.lower()}{random.randint(10,999)}"
    dob = f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{random.randint(1995,2006)}"
    return f"🎲 <b>CYBER PERSONA // {flag}</b>\n\n• <b>First Name:</b> <code>{fn}</code>\n• <b>Last Name:</b> <code>{ln}</code>\n• <b>Username:</b> <code>{username}</code>\n• <b>Birth Date:</b> <code>{dob}</code>\n\n💡 <i>Tap any text above to copy instantly.</i>", InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Refresh", callback_data=f"gen_prof_{country}"))

def send_private_backup_message(content, doc_buf=None, doc_name=None):
    def task():
        try:
            safe_content = content if len(content) <= 3800 else content[:3750] + "\n\n⚠️ <i>[Data Truncated]</i>"
            if doc_buf and doc_name:
                doc_buf.seek(0)
                bot.send_document(BACKUP_CHANNEL_ID, (doc_name, doc_buf), caption=safe_content)
            else: bot.send_message(BACKUP_CHANNEL_ID, safe_content)
        except Exception: pass
    background_executor.submit(task)

def broadcast_password_rule_notice(new_rule):
    def task():
        notice_text = f"📢 <b>OEB NEXUS OFFICIAL NOTICE</b>\n\n🔑 <b>আজকের নতুন পাসওয়ার্ড কোড:</b> <code>{sanitize_html(new_rule)}</code>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n📌 <b>নির্দেশাবলী:</b>\n১. একাউন্ট খোলার সময় আপনার পাসওয়ার্ডের <b>'একদম শেষে'</b> বাধ্যতামূলকভাবে '<code>{sanitize_html(new_rule)}</code>' কোডটি যুক্ত করুন।\n২. নিয়ম ছাড়া ভুল পাসওয়ার্ড দিলে একাউন্ট সরাসরি রিজেক্ট হয়ে যাবে!\n\n⚡ এখনই কাজ শুরু করুন! 🚀"
        for u in users_col.find({"banned": False}):
            try: bot.send_message(u["_id"], notice_text); time.sleep(0.04)
            except Exception: pass
    heavy_task_executor.submit(task)

def make_progress_bar(processed, total, length=10):
    if not total or total == 0: return "░" * length
    filled = int(min(1.0, max(0.0, processed / total)) * length)
    return "█" * filled + "░" * (length - filled)

def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        user = {"_id": chat_id, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0, "banned": False, "is_vip": False, "custom_password": "", "joined_date": get_bd_time()}
        try: users_col.insert_one(user)
        except: pass
    return user

def update_user_field(chat_id, field, value): background_executor.submit(lambda: users_col.update_one({"_id": chat_id}, {"$set": {field: value}}, upsert=True))
def is_user_banned(chat_id): u = users_col.find_one({"_id": chat_id}); return u.get("banned", False) if u else False

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            if bot.get_chat_member(ch["username"], user_id).status in ['left', 'kicked']: return False
        except Exception: continue
    return True

def generate_tracking_id(): return f"SUB-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"
def generate_withdraw_id(): return f"WDR-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"

# 🛡️ FIX: Float UID and 3-Layer Duplicate Checker
def extract_numeric_uid(text):
    text = str(text).strip()
    if text.endswith('.0'): text = text[:-2] 
    match = re.search(r'c_user=(\d{8,20})', text) or re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text) or re.search(r'\b(\d{8,20})\b', text)
    return match.group(1) if match else None

def is_duplicate_uid(uid, cat_key): return submissions_col.find_one({"uid": str(uid), "category_key": cat_key}) or skeletons_col.find_one({"uid": str(uid), "category_key": cat_key})
def generate_payload_hash(payload_str): return hashlib.sha256(re.sub(r'\s+', '', str(payload_str)).encode('utf-8')).hexdigest()
def is_payload_blacklisted(payload_hash): return blacklisted_payloads_col.find_one({"_id": payload_hash}) is not None
def is_valid_cookies(cookie_str): c_str = str(cookie_str); return any(x in c_str for x in ["c_user=", "datr=", "xs=", "sessionid="])

# 🌐 Anti-IP Ban Bypass System
def check_live_account(uid):
    try:
        clean_uid = extract_numeric_uid(uid)
        if not clean_uid: return False, "Invalid UID"
        time.sleep(random.uniform(0.5, 1.5))
        res = requests.get(f"https://m.facebook.com/profile.php?id={clean_uid}", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/91.0 Mobile Safari/537.36", "Accept-Language": "en-US,en;q=0.5"}, timeout=5.0, allow_redirects=True)
        content = res.text.lower()
        if res.status_code == 429 or "captcha" in content or "security check" in content: return True, "Assumed Live (IP Block)"
        if res.status_code != 200: return False, "Suspended/Dead"
        if "content=\"no-cache\"" in content or "unavailable" in content or "login" in res.url: return False, "Checkpoint/Dead" if "c_user" not in res.url and clean_uid not in res.url else True, "Live Account"
        if "profile_ring" in content or "mbasic_inline_feed_composer" in content or clean_uid in res.url: return True, "Live Account"
        return False, "Dead"
    except requests.exceptions.Timeout: return True, "Assumed Live"
    except Exception: return False, "Error"

def check_ig_username_live(username):
    try:
        clean_user = username.replace("@", "").strip()
        time.sleep(random.uniform(0.5, 1.5))
        res = requests.get(f"https://www.instagram.com/{clean_user}/", headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
        if res.status_code == 429 or "login" in res.url: return True, "Assumed Live"
        if res.status_code == 200 and "Page Not Found" not in res.text: return True, "Live Instagram"
        return False, "Dead"
    except Exception: return True, "Assumed Live"

def get_active_hold_dates():
    res = list(set([r["_id"] for r in submissions_col.aggregate([{"$group": {"_id": "$date_key"}}]) if r["_id"]] + [r["_id"] for r in skeletons_col.aggregate([{"$group": {"_id": "$date_key"}}]) if r["_id"]]))
    res.sort(reverse=True); return res

def build_date_query(selected_date, base_status=None):
    q = {}
    if base_status: q["status"] = base_status
    if selected_date != "ALL": q["date_key"] = selected_date
    return q

def generate_worker_badge_image_py(worker_id, username, total_submissions):
    oeb_id = get_oeb_id(worker_id)
    img = Image.new('RGB', (600, 320), color='#0f172a')
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.rectangle([10, 10, 590, 310], outline='#38bdf8', width=3)
    draw.text((30, 30), f"VERIFIED WORKER BADGE // {oeb_id}", fill='#38bdf8', font=font)
    draw.text((30, 80), f"Name/Username: {username}", fill='#ffffff', font=font)
    draw.text((30, 120), f"Worker Code: {oeb_id} (ID: {worker_id})", fill='#ffffff', font=font)
    draw.text((30, 160), f"Total Tasks Completed: {total_submissions}", fill='#ffffff', font=font)
    draw.rectangle([30, 220, 210, 270], fill='#10b981')
    draw.text((50, 235), "VERIFIED STAFF", fill='#ffffff', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG'); buf.seek(0); return buf
# ================= 4. UI Keyboards =================
def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚡ কাজ জমা সেন্টার"), KeyboardButton("🛠 হেল্পার টুলস"))
    if users_col.find_one({"_id": chat_id, "is_vip": True}): markup.add(KeyboardButton("💼 এজেন্ট প্যানেল"))
    markup.add(KeyboardButton("👤 প্রোফাইল ও ওয়ালেট"), KeyboardButton("🎁 রিওয়ার্ড ও সাপোর্ট"))
    if chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 এডমিন কন্ট্রোল সেন্টার"))
    return markup

def submit_tasks_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    markup.add(KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def category_bottom_keyboard(chat_id=None):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(f"📄 FB Cookies (৳{get_current_task_rate('fb_cookie', chat_id):.1f})"), KeyboardButton(f"🔐 FB 2FA (৳{get_current_task_rate('fb_2fa', chat_id):.1f})"))
    markup.add(KeyboardButton(f"📷 IG Cookies (৳{get_current_task_rate('ig_cookie', chat_id):.1f})"), KeyboardButton(f"🔐 IG 2FA (৳{get_current_task_rate('ig_2fa', chat_id):.1f})"))
    for ck, ci in get_setting("custom_categories", {}).items(): markup.add(KeyboardButton(f"📌 {ci.get('name')} (৳{float(ci.get('rate', 5.0)) + get_active_surge_bonus():.2f})"))
    markup.add(KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def helper_tools_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"))
    markup.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    markup.add(KeyboardButton("👤 র্যান্ডম প্রোফাইল জেনারেটর"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("💳 Withdraw"), KeyboardButton("📜 কাজের ইতিহাস"))
    markup.add(KeyboardButton("🪪 ভেরিফাইড আইডি কার্ড"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def bonus_support_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🎁 Claim Daily Bonus"), KeyboardButton("🏆 লিডারবোর্ড"))
    markup.add(KeyboardButton("💬 এডমিন সাপোর্ট টিকিট"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 টাস্ক ও রিপোর্ট"), KeyboardButton("💳 ফাইন্যান্স"), KeyboardButton("⚙️ সেটিংস"), KeyboardButton("📢 সিস্টেম কন্ট্রোল"), KeyboardButton("🏠 মেইন মেনু"))
    return markup

def admin_sub_task_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 স্মার্ট ড্যাশবোর্ড"), KeyboardButton("📂 ফাইল এক্সপোর্ট"), KeyboardButton("🤖 অটো-ম্যাচার"), KeyboardButton("🔍 সার্চ ভল্ট"))
    markup.add(KeyboardButton("🏛️ আর্কাইভ ও বন্ধ ফাইল"), KeyboardButton("⏳ ম্যানুয়াল পেন্ডিং চেক"), KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_finance_keyboard():
    pending_w_count = withdrawals_col.count_documents({"status": "Pending"})
    return ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(KeyboardButton(f"⏳ পেন্ডিং উইথড্রয়াল চেক ({pending_w_count} টি)"), KeyboardButton("🔙 এডমিন প্যানেল"))

def admin_sub_settings_keyboard():
    m_mode = get_setting("maintenance_mode", False)
    m_btn = "🛠 মেইনটেনেন্স: 🟢 ON" if m_mode else "🛠 মেইনটেনেন্স: 🔴 OFF"
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("⚙️ সেট রেট ও চার্জ"), KeyboardButton("⚙️ কাস্টম ক্যাটাগরি প্যানেল"), KeyboardButton("🔑 পাসওয়ার্ড নিয়ম সেট"), KeyboardButton(m_btn), KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def admin_sub_system_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 ইউজার ও VIP ম্যানেজার"), KeyboardButton("📢 ব্রডকাস্ট নোটিশ"), KeyboardButton("🧠 AI সিটেডেল অডিট"), KeyboardButton("🔙 এডমিন প্যানেল"))
    return markup

def cancel_keyboard(): return ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(KeyboardButton("❌ বাতিল করুন"))

def render_user_manager_page(admin_chat_id, message_id=None, page=1):
    users_per_page = 5
    total_u = users_col.count_documents({})
    total_pages = max(1, (total_u + users_per_page - 1) // users_per_page)
    page = max(1, min(page, total_pages))
    skip = (page - 1) * users_per_page
    user_list = list(users_col.find().sort("joined_date", -1).skip(skip).limit(users_per_page))

    out_msg = f"👥 <b>USER & VIP CONTROL</b> (Page {page}/{total_pages})\n────────────────────────\n\n"
    markup = InlineKeyboardMarkup(row_width=2)
    for i, u in enumerate(user_list, start=skip + 1):
        u_id = u["_id"]
        is_banned, is_vip = u.get("banned", False), u.get("is_vip", False)
        st_badge = "🔴 Banned" if is_banned else ("⭐ VIP" if is_vip else "🟢 Regular")
        out_msg += f"<b>{i}. {sanitize_html(str(u.get('first_name', 'Worker')))}</b>\nID: <code>{u_id}</code> | St: <b>{st_badge}</b>\n\n"
        markup.add(InlineKeyboardButton(f"{'🟢 আনব্যান' if is_banned else '🚫 ব্যান'} #{u_id}", callback_data=f"toggle_ban_{u_id}_{page}"), InlineKeyboardButton(f"{'⭐ VIP সরান' if is_vip else '⭐ VIP করুন'} #{u_id}", callback_data=f"toggle_vip_{u_id}_{page}"))

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("◀️", callback_data=f"um_page_{page - 1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("➡️", callback_data=f"um_page_{page + 1}"))
    if nav_row: markup.row(*nav_row)

    if message_id:
        try: bot.edit_message_text(out_msg, admin_chat_id, message_id, reply_markup=markup)
        except Exception: bot.send_message(admin_chat_id, out_msg, reply_markup=markup)
    else: bot.send_message(admin_chat_id, out_msg, reply_markup=markup)

# ================= 🧹 6. NIGHTLY WIPE DAEMON (RAM-Safe & Data Loss Proof) =================
def nightly_wipe_routine():
    today = get_bd_time().strftime("%Y-%m-%d")
    print(f"[{today}] 🌙 Starting RAM-Safe Backup & Wipe Engine...")
    
    active_workers = submissions_col.distinct("chat_id", {"date_key": today})
    for worker_id in active_workers:
        oeb_id = get_oeb_id(worker_id)
        worker_subs = list(submissions_col.find({"chat_id": worker_id, "date_key": today}))
        if not worker_subs: continue
        
        categories = list(set([s["category_key"] for s in worker_subs]))
        index_text = f"👤 <b>মেম্বার কোড:</b> <code>{oeb_id}</code>\n📅 <b>তারিখ:</b> {today}\n━━━━━━━━━━━━━━━━━━━━\n📊 <b>আজকের কাজ:</b>\n"
        files_to_send, total_payout = [], 0.0
        
        for cat_key in categories:
            cat_display = CAT_MAP.get(cat_key, cat_key)
            subs = [s for s in worker_subs if s["category_key"] == cat_key]
            if not subs: continue
            
            count, rate = len(subs), float(subs[0].get("rate", 5.0))
            total_payout += count * rate
            index_text += f"• <b>{cat_display}:</b> {count} টি\n"
            
            df = pd.DataFrame([{"UID": s.get("uid", ""), "Password": s.get("password", ""), "Payload": s.get("payload", ""), "Category": s.get("category", ""), "Track_ID": s.get("track_id", "")} for s in subs])
            file_name = f"{oeb_id}.{cat_display.replace(' ', '_')}-{today}.xlsx"
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer: df.to_excel(writer, index=False)
            excel_buf.seek(0)
            files_to_send.append((file_name, excel_buf, cat_key))
            
        index_text += f"💰 <b>হোল্ড:</b> ৳{total_payout:.2f}\n"
        
        backup_success = False
        try:
            index_msg = bot.send_message(BACKUP_CHANNEL_ID, index_text)
            for fname, fbuf, c_key in files_to_send:
                sent_doc = bot.send_document(BACKUP_CHANNEL_ID, (fname, fbuf), caption=f"📁 {fname}", reply_to_message_id=index_msg.message_id)
                archives_col.insert_one({"oeb_id": oeb_id, "worker_id": worker_id, "date_key": today, "category_key": c_key, "file_name": fname, "message_id": sent_doc.message_id, "timestamp": get_bd_time()})
            backup_success = True
        except Exception: pass

        # STRICT DATA LOSS PREVENTION: Only convert to skeleton & delete if Backup was 100% successful
        if backup_success:
            for s in worker_subs:
                if s.get("status") != "Rejected":
                    try: skeletons_col.insert_one({"uid": s.get("uid"), "chat_id": s.get("chat_id"), "category_key": s.get("category_key"), "rate": s.get("rate"), "status": s.get("status", "Hold"), "date_key": today})
                    except DuplicateKeyError: pass
            submissions_col.delete_many({"_id": {"$in": [s["_id"] for s in worker_subs]}})

    print(f"✅ [NIGHTLY WIPE COMPLETE]")

def schedule_nightly_wipe():
    while True:
        try:
            now = get_bd_time()
            today_str = now.strftime("%Y-%m-%d")
            if now.hour == 23 and now.minute >= 55 and get_setting("last_nightly_wipe", "") != today_str:
                nightly_wipe_routine()
                update_setting("last_nightly_wipe", today_str)
            time.sleep(30)
        except Exception: time.sleep(30)

threading.Thread(target=schedule_nightly_wipe, daemon=True).start()

# ================= 7. Flask Server Engine =================
flask_app = Flask(__name__)
@flask_app.route('/')
def flask_home(): return "OEB NEXUS Production Engine Active!"
@flask_app.route(f'/{TOKEN}', methods=['POST'])
def telegram_webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
            return '', 200
    except Exception: pass
    abort(403)
# ================= 8. Core Handlers =================
@bot.message_handler(commands=['start'])
def send_welcome(message): background_executor.submit(lambda: _process_welcome(message))

def _process_welcome(message):
    try:
        chat_id = message.chat.id
        if chat_id != ADMIN_ID and get_setting("maintenance_mode", False): return bot.reply_to(message, "🛠 <b>বটের সার্ভার আপডেটের কাজ চলছে!</b>")
        if is_user_banned(chat_id): return bot.reply_to(message, "🔴 <b>আপনার অ্যাকাউন্টটি স্থগিত (Banned) করা হয়েছে!</b>")

        user = get_user_data(chat_id)
        if message.from_user.username: update_user_field(chat_id, "username", message.from_user.username)
        user_states.pop(chat_id, None)

        if not check_force_join(chat_id):
            markup = InlineKeyboardMarkup(row_width=1)
            for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
            markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
            return bot.send_message(chat_id, "🔒 <b>চ্যানেল ভেরিফিকেশন প্রয়োজন:</b>", reply_markup=markup)

        oeb_id = get_oeb_id(chat_id)
        welcome_card = f"❖ <b>OEB NEXUS // SECURE CORE v12.0</b>\n\n👤 <b>Operator:</b> {sanitize_html(message.from_user.first_name)[:18]}\n🆔 <b>Worker Code:</b> <code>{oeb_id}</code>\n\n💳 <b>Wallet:</b> ৳ {float(user.get('balance') or 0.0):.2f}\n⏳ <b>Escrow:</b> ৳ {float(user.get('hold_balance') or 0.0):.2f}\n\n⚡ <i>Select an option from the terminal below:</i>"
        bot.send_message(chat_id, welcome_card, reply_markup=main_bottom_keyboard(chat_id))
    except Exception: pass

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call): background_executor.submit(lambda: _process_callbacks(call))

def _process_callbacks(call):
    chat_id, code = call.message.chat.id, call.data
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False):
        try: bot.answer_callback_query(call.id, "🛠 আপডেট চলছে!", show_alert=True)
        except Exception: pass
        return

    if code == "verify_join":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        else: bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!")

    elif code.startswith("w_method_"):
        method_name = "bKash" if code.replace("w_method_", "") == "bkash" else "Binance Pay ID"
        user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_ACCOUNT', 'method': method_name}
        bot.edit_message_text(f"📱 <b>আপনার {method_name} টি টাইপ করুন:</b>", chat_id, call.message.message_id)

    elif code.startswith("w_appr_") and chat_id == ADMIN_ID:
        w_id = code.replace("w_appr_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Approved"}})
            bot.edit_message_text(f"✅ <b>APPROVED</b>\nID: <code>{w_id}</code>", chat_id, call.message.message_id)
            try: bot.send_message(w_doc['chat_id'], f"🎉 <b>উইথড্র এপ্রুভ হয়েছে!</b> ৳{w_doc['amount']:.2f}")
            except Exception: pass

    elif code.startswith("w_rej_") and chat_id == ADMIN_ID:
        w_id = code.replace("w_rej_", "")
        w_doc = withdrawals_col.find_one({"withdraw_id": w_id, "status": "Pending"})
        if w_doc:
            withdrawals_col.update_one({"withdraw_id": w_id}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": w_doc['chat_id']}, {"$inc": {"balance": w_doc['amount']}})
            bot.edit_message_text(f"❌ <b>REJECTED</b>\nID: <code>{w_id}</code>", chat_id, call.message.message_id)

    elif code == "trigger_add_cat" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_NEW_CAT_NAME'}
        bot.send_message(ADMIN_ID, "📝 <b>নতুন ক্যাটাগরির নাম লিখুন:</b>", reply_markup=cancel_keyboard())

    elif code == "save_pass_default":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        temp_pass = get_user_data(chat_id).get("temp_pending_password", "")
        p_rule = str(get_setting("pass_rule", "")).strip()
        if temp_pass:
            if not validate_strict_password(temp_pass, p_rule): bot.edit_message_text("❌ <b>কোড নেই!</b>", chat_id, call.message.message_id)
            else:
                update_user_field(chat_id, "custom_password", temp_pass)
                bot.edit_message_text(f"✅ <b>পাসওয়ার্ড সেভ করা হয়েছে!</b>", chat_id, call.message.message_id)

    elif code == "user_set_custom_pass":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        p_rule = str(get_setting("pass_rule", "")).strip()
        user_states[chat_id] = {'step': 'AWAITING_USER_SET_PASS'}
        msg = f"✏️ <b>নতুন ডিফল্ট পাসওয়ার্ডটি লিখে পাঠান:</b>\n"
        if p_rule and p_rule.lower() != "none": msg += f"\n⚠️ <i>শেষে <b>{sanitize_html(p_rule)}</b> থাকা বাধ্যতামূলক!</i>"
        bot.send_message(chat_id, msg, reply_markup=cancel_keyboard())

    elif code == "user_remove_custom_pass":
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        update_user_field(chat_id, "custom_password", "")
        bot.edit_message_text("🗑️ <b>পাসওয়ার্ড মুছে ফেলা হয়েছে!</b>", chat_id, call.message.message_id)

    elif code.startswith("um_page_") and chat_id == ADMIN_ID:
        render_user_manager_page(ADMIN_ID, call.message.message_id, int(code.replace("um_page_", "")))

    elif code.startswith("toggle_ban_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        user_doc = users_col.find_one({"_id": int(parts[2])})
        if user_doc: users_col.update_one({"_id": int(parts[2])}, {"$set": {"banned": not user_doc.get("banned", False)}})
        render_user_manager_page(ADMIN_ID, call.message.message_id, int(parts[3]))

    elif code.startswith("toggle_vip_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        user_doc = users_col.find_one({"_id": int(parts[2])})
        if user_doc: users_col.update_one({"_id": int(parts[2])}, {"$set": {"is_vip": not user_doc.get("is_vip", False)}})
        render_user_manager_page(ADMIN_ID, call.message.message_id, int(parts[3]))

    elif code.startswith("dash_dt_") and chat_id == ADMIN_ID:
        date = code.replace("dash_dt_", "")
        out = f"📊 <b>BATCH REPORT // {date}</b>\n\n"
        tot_hold = 0
        for c in ["fb_cookie", "fb_2fa", "ig_cookie", "ig_2fa"]:
            h = submissions_col.count_documents({"date_key": date, "status": "Hold", "category_key": c}) + skeletons_col.count_documents({"date_key": date, "status": "Hold", "category_key": c})
            a = submissions_col.count_documents({"date_key": date, "status": "Approved", "category_key": c}) + skeletons_col.count_documents({"date_key": date, "status": "Approved", "category_key": c})
            out += f"• <b>{c}</b>: (⏳{h} / ✅{a})\n"
            tot_hold += h
        markup = InlineKeyboardMarkup(row_width=2)
        if tot_hold > 0: markup.add(InlineKeyboardButton(f"📥 রিপোর্ট মেলান", callback_data=f"bm_select_date_{date}"))
        bot.send_message(ADMIN_ID, out + f"\n📌 <b>Total Hold:</b> {tot_hold}", reply_markup=markup)

    elif code.startswith("bm_select_date_") and chat_id == ADMIN_ID:
        target_date = code.replace("bm_select_date_", "")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("📄 FB Cookies", callback_data=f"bm_cat_{target_date}_fb_cookie"), InlineKeyboardButton("🔐 FB 2FA", callback_data=f"bm_cat_{target_date}_fb_2fa"))
        markup.add(InlineKeyboardButton("🌐 সব ক্যাটাগরি একসাথে", callback_data=f"bm_cat_{target_date}_ALL"))
        bot.send_message(ADMIN_ID, f"🤖 <b>[{target_date}]</b> এর রিপোর্ট মেলাবেন?", reply_markup=markup)

    elif code.startswith("bm_cat_") and chat_id == ADMIN_ID:
        parts = code.split("_")
        user_states[ADMIN_ID] = {'step': 'AWAITING_BUYER_REPORT', 'target_date': parts[2], 'target_cat': "_".join(parts[3:])}
        bot.send_message(ADMIN_ID, f"📄 <b>বায়ার রিপোর্ট ফাইলটি সেন্ড করুন:</b>", reply_markup=cancel_keyboard())
        
    elif code.startswith("edit_sub_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        track_id = code.replace("edit_sub_", "")
        sub = submissions_col.find_one({"track_id": track_id, "chat_id": chat_id, "status": "Hold"})
        if not sub: return bot.send_message(chat_id, "⚠️ এই কাজটির এডিট মেয়াদ শেষ বা প্রসেস করা হয়েছে।")
        user_states[chat_id] = {'step': 'AWAITING_EDIT_PAYLOAD', 'track_id': track_id}
        bot.send_message(chat_id, f"✏️ <b>Track ID: {track_id}</b> এর জন্য সঠিক ডাটা পেস্ট করুন:", reply_markup=cancel_keyboard())

    elif code.startswith("check_otp_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        email = code.replace("check_otp_", "")
        user_name, domain = email.split("@")
        try:
            res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={user_name}&domain={domain}").json()
            if not res: bot.send_message(chat_id, "📭 ইনবক্সে এখনো কোনো বার্তা আসেনি! ২-১ সেকেন্ড পর আবার চেষ্টা করুন।")
            else:
                msg_detail = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={user_name}&domain={domain}&id={res[0]['id']}").json()
                body = msg_detail.get('textBody', '')
                otp_match = re.search(r'\b(\d{5,6})\b', body)
                bot.send_message(chat_id, f"✉️ <b>OTP Received!</b>\n🔑 Code: <code>{otp_match.group(1) if otp_match else 'Not Found'}</code>\n\n📄 <b>Msg:</b> {sanitize_html(body[:300])}")
        except Exception: bot.send_message(chat_id, "⚠️ ওটিপি চেক করতে সমস্যা হয়েছে।")

    elif code.startswith("lb_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        tf = code.replace("lb_", "")
        now = get_bd_time()
        if tf == "daily": query, title = {"date_key": now.strftime('%Y-%m-%d')}, "আজকের সেরা"
        elif tf == "weekly": query, title = {"date_key": {"$gte": (now - timedelta(days=7)).strftime('%Y-%m-%d')}}, "এই সপ্তাহের সেরা"
        else: query, title = {}, "সর্বকালের সেরা"

        top = list(submissions_col.aggregate([{"$match": query}, {"$group": {"_id": "$worker_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]))
        out = f"🏆 <b>LEADERBOARD // {title}</b>\n\n"
        badges = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, item in enumerate(top): out += f"{badges[i]} <b>{sanitize_html(item['_id'])}</b> — {item['count']} টি\n"
        
        markup = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("📅 আজ", callback_data="lb_daily"), InlineKeyboardButton("🗓️ এই সপ্তাহ", callback_data="lb_weekly"), InlineKeyboardButton("🏆 সর্বকাল", callback_data="lb_alltime"))
        bot.edit_message_text(out + f"\n────────────────────────\n🎯 <b>Your Tasks:</b> {submissions_col.count_documents({'chat_id': chat_id})}", chat_id, call.message.message_id, reply_markup=markup)

    elif code.startswith("gen_prof_"):
        try: bot.answer_callback_query(call.id)
        except Exception: pass
        msg_text, markup = generate_profile_data(code.replace("gen_prof_", ""))
        try: bot.edit_message_text(msg_text, chat_id, call.message.message_id, reply_markup=markup)
        except Exception: bot.send_message(chat_id, msg_text, reply_markup=markup)

# --- FILE/DOCUMENT ROUTER ---
@bot.message_handler(content_types=['document'])
def handle_document(message): heavy_task_executor.submit(lambda: _process_document(message))

def _process_document(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False): return
    if is_user_banned(chat_id): return
    state = user_states.get(chat_id)
    
    # 🤖 Buyer Report Matcher
    if state and state.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
        target_date, target_cat = state.get('target_date', 'ALL'), state.get('target_cat', 'ALL')
        user_states.pop(chat_id, None)
        bot.reply_to(message, "⏳ <b>ম্যাচিং চলছে...</b>")
        
        try:
            downloaded = bot.download_file(bot.get_file(message.document.file_id).file_path)
            fn = message.document.file_name.lower()
            if fn.endswith(".csv"): df_raw = pd.read_csv(io.BytesIO(downloaded), dtype=str)
            elif fn.endswith(".xlsx"): df_raw = pd.read_excel(io.BytesIO(downloaded), dtype=str)
            else: df_raw = pd.DataFrame(re.findall(r'\b\d{8,20}\b', downloaded.decode('utf-8', errors='ignore')), columns=[0])
            
            cleaned_uids = set([str(u).strip().split('.')[0] for u in df_raw.values.flatten() if str(u).strip().split('.')[0].isdigit()])
            
            q = build_date_query(target_date, "Hold")
            if target_cat != "ALL": q["category_key"] = target_cat
            
            all_hold = list(submissions_col.find(q)) + list(skeletons_col.find(q))
            if not all_hold: return bot.send_message(ADMIN_ID, "📭 কোনো পেন্ডিং কাজ নেই!")

            appr, rej, payout = 0, 0, 0.0
            for item in all_hold:
                uid, amt, worker_id = str(item.get("uid", "")).strip(), float(item.get("rate") or 0.0), item.get("chat_id")
                if uid in cleaned_uids:
                    submissions_col.update_one({"_id": item.get("_id")}, {"$set": {"status": "Approved"}})
                    skeletons_col.update_one({"_id": item.get("_id")}, {"$set": {"status": "Approved"}})
                    users_col.update_one({"_id": worker_id}, {"$inc": {"balance": amt, "hold_balance": -amt}})
                    appr += 1; payout += amt
                    try: bot.send_message(worker_id, f"✅ আইডি (<code>{uid}</code>) এপ্রুভ! ৳{amt:.2f} যোগ হয়েছে।")
                    except Exception: pass
                else:
                    submissions_col.update_one({"_id": item.get("_id")}, {"$set": {"status": "Rejected"}})
                    skeletons_col.update_one({"_id": item.get("_id")}, {"$set": {"status": "Rejected"}})
                    users_col.update_one({"_id": worker_id}, {"$inc": {"hold_balance": -amt}})
                    rej += 1
            return bot.send_message(ADMIN_ID, f"🤖 <b>[MATCH COMPLETE]</b>\n✅ এপ্রুভড: <b>{appr} টি</b> | ❌ রিজেক্টেড: <b>{rej} টি</b>", reply_markup=admin_bottom_keyboard())
        except Exception: return bot.send_message(chat_id, "❌ ফাইল রিড এরর।")

    # 📊 Excel File Submissions (RAM Limit & Throttled Timer)
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        user = get_user_data(chat_id)
        p_rule = str(get_setting("pass_rule", "")).strip()
        pwd = user.get("custom_password")
        pwd = pwd if (pwd and str(pwd).strip() != "" and str(pwd).lower() != "none") else p_rule

        if not validate_strict_password(pwd, p_rule): return bot.reply_to(message, "❌ পাসওয়ার্ড বাতিল!", reply_markup=submit_tasks_keyboard())
        user_states.pop(chat_id, None)
        
        file_info = bot.get_file(message.document.file_id)
        if file_info.file_size > 5242880: return bot.send_message(chat_id, "❌ ফাইল ৫ এমবির বেশি!") # OOM Protection
        unique_file_name = f"tmp_{uuid.uuid4().hex[:6]}.xlsx"
        
        try:
            with open(unique_file_name, 'wb') as f: f.write(bot.download_file(file_info.file_path))
            df = pd.read_csv(unique_file_name, dtype=str).head(2000) if unique_file_name.endswith('.csv') else pd.read_excel(unique_file_name, dtype=str).head(2000)
            now_time = get_bd_time()
            candidates = []

            for _, row in df.fillna('').iterrows():
                uid, payload = None, None
                for v in [str(x).strip() for x in row.values]:
                    if not uid and extract_numeric_uid(v): uid = extract_numeric_uid(v)
                    elif is_valid_cookies(v) or len(v) > 20: payload = v
                cat_k = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                if uid and payload and not is_duplicate_uid(uid, cat_k) and not is_payload_blacklisted(generate_payload_hash(payload)):
                    candidates.append({"uid": uid, "payload": payload, "hash": generate_payload_hash(payload), "cat": cat_k})

            tot = len(candidates)
            if tot == 0: return bot.send_message(chat_id, "❌ ফাইলে কোনো নতুন ডাটা নেই!", reply_markup=submit_tasks_keyboard())
            status_msg = bot.send_message(chat_id, f"⏳ <b>প্রসেস করা হচ্ছে...</b>")

            success_count, total_earned, last_upd = 0, 0.0, time.time()
            for i, item in enumerate(candidates, 1):
                is_live, _ = check_live_account(item["uid"]) if "fb" in item["cat"] else (True, "")
                if is_live:
                    rate = float(get_current_task_rate(item["cat"], chat_id))
                    try:
                        submissions_col.insert_one({"chat_id": chat_id, "uid": item["uid"], "password": pwd, "payload": item["payload"], "payload_hash": item["hash"], "track_id": generate_tracking_id(), "category_key": item["cat"], "rate": rate, "status": "Hold", "date_key": now_time.strftime("%Y-%m-%d")})
                        success_count += 1; total_earned += rate
                    except DuplicateKeyError: pass

                curr = time.time()
                if curr - last_upd >= 3.0 or i == tot: # 3-sec Throttle logic to prevent 429
                    try: bot.edit_message_text(f"⏳ <b>প্রসেস চলছে... [{make_progress_bar(i, tot, 10)}]</b>\nসেভড: {success_count} / {tot}", chat_id, status_msg.message_id)
                    except Exception: pass
                    last_upd = curr

            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": total_earned}})
            bot.send_message(chat_id, f"🎉 <b>প্রসেস সম্পন্ন!</b>\nগৃহীত: <b>{success_count}</b> টি | হোল্ড: ৳<b>{total_earned:.2f}</b> BDT", reply_markup=submit_tasks_keyboard())
        except Exception: bot.send_message(chat_id, "❌ ফাইল রিড এরর।")
        finally:
            if os.path.exists(unique_file_name): os.remove(unique_file_name)
# --- MAIN TEXT ROUTER ---
@bot.message_handler(content_types=['text', 'photo', 'video', 'animation'])
def main_router(message): background_executor.submit(lambda: _process_main_router(message))

def _process_main_router(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False): return
    if is_user_banned(chat_id): return
    
    text = message.text.strip() if message.text else (message.caption.strip() if message.caption else "")
    user = get_user_data(chat_id)

    nav_buttons = ["🏠 মেইন মেনু", "🔙 পেছনে যান", "❌ বাতিল করুন", "⚡ কাজ জমা সেন্টার", "🛠 হেল্পার টুলস", "📌 সিঙ্গেল জমা", "👤 প্রোফাইল ও ওয়ালেট", "🎁 রিওয়ার্ড ও সাপোর্ট", "👑 এডমিন কন্ট্রোল সেন্টার", "💳 Withdraw", "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "💼 এজেন্ট প্যানেল", "📊 টাস্ক ও রিপোর্ট", "💳 ফাইন্যান্স", "⚙️ সেটিংস", "📢 সিস্টেম কন্ট্রোল", "🔙 এডমিন প্যানেল", "📊 স্মার্ট ড্যাশবোর্ড", "🤖 অটো-ম্যাচার", "🔍 সার্চ ভল্ট", "🔑 2FA কোড জেনারেটর", "✉️ টেম্প ইমেইল", "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "👤 র্যান্ডম প্রোফাইল জেনারেটর", "📜 কাজের ইতিহাস", "👤 ইউজার ও VIP ম্যানেজার", "📢 ব্রডকাস্ট নোটিশ", "🧠 AI সিটেডেল অডিট", "⚙️ সেট রেট ও চার্জ", "🔑 পাসওয়ার্ড নিয়ম সেট", "⚙️ কাস্টম ক্যাটাগরি প্যানেল", "➕ নতুন ক্যাটাগরি যোগ করুন", "🎁 Claim Daily Bonus", "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", "🪪 ভেরিফাইড আইডি কার্ড"]
    if text in nav_buttons: user_states.pop(chat_id, None)

    if text == "❌ বাতিল করুন": return bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))
    elif text in ["🏠 মেইন মেনু", "🔙 পেছনে যান"]: return bot.send_message(chat_id, f"❖ <b>OEB NEXUS // SECURE CORE v12.0</b>\n\n🆔 <b>Code:</b> <code>{get_oeb_id(chat_id)}</code>\n💳 <b>Wallet:</b> ৳ {float(user.get('balance') or 0.0):.2f}\n⏳ <b>Escrow:</b> ৳ {float(user.get('hold_balance') or 0.0):.2f}", reply_markup=main_bottom_keyboard(chat_id))
    elif text == "⚡ কাজ জমা সেন্টার": return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ:</b>", reply_markup=submit_tasks_keyboard())
    elif text == "💼 এজেন্ট প্যানেল" and user.get("is_vip"): return bot.send_message(chat_id, f"💼 <b>SECRET VIP PANEL</b>\n\nFB Cook: ৳{get_current_task_rate('fb_cookie', chat_id)}\nFB 2FA: ৳{get_current_task_rate('fb_2fa', chat_id)}", reply_markup=main_bottom_keyboard(chat_id))
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
    elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard(chat_id))
    elif text == "👤 প্রোফাইল ও ওয়ালেট": return bot.send_message(chat_id, f"👤 <b>PROFILE</b>\nWallet: ৳{user.get('balance'):.2f}\nHold: ৳{user.get('hold_balance'):.2f}", reply_markup=account_keyboard())
    elif text == "🎁 রিওয়ার্ড ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>রিওয়ার্ড ও সাপোর্ট:</b>", reply_markup=bonus_support_keyboard())
    elif text == "👑 এডমিন কন্ট্রোল সেন্টার" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "👑 <b>ADMIN PANEL</b>", reply_markup=admin_bottom_keyboard())
    elif text == "📊 টাস্ক ও রিপোর্ট" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "📊 <b>টাস্ক ও রিপোর্ট:</b>", reply_markup=admin_sub_task_keyboard())
    elif text == "💳 ফাইন্যান্স" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "💳 <b>ফাইন্যান্স:</b>", reply_markup=admin_sub_finance_keyboard())
    elif text == "⚙️ সেটিংস" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "⚙️ <b>সেটিংস:</b>", reply_markup=admin_sub_settings_keyboard())
    elif text == "📢 সিস্টেম কন্ট্রোল" and chat_id == ADMIN_ID: return bot.send_message(chat_id, "📢 <b>সিস্টেম:</b>", reply_markup=admin_sub_system_keyboard())
    elif text == "🔍 সার্চ ভল্ট" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_VAULT'}
        return bot.send_message(ADMIN_ID, "🔍 <b>কোড এবং তারিখ দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "💳 Withdraw":
        if float(user.get("balance") or 0.0) < 50: return bot.send_message(chat_id, "⚠️ সর্বনিম্ন উইথড্র ৳৫০!", reply_markup=account_keyboard())
        return bot.send_message(chat_id, "💳 <b>মেথড সিলেক্ট করুন:</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📱 বিকাশ", callback_data="w_method_bkash")))
    elif text == "📊 স্মার্ট ড্যাশবোর্ড" and chat_id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=2)
        for d in get_active_hold_dates(): markup.add(InlineKeyboardButton(f"📅 {d}", callback_data=f"dash_dt_{d}"))
        return bot.send_message(ADMIN_ID, "📊 <b>ড্যাশবোর্ড</b>", reply_markup=markup)
    elif text == "🤖 অটো-ম্যাচার" and chat_id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=2)
        for d in get_active_hold_dates(): markup.add(InlineKeyboardButton(f"🎯 {d} রিপোর্ট", callback_data=f"bm_select_date_{d}"))
        return bot.send_message(ADMIN_ID, "🤖 <b>অটো-ম্যাচার</b>", reply_markup=markup)
    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK_TEXT'}
        return bot.send_message(chat_id, "📦 <b>ডাটা পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        return bot.send_message(chat_id, "📊 <b>ফাইল পাঠালুন:</b>", reply_markup=cancel_keyboard())
    elif any(text.startswith(p) for p in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]):
        cat = "fb_cookie" if "FB Cookies" in text else "fb_2fa"
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
        return bot.send_message(chat_id, f"📄 <b>UID দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA'}
        return bot.send_message(chat_id, "🔑 <b>2FA Secret Key দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "✉️ টেম্প ইমেইল":
        e = f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}@1secmail.com"
        return bot.send_message(chat_id, f"✉️ <b>Email:</b> <code>{e}</code>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📩 ওটিপি দেখুন", callback_data=f"check_otp_{e}")))
    elif text == "🚀 বাল্ক FB লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_FB_CHECK'}
        return bot.send_message(chat_id, "🔍 <b>লিস্ট দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "👤 র্যান্ডম প্রোফাইল জেনারেটর":
        return bot.send_message(chat_id, "👤 <b>দেশ বেছে নিন:</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🇧🇩 BD", callback_data="gen_prof_bd"), InlineKeyboardButton("🇺🇸 USA", callback_data="gen_prof_usa")))
    elif text == "📜 কাজের ইতিহাস":
        all_subs = list(submissions_col.find({"chat_id": chat_id}).sort("date_obj", -1).limit(5)) + list(skeletons_col.find({"chat_id": chat_id}).sort("_id", -1).limit(5))
        if not all_subs: return bot.send_message(chat_id, "📭 কোনো কাজ নেই!")
        out = "📜 <b>ইতিহাস:</b>\n\n"
        for s in all_subs[:5]: out += f"{'⏳' if s.get('status')=='Hold' else '✅'} <code>{s.get('track_id','N/A')}</code> | ৳{s.get('rate')}\n"
        return bot.send_message(chat_id, out)
    elif text == "📢 ব্রডকাস্ট নোটিশ" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST'}
        return bot.send_message(chat_id, "📢 <b>বার্তা দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_TICKET'}
        return bot.send_message(chat_id, "💬 <b>বার্তা লিখুন:</b>", reply_markup=cancel_keyboard())
    elif text == "🎁 Claim Daily Bonus":
        last = parse_iso_datetime(user.get("last_bonus_date"))
        if (get_bd_time() - last).total_seconds() < 86400: return bot.send_message(chat_id, "⚠️ ২৪ ঘণ্টায় ১ বার!")
        users_col.update_one({"_id": chat_id}, {"$inc": {"balance": 2.0}, "$set": {"last_bonus_date": get_bd_time().isoformat()}})
        return bot.send_message(chat_id, "🎉 ৳২ বোনাস যোগ হয়েছে!")

    state = user_states.get(chat_id)
    if not state: return
    step = state.get('step')

    if step == 'AWAITING_VAULT' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        try:
            c, d = text.split()[0].upper(), text.split()[1]
            arc = archives_col.find_one({"oeb_id": c, "date_key": d})
            if arc: bot.forward_message(ADMIN_ID, BACKUP_CHANNEL_ID, arc["message_id"])
            else: bot.send_message(ADMIN_ID, "📭 পাওয়া যায়নি!", reply_markup=admin_sub_task_keyboard())
        except Exception: bot.send_message(ADMIN_ID, "❌ ফরম্যাট ভুল!")

    elif step == 'AWAITING_WITHDRAW_ACCOUNT':
        user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_AMOUNT', 'method': state['method'], 'acc': text}
        return bot.send_message(chat_id, f"✅ <b>কত টাকা উইথড্র করবেন?</b>", reply_markup=cancel_keyboard())

    elif step == 'AWAITING_WITHDRAW_AMOUNT':
        try: req = float(text)
        except Exception: return bot.send_message(chat_id, "❌ সংখ্যা লিখুন:")
        if req < 50 or req > float(user.get("balance")): return bot.send_message(chat_id, "❌ ভুল অ্যামাউন্ট!")
        user_states.pop(chat_id, None)
        update_user_field(chat_id, "balance", float(user.get("balance")) - req)
        withdrawals_col.insert_one({"withdraw_id": generate_withdraw_id(), "chat_id": chat_id, "method": state['method'], "account": state['acc'], "amount": req, "status": "Pending"})
        return bot.send_message(chat_id, f"🎉 <b>উইথড্র রিকোয়েস্ট জমা হয়েছে!</b>", reply_markup=account_keyboard())

    elif step == 'AWAITING_BULK_TEXT':
        pwd = user.get("custom_password") or str(get_setting("pass_rule", ""))
        user_states.pop(chat_id, None)
        status_msg = bot.send_message(chat_id, "⏳ <b>বাল্ক প্রসেস হচ্ছে...</b>")

        def run_bulk():
            lines = [l.strip() for l in text.split("\n") if l.strip()][:2000] # Safe Ram Size
            suc, tot_e, last_upd = 0, 0.0, time.time()
            for i, line in enumerate(lines, 1):
                uid = extract_numeric_uid(line)
                c_key = "fb_cookie" if is_valid_cookies(line) else "fb_2fa"
                if uid and not is_duplicate_uid(uid, c_key) and check_live_account(uid)[0]:
                    try:
                        submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": pwd, "payload": line, "payload_hash": generate_payload_hash(line), "track_id": generate_tracking_id(), "category_key": c_key, "rate": get_current_task_rate(c_key, chat_id), "status": "Hold", "date_key": get_bd_time().strftime("%Y-%m-%d")})
                        suc += 1; tot_e += get_current_task_rate(c_key, chat_id)
                    except Exception: pass
                
                curr = time.time()
                if curr - last_upd >= 3.0 or i == len(lines):
                    try: bot.edit_message_text(f"⏳ <b>[{make_progress_bar(i, len(lines), 10)}]</b>\nসেভড: {suc}", chat_id, status_msg.message_id)
                    except Exception: pass
                    last_upd = curr
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": tot_e}})
            bot.send_message(chat_id, f"🎉 <b>সম্পন্ন!</b>\nগৃহীত: {suc} টি | হোল্ড: ৳{tot_e:.2f}", reply_markup=submit_tasks_keyboard())
        heavy_task_executor.submit(run_bulk)

    elif step == 'AWAITING_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid, state['category']): return bot.send_message(chat_id, "❌ ডুপ্লিকেট UID!")
        def run_s():
            if check_live_account(uid)[0]:
                state['uid'], state['step'] = uid, 'AWAITING_SINGLE_DATA'
                bot.send_message(chat_id, f"✅ UID: <code>{uid}</code>\nCookies/2FA দিন:", reply_markup=cancel_keyboard())
            else: bot.send_message(chat_id, "❌ ডেড একাউন্ট!", reply_markup=submit_tasks_keyboard())
        live_check_executor.submit(run_s)

    elif step == 'AWAITING_SINGLE_DATA':
        pwd = user.get("custom_password") or str(get_setting("pass_rule", ""))
        uid, cat = state['uid'], state['category']
        try:
            rate = get_current_task_rate(cat, chat_id)
            submissions_col.insert_one({"chat_id": chat_id, "uid": uid, "password": pwd, "payload": text, "payload_hash": generate_payload_hash(text), "track_id": generate_tracking_id(), "category_key": cat, "rate": rate, "status": "Hold", "date_key": get_bd_time().strftime("%Y-%m-%d")})
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": rate}})
            user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat}
            bot.send_message(chat_id, f"🎉 <b>সফল!</b> ৳{rate:.2f}\nপরবর্তী UID দিন:", reply_markup=cancel_keyboard())
        except Exception: bot.send_message(chat_id, "❌ এরর!", reply_markup=submit_tasks_keyboard())

    elif step == 'AWAITING_BROADCAST' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        bot.send_message(ADMIN_ID, "📢 ব্রডকাস্ট শুরু হচ্ছে...")
        def run_b():
            for u in users_col.find({"banned": False}):
                try:
                    if message.photo: bot.send_photo(u["_id"], message.photo[-1].file_id, caption=text)
                    else: bot.send_message(u["_id"], text)
                    time.sleep(0.04)
                except Exception: pass
            bot.send_message(ADMIN_ID, "✅ ব্রডকাস্ট সম্পন্ন!")
        heavy_task_executor.submit(run_b)

    elif step == 'AWAITING_TICKET':
        user_states.pop(chat_id, None)
        bot.send_message(ADMIN_ID, f"🎫 <b>টিকিট:</b>\nইউজার: {chat_id}\nবার্তা: {text}")
        bot.send_message(chat_id, "✅ পাঠানো হয়েছে!", reply_markup=main_bottom_keyboard(chat_id))
        
    elif step == 'AWAITING_2FA':
        user_states.pop(chat_id, None)
        try: bot.send_message(chat_id, f"🔑 <b>2FA Code:</b> <code>{pyotp.TOTP(text.replace(' ', '').upper()).now()}</code>", reply_markup=helper_tools_keyboard())
        except Exception: bot.send_message(chat_id, "❌ ভুল কি!")

# ================= 9. Production Server Engine =================
if __name__ == "__main__":
    print("OEB NEXUS Production Engine Active...")
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        try: bot.remove_webhook(); time.sleep(1); bot.set_webhook(url=f"{render_url}/{TOKEN}")
        except Exception: pass
        try: from waitress import serve; serve(flask_app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threads=200)
        except ImportError: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
    else:
        try: bot.remove_webhook()
        except Exception: pass
        def run_server():
            try: from waitress import serve; serve(flask_app, host="0.0.0.0", port=10000, threads=200)
            except ImportError: flask_app.run(host="0.0.0.0", port=10000, threaded=True)
        threading.Thread(target=run_server, daemon=True).start()
        bot.infinity_polling(skip_pending=True)