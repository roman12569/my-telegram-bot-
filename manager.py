import os
import re
import csv
import time
import random
import datetime
import threading
import requests
import pyotp
import telebot
import pandas as pd
from flask import Flask
from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pymongo import MongoClient

# ================= 1. Web Server for Render 24/7 =================
app = Flask(__name__)
@app.route('/')
def home():
    return "Enterprise Earning Bazar Bot is Running flawlessly!"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
threading.Thread(target=run_flask).start()

# ================= 2. Configuration =================
TOKEN = 'YOUR_BOT_TOKEN_HERE'  
ADMIN_ID = 123456789  # আপনার অরিজিনাল অ্যাডমিন আইডি দিন        

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_GOOGLE_SHEET_ID_HERE")
CREDENTIALS_FILE = "credentials.json"
MONGO_URL = "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0"

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

# ================= 3. Database Setup =================
client = MongoClient(MONGO_URL)
db = client['earning_bazar_advanced']
users_collection = db['users']
accounts_collection = db['accounts']      
withdrawals_collection = db['withdraws']  

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

RATES = {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0}
single_submit_active, bulk_submit_active = True, True
MAINTENANCE_MODE = False
pass_rule = "20"
MIN_WITHDRAW = 50.0
DAILY_BONUS_AMT = 2.0  # ডেইলি বোনাস ২ টাকা

user_states = {}
user_last_msg_time = {} # Anti-spam check

# ================= 4. Core Helper Functions =================

def get_or_create_user(chat_id, first_name, referrer_id=None):
    user = users_collection.find_one({"_id": chat_id})
    if not user:
        user = {
            "_id": chat_id, "first_name": first_name, "balance": 0.0, 
            "password": f"Pass_{pass_rule}", "language": "en", 
            "is_banned": False, "referred_by": referrer_id, "last_bonus_date": ""
        }
        users_collection.insert_one(user)
        # Add bonus to referrer
        if referrer_id and referrer_id != chat_id:
            users_collection.update_one({"_id": referrer_id}, {"$inc": {"balance": 5.0}}) # রেফার বোনাস ৫ টাকা
            try: bot.send_message(referrer_id, f"🎉 **নতুন রেফারেল!** আপনার লিংকে ক্লিক করে একজন জয়েন করেছে। আপনি **৳৫.০০** বোনাস পেয়েছেন!")
            except: pass
    return user

def extract_numeric_uid(text):
    text = str(text).strip()
    if text.isdigit() and 8 <= len(text) <= 20: return text
    match = re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text)
    return match.group(1) if match else None

def is_duplicate_uid(uid): return accounts_collection.find_one({"uid": str(uid)}) is not None

def generate_tracking_id(): return f"#SUB-{random.randint(10000, 99999)}"

# ================= 5. Keyboard Layouts =================

