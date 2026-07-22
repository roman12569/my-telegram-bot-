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
TOKEN = '8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4'  
ADMIN_ID = 6257034751         

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1aWntk0eMZt6w7GWmXs_PmckvoDT1uCCRiGUELiV4NKA")
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
DAILY_BONUS_AMT = 2.0  

user_states = {}
user_last_msg_time = {} 

# ================= 4. Core Helper Functions =================

def get_or_create_user(chat_id, first_name, referrer_id=None):
    safe_name = first_name if first_name else "Member" 
    user = users_collection.find_one({"_id": chat_id})
    if not user:
        user = {
            "_id": chat_id, "first_name": safe_name, "balance": 0.0, 
            "password": f"Pass_{pass_rule}", "language": "en", 
            "is_banned": False, "referred_by": referrer_id, "last_bonus_date": ""
        }
        users_collection.insert_one(user)
        if referrer_id and referrer_id != chat_id:
            users_collection.update_one({"_id": referrer_id}, {"$inc": {"balance": 5.0}})
            try: bot.send_message(referrer_id, f"🎉 **নতুন রেফারেল!** আপনার লিংকে ক্লিক করে একজন জয়েন করেছে। আপনি **৳৫.০০** বোনাস পেয়েছেন!")
            except: pass
    return user

def extract_numeric_uid(text):
    text = str(text).strip()
    if text.isdigit() and 8 <= len(text) <= 20: return text
    match = re.search(r'(?:id=|\/|profile\.php\?id=|\/u\/)(\d{8,20})', text)
    return match.group(1) if match else None

def is_duplicate_uid(uid): return accounts_collection.find_one({"uid": str(uid)}) is not None
def is_valid_2fa_key(key_str): return bool(re.match(r'^[A-Z2-7]{16,32}$', str(key_str).replace(" ", "").upper()))
def is_valid_cookies(cookie_str): return any(x in str(cookie_str) for x in ["c_user=", "datr=", "xs=", "sessionid="])
def generate_tracking_id(): return f"#SUB-{random.randint(10000, 99999)}"

# ================= Google Sheets Integration =================
def async_save_to_sheet(tab_name, row_data):
    def task():
        try:
            if not os.path.exists(CREDENTIALS_FILE): return 
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            g_client = gspread.authorize(creds)
            g_client.open_by_key(SPREADSHEET_ID).worksheet(tab_name).append_row(row_data)
        except Exception as e:
            print(f"Sheet Error: {e}")
    threading.Thread(target=task).start()

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

# ================= 6. Check Channels & Commands =================

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            if bot.get_chat_member(ch["username"], user_id).status in ['left', 'kicked']: return False
        except Exception: continue
    return True

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    text_args = message.text.split()
    referrer_id = int(text_args[1]) if len(text_args) > 1 and text_args[1].isdigit() else None
    
    db_user = get_or_create_user(chat_id, message.from_user.first_name, referrer_id)
    if db_user.get("is_banned"): return bot.reply_to(message, "🚫 Your account has been suspended.")
    
    user_states.pop(chat_id, None)
    lang = db_user.get("language", "en")
    
    if not check_force_join(chat_id):
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in REQUIRED_CHANNELS: markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
        markup.add(InlineKeyboardButton("✅ Verify", callback_data="verify_join"))
        return bot.send_message(chat_id, "🔒 **Join our channels first:**", reply_markup=markup)
        
    bot.send_message(chat_id, "👑 **ONLINE EARNING BAZAR**\nWelcome!", reply_markup=main_bottom_keyboard(chat_id, lang))

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)
    db_user = get_or_create_user(chat_id, call.message.chat.first_name)
    lang = db_user.get("language", "en")

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ Success!", reply_markup=main_bottom_keyboard(chat_id, lang))
        else: bot.send_message(chat_id, "❌ Not joined all channels!")
    elif code == "prof_withdraw":
        balance = db_user.get("balance", 0.0)
        if balance < MIN_WITHDRAW: bot.send_message(chat_id, f"⚠️ Min: ৳{MIN_WITHDRAW:.2f}. Bal: ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 Enter Number & Amount (e.g. `01700000000 | 100`):", reply_markup=cancel_keyboard(lang))

# ================= 7. Document / Broadcast Handler =================

