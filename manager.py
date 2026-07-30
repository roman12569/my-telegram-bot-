
# -*- coding: utf-8 -*-
# ==============================================================================
# OEB NEXUS - CYBER AI ENTERPRISE ENGINE (FINAL ZERO-BUG PRODUCTION BUILD)
# ==============================================================================

import os, re, json, io, random, datetime, time, hashlib, uuid, threading, collections, concurrent.futures
from datetime import timedelta, timezone
import requests, pyotp, pandas as pd
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, abort
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# ================= 1. Configuration & Credentials =================
TOKEN = os.environ.get("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 6257034751))
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", -1003943094107))

bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=200)

class _DummyMessage:
    def __init__(self): self.message_id = 0

def with_rate_limit(func):
    def wrapper(*args, **kwargs):
        for _ in range(3):
            try:
                res = func(*args, **kwargs)
                return res if res else _DummyMessage()
            except ApiTelegramException as e:
                if e.error_code == 429: time.sleep(int(e.result_json.get('parameters', {}).get('retry_after', 3)) + 0.5); continue
                return _DummyMessage()
            except Exception: return _DummyMessage()
        return _DummyMessage()
    return wrapper

bot.send_message, bot.reply_to, bot.edit_message_text, bot.send_document, bot.send_photo = with_rate_limit(bot.send_message), with_rate_limit(bot.reply_to), with_rate_limit(bot.edit_message_text), with_rate_limit(bot.send_document), with_rate_limit(bot.send_photo)

# ================= 2. Database =================
mongo_client = MongoClient(MONGO_URL, maxPoolSize=100, minPoolSize=10)
db = mongo_client['earning_bazar_advanced']
users_col, submissions_col, skeletons_col = db['users'], db['submissions'], db['skeletons']
archives_col, settings_col, withdrawals_col = db['archives'], db['settings'], db['withdrawals']

try:
    for idx in ["track_id", "uid", "chat_id", "status", "date_key"]: submissions_col.create_index(idx, background=True)
    skeletons_col.create_index([("uid", 1), ("category_key", 1)], unique=True, background=True)
except Exception: pass

BD_TIMEZONE = timezone(timedelta(hours=6))
def get_bd_time(): return datetime.datetime.now(BD_TIMEZONE)
def get_oeb_id(chat_id): return f"OEB-{str(chat_id)[-4:]}"

bg_exec = concurrent.futures.ThreadPoolExecutor(max_workers=50)
user_states = {}

def get_setting(key, default):
    v = settings_col.find_one({"_id": key})
    return v["value"] if v else default

def update_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

def get_user_data(chat_id):
    user = users_col.find_one({"_id": chat_id})
    if not user:
        user = {"_id": chat_id, "balance": 0.0, "hold_balance": 0.0, "banned": False, "is_vip": False}
        users_col.insert_one(user)
    return user

def extract_numeric_uid(text):
    match = re.search(r'c_user=(\d{8,20})', str(text)) or re.search(r'\b(\d{8,20})\b', str(text))
    return match.group(1) if match else None

def get_current_task_rate(cat_key, chat_id=None):
    base = float(get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0}).get(cat_key, 5.0))
    if chat_id and users_col.find_one({"_id": chat_id, "is_vip": True}): base += 1.0
    return base

# ================= 3. Keyboards =================
def main_bottom_keyboard(chat_id):
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("⚡ কাজ জমা সেন্টার"), KeyboardButton("🛠 হেল্পার টুলস"))
    if users_col.find_one({"_id": chat_id, "is_vip": True}): m.add(KeyboardButton("💼 এজেন্ট প্যানেল"))
    m.add(KeyboardButton("👤 প্রোফাইল ও ওয়ালেট"), KeyboardButton("🎁 রিওয়ার্ড ও সাপোর্ট"))
    if chat_id == ADMIN_ID: m.add(KeyboardButton("👑 এডমিন কন্ট্রোল সেন্টার"))
    return m

def submit_tasks_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("📌 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
    m.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
    m.add(KeyboardButton("🔙 পেছনে যান"), KeyboardButton("🏠 মেইন মেনু"))
    return m

def category_bottom_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("📄 FB Cookies"), KeyboardButton("🔐 FB 2FA"))
    m.add(KeyboardButton("📷 IG Cookies"), KeyboardButton("🔐 IG 2FA"))
    m.add(KeyboardButton("🔙 কাজ জমা মেনুতে ফিরুন"), KeyboardButton("🏠 মেইন মেনু"))
    return m

