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

# Database Caches
user_passwords = {}
user_states = {}
user_balances = {}

# ================= Helpers =================

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
            print(f"Sheet Save Error: {e}")
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

# ================= Keyboards =================

def force_join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(InlineKeyboardButton("✅ ভেরিফাই করুন", callback_data="verify_join"))
    return markup

def main_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📥 আইডি সাবমিশন"),
        KeyboardButton("🛠️ হেল্পার টুলস")
    )
    markup.add(
        KeyboardButton("👤 আমার প্রোফাইল"),
        KeyboardButton("🏆 লিডারবোর্ড")
    )
    if chat_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
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
        InlineKeyboardButton("📥 সিঙ্গেল আইডি জমা", callback_data="sub_single"),
        InlineKeyboardButton("📦 বাল্ক জমা (Text)", callback_data="sub_bulk")
    )
    markup.add(
        InlineKeyboardButton("⚙️ পাসওয়ার্ড নিয়ম", callback_data="sub_pass_settings")
    )
    return markup

def inline_tools_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔑 2FA কোড জেনারেটর", callback_data="tool_2fa"),
        InlineKeyboardButton("🔍 লিংক থেকে UID", callback_data="tool_uid")
    )
    markup.add(
        InlineKeyboardButton("📧 টেম্প ইমেইল", callback_data="tool_mail"),
        InlineKeyboardButton("👤 রেন্ডম নাম জেনারেটর", callback_data="tool_name")
    )
    return markup

def inline_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    single_status = "🟢" if single_submit_active else "🔴"
    bulk_status = "🟢" if bulk_submit_active else "🔴"
    
    markup.add(
        InlineKeyboardButton("💰 রেট সেটিংস", callback_data="adm_rates"),
        InlineKeyboardButton(f"{single_status} সিঙ্গেল মোড", callback_data="adm_toggle_single")
    )
    markup.add(
        InlineKeyboardButton(f"{bulk_status} বাল্ক মোড", callback_data="adm_toggle_bulk"),
        InlineKeyboardButton("🔑 পাসওয়ার্ড নিয়ম", callback_data="adm_pass_rule")
    )
    markup.add(
        InlineKeyboardButton("📊 টিমের হিসাব", callback_data="adm_stats"),
        InlineKeyboardButton("📥 এক্সেল ফাইল", callback_data="adm_excel")
    )
    markup.add(
        InlineKeyboardButton("📢 ব্রডকাস্ট নোটিশ", callback_data="adm_notice"),
        InlineKeyboardButton("📄 বায়ার TXT ফাইল", callback_data="adm_txt")
    )
    return markup

# ================= Start & Base Commands =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 আপনার অ্যাকাউন্টটি নিষিদ্ধ করা হয়েছে।")
        return
    
    save_user(message.chat.id)
    user_states.pop(message.chat.id, None)

    if not check_force_join(message.chat.id):
        text = (
            "📌 **অফিসিয়াল চ্যানেল ভেরিফিকেশন**\n\n"
            "বটের সেবা গ্রহণ করতে নিচের চ্যানেলগুলোতে যুক্ত থাকা বাধ্যতামূলক। জয়েন সম্পন্ন করে **ভেরিফাই করুন** বাটনে চাপ দিন:"
        )
        bot.send_message(message.chat.id, text, reply_markup=force_join_keyboard())
        return

    welcome_text = (
        "👑 **ONLINE EARNING BAZAR**\n"
        "─────────────────────────\n"
        "স্বাগতম! এটি আমাদের কাজের অফিসিয়াল ডাটা কালেকশন প্যানেল।\n\n"
        "কাজ জমা দিতে অথবা টুলস ব্যবহার করতে নিচের মেনু থেকে অপশন নির্বাচন করুন।"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text == "❌ বাতিল করুন")
