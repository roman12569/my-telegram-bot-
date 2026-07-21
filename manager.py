import os
import re
import csv
import random
import datetime
import threading
import requests
import pyotp
import telebot
import pandas as pd
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

# System Memory Caches
user_passwords = {}
user_states = {}
user_balances = {}
user_languages = {}  # 'en' or 'bn'

# ================= Language Dictionary =================
TEXTS = {
    'en': {
        'welcome_lang': "🌐 **Select Your Language / আপনার পছন্দনীয় ভাষা নির্বাচন করুন:**",
        'welcome': "👑 **ONLINE EARNING BAZAR**\n─────────────────────────\nWelcome to the official automation panel.\nSelect an option from the menu to get started.",
        'btn_sub': "⚡ ID Submission ⚡",
        'btn_tools': "🛠️ Helper Tools",
        'btn_profile': "👤 My Profile",
        'btn_leaderboard': "🏆 Leaderboard",
        'btn_admin': "👑 Admin Panel",
        'btn_cancel': "❌ Cancel",
        'cancelled': "✅ Current process cancelled.",
        'sub_title': "📥 **ID SUBMISSION CENTER**\n─────────────────────────\nChoose submission method:",
        'sub_single': "📥 Single Submit",
        'sub_bulk': "📦 Bulk Text Submit",
        'sub_excel': "📊 Excel/Sheet File Submit",
        'sub_pass': "⚙️ Password Rules",
        'tools_title': "🛠️ **WORKER HELPER SUITE**\n─────────────────────────\nSelect a tool:",
        'tool_2fa': "🔑 2FA Authenticative",
        'tool_uid': "🔍 Profile Link -> UID",
        'tool_mail': "📧 Temp Mailbox",
        'tool_name': "👤 Random Profile",
        'lang_change': "🌐 Change Language",
        'force_join': "🔒 **Channel Verification Required**\n\nPlease join all our official channels to unlock the bot:",
        'verify_btn': "✅ Verified / Check",
        'not_joined': "❌ You haven't joined all channels yet!",
        'verified_ok': "✅ Verification successful! You can now use the bot.",
        'uid_prompt': "🆔 Send **15-20 digit UID** or Profile Link:",
        'invalid_uid': "❌ Invalid or duplicate UID! Try again:",
        'cookies_prompt': "🍪 Paste your **Cookies** string:",
        'twofa_prompt': "🔐 Send your **2FA Secret Key**:",
        'sub_success': "🎉 **Submission Successful!**\n\n📌 **Tracking ID:** `{track_id}`\n📌 **UID:** `{uid}`\n💰 **Earned:** ৳{rate:.2f}",
        'withdraw_min': "⚠️ Minimum withdraw is ৳{min_val:.2f}. Your balance is ৳{bal:.2f}.",
        'withdraw_prompt': "💳 Enter Bkash/Nagad number & Amount (e.g., `01700000000 | 100`):"
    },
    'bn': {
        'welcome_lang': "🌐 **Select Your Language / আপনার পছন্দনীয় ভাষা নির্বাচন করুন:**",
        'welcome': "👑 **ONLINE EARNING BAZAR**\n─────────────────────────\nস্বাগতম! এটি আমাদের অফিশিয়াল অটোমেশন প্যানেল।\nকাজ শুরু করতে নিচের মেনু থেকে অপশন নির্বাচন করুন।",
        'btn_sub': "⚡ আইডি সাবমিশন ⚡",
        'btn_tools': "🛠️ হেল্পার টুলস",
        'btn_profile': "👤 আমার প্রোফাইল",
        'btn_leaderboard': "🏆 লিডারবোর্ড",
        'btn_admin': "👑 এডমিন প্যানেল",
        'btn_cancel': "❌ বাতিল করুন",
        'cancelled': "✅ প্রক্রিয়াটি বাতিল করা হয়েছে।",
        'sub_title': "📥 **আইডি সাবমিশন সেন্টার**\n─────────────────────────\nজমা দেওয়ার মাধ্যম নির্বাচন করুন:",
        'sub_single': "📥 সিঙ্গেল জমা",
        'sub_bulk': "📦 বাল্ক জমা (Text)",
        'sub_excel': "📊 এক্সেল / শিট জমা (Excel)",
        'sub_pass': "⚙️ পাসওয়ার্ড নিয়ম",
        'tools_title': "🛠️ **ওয়ার্কার হেল্পার টুলস**\n─────────────────────────\nপ্রয়োজনীয় সার্ভিস বেছে নিন:",
        'tool_2fa': "🔑 2FA কোড জেনারেটর",
        'tool_uid': "🔍 লিংক থেকে UID",
        'tool_mail': "📧 টেম্প ইমেইল",
        'tool_name': "👤 রেন্ডম নাম জেনারেটর",
        'lang_change': "🌐 ভাষা পরিবর্তন",
        'force_join': "🔒 **অফিসিয়াল চ্যানেল ভেরিফিকেশন**\n\nবট আনলক করতে নিচের ৩টি চ্যানেলে যুক্ত হয়ে ভেরিফাই করুন:",
        'verify_btn': "✅ ভেরিফাই করুন",
        'not_joined': "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!",
        'verified_ok': "✅ ভেরিফিকেশন সফল হয়েছে! এখন সার্ভিস ব্যবহার করতে পারেন।",
        'uid_prompt': "🆔 **১৫-২০ ডিজিটের UID** অথবা প্রোফাইল লিংক দিন:",
        'invalid_uid': "❌ ভুল বা ডুপ্লিকেট UID! সঠিক UID দিন:",
        'cookies_prompt': "🍪 আপনার **Cookies** পেস্ট করুন:",
        'twofa_prompt': "🔐 আপনার **2FA Secret Key** দিন:",
        'sub_success': "🎉 **কাজ জমা সফল হয়েছে!**\n\n📌 **Tracking ID:** `{track_id}`\n📌 **UID:** `{uid}`\n💰 একাউন্টে যোগ হয়েছে: ৳{rate:.2f}",
        'withdraw_min': "⚠️ সর্বনিম্ন ৳{min_val:.2f} তুলতে পারবেন। আপনার ব্যালেন্স ৳{bal:.2f}।",
        'withdraw_prompt': "💳 বিকাশ/নগদ নম্বর এবং টাকার পরিমাণ লিখুন (যেমন: `01700000000 | 100`):"
    }
}