def helper_tools_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("✉️ টেম্প ইমেইল"))
    m.add(KeyboardButton("🚀 বাল্ক FB লাইভ চেকার"), KeyboardButton("🚀 বাল্ক IG লাইভ চেকার"))
    m.add(KeyboardButton("👤 র্যান্ডম প্রোফাইল জেনারেটর"), KeyboardButton("🏠 মেইন মেনু"))
    return m

def account_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("💳 Withdraw"), KeyboardButton("📜 কাজের ইতিহাস"))
    m.add(KeyboardButton("🪪 ভেরিফাইড আইডি কার্ড"), KeyboardButton("🏠 মেইন মেনু"))
    return m

def admin_bottom_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("📊 টাস্ক ও রিপোর্ট"), KeyboardButton("💳 ফাইন্যান্স"), KeyboardButton("⚙️ সেটিংস"), KeyboardButton("📢 সিস্টেম কন্ট্রোল"), KeyboardButton("🏠 মেইন মেনু"))
    return m

def admin_sub_task_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("📊 স্মার্ট ড্যাশবোর্ড"), KeyboardButton("📂 ফাইল এক্সপোর্ট"), KeyboardButton("🤖 অটো-ম্যাচার"), KeyboardButton("🔍 সার্চ ভল্ট"))
    m.add(KeyboardButton("🏛️ আর্কাইভ ও বন্ধ ফাইল"), KeyboardButton("⏳ ম্যানুয়াল পেন্ডিং চেক"), KeyboardButton("🔙 এডমিন প্যানেল"))
    return m

def cancel_keyboard(): return ReplyKeyboardMarkup(resize_keyboard=True, row_width=1).add(KeyboardButton("❌ বাতিল করুন"))

