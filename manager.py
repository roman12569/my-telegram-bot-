import os
import re
import csv
import random
import datetime
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

bot = telebot.TeleBot(TOKEN)

# Mandatory Channels List
REQUIRED_CHANNELS = [
    {"name": "Earning Bazar", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "Earning Method", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Earning Shop", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

# Dynamic Category Rates (Admin Configurable)
RATES = {
    "fb_cookie": 5.0,
    "fb_2fa": 6.0,
    "ig_cookie": 8.0,
    "ig_2fa": 10.0
}

# System Controls
single_submit_active = True
bulk_submit_active = True
pass_rule = "20"
MIN_WITHDRAW = 50.0

# Memory Storage
user_passwords = {}
user_states = {}
user_balances = {}

# ================= Helpers =================
def save_user(chat_id):
    users = set()
    if os.path.isfile("users.txt"):
        with open("users.txt", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    users.add(line.strip())
    if str(chat_id) not in users:
        with open("users.txt", "a", encoding="utf-8") as f:
            f.write(f"{chat_id}\n")

def is_banned(chat_id):
    if not os.path.isfile("banned.txt"):
        return False
    with open("banned.txt", "r", encoding="utf-8") as f:
        return str(chat_id) in f.read().splitlines()

def check_force_join(user_id):
    """মেম্বার সব চ্যানেলে জয়েন আছে কিনা চেক করার ফাংশন"""
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            print(f"Channel check error for {ch['username']}: {e}")
            return False
    return True

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

def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SPREADSHEET_ID)
    except Exception:
        return None

def save_to_sheet(tab_name, row_data):
    doc = get_google_sheet()
    if doc:
        try:
            worksheet = doc.worksheet(tab_name)
            worksheet.append_row(row_data)
            return True
        except Exception:
            return False
    return False

# ================= KEYBOARDS & UI =================

def force_join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(InlineKeyboardButton("✅ Verified / চেক করুন", callback_data="verify_join"))
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
        InlineKeyboardButton("📊 এক্সেল / শিট জমা (Excel)", callback_data="sub_excel"),
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

def inline_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    single_status = "🟢" if single_submit_active else "🔴"
    bulk_status = "🟢" if bulk_submit_active else "🔴"
    
    markup.add(
        InlineKeyboardButton("💰 ক্যাটাগরি রেট সেট", callback_data="adm_rates"),
        InlineKeyboardButton(f"{single_status} সিঙ্গেল জমা Toggle", callback_data="adm_toggle_single")
    )
    markup.add(
        InlineKeyboardButton(f"{bulk_status} বাল্ক/এক্সেল Toggle", callback_data="adm_toggle_bulk"),
        InlineKeyboardButton("🔑 পাসওয়ার্ড নিয়ম চেঞ্জ", callback_data="adm_pass_rule")
    )
    markup.add(
        InlineKeyboardButton("📊 টিমের হিসাব", callback_data="adm_stats"),
        InlineKeyboardButton("📥 এক্সেল ডাউনলোড", callback_data="adm_excel")
    )
    markup.add(
        InlineKeyboardButton("📢 ব্রডকাস্ট নোটিশ", callback_data="adm_notice"),
        InlineKeyboardButton("📄 বায়ার TXT ফাইল", callback_data="adm_txt")
    )
    return markup

# ================= START & FORCE JOIN CHECK =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।")
        return
    
    save_user(message.chat.id)
    user_states.pop(message.chat.id, None)

    if not check_force_join(message.chat.id):
        text = (
            "🔒 **বট ব্যবহার করতে আমাদের অফিসিয়াল চ্যানেলগুলোতে জয়েন করুন!**\n\n"
            "নিচের সবগুলো চ্যানেলে জয়েন করে ** Verified / চেক করুন ** বোতামে চাপ দিন:"
        )
        bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=force_join_keyboard())
        return

    welcome_text = (
        "╔════════════════════════════╗\n"
        "   👑  *ONLINE EARNING BAZAR*  👑\n"
        "╚════════════════════════════╝\n\n"
        "✨ *স্বাগতম আন্তর্জাতিক মানের অটোমেশন বোট প্যানেলে!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *বর্তমান ক্যাটাগরি রেটসমূহ:*\n"
        f"• Facebook Cookies: `৳{RATES['fb_cookie']}` / পিস\n"
        f"• Facebook 2FA: `৳{RATES['fb_2fa']}` / পিস\n"
        f"• Instagram Cookies: `৳{RATES['ig_cookie']}` / পিস\n"
        f"• Instagram 2FA: `৳{RATES['ig_2fa']}` / পিস\n\n"
        "🎯 কাজের ধরন অনুযায়ী নিচের মেনু থেকে বেছে নিন:"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text == "❌ 𝘾𝙖𝙣𝙘𝙚𝙡 / বাতিল")
def cancel_action(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "🚫 বর্তমান কাজটি বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(message.chat.id))

# Bottom Buttons Listeners

@bot.message_handler(func=lambda msg: msg.text == "⚡ 𝙄𝘿 𝙎𝙪𝙗𝙢𝙞𝙨𝙨𝙞𝙤𝙣 ⚡")
def category_submission(message):
    if not check_force_join(message.chat.id):
        bot.send_message(message.chat.id, "🔒 আগে সবকটি চ্যানেলে জয়েন করুন!", reply_markup=force_join_keyboard())
        return
    text = "📥 *ID SUBMISSION CENTER*\n━━━━━━━━━━━━━━━━━━━━\nজমা দেওয়ার মাধ্যম নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_submission_menu())

@bot.message_handler(func=lambda msg: msg.text == "🛠️ 𝙒𝙤𝙧𝙠𝙚𝙧 𝙏𝙤𝙤𝙡𝙨")
def category_tools(message):
    text = "🛠️ *WORKER HELPER SUITE*\n━━━━━━━━━━━━━━━━━━━━\nআপনার প্রয়োজনীয় সার্ভিসটি বেছে নিন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_tools_menu())

@bot.message_handler(func=lambda msg: msg.text == "👤 𝙈𝙮 𝙋𝙧𝙤𝙛𝙞𝙡𝙚")
def category_profile(message):
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    daily_c = get_user_daily_count(worker_name)
    balance = user_balances.get(chat_id, 0.0)

    text = (
        "┌─────────────────────────┐\n"
        "   👤  *WORKER DASHBOARD*  \n"
        "└─────────────────────────┘\n\n"
        f"👤 *নাম:* `{worker_name}`\n"
        f"📈 *আজকের জমা:* `{daily_c}` টি\n"
        f"💎 *বর্তমান ইনকাম ব্যালেন্স:* `৳{balance:.2f}`\n"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 টাকা তুলুন (Withdraw)", callback_data="prof_withdraw"))
    markup.add(InlineKeyboardButton("🔗 রেফারেল লিংক", callback_data="prof_ref"))
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "🏆 𝙇𝙚𝙖𝙙𝙚𝙧𝙤𝙖𝙧𝙙")
def show_leaderboard(message):
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
    text = "🏆 *TODAY'S TOP WORKERS*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not sorted_workers:
        text += "আজ এখনো কোনো কাজ জমা পড়েনি।"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, count) in enumerate(sorted_workers):
            text += f"{medals[idx]} `{name}` — **{count}** টি আইডি\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "👑 𝘼𝙙𝙢𝙞𝙣 𝙋𝙖𝙣𝙚𝙡")
def category_admin(message):
    if message.chat.id != ADMIN_ID:
        return
    text = "👑 *SECRET ADMIN CONTROL PANEL*\n━━━━━━━━━━━━━━━━━━━━\nএডমিন কন্ট্রোল অপশন নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_admin_menu())

# ================= INLINE CALLBACK HANDLERS =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data
    global single_submit_active, bulk_submit_active, pass_rule

    if code == "verify_join":
        if check_force_join(chat_id):
            bot.answer_callback_query(call.id, "✅ ভেরিফিকেশন সফল হয়েছে!", show_alert=True)
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "🎉 স্বাগতম! এখন আপনি বটের সব সার্ভিস ব্যবহার করতে পারবেন।", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.answer_callback_query(call.id, "❌ আপনি এখনো সবগুলো চ্যানেলে জয়েন করেননি!", show_alert=True)
        return

    # --- Submission Routing ---
    if code == "sub_single":
        if not single_submit_active:
            bot.answer_callback_query(call.id, "⚠️ এডমিন বর্তমানে সিঙ্গেল জমা বন্ধ রেখেছেন!", show_alert=True)
            return
        bot.send_message(chat_id, "📌 প্রথমে আপনার আইডির ক্যাটাগরি বেছে নিন:", reply_markup=category_selection_keyboard())

    elif code.startswith("cat_"):
        cat_type = code.replace("cat_", "")
        user_states[chat_id] = {'step': 'AWAITING_UID', 'category': cat_type}
        bot.send_message(chat_id, "🆔 *১৫-২০ ডিজিটের UID লিখুন:*", parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "sub_bulk":
        if not bulk_submit_active:
            bot.answer_callback_query(call.id, "⚠️ এডমিন বর্তমানে বাল্ক/এক্সেল জমা বন্ধ রেখেছেন!", show_alert=True)
            return
        bot.send_message(chat_id, "📌 বাল্ক জমা দিতে ক্যাটাগরি সিলেক্ট করুন:", reply_markup=category_selection_keyboard())

    elif code == "sub_excel":
        if not bulk_submit_active:
            bot.answer_callback_query(call.id, "⚠️ এডমিন বর্তমানে বাল্ক/এক্সেল জমা বন্ধ রেখেছেন!", show_alert=True)
            return
        user_states[chat_id] = {'step': 'AWAITING_EXCEL_FILE'}
        text = "📄 *Google Sheet/Excel ফাইল (.xlsx/csv) পাঠান:*\n\nকলাম ফরম্যাট এমন হতে হবে:\n`UID` | `Password` | `Cookies/2FA`"
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "sub_pass_settings":
        text = f"🔑 *পাসওয়ার্ড রুল:* `{pass_rule}`\n\nপাসওয়ার্ডে অবশ্যই `{pass_rule}` থাকতে হবে।"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⚙️ ডিফল্ট পাসওয়ার্ড সেভ করুন", callback_data="set_def_pass"))
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

    elif code == "set_def_pass":
        user_states[chat_id] = {'step': 'AWAITING_NEW_PASS'}
        bot.send_message(chat_id, "🔑 আপনার সেভ করতে চাওয়া পাসওয়ার্ড লিখুন:", reply_markup=cancel_keyboard())

    # --- Admin Config Callbacks ---
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
        bot.send_message(chat_id, "💰 কোন ক্যাটাগরির রেট পরিবর্তন করতে চান সিলেক্ট করুন:", reply_markup=markup)

    elif code.startswith("rate_") and chat_id == ADMIN_ID:
        selected_cat = code.replace("rate_", "")
        user_states[chat_id] = {'step': 'AWAITING_CAT_RATE', 'cat': selected_cat}
        bot.send_message(chat_id, f"💰 `{selected_cat}` এর নতুন দাম কত টাকা দিতে চান টাইপ করুন (যেমন: 6.5):", parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "adm_toggle_single" and chat_id == ADMIN_ID:
        single_submit_active = not single_submit_active
        status = "অন 🟢" if single_submit_active else "অফ 🔴"
        bot.answer_callback_query(call.id, f"সিঙ্গেল জমা {status} করা হয়েছে!", show_alert=True)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=inline_admin_menu())

    elif code == "adm_toggle_bulk" and chat_id == ADMIN_ID:
        bulk_submit_active = not bulk_submit_active
        status = "অন 🟢" if bulk_submit_active else "অফ 🔴"
        bot.answer_callback_query(call.id, f"বাল্ক ও এক্সেল জমা {status} করা হয়েছে!", show_alert=True)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=inline_admin_menu())

    elif code == "adm_pass_rule" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_NEW_PASS_RULE'}
        bot.send_message(chat_id, f"🔑 বর্তমান নিয়ম `{pass_rule}`\n\nনতুন নিয়ম টাইপ করুন:", reply_markup=cancel_keyboard())

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
        reply_msg = f"📊 *আজকের মোট জমা:* **{total}** টি\n\n" + "\n".join([f"• `{w}`: {c}টি" for w, c in workers.items()])
        bot.send_message(chat_id, reply_msg, parse_mode="Markdown")

    elif code == "adm_excel" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "rb") as f:
                bot.send_document(chat_id, f, caption="📁 Excel File")
        except Exception:
            bot.answer_callback_query(call.id, "❌ ডাটা খালি!", show_alert=True)

    elif code == "adm_notice" and chat_id == ADMIN_ID:
        user_states[chat_id] = {'step': 'AWAITING_BROADCAST_MSG'}
        bot.send_message(chat_id, "📢 ব্রডকাস্ট নোটিশ লিখুন:", reply_markup=cancel_keyboard())

    # --- Profile & Tools Callbacks ---
    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, f"⚠️ টাকা তুলতে সর্বনিম্ন ৳{MIN_WITHDRAW:.2f} লাগবে। আপনার আছে ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নম্বর এবং পরিমাণ দিন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard())

    elif code == "prof_ref":
        bot_uname = bot.get_me().username
        bot.send_message(chat_id, f"🔗 *আপনার রেফারেল লিংক:*\n`https://t.me/{bot_uname}?start={chat_id}`\n\nরেফারে পাবেন ৳২.০০ বোনাস!", parse_mode="Markdown")

    elif code == "tool_2fa":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 2FA Secret Key দিন:", parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "tool_uid":
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 ফেসবুক/ইনস্টাগ্রাম প্রফাইল লিংক দিন:", parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "tool_mail":
        try:
            domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
            domain = random.choice(domains)
            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
            email = f"{username}@{domain}"
            bot.send_message(chat_id, f"📧 *Temp Mail:* `{email}`", parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, "❌ এরর হয়েছে!")

