import os
import re
import csv
import random
import datetime
import threading
import requests
import pyotp
import telebot
from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= Configuration =================
TOKEN = '8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4'
ADMIN_ID = 6257034751
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_GOOGLE_SHEET_ID_HERE")
CREDENTIALS_FILE = "credentials.json"

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

RATES = {
    "fb_cookie": 5.0,
    "fb_2fa": 6.0,
    "ig_cookie": 8.0,
    "ig_2fa": 10.0
}

single_submit_active = True
bulk_submit_active = True
pass_rule = "20"
MIN_WITHDRAW = 50.0

user_passwords = {}
user_states = {}
user_balances = {}

# ================= Fast Helper Functions =================

def check_force_join(user_id):
    """মেম্বার সব চ্যানেলে জয়েন আছে কিনা সঠিকভাবে যাচাই করার ফিক্সড ফাংশন"""
    if user_id == ADMIN_ID:
        return True
        
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            print(f"⚠️ Channel Check Exception ({ch['username']}): {e}")
            # চ্যানেল চেক এক্সেপশন এড়াতে যদি বট অ্যাডমিন না থাকে
            continue
    return True

def async_save_to_sheet(tab_name, row_data):
    """ব্যাকগ্রাউন্ডে গুগল শিটে সেভ করার থ্রেড (বট স্লো হওয়া রোধ করে)"""
    def task():
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SPREADSHEET_ID)
            worksheet = sheet.worksheet(tab_name)
            worksheet.append_row(row_data)
        except Exception as e:
            print(f"⚠️ Google Sheet Background Save Error: {e}")

    threading.Thread(target=task).start()

def save_user(chat_id):
    def task():
        users = set()
        if os.path.isfile("users.txt"):
            with open("users.txt", "r", encoding="utf-8") as f:
                users = set(f.read().splitlines())
        if str(chat_id) not in users:
            with open("users.txt", "a", encoding="utf-8") as f:
                f.write(f"{chat_id}\n")
    threading.Thread(target=task).start()

def is_banned(chat_id):
    if not os.path.isfile("banned.txt"):
        return False
    with open("banned.txt", "r", encoding="utf-8") as f:
        return str(chat_id) in f.read().splitlines()

def generate_tracking_id():
    return f"#SUB-{random.randint(10000, 99999)}"

def is_duplicate_uid(uid):
    if not os.path.isfile("accounts_list.csv"):
        return False
    with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) > 3 and row[3] == uid:
                return True
    return False

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
    cookie_str = str(cookie_str)
    return ("c_user=" in cookie_str) or ("datr=" in cookie_str) or ("xs=" in cookie_str) or ("sessionid=" in cookie_str)

def clean_cookie_data(cookie_str):
    """কুকিজ থেকে অতিরিক্ত তথ্য বাদ দিয়ে ক্লিন ডাটা বের করা"""
    cookie_str = str(cookie_str).strip()
    return cookie_str

# ================= UI KEYBOARDS =================

def force_join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(InlineKeyboardButton("⚡ Verified / চেক করুন", callback_data="verify_join"))
    return markup

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("⚡ 𝙄𝘿 𝙎𝙪𝙗𝙢𝙞𝙨𝙨𝙞𝙤𝙣 ⚡"),
        KeyboardButton("🛠️ 𝙒𝙤𝙧𝙠𝙚𝙧 𝙏𝙤𝙤𝙡𝙨")
    )
    markup.add(
        KeyboardButton("👤 𝙈𝙮 𝙋𝙧𝙤𝙛𝙞𝙡𝙚"),
        KeyboardButton("🏆 𝙇𝙚𝙖𝙙𝙚𝙧𝙗𝙤𝙖𝙧𝙙")
    )
    if chat_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 𝘼𝙙𝙢𝙞𝙣 𝙋𝙖𝙣𝙚𝙡"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ 𝘾𝙖𝙣𝙘𝙚𝙡 / বাতিল"))
    return markup

def category_selection_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"📘 FB Cookies (৳{RATES['fb_cookie']})", callback_data="cat_fb_cookie"),
        InlineKeyboardButton(f"🔐 FB 2FA (৳{RATES['fb_2fa']})", callback_data="cat_fb_2fa")
    )
    markup.add(
        InlineKeyboardButton(f"📸 IG Cookies (৳{RATES['ig_cookie']})", callback_data="cat_ig_cookie"),
        InlineKeyboardButton(f"🔐 IG 2FA (৳{RATES['ig_2fa']})", callback_data="cat_ig_2fa")
    )
    return markup