def get_text(chat_id, key):
    lang = user_languages.get(chat_id, 'en')
    return TEXTS[lang].get(key, TEXTS['en'].get(key, ''))

# ================= Helper Functions =================

def check_force_join(user_id):
    if user_id == ADMIN_ID:
        return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            continue
    return True

def async_save_to_sheet(tab_name, row_data):
    def task():
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SPREADSHEET_ID)
            worksheet = sheet.worksheet(tab_name)
            worksheet.append_row(row_data)
        except Exception as e:
            print(f"⚠️ Sheet Save Error: {e}")
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

def get_user_daily_count(worker_name):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    count = 0
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 3 and today in row[0] and worker_name == row[2]:
                    count += 1
    return count

def get_user_total_count(worker_name):
    count = 0
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 3 and worker_name == row[2]:
                    count += 1
    return count

# ================= UI Keyboards =================

def language_selection_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en"),
        InlineKeyboardButton("🇧🇩 বাংলা", callback_data="set_lang_bn")
    )
    return markup

def force_join_keyboard(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(InlineKeyboardButton(get_text(chat_id, 'verify_btn'), callback_data="verify_join"))
    return markup

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(get_text(chat_id, 'btn_sub')),
        KeyboardButton(get_text(chat_id, 'btn_tools'))
    )
    markup.add(
        KeyboardButton(get_text(chat_id, 'btn_profile')),
        KeyboardButton(get_text(chat_id, 'btn_leaderboard'))
    )
    if chat_id == ADMIN_ID:
        markup.add(KeyboardButton(get_text(chat_id, 'btn_admin')))
    return markup