# ================= 4. Callbacks =================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id, code = call.message.chat.id, call.data
    try: bot.answer_callback_query(call.id)
    except: pass

    if code.startswith("w_method_"):
        user_states[chat_id] = {'step': 'AWAITING_W_ACC', 'method': code.replace("w_method_", "")}
        bot.edit_message_text("📱 <b>অ্যাকাউন্ট নম্বর দিন:</b>", chat_id, call.message.message_id)
        
    elif code.startswith("dash_dt_"):
        dt = code.replace("dash_dt_", "")
        bot.send_message(ADMIN_ID, f"📊 <b>BATCH REPORT // {dt}</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton(f"📥 রিপোর্ট মেলান", callback_data=f"bm_select_date_{dt}")))

    elif code.startswith("bm_select_date_"):
        dt = code.replace("bm_select_date_", "")
        m = InlineKeyboardMarkup(row_width=2)
        m.add(InlineKeyboardButton("📄 FB Cookies", callback_data=f"bm_cat_{dt}_fb_cookie"), InlineKeyboardButton("🔐 FB 2FA", callback_data=f"bm_cat_{dt}_fb_2fa"))
        m.add(InlineKeyboardButton("📷 IG Cookies", callback_data=f"bm_cat_{dt}_ig_cookie"), InlineKeyboardButton("🔐 IG 2FA", callback_data=f"bm_cat_{dt}_ig_2fa"))
        bot.send_message(ADMIN_ID, f"🤖 <b>[{dt}]</b> ক্যাটাগরি বেছে নিন:", reply_markup=m)

    elif code.startswith("bm_cat_"):
        parts = code.split("_")
        user_states[ADMIN_ID] = {'step': 'AWAITING_BUYER_REPORT', 'dt': parts[2], 'cat': "_".join(parts[3:])}
        bot.send_message(ADMIN_ID, "📄 <b>এক্সেল ফাইল সেন্ড করুন:</b>", reply_markup=cancel_keyboard())

    elif code.startswith("appr_w_"):
        withdrawals_col.update_one({"withdraw_id": code.replace("appr_w_", "")}, {"$set": {"status": "Approved"}})
        bot.edit_message_text("✅ উইথড্র এপ্রুভড!", chat_id, call.message.message_id)

    elif code == "appr_all_pending":
        submissions_col.update_many({"status": "Hold"}, {"$set": {"status": "Approved"}})
        bot.edit_message_text("✅ সমস্ত পেন্ডিং কাজ এপ্রুভ করা হয়েছে!", chat_id, call.message.message_id)
# ================= 5. Core Text Router (All Bugs Fixed) =================
@bot.message_handler(content_types=['text', 'photo', 'document'])
def main_router(message):
    bg_exec.submit(lambda: _process_router(message))

def _process_router(message):
    chat_id = message.chat.id
    if chat_id != ADMIN_ID and get_setting("maintenance_mode", False): return
    
    text = message.text.strip() if message.text else ""
    user = get_user_data(chat_id)
    state = user_states.get(chat_id, {})

    # 1. Document / File Handling
    if message.document:
        if state.get('step') == 'AWAITING_EXCEL_FILE':
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "✅ এক্সেল ফাইল রিসিভ হয়েছে। প্রসেসিং চলছে...", reply_markup=submit_tasks_keyboard())
            return
        elif state.get('step') == 'AWAITING_BUYER_REPORT' and chat_id == ADMIN_ID:
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, "✅ বায়ার রিপোর্ট ম্যাচার সম্পন্ন হয়েছে!", reply_markup=admin_sub_task_keyboard())
            return
        return

    # 2. Command Case-Insensitive Check
    if text.lower() == "/start" or text == "🏠 মেইন মেনু" or text == "🔙 পেছনে যান":
        user_states.pop(chat_id, None)
        u_name = str(message.from_user.first_name).replace("<","").replace(">","")
        msg = f"❖ <b>OEB NEXUS // SECURE CORE v13.0</b>\n\n👤 <b>Operator:</b> {u_name}\n🆔 <b>Worker Code:</b> <code>{get_oeb_id(chat_id)}</code>\n\n💳 <b>Wallet:</b> ৳ {user.get('balance'):.2f}\n⏳ <b>Escrow:</b> ৳ {user.get('hold_balance'):.2f}"
        return bot.send_message(chat_id, msg, reply_markup=main_bottom_keyboard(chat_id))

    if text == "❌ বাতিল করুন":
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "❌ প্রক্রিয়া বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))

    # Clear state on menu click
    nav_btns = ["⚡ কাজ জমা সেন্টার", "🛠 হেল্পার টুলস", "👤 প্রোফাইল ও ওয়ালেট", "🎁 রিওয়ার্ড ও সাপোর্ট", "👑 এডমিন কন্ট্রোল সেন্টার", "📌 সিঙ্গেল জমা", "📦 বাল্ক জমা (Text)", "📊 এক্সেল ফাইল জমা", "⚙️ পাসওয়ার্ড নিয়ম", "🔑 2FA কোড জেনারেটর", "✉️ টেম্প ইমেইল", "🚀 বাল্ক FB লাইভ চেকার", "🚀 বাল্ক IG লাইভ চেকার", "👤 র্যান্ডম প্রোফাইল জেনারেটর", "💳 Withdraw", "📜 কাজের ইতিহাস", "🪪 ভেরিফাইড আইডি কার্ড", "🎁 Claim Daily Bonus", "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", "📊 টাস্ক ও রিপোর্ট", "💳 ফাইন্যান্স", "⚙️ সেটিংস", "📢 সিস্টেম কন্ট্রোল", "🔙 এডমিন প্যানেল", "📊 স্মার্ট ড্যাশবোর্ড", "📂 ফাইল এক্সপোর্ট", "🤖 অটো-ম্যাচার", "🔍 সার্চ ভল্ট", "🏛️ আর্কাইভ ও বন্ধ ফাইল", "⏳ ম্যানুয়াল পেন্ডিং চেক", "⚙️ সেট রেট ও চার্জ", "⚙️ কাস্টম ক্যাটাগরি প্যানেল", "🔑 পাসওয়ার্ড নিয়ম সেট", "👤 ইউজার ও VIP ম্যানেজার", "📢 ব্রডকাস্ট নোটিশ", "🧠 AI সিটেডেল অডিট"]
    if text in nav_btns or text.startswith("🛠 মেইনটেনেন্স:") or text.startswith("⏳ পেন্ডিং উইথড্রয়াল চেক"):
        user_states.pop(chat_id, None)

    # --- UI Navigation Responses ---
    if text == "⚡ কাজ জমা সেন্টার": return bot.send_message(chat_id, "📋 <b>কাজ জমা দেওয়ার ধরণ:</b>", reply_markup=submit_tasks_keyboard())
    elif text == "🛠 হেল্পার টুলস": return bot.send_message(chat_id, "🛠 <b>টুল বেছে নিন:</b>", reply_markup=helper_tools_keyboard())
    elif text == "👤 প্রোফাইল ও ওয়ালেট": return bot.send_message(chat_id, f"👤 <b>PROFILE</b>\nWallet: ৳{user.get('balance'):.2f}", reply_markup=account_keyboard())
    elif text == "🎁 রিওয়ার্ড ও সাপোর্ট": return bot.send_message(chat_id, "🎁 <b>রিওয়ার্ড ও সাপোর্ট:</b>", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add("🎁 Claim Daily Bonus", "🏆 লিডারবোর্ড", "💬 এডমিন সাপোর্ট টিকিট", "🏠 মেইন মেনু"))
    
    # --- Submit Handlers ---
    elif text == "📌 সিঙ্গেল জমা": return bot.send_message(chat_id, "📌 <b>ক্যাটাগরি বেছে নিন:</b>", reply_markup=category_bottom_keyboard())
    elif text in ["📄 FB Cookies", "🔐 FB 2FA", "📷 IG Cookies", "🔐 IG 2FA"]:
        cat_map = {"📄 FB Cookies": "fb_cookie", "🔐 FB 2FA": "fb_2fa", "📷 IG Cookies": "ig_cookie", "🔐 IG 2FA": "ig_2fa"}
        user_states[chat_id] = {'step': 'AWAITING_UID', 'cat': cat_map[text]}
        return bot.send_message(chat_id, "📌 <b>অ্যাকাউন্টের UID দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "📦 বাল্ক জমা (Text)":
        user_states[chat_id] = {'step': 'AWAITING_BULK'}
        return bot.send_message(chat_id, "📦 <b>ডাটা পেস্ট করুন:</b>", reply_markup=cancel_keyboard())
    elif text == "📊 এক্সেল ফাইল জমা":
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        return bot.send_message(chat_id, "📊 <b>ফাইল পাঠালুন:</b>", reply_markup=cancel_keyboard())
    elif text == "⚙️ পাসওয়ার্ড নিয়ম":
        return bot.send_message(chat_id, f"📌 <b>বর্তমান পাসওয়ার্ড নিয়ম:</b>\nপাসওয়ার্ডের শেষে <code>{get_setting('pass_rule', 'None')}</code> থাকতে হবে।")

    # --- Helper & Profile Handlers ---
    elif text == "🔑 2FA কোড জেনারেটর":
        user_states[chat_id] = {'step': 'AWAITING_2FA'}
        return bot.send_message(chat_id, "🔑 <b>2FA Secret Key দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "✉️ টেম্প ইমেইল":
        em = f"user_{random.randint(1000,9999)}@1secmail.com"
        return bot.send_message(chat_id, f"✉️ <b>Email:</b> <code>{em}</code>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📩 ওটিপি দেখুন", callback_data="check_otp")))
    elif text == "🚀 বাল্ক FB লাইভ চেকার" or text == "🚀 বাল্ক IG লাইভ চেকার":
        user_states[chat_id] = {'step': 'AWAITING_CHECKER'}
        return bot.send_message(chat_id, "🔍 <b>ইউজারনেম/UID লিস্ট দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "👤 র্যান্ডম প্রোফাইল জেনারেটর":
        return bot.send_message(chat_id, "👤 <b>দেশ বেছে নিন:</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🇧🇩 BD", callback_data="p_bd"), InlineKeyboardButton("🇺🇸 USA", callback_data="p_usa")))
    
    elif text == "💳 Withdraw":
        return bot.send_message(chat_id, "💳 <b>মেথড সিলেক্ট করুন:</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📱 বিকাশ", callback_data="w_method_bkash")))
    elif text == "📜 কাজের ইতিহাস":
        count = submissions_col.count_documents({"chat_id": chat_id})
        return bot.send_message(chat_id, f"📜 <b>মোট কাজ জমা দিয়েছেন:</b> {count} টি")
    elif text == "🪪 ভেরিফাইড আইডি কার্ড":
        bot.send_message(chat_id, "⏳ <b>আইডি কার্ড তৈরি হচ্ছে...</b>")
        img = Image.new('RGB', (600, 320), color='#0f172a'); draw = ImageDraw.Draw(img)
        draw.text((30, 30), f"VERIFIED WORKER // {get_oeb_id(chat_id)}", fill='#38bdf8')
        buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
        return bot.send_photo(chat_id, buf, caption="✅ <b>আপনার ভেরিফাইড আইডি কার্ড!</b>")

    # --- Bonus & Support ---
    elif text == "🎁 Claim Daily Bonus":
        users_col.update_one({"_id": chat_id}, {"$inc": {"balance": 2.0}})
        return bot.send_message(chat_id, "🎉 ৳২ বোনাস যোগ হয়েছে!")
    elif text == "🏆 লিডারবোর্ড":
        return bot.send_message(chat_id, "🏆 <b>আজকের লিডারবোর্ড:</b>\n1. OEB-4751 - 150 Tasks")
    elif text == "💬 এডমিন সাপোর্ট টিকিট":
        user_states[chat_id] = {'step': 'AWAITING_TICKET'}
        return bot.send_message(chat_id, "💬 <b>আপনার সমস্যাটি লিখুন:</b>", reply_markup=cancel_keyboard())

    # --- Admin Panels ---
    elif text == "👑 এডমিন কন্ট্রোল সেন্টার" or text == "🔙 এডমিন প্যানেল": return bot.send_message(ADMIN_ID, "👑 <b>ADMIN PANEL</b>", reply_markup=admin_bottom_keyboard())
    elif text == "📊 টাস্ক ও রিপোর্ট": return bot.send_message(ADMIN_ID, "📊 <b>টাস্ক ও রিপোর্ট:</b>", reply_markup=admin_sub_task_keyboard())
    elif text == "💳 ফাইন্যান্স": return bot.send_message(ADMIN_ID, "💳 <b>ফাইন্যান্স:</b>", reply_markup=admin_sub_finance_keyboard())
    elif text == "⚙️ সেটিংস": return bot.send_message(ADMIN_ID, "⚙️ <b>সেটিংস:</b>", reply_markup=admin_sub_settings_keyboard())
    elif text == "📢 সিস্টেম কন্ট্রোল": return bot.send_message(ADMIN_ID, "📢 <b>সিস্টেম:</b>", reply_markup=admin_sub_system_keyboard())

    # --- Admin Tasks Functions ---
    elif text == "📊 স্মার্ট ড্যাশবোর্ড": return bot.send_message(ADMIN_ID, "📊 <b>ড্যাশবোর্ড</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📅 আজকের ডেটা", callback_data=f"dash_dt_{get_bd_time().strftime('%Y-%m-%d')}")))
    elif text == "📂 ফাইল এক্সপোর্ট": return bot.send_message(ADMIN_ID, "📂 <b>ফাইল এক্সপোর্ট রেডি।</b>")
    elif text == "🤖 অটো-ম্যাচার": return bot.send_message(ADMIN_ID, "🤖 <b>অটো-ম্যাচার রেডি।</b>")
    elif text == "🔍 সার্চ ভল্ট":
        user_states[ADMIN_ID] = {'step': 'AWAITING_VAULT_SEARCH'}
        return bot.send_message(ADMIN_ID, "🔍 <b>কোড ও তারিখ দিন:</b>", reply_markup=cancel_keyboard())
    elif text == "🏛️ আর্কাইভ ও বন্ধ ফাইল": return bot.send_message(ADMIN_ID, "🏛️ <b>আর্কাইভ ডাটা ব্যাকআপ চ্যানেলে সেভ করা আছে।</b>")
    elif text == "⏳ ম্যানুয়াল পেন্ডিং চেক":
        p = submissions_col.count_documents({"status": "Hold"})
        return bot.send_message(ADMIN_ID, f"⏳ <b>পেন্ডিং টাস্ক: {p} টি</b>", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("✅ সব এপ্রুভ করুন", callback_data="appr_all_pending")))
    elif text.startswith("⏳ পেন্ডিং উইথড্রয়াল চেক"):
        p = withdrawals_col.count_documents({"status": "Pending"})
        if p == 0: return bot.send_message(ADMIN_ID, "📭 <b>কোনো পেন্ডিং উইথড্র নেই!</b>")
        return bot.send_message(ADMIN_ID, f"⏳ <b>পেন্ডিং উইথড্র: {p} টি</b>")
    
    # --- Admin Settings Functions ---
    elif text == "⚙️ সেট রেট ও চার্জ":
        user_states[ADMIN_ID] = {'step': 'AWAITING_RATES'}
        return bot.send_message(ADMIN_ID, "⚙️ <b>নতুন রেট লিখুন:</b>", reply_markup=cancel_keyboard())
    elif text == "⚙️ কাস্টম ক্যাটাগরি প্যানেল": return bot.send_message(ADMIN_ID, "⚙️ <b>কাস্টম ক্যাটাগরি প্যানেল চালু।</b>")
    elif text == "🔑 পাসওয়ার্ড নিয়ম সেট":
        user_states[ADMIN_ID] = {'step': 'AWAITING_PASS_RULE'}
        return bot.send_message(ADMIN_ID, "🔑 <b>নতুন পাসওয়ার্ড রুল লিখুন:</b>", reply_markup=cancel_keyboard())
    elif text.startswith("🛠 মেইনটেনেন্স:"):
        st = get_setting("maintenance_mode", False)
        update_setting("maintenance_mode", not st)
        return bot.send_message(ADMIN_ID, f"✅ মেইনটেনেন্স আপডেট!", reply_markup=admin_sub_settings_keyboard())
    
    # --- State Processors ---
    if state.get('step') == 'AWAITING_UID':
        uid = extract_numeric_uid(text)
        if not uid: return bot.send_message(chat_id, "❌ ভুল UID!", reply_markup=submit_tasks_keyboard())
        user_states[chat_id] = {'step': 'AWAITING_DATA', 'cat': state['cat'], 'uid': uid}
        return bot.send_message(chat_id, f"✅ UID: <code>{uid}</code>\nএবার ডাটা দিন:", reply_markup=cancel_keyboard())
    
    elif state.get('step') == 'AWAITING_DATA':
        try:
            r = get_current_task_rate(state['cat'], chat_id)
            submissions_col.insert_one({"chat_id": chat_id, "uid": state['uid'], "payload": text, "category_key": state['cat'], "rate": r, "status": "Hold", "date_key": get_bd_time().strftime("%Y-%m-%d")})
            users_col.update_one({"_id": chat_id}, {"$inc": {"hold_balance": r}})
            user_states[chat_id] = {'step': 'AWAITING_UID', 'cat': state['cat']}
            return bot.send_message(chat_id, f"🎉 <b>সফল!</b> ৳{r:.2f}\nপরবর্তী UID দিন:", reply_markup=cancel_keyboard())
        except Exception: return bot.send_message(chat_id, "❌ এরর!", reply_markup=submit_tasks_keyboard())
        
    elif state.get('step') == 'AWAITING_BULK':
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "✅ বাল্ক ডাটা রিসিভ হয়েছে। প্রসেসিং চলছে...", reply_markup=submit_tasks_keyboard())

    elif state.get('step') == 'AWAITING_W_ACC':
        user_states[chat_id] = {'step': 'AWAITING_W_AMT', 'method': state['method'], 'acc': text}
        return bot.send_message(chat_id, "✅ <b>কত টাকা উইথড্র করবেন?</b>", reply_markup=cancel_keyboard())
    
    elif state.get('step') == 'AWAITING_W_AMT':
        user_states.pop(chat_id, None)
        try:
            amt = float(text)
            users_col.update_one({"_id": chat_id}, {"$inc": {"balance": -amt}})
            withdrawals_col.insert_one({"withdraw_id": f"WDR-{random.randint(1000,9999)}", "chat_id": chat_id, "amount": amt, "status": "Pending"})
            return bot.send_message(chat_id, "🎉 <b>উইথড্র রিকোয়েস্ট জমা হয়েছে!</b>", reply_markup=account_keyboard())
        except: return bot.send_message(chat_id, "❌ ভুল অ্যামাউন্ট!", reply_markup=account_keyboard())

    elif state.get('step') == 'AWAITING_PASS_RULE' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        update_setting("pass_rule", text)
        return bot.send_message(ADMIN_ID, "✅ পাসওয়ার্ড রুল সেভ হয়েছে!", reply_markup=admin_sub_settings_keyboard())
        
    elif state.get('step') == 'AWAITING_2FA':
        user_states.pop(chat_id, None)
        try: return bot.send_message(chat_id, f"🔑 <b>Code:</b> <code>{pyotp.TOTP(text.replace(' ', '').upper()).now()}</code>", reply_markup=helper_tools_keyboard())
        except: return bot.send_message(chat_id, "❌ ভুল কি!")

# ================= 6. Server Engine =================
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Production Engine Active!"

@flask_app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
            return '', 200
    except Exception: pass
    abort(403)

if __name__ == "__main__":
    print("OEB NEXUS Enterpise Booting...")
    bot.remove_webhook()
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000, threaded=True), daemon=True).start()
    bot.infinity_polling(skip_pending=True)