@bot.message_handler(content_types=['document', 'photo'])
def document_photo_router(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    step = state.get('step')
    
    if step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "⏳ Broadcasting... Please wait.")
        count = 0
        for u in users_collection.find({}):
            try:
                if message.photo: bot.send_photo(u["_id"], message.photo[-1].file_id, caption=message.caption or '')
                elif message.document: bot.send_document(u["_id"], message.document.file_id, caption=message.caption or '')
                count += 1
            except Exception: pass
        return bot.send_message(chat_id, f"✅ Sent to {count} users.", reply_markup=admin_bottom_keyboard())
        
    if step == 'AWAITING_EXCEL_FILE' and message.document:
        if not bulk_submit_active: return bot.send_message(chat_id, "⚠️ Excel mode disabled.")
        try:
            bot.send_message(chat_id, "⏳ Processing file...")
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            file_name = message.document.file_name
            with open(file_name, 'wb') as new_file: new_file.write(downloaded_file)
            
            df = pd.read_csv(file_name, dtype=str) if file_name.endswith('.csv') else pd.read_excel(file_name, dtype=str)
            success, total_earned = 0, 0.0
            password = get_or_create_user(chat_id, message.from_user.first_name).get("password", f"Pass_{pass_rule}")
            
            for _, row in df.fillna('').iterrows():
                vals = [str(x).strip() for x in row.values]
                if len(vals) >= 3:
                    uid, payload = vals[0], vals[2]
                    clean_uid = extract_numeric_uid(uid)
                    if clean_uid and not is_duplicate_uid(clean_uid):
                        rate = RATES["fb_cookie"] if is_valid_cookies(payload) else RATES["fb_2fa"]
                        cat = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        accounts_collection.insert_one({"uid": clean_uid, "worker_id": chat_id, "password": password, "payload": payload, "category": cat, "rate": rate, "date": now_str})
                        async_save_to_sheet("Sheet1", [now_str, generate_tracking_id(), chat_id, clean_uid, password, payload])
                        
                        success += 1
                        total_earned += rate
                        
            if os.path.exists(file_name): os.remove(file_name)
            users_collection.update_one({"_id": chat_id}, {"$inc": {"balance": total_earned}})
            user_states.pop(chat_id, None)
            bot.reply_to(message, f"🎉 **Processed!**\n✅ Saved: {success} pcs\n💰 Credited: ৳{total_earned:.2f}", reply_markup=submission_bottom_keyboard(chat_id, "en"))
        except Exception as e:
            bot.reply_to(message, f"❌ Format error: {e}")

# ================= 8. Master Text Router =================

