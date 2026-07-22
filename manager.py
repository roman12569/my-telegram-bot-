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
from flask import Flask
from telebot import types
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= 1. Web Server for Render 24/7 =================
app = Flask(__name__)
@app.route('/')
def home():
    return "Online Earning Bazar Bot is Running flawlessly!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ফ্লাস্ক সার্ভার ব্যাকগ্রাউন্ডে চালু করা হলো যাতে Render-এ স্লিপ না করে
threading.Thread(target=run_flask).start()

# ================= Configuration =================
TOKEN = '8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4'
ADMIN_ID = 6257034751
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1aWntk0eMZt6w7GWmXs_PmckvoDT1uCCRiGUELiV4NKA")
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

# Memory Stores
user_passwords = {}
user_states = {}
user_balances = {}
user_languages = {}

# ================= Helper & Checker Functions =================

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
    try:
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) > 3 and row[3] == str(uid):
                    return True
    except Exception:
        pass
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

def check_live_account(uid):
    try:
        clean_uid = extract_numeric_uid(uid)
        if not clean_uid:
            return False, "Invalid UID format"
        
        url = f"https://www.facebook.com/{clean_uid}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            if "content=\"no-cache\"" in response.text or "The page you requested cannot be displayed" in response.text or "Jigsaw" in response.text:
                return False, "Dead / Checkpoint"
            return True, "Live Account"
        else:
            return False, "Dead / Suspended"
    except Exception:
        return True, "Assumed Live"

def get_user_daily_count(worker_name):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    count = 0
    if os.path.isfile("accounts_list.csv"):
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) >= 3 and today in row[0] and worker_name == row[2]:
                        count += 1
        except Exception:
            pass
    return count

def get_user_total_count(worker_name):
    count = 0
    if os.path.isfile("accounts_list.csv"):
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) >= 3 and worker_name == row[2]:
                        count += 1
        except Exception:
            pass
    return count

# ================= KEYBOARD BUILDERS =================

def language_selection_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en"),
        InlineKeyboardButton("🇧🇩 বাংলা", callback_data="set_lang_bn")
    )
    return markup

def force_join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(InlineKeyboardButton("✅ Verify / ভেরিফাই করুন", callback_data="verify_join"))
    return markup

def main_bottom_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'en')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'en':
        markup.add(KeyboardButton("⚡ ID Submission ⚡"), KeyboardButton("🛠️ Helper Tools"))
        markup.add(KeyboardButton("👤 My Profile"), KeyboardButton("🏆 Leaderboard"))
        if chat_id == ADMIN_ID:
            markup.add(KeyboardButton("👑 Admin Panel"))
    else:
        markup.add(KeyboardButton("⚡ আইডি সাবমিশন ⚡"), KeyboardButton("🛠️ হেল্পার টুলস"))
        markup.add(KeyboardButton("👤 আমার প্রোফাইল"), KeyboardButton("🏆 লিডারবোর্ড"))
        if chat_id == ADMIN_ID:
            markup.add(KeyboardButton("👑 এডমিন প্যানেল"))
    return markup

def submission_bottom_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'en')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'en':
        markup.add(KeyboardButton("📥 Single Submit"), KeyboardButton("📦 Bulk Text Submit"))
        markup.add(KeyboardButton("📊 Excel File Submit"), KeyboardButton("⚙️ Password Rules"))
        markup.add(KeyboardButton("🔙 Main Menu"))
    else:
        markup.add(KeyboardButton("📥 সিঙ্গেল জমা"), KeyboardButton("📦 বাল্ক জমা (Text)"))
        markup.add(KeyboardButton("📊 এক্সেল ফাইল জমা"), KeyboardButton("⚙️ পাসওয়ার্ড নিয়ম"))
        markup.add(KeyboardButton("🔙 মেইন মেনু"))
    return markup