def cancel_action(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "✅ বর্তমান প্রক্রিয়াটি বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(message.chat.id))

# ================= Bottom Menu Listeners =================

@bot.message_handler(func=lambda msg: msg.text == "📥 আইডি সাবমিশন")
def category_submission(message):
    user_states.pop(message.chat.id, None)
    if not check_force_join(message.chat.id):
        bot.send_message(message.chat.id, "🔒 অনুগ্রহ করে আগে চ্যানেলগুলোতে যুক্ত হন।", reply_markup=force_join_keyboard())
        return
    text = "📥 **আইডি সাবমিশন সেন্টার**\n─────────────────────────\nআপনার জমার ধরন নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, reply_markup=inline_submission_menu())

@bot.message_handler(func=lambda msg: msg.text == "🛠️ হেল্পার টুলস")
def category_tools(message):
    user_states.pop(message.chat.id, None)
    text = "🛠️ **ওয়ার্কার হেল্পার টুলস**\n─────────────────────────\nআপনার প্রয়োজনীয় টুলটি নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, reply_markup=inline_tools_menu())

@bot.message_handler(func=lambda msg: msg.text == "👤 আমার প্রোফাইল")
def category_profile(message):
    user_states.pop(message.chat.id, None)
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    daily_c = get_user_daily_count(worker_name)
    total_c = get_user_total_count(worker_name)
    balance = user_balances.get(chat_id, 0.0)

    bot_uname = bot.get_me().username
    ref_link = f"https://t.me/{bot_uname}?start={chat_id}"

    text = (
        "👤 **ওয়ার্কার প্রোফাইল ও ড্যাশবোর্ড**\n"
        "─────────────────────────\n"
        f"🔹 **নাম:** `{worker_name}`\n"
        f"🔹 **আজকের জমা:** `{daily_c}` টি\n"
        f"🔹 **সর্বমোট জমা:** `{total_c}` টি\n"
        f"💰 **বর্তমান ব্যালেন্স:** `৳{balance:.2f}`\n\n"
        f"🔗 **আপনার রেফারেল লিংক:**\n`{ref_link}`"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 টাকা তুলুন (Withdraw)", callback_data="prof_withdraw"))
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "🏆 লিডারবোর্ড")
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
    text = "🏆 **আজকের সেরা ৫ জন ওয়ার্কার**\n─────────────────────────\n\n"
    if not sorted_workers:
        text += "আজ এখনো কোনো কাজ ডাটাবেজে যুক্ত হয়নি।"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, count) in enumerate(sorted_workers):
            text += f"{medals[idx]} `{name}` — **{count}** টি আইডি\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda msg: msg.text == "👑 এডমিন প্যানেল")
def category_admin(message):
    user_states.pop(message.chat.id, None)
    if message.chat.id != ADMIN_ID:
        return
    text = "👑 **এডমিন কন্ট্রোল প্যানেল**\n─────────────────────────\nসিস্টেমের যেকোনো পরিবর্তন করতে অপশন সিলেক্ট করুন:"
    bot.send_message(message.chat.id, text, reply_markup=inline_admin_menu())