@bot.message_handler(content_types=['text'])
def master_text_router(message):
    global single_submit_active, bulk_submit_active, pass_rule, MAINTENANCE_MODE
    chat_id = message.chat.id
    
    now = time.time()
    if chat_id != ADMIN_ID:
        if now - user_last_msg_time.get(chat_id, 0) < 1.5: return 
    user_last_msg_time[chat_id] = now
    
    if MAINTENANCE_MODE and chat_id != ADMIN_ID: return bot.send_message(chat_id, "⚙️ **সার্ভার মেইনটেনেন্স চলছে!**")

    db_user = get_or_create_user(chat_id, message.from_user.first_name)
    if db_user.get("is_banned"): return bot.send_message(chat_id, "🚫 Account suspended.")
    
    text = message.text.strip()
    lang = db_user.get("language", "en")
    state = user_states.get(chat_id, {})
    step = state.get('step')

    if text in ["🔙 Main Menu", "🔙 মেইন মেনু", "❌ Cancel", "❌ বাতিল করুন"]:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "👑 Main Menu:", reply_markup=main_bottom_keyboard(chat_id, lang))

    if text in ["🎁 Daily Bonus", "🎁 ডেইলি বোনাস"]:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if db_user.get("last_bonus_date") == today: return bot.send_message(chat_id, "❌ আপনি আজকের বোনাস পেয়ে গেছেন!")
        users_collection.update_one({"_id": chat_id}, {"$set": {"last_bonus_date": today}, "$inc": {"balance": DAILY_BONUS_AMT}})
        return bot.send_message(chat_id, f"🎉 **অভিনন্দন!** ডেইলি বোনাস **৳{DAILY_BONUS_AMT}** পেয়েছেন।")

    if text in ["🔗 Invite Friends", "🔗 ইনভাইট করুন"]:
        return bot.send_message(chat_id, f"🔗 **আপনার রেফারেল লিংক:**\n`https://t.me/{bot.get_me().username}?start={chat_id}`\n\nপ্রতিটি রেফারে **৳৫.০০** বোনাস!")

    if "ID Submission" in text or "আইডি সাবমিশন" in text:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "📥 **SUBMISSION CENTER**", reply_markup=submission_bottom_keyboard(chat_id, lang))
        
    if "Helper Tools" in text or "হেল্পার টুলস" in text:
        user_states.pop(chat_id, None)
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(KeyboardButton("🔑 2FA Gen"), KeyboardButton("🔍 Link -> UID"), KeyboardButton("🔙 Main Menu"))
        return bot.send_message(chat_id, "🛠️ **TOOLS**", reply_markup=markup)

    if "My Profile" in text or "আমার প্রোফাইল" in text:
        user_states.pop(chat_id, None)
        msg_str = (f"👤 **Name:** `{message.from_user.first_name}`\n🆔 **ID:** `{chat_id}`\n"
                   f"🔹 **Submissions:** `{accounts_collection.count_documents({'worker_id': chat_id})}` pcs\n💰 **Balance:** `৳{db_user.get('balance', 0.0):.2f}`")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💳 Withdraw", callback_data="prof_withdraw"))
        return bot.send_message(chat_id, msg_str, reply_markup=markup)

    if "Admin Panel" in text and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, "👑 **ADMIN PANEL**", reply_markup=admin_bottom_keyboard())

    if "Maintenance Mode" in text and chat_id == ADMIN_ID:
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        return bot.send_message(chat_id, f"⚙️ Maintenance Mode: **{'ON 🔴' if MAINTENANCE_MODE else 'OFF 🟢'}**", reply_markup=admin_bottom_keyboard())
        
    if "📢 Broadcast" in text and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        return bot.send_message(chat_id, "Send message to broadcast:", reply_markup=cancel_keyboard(lang))

    if text == "👥 মেম্বার সংখ্যা" and chat_id == ADMIN_ID:
        return bot.send_message(chat_id, f"👥 **Total Members:** {users_collection.count_documents({})}")

    if text == "💳 Pending Withdraws" and chat_id == ADMIN_ID:
        pendings = withdrawals_collection.find({"status": "pending"})
        msg = "💳 **PENDING WITHDRAWALS:**\n\n"
        for p in pendings: msg += f"👤 {p['name']} (`{p['user_id']}`)\n💰 `৳{p['amount']}` | Num: `{p['number']}`\n\n"
        if msg == "💳 **PENDING WITHDRAWALS:**\n\n": msg += "No pending requests."
        return bot.send_message(chat_id, msg)

    if step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        count = 0
        for u in users_collection.find({}):
            try:
                bot.send_message(u["_id"], f"📢 **NOTICE:**\n\n{text}")
                count += 1
            except Exception: pass
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, f"✅ Broadcast sent to {count} users.", reply_markup=admin_bottom_keyboard())

    if step == 'AWAITING_WITHDRAW_DETAILS':
        parts = [p.strip() for p in text.split("|")]
        current_bal = db_user.get("balance", 0.0)
        if len(parts) == 2 and parts[1].replace(".", "", 1).isdigit():
            num, amt = parts[0], float(parts[1])
            if MIN_WITHDRAW <= amt <= current_bal:
                users_collection.update_one({"_id": chat_id}, {"$inc": {"balance": -amt}})
                withdrawals_collection.insert_one({"user_id": chat_id, "name": message.from_user.first_name, "number": num, "amount": amt, "status": "pending"})
                bot.send_message(chat_id, f"✅ Withdraw requested: ৳{amt:.2f} ({num})", reply_markup=main_bottom_keyboard(chat_id, lang))
                try: bot.send_message(ADMIN_ID, f"🔔 **NEW WITHDRAW:**\n👤 User: `{chat_id}`\n📞 Num: `{num}`\n💰 Amt: ৳{amt:.2f}")
                except: pass
            else: bot.send_message(chat_id, f"❌ Invalid Amount! Bal: ৳{current_bal:.2f}")
        else: bot.send_message(chat_id, "❌ Format error! Ex: `01700000000 | 100`")
        user_states.pop(chat_id, None)
        return

    if "Single Submit" in text or "সিঙ্গেল জমা" in text:
        user_states[chat_id] = {'step': 'AWAITING_SINGLE_UID'}
        return bot.send_message(chat_id, "🆔 Send **UID**:", reply_markup=cancel_keyboard(lang))

    if "Bulk Submit" in text or "বাল্ক জমা" in text:
        user_states[chat_id] = {'step': 'AWAITING_BULK_DATA'}
        return bot.send_message(chat_id, "📦 Format:\n`UID | Password | Cookies/2FA`", reply_markup=cancel_keyboard(lang))

    if "Excel Submit" in text or "এক্সেল জমা" in text:
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        return bot.send_message(chat_id, "📄 Send .xlsx/.csv file:", reply_markup=cancel_keyboard(lang))

    if "2FA Gen" in text or "2FA" in text:
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        return bot.send_message(chat_id, "📌 Send 2FA Secret Key:", reply_markup=cancel_keyboard(lang))
        
    if "Link -> UID" in text:
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        return bot.send_message(chat_id, "🔍 Send profile link:", reply_markup=cancel_keyboard(lang))

    if step == 'AWAITING_SINGLE_UID':
        uid = extract_numeric_uid(text)
        if not uid or is_duplicate_uid(uid): return bot.send_message(chat_id, "❌ Invalid/Duplicate UID!")
        user_states[chat_id]['uid'] = uid
        user_states[chat_id]['step'] = 'AWAITING_SINGLE_PAYLOAD'
        return bot.send_message(chat_id, "✅ UID Verified. Now send **Cookies / 2FA**:")

    elif step == 'AWAITING_SINGLE_PAYLOAD':
        uid = state.get('uid')
        password = db_user.get("password", f"Pass_{pass_rule}")
        cat = "fb_cookie" if is_valid_cookies(text) else "fb_2fa"
        rate = RATES.get(cat, 5.0)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        accounts_collection.insert_one({"uid": uid, "worker_id": chat_id, "password": password, "payload": text, "category": cat, "rate": rate, "date": now_str})
        users_collection.update_one({"_id": chat_id}, {"$inc": {"balance": rate}})
        async_save_to_sheet("Sheet1", [now_str, generate_tracking_id(), chat_id, uid, password, text])
        
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, f"🎉 **SAVED!**\nUID: `{uid}`\n💰 Earned: ৳{rate:.2f}", reply_markup=submission_bottom_keyboard(chat_id, lang))

    elif step == 'AWAITING_BULK_DATA':
        success, total = 0, 0.0
        password = db_user.get("password", f"Pass_{pass_rule}")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for line in text.split("\n"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                uid, payload = parts[0], parts[-1]
                clean_uid = extract_numeric_uid(uid)
                if clean_uid and not is_duplicate_uid(clean_uid):
                    cat = "fb_cookie" if is_valid_cookies(payload) else "fb_2fa"
                    rate = RATES.get(cat, 5.0)
                    
                    accounts_collection.insert_one({"uid": clean_uid, "worker_id": chat_id, "password": password, "payload": payload, "category": cat, "rate": rate, "date": now_str})
                    async_save_to_sheet("Sheet1", [now_str, generate_tracking_id(), chat_id, clean_uid, password, payload])
                    
                    success += 1; total += rate
                    
        users_collection.update_one({"_id": chat_id}, {"$inc": {"balance": total}})
        user_states.pop(chat_id, None)
        return bot.send_message(chat_id, f"🎉 **Bulk Saved:** {success} pcs\n💰 **Credited:** ৳{total:.2f}", reply_markup=submission_bottom_keyboard(chat_id, lang))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try: bot.send_message(chat_id, f"🔑 **Code:** `{pyotp.TOTP(clean_key).now()}`")
            except: bot.send_message(chat_id, "❌ Invalid Key!")
        else: bot.send_message(chat_id, "❌ Invalid format!")
        user_states.pop(chat_id, None)

    elif step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        if uid: bot.send_message(chat_id, f"✅ UID:\n`{uid}`")
        else: bot.send_message(chat_id, "❌ No valid UID found.")
        user_states.pop(chat_id, None)

    if not step and chat_id != ADMIN_ID:
        bot.send_message(chat_id, "Select an option:", reply_markup=main_bottom_keyboard(chat_id, lang))

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)