def cancel_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton(get_text(chat_id, 'btn_cancel')))
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

def inline_submission_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(get_text(chat_id, 'sub_single'), callback_data="sub_single"),
        InlineKeyboardButton(get_text(chat_id, 'sub_bulk'), callback_data="sub_bulk")
    )
    markup.add(
        InlineKeyboardButton(get_text(chat_id, 'sub_excel'), callback_data="sub_excel"),
        InlineKeyboardButton(get_text(chat_id, 'sub_pass'), callback_data="sub_pass_settings")
    )
    return markup

def inline_tools_menu(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(get_text(chat_id, 'tool_2fa'), callback_data="tool_2fa"),
        InlineKeyboardButton(get_text(chat_id, 'tool_uid'), callback_data="tool_uid")
    )
    markup.add(
        InlineKeyboardButton(get_text(chat_id, 'tool_mail'), callback_data="tool_mail"),
        InlineKeyboardButton(get_text(chat_id, 'tool_name'), callback_data="tool_name")
    )
    return markup

def inline_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    single_status = "🟢" if single_submit_active else "🔴"
    bulk_status = "🟢" if bulk_submit_active else "🔴"
    
    markup.add(
        InlineKeyboardButton("💰 Rate Config", callback_data="adm_rates"),
        InlineKeyboardButton(f"{single_status} Single Mode", callback_data="adm_toggle_single")
    )
    markup.add(
        InlineKeyboardButton(f"{bulk_status} Bulk Mode", callback_data="adm_toggle_bulk"),
        InlineKeyboardButton("🔑 Pass Rule", callback_data="adm_pass_rule")
    )
    markup.add(
        InlineKeyboardButton("📊 Team Stats", callback_data="adm_stats"),
        InlineKeyboardButton("📥 Excel File", callback_data="adm_excel")
    )
    markup.add(
        InlineKeyboardButton("📢 Broadcast Notice", callback_data="adm_notice"),
        InlineKeyboardButton("📄 Buyer TXT", callback_data="adm_txt")
    )
    return markup

# ================= Start & Command Handlers =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 Your account has been suspended.")
        return
    
    save_user(message.chat.id)
    user_states.pop(message.chat.id, None)

    if message.chat.id not in user_languages:
        bot.send_message(message.chat.id, TEXTS['en']['welcome_lang'], reply_markup=language_selection_keyboard())
        return

    if not check_force_join(message.chat.id):
        bot.send_message(message.chat.id, get_text(message.chat.id, 'force_join'), reply_markup=force_join_keyboard(message.chat.id))
        return

    bot.send_message(message.chat.id, get_text(message.chat.id, 'welcome'), reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["❌ Cancel", "❌ বাতিল করুন"])
def cancel_action(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, get_text(message.chat.id, 'cancelled'), reply_markup=main_bottom_keyboard(message.chat.id))

# ================= Bottom Navigation Handlers =================