# ================= Inline Callbacks =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ ভেরিফিকেশন সফল হয়েছে। এবার কাজ শুরু করতে পারেন।", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ আপনি এখনো সবগুলো চ্যানেলে যুক্ত হননি। অনুগ্রহ করে জয়েন করুন।")
        return

    # Tools Fixing
    if code == "tool_mail":
        try:
            domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
            domain = random.choice(domains)
            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
            email = f"{username}@{domain}"
            bot.send_message(chat_id, f"📧 **আপনার টেম্পোরারি ইমেইল:**\n\n`{email}`")
        except Exception:
            bot.send_message(chat_id, "❌ ইমেইল তৈরিতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

    elif code == "tool_name":
        firsts = ["Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi", "Anik", "Parvez"]
        lasts = ["Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury", "Khan", "Sarker"]
        name = f"{random.choice(firsts)} {random.choice(lasts)}"
        year = random.randint(1996, 2004)
        bot.send_message(chat_id, f"👤 **রেন্ডম প্রোফাইল নাম:**\n\n🔹 **Name:** `{name}`\n🔹 **DOB Year:** `{year}`")

    elif code == "tool_2fa":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 আপনার 2FA Secret Key টি পাঠান:", reply_markup=cancel_keyboard())

    elif code == "tool_uid":
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 ফেসবুক বা ইনস্টাগ্রাম প্রোফাইল লিংক দিন:", reply_markup=cancel_keyboard())

    # Submissions
    elif code == "sub_single":
        if not single_submit_active:
            bot.send_message(chat_id, "⚠️ বর্তমানে সিঙ্গেল সাবমিশন বন্ধ রয়েছে।")
            return
        bot.send_message(chat_id, "📌 আইডির ক্যাটাগরি বেছে নিন:", reply_markup=category_selection_keyboard())

    elif code.startswith("cat_"):
        cat_type = code.replace("cat_", "")
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat_type}
        bot.send_message(chat_id, "🆔 **আইডির ১৫-২০ ডিজিটের UID দিন:**", reply_markup=cancel_keyboard())

    elif code == "sub_bulk":
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ বর্তমানে বাল্ক সাবমিশন বন্ধ রয়েছে।")
            return
        bot.send_message(chat_id, "📌 বাল্ক জমা দিতে ক্যাটাগরি বেছে নিন:", reply_markup=category_selection_keyboard())

    elif code == "sub_pass_settings":
        bot.send_message(chat_id, f"🔑 **আজকের পাসওয়ার্ড নিয়ম:** `{pass_rule}`\n\nপাসওয়ার্ড জমা দিলে অবশ্যই এই রুল থাকতে হবে।")

    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, f"⚠️ সর্বনিম্ন ৳{MIN_WITHDRAW:.2f} টাকা তুলতে পারবেন। আপনার বর্তমান ব্যালেন্স ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ বা নগদ নাম্বার এবং টাকার পরিমাণ লিখুন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard())

    # Admin Panel Actions
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
        reply_msg = f"📊 **আজকের টিম রিপোর্ট**\n─────────────────────────\nমোট জমা: **{total}** টি\n\n" + "\n".join([f"• `{w}`: {c}টি" for w, c in workers.items()])
        bot.send_message(chat_id, reply_msg)

    elif code == "adm_excel" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "rb") as f:
                bot.send_document(chat_id, f, caption="📁 সম্পূর্ণ একাউন্ট লিস্ট ফাইল")
        except Exception:
            bot.send_message(chat_id, "❌ ডাটাবেজে কোনো ফাইল পাওয়া যায়নি।")

# ================= General Message Handler =================

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    # যদি ইউজার কোনো প্রসেসে না থাকে
    if not state:
        bot.send_message(chat_id, "অনুগ্রহ করে নিচের মেনু থেকে কাজ নির্বাচন করুন।", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if uid:
            bot.send_message(chat_id, f"✅ প্রোফাইল থেকে প্রাপ্ত Numeric UID:\n\n`{uid}`", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ প্রোফাইল থেকে কোনো সঠিক UID উদ্ধার করা যায়নি।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try:
                totp = pyotp.TOTP(clean_key)
                code = totp.now()
                bot.send_message(chat_id, f"🔑 **আপনার 2FA কোড:**\n\n`{code}`", reply_markup=main_bottom_keyboard(chat_id))
                user_states.pop(chat_id, None)
            except Exception:
                bot.send_message(chat_id, "❌ সিক্রেট কি-টি দিয়ে কোড জেনারেট করা সম্ভব হয়নি।")
        else:
            bot.send_message(chat_id, "❌ অকার্যকর 2FA সিক্রেট কি! সঠিক কি দিন:")

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, "❌ এটি একটি ভুল অথবা ডুপ্লিকেট UID! অন্য UID দিন:")
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        
        req_type = "Cookies" if "cookie" in cat else "2FA Key"
        bot.send_message(chat_id, f"✅ UID গৃহিত হয়েছে: `{numeric_uid}`\n\nএখন আপনার **{req_type}** পেস্ট করুন:")

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{pass_rule}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if "cookie" in cat and not is_valid_cookies(text):
            bot.send_message(chat_id, "❌ অকার্যকর কুকিজ! অরিজিনাল কুকিজ পেস্ট করুন:")
            return
        elif "2fa" in cat and not is_valid_2fa_key(text):
            bot.send_message(chat_id, "❌ অকার্যকর 2FA Key! সঠিক Key পেস্ট করুন:")
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
        bot.send_message(
            chat_id, 
            f"🎉 **কাজ সফলভাবে জমা হয়েছে!**\n\n📌 **Tracking ID:** `{track_id}`\n📌 **UID:** `{uid}`\n💰 একাউন্টে যোগ হয়েছে: ৳{rate:.2f}", 
            reply_markup=main_bottom_keyboard(chat_id)
        )
        user_states.pop(chat_id, None)

if __name__ == "__main__":
    print("Zero-Bug Bot Started...")
    bot.infinity_polling(skip_pending=True)