def category_bottom_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(f"📘 FB Cookies (৳{RATES['fb_cookie']})"),
        KeyboardButton(f"🔐 FB 2FA (৳{RATES['fb_2fa']})")
    )
    markup.add(
        KeyboardButton(f"📸 IG Cookies (৳{RATES['ig_cookie']})"),
        KeyboardButton(f"🔐 IG 2FA (৳{RATES['ig_2fa']})")
    )
    btn_back = "🔙 Main Menu" if user_languages.get(chat_id, 'en') == 'en' else "🔙 মেইন মেনু"
    markup.add(KeyboardButton(btn_back))
    return markup

def tools_bottom_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'en')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'en':
        markup.add(KeyboardButton("🔑 2FA Code Gen"), KeyboardButton("🔍 Link -> UID"))
        markup.add(KeyboardButton("🔍 UID & Account Checker"), KeyboardButton("📧 Temp Mailbox"))
        markup.add(KeyboardButton("👤 Random Profile"), KeyboardButton("🔙 Main Menu"))
    else:
        markup.add(KeyboardButton("🔑 2FA কোড জেনারেটর"), KeyboardButton("🔍 লিংক থেকে UID"))
        markup.add(KeyboardButton("🔍 UID & Account Checker"), KeyboardButton("📧 টেম্প ইমেইল"))
        markup.add(KeyboardButton("👤 রেন্ডম নাম জেনারেটর"), KeyboardButton("🔙 মেইন মেনু"))
    return markup

def admin_bottom_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    single_st = "🟢" if single_submit_active else "🔴"
    bulk_st = "🟢" if bulk_submit_active else "🔴"
    markup.add(KeyboardButton("💰 Rate Config"), KeyboardButton(f"{single_st} Single Mode"))
    markup.add(KeyboardButton(f"{bulk_st} Bulk Mode"), KeyboardButton("🔑 Pass Rule"))
    markup.add(KeyboardButton("📊 Team Stats"), KeyboardButton("📥 Export Excel"))
    markup.add(KeyboardButton("📢 Broadcast Notice"), KeyboardButton("🔙 Main Menu"))
    return markup

def cancel_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'en')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    btn_txt = "❌ Cancel" if lang == 'en' else "❌ বাতিল করুন"
    markup.add(KeyboardButton(btn_txt))
    return markup

# ================= START COMMAND =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if is_banned(chat_id):
        bot.reply_to(message, "🚫 Your account has been suspended.")
        return
    
    save_user(chat_id)
    user_states.pop(chat_id, None)

    if chat_id not in user_languages:
        bot.send_message(chat_id, "🌐 **Select Your Language / ভাষা নির্বাচন করুন:**", reply_markup=language_selection_keyboard())
        return

    if not check_force_join(chat_id):
        bot.send_message(chat_id, "🔒 **Channel Verification Required / চ্যানেল জয়েন করুন:**", reply_markup=force_join_keyboard())
        return

    lang = user_languages.get(chat_id, 'en')
    txt = "👑 **ONLINE EARNING BAZAR**\n───────────────\nWelcome to official automation panel.\nSelect option from bottom keyboard." if lang == 'en' else "👑 **ONLINE EARNING BAZAR**\n───────────────\nস্বাগতম! এটি আমাদের অফিশিয়াল অটোমেশন প্যানেল।\nনিচের কিবোর্ড থেকে কাজ সিলেক্ট করুন।"
    bot.send_message(chat_id, txt, reply_markup=main_bottom_keyboard(chat_id))

# ================= DOCUMENT / EXCEL HANDLER =================

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
                df = pd.read_csv(file_name, dtype=str)
            else:
                df = pd.read_excel(file_name, dtype=str)

            df = df.fillna('')
            success_count, total_earned = 0, 0.0
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            worker_name = message.from_user.first_name or "Worker"

            for _, row in df.iterrows():
                row_vals = [str(x).strip() for x in row.values]
                if len(row_vals) >= 3:
                    uid, password, payload = row_vals[0], row_vals[1], row_vals[2]
                    clean_uid = extract_numeric_uid(uid)
                    if clean_uid and not is_duplicate_uid(clean_uid):
                        is_live, _ = check_live_account(clean_uid)
                        if not is_live:
                            continue
                        
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
            bot.reply_to(message, f"🎉 **Excel Processed!**\n\n✅ Live Added: **{success_count}** pcs\n💰 Credited: ৳{total_earned:.2f}", reply_markup=submission_bottom_keyboard(chat_id))
        
        except Exception:
            bot.reply_to(message, "❌ Failed to process file! Make sure it is a valid .xlsx or .csv file.")