@bot.message_handler(func=lambda msg: msg.text in ["⚡ ID Submission ⚡", "⚡ আইডি সাবমিশন ⚡", "📥 ID Submission", "📥 আইডি সাবমিশন"])
def category_submission(message):
    user_states.pop(message.chat.id, None)
    if not check_force_join(message.chat.id):
        bot.send_message(message.chat.id, get_text(message.chat.id, 'force_join'), reply_markup=force_join_keyboard(message.chat.id))
        return
    bot.send_message(message.chat.id, get_text(message.chat.id, 'sub_title'), reply_markup=inline_submission_menu(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["🛠️ Helper Tools", "🛠️ হেল্পার টুলস"])
def category_tools(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, get_text(message.chat.id, 'tools_title'), reply_markup=inline_tools_menu(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["👤 My Profile", "👤 আমার প্রোফাইল"])
def category_profile(message):
    user_states.pop(message.chat.id, None)
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    daily_c = get_user_daily_count(worker_name)
    total_c = get_user_total_count(worker_name)
    balance = user_balances.get(chat_id, 0.0)

    bot_uname = bot.get_me().username
    ref_link = f"https://t.me/{bot_uname}?start={chat_id}"

    lang = user_languages.get(chat_id, 'en')
    if lang == 'en':
        text = (
            "👤 **WORKER PROFILE & DASHBOARD**\n"
            "───────────────\n"
            f"🔹 **Name:** `{worker_name}`\n"
            f"🔹 **Submitted Today:** `{daily_c}` pcs\n"
            f"🔹 **Total Submissions:** `{total_c}` pcs\n"
            f"💰 **Current Balance:** `৳{balance:.2f}`\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`"
        )
    else:
        text = (
            "👤 **ওয়ার্কার প্রোফাইল ও ড্যাশবোর্ড**\n"
            "───────────────\n"
            f"🔹 **নাম:** `{worker_name}`\n"
            f"🔹 **আজকের জমা:** `{daily_c}` টি\n"
            f"🔹 **সর্বমোট জমা:** `{total_c}` টি\n"
            f"💰 **বর্তমান ব্যালেন্স:** `৳{balance:.2f}`\n\n"
            f"🔗 **আপনার রেফারেল লিংক:**\n`{ref_link}`"
        )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💳 Withdraw Money / টাকা তুলুন", callback_data="prof_withdraw"),
        InlineKeyboardButton(get_text(chat_id, 'lang_change'), callback_data="change_lang")
    )
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in ["🏆 Leaderboard", "🏆 লিডারবোর্ড"])
def show_leaderboard(message):
    user_states.pop(message.chat.id, None)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    workers = {}
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 5 and today in row[0]:
                    w_name = row[2]
                    workers[w_name] = workers.get(w_name, 0) + 1

    sorted_workers = sorted(workers.items(), key=lambda x: x[1], reverse=True)[:5]
    
    lang = user_languages.get(message.chat.id, 'en')
    title = "🏆 **TODAY'S TOP 5 WORKERS**\n───────────────\n\n" if lang == 'en' else "🏆 **আজকের সেরা ৫ জন ওয়ার্কার**\n───────────────\n\n"
    
    if not sorted_workers:
        title += "No accounts submitted today yet." if lang == 'en' else "আজ এখনো কোনো কাজ জমা পড়েনি।"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, count) in enumerate(sorted_workers):
            title += f"{medals[idx]} `{name}` — **{count}** pcs\n"
            
    bot.send_message(message.chat.id, title)

@bot.message_handler(func=lambda msg: msg.text in ["👑 Admin Panel", "👑 এডমিন প্যানেল"])
def category_admin(message):
    user_states.pop(message.chat.id, None)
    if message.chat.id != ADMIN_ID:
        return
    text = "👑 **ADMIN CONTROL PANEL**\n───────────────\nSelect an option to manage system:"
    bot.send_message(message.chat.id, text, reply_markup=inline_admin_menu())