def inline_submission_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📥 সিঙ্গেল জমা (Single)", callback_data="sub_single"),
        InlineKeyboardButton("📦 বাল্ক জমা (Text)", callback_data="sub_bulk")
    )
    markup.add(
        InlineKeyboardButton("⚙️ পাসওয়ার্ড নিয়ম", callback_data="sub_pass_settings")
    )
    return markup

def inline_tools_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔑 2FA Authenticative", callback_data="tool_2fa"),
        InlineKeyboardButton("🔍 Profile Link -> UID", callback_data="tool_uid")
    )
    markup.add(
        InlineKeyboardButton("📧 Temp Mailbox", callback_data="tool_mail"),
        InlineKeyboardButton("👤 Random Profile", callback_data="tool_name")
    )
    return markup

# ================= START & SYSTEM HANDLERS =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।")
        return
    
    save_user(message.chat.id)
    user_states.pop(message.chat.id, None)

    if not check_force_join(message.chat.id):
        text = (
            "🔒 **বট ব্যবহার করতে আমাদের তিনটি চ্যানেল জয়েন সম্পন্ন করুন:**\n\n"
            "নিচের সবগুলো চ্যানেলে যুক্ত হয়ে ** Verified / চেক করুন ** বোতামে চাপ দিন:"
        )
        bot.send_message(message.chat.id, text, reply_markup=force_join_keyboard())
        return

    welcome_text = (
        "╔════════════════════════════╗\n"
        "   👑  *ONLINE EARNING BAZAR*  👑\n"
        "╚════════════════════════════╝\n\n"
        "✨ *স্বাগতম সুপারফাস্ট অটোমেশন বোট প্যানেলে!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 নিচের আকর্ষণীয় মেনু থেকে কাজ শুরু করুন:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text == "❌ 𝘾𝙖𝙣𝙘𝙚𝙡 / বাতিল")
def cancel_action(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "🚫 বর্তমান কাজটি বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text == "⚡ 𝙄𝘿 𝙎𝙪𝙗𝙢𝙞𝙨𝙨𝙞𝙤𝙣 ⚡")
def category_submission(message):
    if not check_force_join(message.chat.id):
        bot.send_message(message.chat.id, "🔒 আগে সবকটি চ্যানেলে জয়েন করুন!", reply_markup=force_join_keyboard())
        return
    text = "📥 *ID SUBMISSION CENTER*\n━━━━━━━━━━━━━━━━━━━━\nজমা দেওয়ার মাধ্যম নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, reply_markup=inline_submission_menu())

@bot.message_handler(func=lambda msg: msg.text == "🛠️ 𝙒𝙤𝙧𝙠𝙚𝙧 𝙏𝙤𝙤𝙡𝙨")
def category_tools(message):
    text = "🛠️ *WORKER HELPER SUITE*\n━━━━━━━━━━━━━━━━━━━━\nআপনার প্রয়োজনীয় সার্ভিসটি বেছে নিন:"
    bot.send_message(message.chat.id, text, reply_markup=inline_tools_menu())

@bot.message_handler(func=lambda msg: msg.text == "👤 𝙈𝙮 𝙋𝙧𝙤𝙛𝙞𝙡𝙚")
def category_profile(message):
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    balance = user_balances.get(chat_id, 0.0)

    text = (
        "┌─────────────────────────┐\n"
        "   👤  *WORKER DASHBOARD*  \n"
        "└─────────────────────────┘\n\n"
        f"👤 *নাম:* `{worker_name}`\n"
        f"💎 *বর্তমান ইনকাম ব্যালেন্স:* `৳{balance:.2f}`\n"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 টাকা তুলুন (Withdraw)", callback_data="prof_withdraw"))
    markup.add(InlineKeyboardButton("🔗 রেফারেল লিংক", callback_data="prof_ref"))
    bot.send_message(chat_id, text, reply_markup=markup)

# ================= CALLBACK HANDLER =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)  # স্পিড আপের জন্য সাথে সাথে উত্তর দেওয়া

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "🎉 ভেরিফিকেশন সফল হয়েছে! এখন সার্ভিস ব্যবহার করুন।", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি! নিশ্চিত হয়ে আবার চাপ দিন।")
        return

    if code == "sub_single":
        if not single_submit_active:
            bot.send_message(chat_id, "⚠️ এডমিন বর্তমানে সিঙ্গেল জমা বন্ধ রেখেছেন!")
            return
        bot.send_message(chat_id, "📌 আইডির ক্যাটাগরি বেছে নিন:", reply_markup=category_selection_keyboard())

    elif code.startswith("cat_"):
        cat_type = code.replace("cat_", "")
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat_type}
        bot.send_message(chat_id, "🆔 *১৫-২০ ডিজিটের UID লিখুন:*", reply_markup=cancel_keyboard())

    elif code == "sub_bulk":
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ এডমিন বর্তমানে বাল্ক জমা বন্ধ রেখেছেন!")
            return
        bot.send_message(chat_id, "📌 বাল্ক জমা দিতে ক্যাটাগরি সিলেক্ট করুন:", reply_markup=category_selection_keyboard())

    elif code == "tool_2fa":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 2FA Secret Key দিন:", reply_markup=cancel_keyboard())

    elif code == "tool_uid":
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 প্রফাইল লিংক দিন:", reply_markup=cancel_keyboard())

    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, f"⚠️ সর্বনিম্ন ৳{MIN_WITHDRAW:.2f} লাগবে। আপনার আছে ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নম্বর এবং পরিমাণ দিন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard())

    elif code == "prof_ref":
        bot_uname = bot.get_me().username
        bot.send_message(chat_id, f"🔗 *আপনার রেফারেল লিংক:*\n`https://t.me/{bot_uname}?start={chat_id}`")

# ================= GENERAL MESSAGE HANDLER =================

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    if not state:
        bot.send_message(chat_id, "নিচের মেনু থেকে অপশন বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if uid:
            bot.send_message(chat_id, f"✅ প্রফাইল থেকে প্রাপ্ত Numeric UID:\n\n`{uid}`", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ কোনো সঠিক UID পাওয়া যায়নি।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try:
                totp = pyotp.TOTP(clean_key)
                code = totp.now()
                bot.send_message(chat_id, f"🔑 আপনার ১-ট্যাপ কপি 2FA কোড:\n\n`{code}`", reply_markup=main_bottom_keyboard(chat_id))
                user_states.pop(chat_id, None)
            except Exception:
                bot.send_message(chat_id, "❌ কোড জেনারেট করা যায়নি।")
        else:
            bot.send_message(chat_id, "❌ ভুল 2FA Key!")

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID! অন্য UID দিন:")
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        
        req_type = "Cookies" if "cookie" in cat else "2FA Key"
        bot.send_message(chat_id, f"✅ UID গৃহীত: `{numeric_uid}`\n\nএখন আপনার **{req_type}** পেস্ট করুন:")

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{pass_rule}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if "cookie" in cat and not is_valid_cookies(text):
            bot.send_message(chat_id, "❌ অকার্যকর কুকিজ! সঠিক কুকিজ পেস্ট করুন:")
            return
        elif "2fa" in cat and not is_valid_2fa_key(text):
            bot.send_message(chat_id, "❌ ভুল 2FA Key! সঠিক Key পেস্ট করুন:")
            return

        rate = RATES.get(cat, 5.0)
        track_id = generate_tracking_id()
        tab = "Cookies_Data" if "cookie" in cat else "2FA_Data"
        
        # ব্যাকগ্রাউন্ড থ্রেডে গুগল শিটে সেভ (ফাস্ট রেসপন্সের জন্য)
        async_save_to_sheet(tab, [now_str, track_id, str(chat_id), uid, password, text])
        
        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                writer.writerow(["Date & Time", "Tracking ID", "Worker Name", "UID", "Password", "2FA/Cookies"])
            writer.writerow([now_str, track_id, worker_name, uid, password, text])

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + rate
        bot.send_message(
            chat_id, 
            f"🎉 *জমা সফল হয়েছে!*\n\n📌 **Tracking ID:** `{track_id}`\n📌 **UID:** `{uid}`\n💰 যোগ হয়েছে: ৳{rate:.2f}", 
            reply_markup=main_bottom_keyboard(chat_id)
        )
        user_states.pop(chat_id, None)

if __name__ == "__main__":
    print("Fast Bot Runner Started...")
    bot.infinity_polling(skip_pending=True)