# ================= DOCUMENT / EXCEL FILE HANDLER =================

@bot.message_handler(content_types=['document'])
def handle_excel_document(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    
    if state and state.get('step') == 'AWAITING_EXCEL_FILE':
        if not bulk_submit_active:
            bot.send_message(chat_id, "⚠️ বর্তমানে ফাইল বা বাল্ক জমা বন্ধ আছে!", reply_markup=main_bottom_keyboard(chat_id))
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
                        
                        save_to_sheet(tab, [now_str, track_id, str(chat_id), clean_uid, password, payload])
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

            bot.reply_to(message, f"🎉 *এক্সেল ফাইল প্রসেস সফল!*\n\n✅ যোগ করা হয়েছে: **{success_count}** টি আইডি\n💰 অর্জিত টাকা: ৳{total_earned:.2f}", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))
        
        except Exception:
            bot.reply_to(message, "❌ ফাইল প্রসেস করতে ব্যর্থ হয়েছে! সঠিক ফরম্যাটে .xlsx বা .csv ফাইল আপলোড করুন।")

# ================= GENERAL STATE MESSAGE HANDLER =================

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)
    global pass_rule

    if not state:
        bot.send_message(chat_id, "নিচের মেনু থেকে অপশন বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    # Admin State Actions
    if step == 'AWAITING_CAT_RATE' and chat_id == ADMIN_ID:
        cat = state.get('cat')
        try:
            new_r = float(text)
            RATES[cat] = new_r
            user_states.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ `{cat}` এর নতুন রেট আপডেট হয়েছে: ৳{new_r:.2f}", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))
        except ValueError:
            bot.send_message(chat_id, "❌ সঠিক সংখ্যা লিখুন (যেমন: 6.5):")

    elif step == 'AWAITING_NEW_PASS_RULE' and chat_id == ADMIN_ID:
        pass_rule = text
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"✅ পাসওয়ার্ড রুল আপডেট হয়েছে: `{pass_rule}`", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_BROADCAST_MSG' and chat_id == ADMIN_ID:
        user_states.pop(chat_id, None)
        count = 0
        if os.path.isfile("users.txt"):
            with open("users.txt", "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        bot.send_message(line.strip(), f"📢 *NOTICE FROM ADMIN:*\n\n{text}", parse_mode="Markdown")
                        count += 1
                    except Exception:
                        pass
        bot.send_message(chat_id, f"✅ {count} জনের কাছে নোটিশ চলে গেছে!", reply_markup=main_bottom_keyboard(chat_id))

    # User States Actions
    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID! অন্য UID দিন:")
            return

        cat = state.get('category', 'fb_cookie')
        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_SINGLE_DATA'
        
        req_type = "Cookies" if "cookie" in cat else "2FA Key"
        bot.send_message(chat_id, f"✅ UID গৃহীত: `{numeric_uid}`\n\nএখন আপনার **{req_type}** পেস্ট করুন:", parse_mode="Markdown")

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
        
        save_to_sheet(tab, [now_str, track_id, str(chat_id), uid, password, text])
        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                writer.writerow(["Date & Time", "Tracking ID", "Worker Name", "UID", "Password", "2FA/Cookies"])
            writer.writerow([now_str, track_id, worker_name, uid, password, text])

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + rate
        bot.send_message(
            chat_id, 
            f"🎉 *জমা সফল হয়েছে!*\n\n📌 **Tracking ID:** `{track_id}`\n📌 **UID:** `{uid}`\n💰 যোগ হয়েছে: ৳{rate:.2f}", 
            parse_mode="Markdown", 
            reply_markup=main_bottom_keyboard(chat_id)
        )
        user_states.pop(chat_id, None)

# ================= RUNNER =================
if __name__ == "__main__":
    print("Bot Running with Category Rates & Mandatory Channel System...")
    bot.infinity_polling(skip_pending=True)