def main_bottom_keyboard(chat_id, lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'en':
        markup.add(KeyboardButton("⚡ ID Submission"), KeyboardButton("🛠️ Helper Tools"))
        markup.add(KeyboardButton("👤 My Profile"), KeyboardButton("🏆 Leaderboard"))
        markup.add(KeyboardButton("🎁 Daily Bonus"), KeyboardButton("🔗 Invite Friends"))
        if chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 Admin Panel"))
    else:
        markup.add(KeyboardButton("⚡ আইডি সাবমিশন"), KeyboardButton("🛠️ হেল্পার টুলস"))
        markup.add(KeyboardButton("👤 আমার প্রোফাইল"), KeyboardButton("🏆 লিডারবোর্ড"))
        markup.add(KeyboardButton("🎁 ডেইলি বোনাস"), KeyboardButton("🔗 ইনভাইট করুন"))
        if chat_id == ADMIN_ID: markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def submission_bottom_keyboard(chat_id, lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'en':
        markup.add(KeyboardButton("📥 Single Submit"), KeyboardButton("📦 Bulk Submit"))
        markup.add(KeyboardButton("📊 Excel Submit"), KeyboardButton("⚙️ Password Rules"))
        markup.add(KeyboardButton("🔙 Main Menu"))
    else:
        markup.add(KeyboardButton("📥 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা"))
        markup.add(KeyboardButton("📊 এক্সেল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
        markup.add(KeyboardButton("🔙 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m_st = "🔴" if MAINTENANCE_MODE else "🟢"
    markup.add(KeyboardButton("💰 Rate Config"), KeyboardButton(f"{m_st} Maintenance Mode"))
    markup.add(KeyboardButton("💳 Pending Withdraws"), KeyboardButton("📊 Team Stats"))
    markup.add(KeyboardButton("📢 Broadcast"), KeyboardButton("👥 মেম্বার সংখ্যা"))
    markup.add(KeyboardButton("🚫 ব্লক/আনব্লক"), KeyboardButton("🔍 User Search"))
    markup.add(KeyboardButton("🔙 Main Menu"))
    return markup

def cancel_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Cancel" if lang == 'en' else "❌ বাতিল করুন"))
    return markup

# ================= 6. Anti-Spam & Command Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    text_args = message.text.split()
    referrer_id = int(text_args[1]) if len(text_args) > 1 and text_args[1].isdigit() else None
    
    db_user = get_or_create_user(chat_id, message.from_user.first_name, referrer_id)
    if db_user.get("is_banned"): return bot.reply_to(message, "🚫 Your account has been suspended.")
    
    user_states.pop(chat_id, None)
    lang = db_user.get("language", "en")
    bot.send_message(chat_id, "👑 **ONLINE EARNING BAZAR**\nWelcome!", reply_markup=main_bottom_keyboard(chat_id, lang))

# ================= 7. Master Message Router =================

@bot.message_handler(content_types=['text', 'photo', 'document'])
def master_router(message):
    global single_submit_active, bulk_submit_active, pass_rule, MAINTENANCE_MODE
    chat_id = message.chat.id
    
    # Anti-Spam Check (1 msg per 1.5 seconds max)
    now = time.time()
    if chat_id != ADMIN_ID:
        last_time = user_last_msg_time.get(chat_id, 0)
        if now - last_time < 1.5: return # Ignore spam
    user_last_msg_time[chat_id] = now
    
    # Maintenance Check
    if MAINTENANCE_MODE and chat_id != ADMIN_ID:
        return bot.send_message(chat_id, "⚙️ **সার্ভার মেইনটেনেন্স চলছে!**\nকিছুক্ষণ পর আবার চেষ্টা করুন।")

    db_user = get_or_create_user(chat_id, message.from_user.first_name)
    if db_user.get("is_banned"): return bot.send_message(chat_id, "🚫 Account suspended.")
    
    text = message.text.strip() if message.text else ""
    lang = db_user.get("language", "en")
    state = user_states.get(chat_id, {})
    step = state.get('step')

    # Media Broadcast Handling (Admin Only)
    if step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "⏳ Broadcasting... Please wait.")
        count = 0
        for u in users_collection.find({}):
            try:
                if message.photo:
                    bot.send_photo(u["_id"], message.photo[-1].file_id, caption=f"📢 **NOTICE:**\n{message.caption or ''}")
                elif message.document:
                    bot.send_document(u["_id"], message.document.file_id, caption=f"📢 **NOTICE:**\n{message.caption or ''}")
                else:
                    bot.send_message(u["_id"], f"📢 **NOTICE:**\n\n{text}")
                count += 1
            except Exception: pass
        return bot.send_message(chat_id, f"✅ Broadcast sent to {count} users.", reply_markup=admin_bottom_keyboard())

    if not text: return # If they sent a document/photo outside of expected states, ignore.

    # 🔙 Back & Navigation
    if text in ["🔙 Main Menu", "🔙 মেইন মেনু", "❌ Cancel", "❌ বাতিল করুন"]:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "👑 Main Menu:", reply_markup=main_bottom_keyboard(chat_id, lang))

    # 🎁 Daily Bonus
    if text in ["🎁 Daily Bonus", "🎁 ডেইলি বোনাস"]:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if db_user.get("last_bonus_date") == today:
            return bot.send_message(chat_id, "❌ আপনি আজকের বোনাস পেয়ে গেছেন! আগামীকাল আবার চেষ্টা করুন।")
        users_collection.update_one({"_id": chat_id}, {"$set": {"last_bonus_date": today}, "$inc": {"balance": DAILY_BONUS_AMT}})
        return bot.send_message(chat_id, f"🎉 **অভিনন্দন!** আপনি আজকের ডেইলি বোনাস হিসেবে **৳{DAILY_BONUS_AMT}** পেয়েছেন।")

    # 🔗 Invite Friends (Referral)
    if text in ["🔗 Invite Friends", "🔗 ইনভাইট করুন"]:
        bot_uname = bot.get_me().username
        ref_link = f"https://t.me/{bot_uname}?start={chat_id}"
        return bot.send_message(chat_id, f"🔗 **আপনার রেফারেল লিংক:**\n\n`{ref_link}`\n\nপ্রতিটি সফল রেফারেলের জন্য আপনি **৳৫.০০** বোনাস পাবেন!")

    # 👑 ADMIN PANEL ROOT
    if "Admin Panel" in text and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "👑 **ADMIN PANEL**", reply_markup=admin_bottom_keyboard())

    if "Maintenance Mode" in text and chat_id == ADMIN_ID:
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        status = "ON 🔴" if MAINTENANCE_MODE else "OFF 🟢"
        return bot.send_message(chat_id, f"⚙️ Maintenance Mode is now **{status}**", reply_markup=admin_bottom_keyboard())
        
    if "📢 Broadcast" in text and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        return bot.send_message(chat_id, "Send text, photo, or file to broadcast:", reply_markup=cancel_keyboard(lang))

    # Basic Menus (ID Submission, Profile, etc.)
    if "ID Submission" in text or "আইডি সাবমিশন" in text:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "📥 **SUBMISSION CENTER**", reply_markup=submission_bottom_keyboard(chat_id, lang))
        
    if "My Profile" in text or "আমার প্রোফাইল" in text:
        user_states.pop(chat_id, None)
        bal = db_user.get("balance", 0.0)
        total_sub = accounts_collection.count_documents({"worker_id": chat_id})
        msg_str = (f"👤 **Name:** `{message.from_user.first_name}`\n🆔 **ID:** `{chat_id}`\n"
                   f"🔹 **Total Submissions:** `{total_sub}` pcs\n💰 **Current Balance:** `৳{bal:.2f}`")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💳 Withdraw", callback_data="prof_withdraw"))
        return bot.send_message(chat_id, msg_str, reply_markup=markup)

    # State Handling (Single submits, Admin Search, etc.)
    if step == 'AWAITING_SINGLE_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ Invalid or Duplicate UID!")
        user_states[chat_id]['uid'] = uid
        user_states[chat_id]['step'] = 'AWAITING_SINGLE_PAYLOAD'
        return bot.send_message(chat_id, "✅ Valid UID. Now send **Cookies / 2FA**:")

    elif step == 'AWAITING_SINGLE_PAYLOAD':
        uid = state.get('uid')
        password = db_user.get("password", f"Pass_{pass_rule}")
        rate = RATES.get("fb_cookie", 5.0) # Simplified logic for space
        acc_data = {"uid": uid, "worker_id": chat_id, "password": password, "payload": text, "rate": rate, "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        
        accounts_collection.insert_one(acc_data)
        users_collection.update_one({"_id": chat_id}, {"$inc": {"balance": rate}})
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, f"🎉 **SAVED!**\nUID: `{uid}`\n💰 Earned: ৳{rate:.2f}", reply_markup=submission_bottom_keyboard(chat_id, lang))

    if not step:
        bot.send_message(chat_id, "Please select an option:", reply_markup=main_bottom_keyboard(chat_id, lang))

if __name__ == "__main__":
    print("🚀 ENTERPRISE V2 BOT STARTED SUCCESSFULLY...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)