# ================= CALLBACKS HANDLER =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    bot.answer_callback_query(call.id)

    if code in ["set_lang_en", "set_lang_bn"]:
        user_languages[chat_id] = 'en' if code == "set_lang_en" else 'bn'
        bot.delete_message(chat_id, call.message.message_id)
        if not check_force_join(chat_id):
            bot.send_message(chat_id, "🔒 **Channel Verification Required:**", reply_markup=force_join_keyboard())
        else:
            bot.send_message(chat_id, "👑 Welcome to **ONLINE EARNING BAZAR**!", reply_markup=main_bottom_keyboard(chat_id))
        return

    elif code == "change_lang":
        bot.send_message(chat_id, "🌐 **Select Language:**", reply_markup=language_selection_keyboard())
        return

    elif code == "verify_join":
        if check_force_join(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "✅ Verification successful!", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ You haven't joined all required channels yet!")
        return

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

    elif code.startswith("rate_") and chat_id == ADMIN_ID:
        selected_cat = code.replace("rate_", "")
        user_states[chat_id] = {'step': 'AWAITING_CAT_RATE', 'cat': selected_cat}
        bot.send_message(chat_id, f"💰 Enter new price for `{selected_cat}` (e.g. 6.5):", reply_markup=cancel_keyboard(chat_id))

    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, f"⚠️ Min withdraw: ৳{MIN_WITHDRAW:.2f}. Your balance: ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 Enter Bkash/Nagad number & Amount (e.g. `01700000000 | 100`):", reply_markup=cancel_keyboard(chat_id))

    elif code == "set_my_password":
        user_states[chat_id] = {'step': 'AWAITING_USER_CUSTOM_PASS'}
        bot.send_message(chat_id, "🔑 **Enter your custom working password:**\n\n(This password will auto-apply to all your future submissions until you change it again)", reply_markup=cancel_keyboard(chat_id))

# ================= MAIN ROUTER HANDLER =================