# ================= Inline Callbacks Handler =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    global single_submit_active, bulk_submit_active, pass_rule
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)

    # --- Language ---
    if code in ["set_lang_en", "set_lang_bn"]:
        user_languages[chat_id] = 'en' if code == "set_lang_en" else 'bn'
        bot.delete_message(chat_id, call.message.message_id)
        if not check_force_join(chat_id):
            bot.send_message(chat_id, get_text(chat_id, 'force_join'), reply_markup=force_join_keyboard(chat_id))
        else:
            bot.send_message(chat_id, get_text(chat_id, 'welcome'), reply_markup=main_bottom_keyboard(chat_id))
        return

    if code == "change_lang":
        bot.send_message(chat_id, TEXTS['en']['welcome_lang'], reply_markup=language_selection_keyboard())
        return

    # --- Force Join Verification ---
    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, get_text(chat_id, 'verified_ok'), reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, get_text(chat_id, 'not_joined'))
        return

    # --- Helper Tools Callbacks ---
    if code == "tool_mail":
        try:
            domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
            domain = random.choice(domains)
            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
            email = f"{username}@{domain}"
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔄 Check Inbox (OTP)", callback_data=f"inbox_{username}_{domain}"))
            bot.send_message(chat_id, f"📧 **Temporary Email:**\n\n`{email}`", reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, "❌ Error generating email. Try again.")

    elif code.startswith("inbox_"):
        parts = code.split("_")
        username, domain = parts[1], parts[2]
        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={username}&domain={domain}"
        try:
            res = requests.get(url, timeout=10).json()
            if not res:
                bot.answer_callback_query(call.id, "📭 Inbox empty!", show_alert=True)
                return
            msg_id = res[0]['id']
            msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={username}&domain={domain}&id={msg_id}"
            body = requests.get(msg_url, timeout=10).json().get('textBody', 'No Content')
            bot.send_message(chat_id, f"💬 **Content/OTP:**\n`{body}`")
        except Exception:
            bot.answer_callback_query(call.id, "❌ Error checking inbox!", show_alert=True)

    elif code == "tool_name":
        firsts = ["Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi", "Anik", "Parvez"]
        lasts = ["Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury", "Khan", "Sarker"]
        name = f"{random.choice(firsts)} {random.choice(lasts)}"
        year = random.randint(1996, 2004)
        bot.send_message(chat_id, f"👤 **Random Profile Identity:**\n\n🔹 **Name:** `{name}`\n🔹 **DOB Year:** `{year}`")

    elif code == "tool_2fa":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 Send your **2FA Secret Key**:", reply_markup=cancel_keyboard(chat_id))

    elif code == "tool_uid":
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 Send profile link:", reply_markup=cancel_keyboard(chat_id))

    # --- Submissions Callbacks ---
    elif code == "sub_single":
        if not single_submit_active:
            bot.send_message(chat_id, "⚠️ Single submission mode is disabled by Admin.")
            return
        bot.send_message(chat_id, "📌 Select account category:", reply_markup=category_selection_keyboard())

    elif code.startswith("cat_"):
        cat_type = code.replace("cat_", "")
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat_type}
        bot.send_message(chat_id, get_text(chat_id, 'uid_prompt'), reply_markup=cancel_keyboard(chat_id))

    elif code == "sub_bulk":
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ Bulk submission mode is disabled by Admin.")
            return
        user_states[chat_id] = {'step': 'AWAITING_BULK_DATA'}
        text = "📦 **Paste Bulk Accounts:**\n\nFormat per line:\n`UID | Password | Cookies/2FA`"
        bot.send_message(chat_id, text, reply_markup=cancel_keyboard(chat_id))

    elif code == "sub_excel":
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ File submission mode is disabled by Admin.")
            return
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        text = "📄 **Send Excel/CSV File (.xlsx/.csv):**\n\nMake sure columns are:\n`UID` | `Password` | `Cookies/2FA`"
        bot.send_message(chat_id, text, reply_markup=cancel_keyboard(chat_id))

    elif code == "sub_pass_settings":
        bot.send_message(chat_id, f"🔑 **Current Password Requirement:** `{pass_rule}`")

    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, get_text(chat_id, 'withdraw_min').format(min_val=MIN_WITHDRAW, bal=balance))
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, get_text(chat_id, 'withdraw_prompt'), reply_markup=cancel_keyboard(chat_id))

    # --- Admin Callbacks ---
    elif code == "adm_rates" and chat_id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(f"FB Cookie (৳{RATES['fb_cookie']})", callback_data="rate_fb_cookie"),
            InlineKeyboardButton(f"FB 2FA (৳{RATES['fb_2fa']})", callback_data="rate_fb_2fa")
        )
        markup.add(
            InlineKeyboardButton(f"IG Cookie (৳{RATES['ig_cookie']})", callback_data="rate_ig_cookie"),
            InlineKeyboardButton(f"IG 2FA (৳{RATES['ig_2fa']})", callback_data="rate_ig_2fa")
        )
        bot.send_message(chat_id, "💰 Select category to update rate:", reply_markup=markup)

    elif code.startswith("rate_") and chat_id == ADMIN_ID:
        selected_cat = code.replace("rate_", "")
        user_states[chat_id] = {'step': 'AWAITING_CAT_RATE', 'cat': selected_cat}
        bot.send_message(chat_id, f"💰 Enter new price for `{selected_cat}` (e.g. 6.5):", reply_markup=cancel_keyboard(chat_id))

    elif code == "adm_toggle_single" and chat_id == ADMIN_ID:
        single_submit_active = not single_submit_active
        bot.send_message(chat_id, f"Single Submit Mode: {'ON 🟢' if single_submit_active else 'OFF 🔴'}")

    elif code == "adm_toggle_bulk" and chat_id == ADMIN_ID:
        bulk_submit_active = not bulk_submit_active
        bot.send_message(chat_id, f"Bulk Submit Mode: {'ON 🟢' if bulk_submit_active else 'OFF 🔴'}")

    elif code == "adm_stats" and chat_id == ADMIN_ID:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        total, workers = 0, {}
        if os.path.isfile("accounts_list.csv"):
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) >= 5 and today in row[0]:
                        total += 1
                        w_name = row[2]
                        workers[w_name] = workers.get(w_name, 0) + 1
        reply_msg = f"📊 **TODAY'S TEAM REPORT**\n───────────────\nTotal Submissions: **{total}** pcs\n\n" + "\n".join([f"• `{w}`: {c} pcs" for w, c in workers.items()])
        bot.send_message(chat_id, reply_msg)

    elif code == "adm_excel" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "rb") as f:
                bot.send_document(chat_id, f, caption="📁 Complete Accounts CSV Database")
        except Exception:
            bot.send_message(chat_id, "❌ No database file found.")