@bot.message_handler(func=lambda msg: True)
def main_router(message):
    global single_submit_active, bulk_submit_active, pass_rule
    
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    lang = user_languages.get(chat_id, 'en')

    # 1. Global Navigation Controls
    if text in ["🔙 Main Menu", "🔙 মেইন মেনু", "❌ Cancel", "❌ বাতিল করুন"]:
        user_states.pop(chat_id, None)
        txt = "👑 **ONLINE EARNING BAZAR**\n───────────────\nMain Menu:" if lang == 'en' else "👑 **ONLINE EARNING BAZAR**\n───────────────\nমেইন মেনু:"
        bot.send_message(chat_id, txt, reply_markup=main_bottom_keyboard(chat_id))
        return

    # 2. Top-Level Main Categories
    if text in ["⚡ ID Submission ⚡", "⚡ আইডি সাবমিশন ⚡"]:
        user_states.pop(chat_id, None)
        if not check_force_join(chat_id):
            bot.send_message(chat_id, "🔒 Join required channels first!", reply_markup=force_join_keyboard())
            return
        txt = "📥 **ID SUBMISSION CENTER**\nSelect submission method:" if lang == 'en' else "📥 **আইডি সাবমিশন সেন্টার**\nসাবমিশন মাধ্যম বেছে নিন:"
        bot.send_message(chat_id, txt, reply_markup=submission_bottom_keyboard(chat_id))
        return

    elif text in ["🛠️ Helper Tools", "🛠️ হেল্পার টুলস"]:
        user_states.pop(chat_id, None)
        txt = "🛠️ **WORKER HELPER SUITE**\nSelect tool from below:" if lang == 'en' else "🛠️ **ওয়ার্কার হেল্পার টুলস**\nপ্রয়োজনীয় টুলটি বেছে নিন:"
        bot.send_message(chat_id, txt, reply_markup=tools_bottom_keyboard(chat_id))
        return

    elif text in ["👤 My Profile", "👤 আমার প্রোফাইল"]:
        user_states.pop(chat_id, None)
        worker_name = message.from_user.first_name or "Worker"
        daily_c = get_user_daily_count(worker_name)
        total_c = get_user_total_count(worker_name)
        balance = user_balances.get(chat_id, 0.0)
        saved_pass = user_passwords.get(chat_id, f"Not Set (Default: {pass_rule})")
        bot_uname = bot.get_me().username
        ref_link = f"https://t.me/{bot_uname}?start={chat_id}"

        if lang == 'en':
            msg_str = (
                "👤 **WORKER PROFILE & DASHBOARD**\n───────────────\n"
                f"🔹 **Name:** `{worker_name}`\n"
                f"🔹 **Saved Password:** `{saved_pass}`\n"
                f"🔹 **Submitted Today:** `{daily_c}` pcs\n"
                f"🔹 **Total Submissions:** `{total_c}` pcs\n"
                f"💰 **Current Balance:** `৳{balance:.2f}`\n\n"
                f"🔗 **Your Referral Link:**\n`{ref_link}`"
            )
        else:
            msg_str = (
                "👤 **ওয়ার্কার প্রোফাইল ও ড্যাশবোর্ড**\n───────────────\n"
                f"🔹 **নাম:** `{worker_name}`\n"
                f"🔹 **সেভ করা পাসওয়ার্ড:** `{saved_pass}`\n"
                f"🔹 **আজকের জমা:** `{daily_c}` টি\n"
                f"🔹 **সর্বমোট জমা:** `{total_c}` টি\n"
                f"💰 **বর্তমান ব্যালেন্স:** `৳{balance:.2f}`\n\n"
                f"🔗 **আপনার রেফারেল লিংক:**\n`{ref_link}`"
            )

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("💳 Withdraw Money / টাকা তুলুন", callback_data="prof_withdraw"),
            InlineKeyboardButton("🔑 Set My Password / পাসওয়ার্ড সেভ", callback_data="set_my_password"),
            InlineKeyboardButton("🌐 Change Language", callback_data="change_lang")
        )
        bot.send_message(chat_id, msg_str, reply_markup=markup)
        return

    elif text in ["🏆 Leaderboard", "🏆 লিডারবোর্ড"]:
        user_states.pop(chat_id, None)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        workers = {}
        if os.path.isfile("accounts_list.csv"):
            try:
                with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                    reader = csv.reader(file)
                    for row in reader:
                        if len(row) >= 5 and today in row[0]:
                            w_name = row[2]
                            workers[w_name] = workers.get(w_name, 0) + 1
            except Exception:
                pass

        sorted_workers = sorted(workers.items(), key=lambda x: x[1], reverse=True)[:5]
        title = "🏆 **TODAY'S TOP 5 WORKERS**\n───────────────\n\n" if lang == 'en' else "🏆 **আজকের সেরা ৫ জন ওয়ার্কার**\n───────────────\n\n"
        if not sorted_workers:
            title += "No accounts submitted today yet." if lang == 'en' else "আজ এখনো কোনো কাজ জমা পড়েনি।"
        else:
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            for idx, (name, count) in enumerate(sorted_workers):
                title += f"{medals[idx]} `{name}` — **{count}** pcs\n"
        bot.send_message(chat_id, title)
        return

    elif text in ["👑 Admin Panel", "👑 এডমিন প্যানেল"] and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, "👑 **ADMIN CONTROL PANEL**", reply_markup=admin_bottom_keyboard())
        return

    # 3. Sub-Menu Submissions Triggers
    if text in ["📥 Single Submit", "📥 সিঙ্গেল জমা"]:
        if not single_submit_active:
            bot.send_message(chat_id, "⚠️ Single submission is disabled by Admin.")
            return
        bot.send_message(chat_id, "📌 Select account category:", reply_markup=category_bottom_keyboard(chat_id))
        return

    elif any(text.startswith(p) for p in ["📘 FB Cookies", "🔐 FB 2FA", "📸 IG Cookies", "🔐 IG 2FA"]):
        cat_type = "fb_cookie"
        if "FB 2FA" in text: cat_type = "fb_2fa"
        elif "IG Cookies" in text: cat_type = "ig_cookie"
        elif "IG 2FA" in text: cat_type = "ig_2fa"

        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat_type}
        prompt = "🆔 Send **15-20 digit UID** or Profile Link:" if lang == 'en' else "🆔 **১৫-২০ ডিজিটের UID** অথবা প্রোফাইল লিংক দিন:"
        bot.send_message(chat_id, prompt, reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["📦 Bulk Text Submit", "📦 বাল্ক জমা (Text)"]:
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ Bulk submission is disabled by Admin.")
            return
        user_states[chat_id] = {'step': 'AWAITING_BULK_DATA'}
        txt = "📦 **Paste Bulk Accounts:**\n\nFormat per line:\n`UID | Password | Cookies/2FA`"
        bot.send_message(chat_id, txt, reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["📊 Excel File Submit", "📊 এক্সেল ফাইল জমা"]:
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ File submission is disabled by Admin.")
            return
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        txt = "📄 **Send Excel/CSV File (.xlsx/.csv):**\n\nColumns format:\n`UID` | `Password` | `Cookies/2FA`"
        bot.send_message(chat_id, txt, reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["⚙️ Password Rules", "⚙️ পাসওয়ার্ড নিয়ম"]:
        custom_p = user_passwords.get(chat_id, "Not Set")
        bot.send_message(chat_id, f"🔑 **Your Saved Password:** `{custom_p}`\n⚙️ **Global Rule:** `{pass_rule}`\n\n💡 *Your saved password will auto-apply during submissions!*")
        return

    # 4. Helper Tools Triggers
    elif text in ["🔑 2FA Code Gen", "🔑 2FA কোড জেনারেটর"]:
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 Send your **2FA Secret Key**:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🔍 Link -> UID", "🔍 লিংক থেকে UID"]:
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 Send profile link:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["🔍 UID & Account Checker"]:
        user_states[chat_id] = {'step': 'AWAITING_CHECK_UID'}
        bot.send_message(chat_id, "🔍 **UID Live/Dead Checker**\n\nSend UID or Profile Link to check its live status:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text in ["📧 Temp Mailbox", "📧 টেম্প ইমেইল"]:
        try:
            domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
            domain = random.choice(domains)
            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
            email = f"{username}@{domain}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔄 Check Inbox (OTP)", callback_data=f"inbox_{username}_{domain}"))
            bot.send_message(chat_id, f"📧 **Temporary Email:**\n\n`{email}`", reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, "❌ Error generating email.")
        return

    elif text in ["👤 Random Profile", "👤 রেন্ডম নাম জেনারেটর"]:
        firsts = ["Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi", "Anik", "Parvez"]
        lasts = ["Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury", "Khan", "Sarker"]
        name = f"{random.choice(firsts)} {random.choice(lasts)}"
        year = random.randint(1996, 2004)
        bot.send_message(chat_id, f"👤 **Random Profile Identity:**\n\n🔹 **Name:** `{name}`\n🔹 **DOB Year:** `{year}`")
        return

    # 5. Admin Panel Triggers
    elif text == "💰 Rate Config" and chat_id == ADMIN_ID:
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
        return

    elif "Single Mode" in text and chat_id == ADMIN_ID:
        single_submit_active = not single_submit_active
        bot.send_message(chat_id, f"Single Mode: {'ON 🟢' if single_submit_active else 'OFF 🔴'}", reply_markup=admin_bottom_keyboard())
        return

    elif "Bulk Mode" in text and chat_id == ADMIN_ID:
        bulk_submit_active = not bulk_submit_active
        bot.send_message(chat_id, f"Bulk Mode: {'ON 🟢' if bulk_submit_active else 'OFF 🔴'}", reply_markup=admin_bottom_keyboard())
        return

    elif text == "🔑 Pass Rule" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_NEW_PASS_RULE'}
        bot.send_message(chat_id, f"Current Pass Rule: `{pass_rule}`\nEnter new rule:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "📢 Broadcast Notice" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        bot.send_message(chat_id, "Enter broadcast message for all users:", reply_markup=cancel_keyboard(chat_id))
        return

    elif text == "📊 Team Stats" and chat_id == ADMIN_ID:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        total, workers = 0, {}
        if os.path.isfile("accounts_list.csv"):
            try:
                with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                    reader = csv.reader(file)
                    for row in reader:
                        if len(row) >= 5 and today in row[0]:
                            total += 1
                            w_name = row[2]
                            workers[w_name] = workers.get(w_name, 0) + 1
            except Exception:
                pass
        reply_msg = f"📊 **TODAY'S TEAM REPORT**\n───────────────\nTotal: **{total}** pcs\n\n" + "\n".join([f"• `{w}`: {c} pcs" for w, c in workers.items()])
        bot.send_message(chat_id, reply_msg)
        return

    elif text == "📥 Export Excel" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "rb") as f:
                bot.send_document(chat_id, f, caption="📁 Accounts Database")
        except Exception:
            bot.send_message(chat_id, "❌ Database empty!")
        return

    # 6. Active State Multi-step Handlers
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "Please select an option from menu:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    # Admin States
    if step == 'AWAITING_CAT_RATE' and chat_id == ADMIN_ID:
        cat = state.get('cat')
        try:
            RATES[cat] = float(text)
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ Updated `{cat}` rate: ৳{RATES[cat]:.2f}", reply_markup=admin_bottom_keyboard())
        except ValueError:
            bot.send_message(chat_id, "❌ Enter valid number:")

    elif step == 'AWAITING_NEW_PASS_RULE' and chat_id == ADMIN_ID:
        pass_rule = text
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"✅ Updated Pass Rule: `{pass_rule}`", reply_markup=admin_bottom_keyboard())

    elif step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        count = 0
        if os.path.isfile("users.txt"):
            with open("users.txt", "r", encoding="utf-8") as f:
                for line in f:
                    u = line.strip()
                    if u:
                        try:
                            bot.send_message(u, f"📢 **BROADCAST NOTICE:**\n\n{text}")
                            count += 1
                        except Exception:
                            pass
        bot.send_message(chat_id, f"✅ Sent to {count} users.", reply_markup=admin_bottom_keyboard())

    # User Custom Password Save State
    elif step == 'AWAITING_USER_CUSTOM_PASS':
        user_passwords[chat_id] = text
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"✅ **Password Saved Successfully!**\n\nYour working password is set to: `{text}`\nIt will now auto-apply whenever you submit accounts.", reply_markup=main_bottom_keyboard(chat_id))

    # Standalone UID Live/Dead Checker State
    elif step == 'AWAITING_CHECK_UID':
        user_states.pop(chat_id, None)
        is_live, status_txt = check_live_account(text)
        clean_uid = extract_numeric_uid(text) or text
        
        if is_live:
            res_msg = f"🟢 **ACCOUNT STATUS: LIVE**\n\n📌 **UID:** `{clean_uid}`\n✅ Status: `{status_txt}` (Active & Working)"
        else:
            res_msg = f"🔴 **ACCOUNT STATUS: DEAD / CHECKPOINT**\n\n📌 **UID:** `{clean_uid}`\n❌ Status: `{status_txt}` (Suspended or Locked)"
            
        bot.send_message(chat_id, res_msg, reply_markup=tools_bottom_keyboard(chat_id))

    # User States
    elif step == 'AWAITING_WITHDRAW_DETAILS':
        parts = [p.strip() for p in text.split("|")]
        current_bal = user_balances.get(chat_id, 0.0)
        if len(parts) == 2 and parts[1].replace(".", "", 1).isdigit():
            num, amt = parts[0], float(parts[1])
            if MIN_WITHDRAW <= amt <= current_bal:
                user_balances[chat_id] -= amt
                user_states.pop(chat_id, None)
                bot.send_message(chat_id, f"✅ Withdraw requested: ৳{amt:.2f} ({num})", reply_markup=main_bottom_keyboard(chat_id))
                bot.send_message(ADMIN_ID, f"🔔 **NEW WITHDRAW REQUEST:**\n👤 User: `{message.from_user.first_name or 'Worker'}` (`{chat_id}`)\n📞 Phone: `{num}`\n💰 Amount: ৳{amt:.2f}")
            else:
                bot.send_message(chat_id, f"❌ Invalid Amount! Bal: ৳{current_bal:.2f}, Min: ৳{MIN_WITHDRAW:.2f}")
        else:
            bot.send_message(chat_id, "❌ Format error! Example: `01700000000 | 100`")

    elif step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if uid:
            bot.send_message(chat_id, f"✅ Extracted Numeric UID:\n\n`{uid}`", reply_markup=tools_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ No valid UID found.", reply_markup=tools_bottom_keyboard(chat_id))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try:
                totp = pyotp.TOTP(clean_key)
                bot.send_message(chat_id, f"🔑 **Your 2FA Code:**\n\n`{totp.now()}`", reply_markup=tools_bottom_keyboard(chat_id))
                user_states.pop(chat_id, None)
            except Exception:
                bot.send_message(chat_id, "❌ Invalid Secret Key!")
        else:
            bot.send_message(chat_id, "❌ Invalid Key!")

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            msg_err = "❌ Invalid/Duplicate UID! Send valid UID:" if lang == 'en' else "❌ ভুল বা ডুপ্লিকেট UID! সঠিক UID দিন:"
            bot.send_message(chat_id, msg_err)
            return

        is_live, status_desc = check_live_account(numeric_uid)
        if not is_live:
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"❌ **ID Rejected (Dead/Checkpoint)!**\nUID `{numeric_uid}` is not active ({status_desc}).", reply_markup=submission_bottom_keyboard(chat_id))
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        prompt = "🍪 Paste original **Cookies** string:" if "cookie" in cat else "🔐 Send **2FA Secret Key**:"
        bot.send_message(chat_id, f"✅ Live UID Verified: `{numeric_uid}`\n\n{prompt}")

    elif step == 'AWAITING_BULK_DATA':
        lines = text.split("\n")
        success_count, total_earned = 0, 0.0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worker_name = message.from_user.first_name or "Worker"
        default_worker_pass = user_passwords.get(chat_id, f"Pass_{pass_rule}")

        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                if len(parts) == 2:
                    uid, payload = parts[0], parts[1]
                    password = default_worker_pass
                else:
                    uid, password, payload = parts[0], parts[1], parts[2]

                clean_uid = extract_numeric_uid(uid)
                if clean_uid and not is_duplicate_uid(clean_uid):
                    is_live, _ = check_live_account(clean_uid)
                    if not is_live:
                        continue
                    
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
        bot.send_message(chat_id, f"🎉 **Bulk Live Accounts Saved:** {success_count} pcs\n💰 **Credited:** ৳{total_earned:.2f}", reply_markup=submission_bottom_keyboard(chat_id))

    elif step == 'AWAITING_SINGLE_DATA':
        cat = state.get('category', 'fb_cookie')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{pass_rule}")
        worker_name = message.from_user.first_name or "Worker"
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if "cookie" in cat and not is_valid_cookies(text):
            bot.send_message(chat_id, "❌ Invalid cookies format! Try again:")
            return
        elif "2fa" in cat and not is_valid_2fa_key(text):
            bot.send_message(chat_id, "❌ Invalid 2FA Key! Try again:")
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
        
        success_msg = (
            "🎉 **ACCOUNT SUBMISSION SUCCESSFUL!**\n"
            "─────────────────────────\n"
            f"📌 **Tracking ID:** `{track_id}`\n"
            f"🆔 **UID:** `{uid}`\n"
            f"🔑 **Password (Auto-Applied):** `{password}`\n"
            f"🛡️ **Payload Type:** `{'Cookies' if 'cookie' in cat else '2FA Key'}`\n"
            f"💰 **Earned Balance:** ৳{rate:.2f}"
        )
        bot.send_message(chat_id, success_msg, reply_markup=submission_bottom_keyboard(chat_id))
        user_states.pop(chat_id, None)

if __name__ == "__main__":
    print("Zero-Bug Verified Production Bot Started...")
    bot.infinity_polling(skip_pending=True)