# ================= DOCUMENT / EXCEL FILE HANDLER =================

@bot.message_handler(content_types=['document'])
def handle_excel_document(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ File submit mode is disabled!", reply_markup=main_bottom_keyboard(chat_id))
            return

        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            file_name = message.document.file_name

            with open(file_name, 'wb') as new_file:
                new_file.write(downloaded_file)

            if file_name.endswith('.csv'):
                df = pd.read_csv(file_name)
            else:
                df = pd.read_excel(file_name)

            success_count = 0
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            worker_name = message.from_user.first_name
            total_earned = 0.0

            for _, row in df.iterrows():
                row_vals = [str(x).strip() for x in row.values]
                if len(row_vals) >= 3:
                    uid, password, payload = row_vals[0], row_vals[1], row_vals[2]
                    clean_uid = extract_numeric_uid(uid)
                    if clean_uid and not is_duplicate_uid(clean_uid):
                        track_id = generate_tracking_id()
                        rate = RATES["fb_cookie"] if is_valid_cookies(payload) else RATES["fb_2fa"]
                        tab = "Cookies_Data" if is_valid_cookies(payload) else "2FA_Data"
                        
                        async_save_to_sheet(tab, [now_str, track_id, str(chat_id), clean_uid, password, payload])
                        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                            writer = csv.writer(file)
                            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                                writer.writerow(["Date & Time", "Tracking ID", "Worker Name", "UID", "Password", "2FA/Cookies"])
                            writer.writerow([now_str, track_id, worker_name, clean_uid, password, payload])
                        
                        success_count += 1
                        total_earned += rate

            if os.path.exists(file_name):
                os.remove(file_name)

            user_balances[chat_id] = user_balances.get(chat_id, 0.0) + total_earned
            user_states.pop(chat_id, None)

            bot.reply_to(message, f"🎉 **Excel Processed!**\n\n✅ Added: **{success_count}** pcs\n💰 Credited: ৳{total_earned:.2f}", reply_markup=main_bottom_keyboard(chat_id))
        
        except Exception:
            bot.reply_to(message, "❌ Failed to process file! Make sure it is a valid .xlsx or .csv file.")

# ================= General Message Handler =================

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    if not state:
        bot.send_message(chat_id, get_text(chat_id, 'welcome'), reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    # Admin State Actions
    if step == 'AWAITING_CAT_RATE' and chat_id == ADMIN_ID:
        cat = state.get('cat')
        try:
            new_r = float(text)
            RATES[cat] = new_r
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ Updated `{cat}` rate: ৳{new_r:.2f}", reply_markup=main_bottom_keyboard(chat_id))
        except ValueError:
            bot.send_message(chat_id, "❌ Enter valid number (e.g. 6.5):")

    # User States Actions
    elif step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if uid:
            bot.send_message(chat_id, f"✅ Extracted Numeric UID:\n\n`{uid}`", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ Could not extract valid UID.", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try:
                totp = pyotp.TOTP(clean_key)
                code = totp.now()
                bot.send_message(chat_id, f"🔑 **Your 2FA Code:**\n\n`{code}`", reply_markup=main_bottom_keyboard(chat_id))
                user_states.pop(chat_id, None)
            except Exception:
                bot.send_message(chat_id, "❌ Failed to generate code from key.")
        else:
            bot.send_message(chat_id, "❌ Invalid 2FA Secret Key!")

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, get_text(chat_id, 'invalid_uid'))
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        
        prompt = get_text(chat_id, 'cookies_prompt') if "cookie" in cat else get_text(chat_id, 'twofa_prompt')
        bot.send_message(chat_id, f"✅ UID Accepted: `{numeric_uid}`\n\n{prompt}")

    elif step == 'AWAITING_BULK_DATA':
        lines = text.split("\n")
        success_count = 0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worker_name = message.from_user.first_name
        total_earned = 0.0

        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                uid, password, payload = parts[0], parts[1], parts[2]
                clean_uid = extract_numeric_uid(uid)
                if clean_uid and not is_duplicate_uid(clean_uid):
                    track_id = generate_tracking_id()
                    rate = RATES["fb_cookie"] if is_valid_cookies(payload) else RATES["fb_2fa"]
                    tab = "Cookies_Data" if is_valid_cookies(payload) else "2FA_Data"
                    
                    async_save_to_sheet(tab, [now_str, track_id, str(chat_id), clean_uid, password, payload])
                    with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                        writer = csv.writer(file)
                        if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                            writer.writerow(["Date & Time", "Tracking ID", "Worker Name", "UID", "Password", "2FA/Cookies"])
                        writer.writerow([now_str, track_id, worker_name, clean_uid, password, payload])
                    
                    success_count += 1
                    total_earned += rate

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + total_earned
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"🎉 **Bulk Submission Done!**\n\n✅ Saved: **{success_count}** pcs\n💰 Earned: ৳{total_earned:.2f}", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{pass_rule}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if "cookie" in cat and not is_valid_cookies(text):
            bot.send_message(chat_id, "❌ Invalid cookies format! Paste original cookies:")
            return
        elif "2fa" in cat and not is_valid_2fa_key(text):
            bot.send_message(chat_id, "❌ Invalid 2FA Key! Paste valid key:")
            return

        rate = RATES.get(cat, 5.0)
        track_id = generate_tracking_id()
        tab = "Cookies_Data" if "cookie" in cat else "2FA_Data"
        
        async_save_to_sheet(tab, [now_str, track_id, str(chat_id), uid, password, text])
        
        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                writer.writerow(["Date & Time", "Tracking ID", "Worker Name", "UID", "Password", "2FA/Cookies"])
            writer.writerow([now_str, track_id, worker_name, uid, password, text])

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + rate
        
        msg = get_text(chat_id, 'sub_success').format(track_id=track_id, uid=uid, rate=rate)
        bot.send_message(chat_id, msg, reply_markup=main_bottom_keyboard(chat_id))
        user_states.pop(chat_id, None)

if __name__ == "__main__":
    print("100% Tested Production Bot Started...")
    bot.infinity_polling(skip_pending=True)