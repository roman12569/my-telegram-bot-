import os
import re
import csv
import random
import datetime
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
DAILY_TARGET = 20

bot = telebot.TeleBot(TOKEN)

# In-Memory State & Settings
user_passwords = {}
user_states = {}
user_languages = {} # Language Preference ('bn' or 'en')

# ================= Name & Picture Database =================
FIRST_NAMES = [
    "Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi", "Jahid", "Shohel",
    "Rashed", "Al-Amin", "Monir", "Ripon", "Sumon", "Ariful", "Nazmul", "Sujon", "Hasan", "Hossain",
    "Anik", "Parvez", "Shihab", "Rony", "Joy", "Rifat", "Akash", "Arman", "Rubel", "Mamun",
    "Nusrat", "Sadia", "Jannat", "Mim", "Tania", "Bristy", "Priya", "Puja", "Tasnim", "Mahiya",
    "Farzana", "Sumaiya", "Nipa", "Ananna", "Mehedina", "Meem", "Rimi", "Sharmin", "Sabrina", "Fariha"
]

LAST_NAMES = [
    "Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury", "Khan", "Sarker", "Talukder", "Bhuiyan",
    "Miah", "Khandakar", "Ali", "Sheikh", "Biswas", "Roy", "Das", "Hawlader", "Dewan", "Firoz"
]

HUMAN_FACES = [
    "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=400&h=400&fit=crop"
]

# ================= Google Sheets Helper =================
def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID)
        return sheet
    except Exception as e:
        print(f"⚠️ Google Sheet Connection Error: {e}")
        return None

def save_to_sheet(tab_name, row_data):
    doc = get_google_sheet()
    if doc:
        try:
            worksheet = doc.worksheet(tab_name)
            worksheet.append_row(row_data)
            return True
        except Exception as e:
            print(f"⚠️ Sheet Append Error ({tab_name}): {e}")
            return False
    return False

# ================= Local File Helpers =================
def get_pass_rule():
    if not os.path.isfile("pass_rule.txt"):
        with open("pass_rule.txt", "w", encoding="utf-8") as f:
            f.write("20")
    with open("pass_rule.txt", "r", encoding="utf-8") as f:
        return f.read().strip()

def set_pass_rule(new_rule):
    with open("pass_rule.txt", "w", encoding="utf-8") as f:
        f.write(new_rule)

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
        banned_users = f.read().splitlines()
    return str(chat_id) in banned_users

def ban_user(chat_id):
    with open("banned.txt", "a", encoding="utf-8") as f:
        f.write(f"{chat_id}\n")

def is_duplicate_uid(uid):
    if not os.path.isfile("accounts_list.csv"):
        return False
    with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) > 2 and row[2] == uid:
                return True
    return False

def get_user_daily_count(worker_name):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    count = 0
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 2 and today in row[0] and worker_name == row[1]:
                    count += 1
    return count

# ================= Validation Helpers =================
def is_valid_uid(uid_str):
    return bool(re.match(r'^\d{8,20}$', uid_str.strip()))

def is_valid_2fa_key(key_str):
    cleaned = key_str.replace(" ", "").upper()
    return bool(re.match(r'^[A-Z2-7]{16,32}$', cleaned))

def is_valid_cookies(cookie_str):
    return ("c_user=" in cookie_str) or ("datr=" in cookie_str) or ("xs=" in cookie_str)

# ================= Menus & Keyboards =================
def get_language_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
        InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")
    )
    return markup

def worker_menu(chat_id):
    lang = user_languages.get(chat_id, 'bn')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if lang == 'en':
        markup.add(KeyboardButton("📥 Submit Single ID"), KeyboardButton("📦 Bulk Submit IDs"))
        markup.add(KeyboardButton("👤 Random Name Gen"), KeyboardButton("🖼️ Fake Picture Gen"))
        markup.add(KeyboardButton("📧 Get Temp Mail"), KeyboardButton("🔑 Generate 2FA Code"))
        markup.add(KeyboardButton("⚙️ Set Default Pass"), KeyboardButton("🔑 Today's Password"))
        markup.add(KeyboardButton("📋 My Submissions"), KeyboardButton("🌐 Change Language"))
    else:
        markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("📦 একসাথে অনেক জমা দিন"))
        markup.add(KeyboardButton("👤 রেন্ডম নাম জেনারেট"), KeyboardButton("🖼️ ফেক পিকচার জেনারেট"))
        markup.add(KeyboardButton("📧 টেম্প মেইল নিন"), KeyboardButton("🔑 2FA কোড জেনারেট করুন"))
        markup.add(KeyboardButton("⚙️ পাসওয়ার্ড সেট করুন"), KeyboardButton("🔑 আজকের পাসওয়ার্ড"))
        markup.add(KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"), KeyboardButton("🌐 ভাষা পরিবর্তন"))
    return markup

def admin_menu(chat_id):
    lang = user_languages.get(chat_id, 'bn')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if lang == 'en':
        markup.add(KeyboardButton("📥 Submit Single ID"), KeyboardButton("📦 Bulk Submit IDs"))
        markup.add(KeyboardButton("👤 Random Name Gen"), KeyboardButton("🖼️ Fake Picture Gen"))
        markup.add(KeyboardButton("📧 Get Temp Mail"), KeyboardButton("🔑 Generate 2FA Code"))
        markup.add(KeyboardButton("⚙️ Set Default Pass"), KeyboardButton("🔑 Today's Password"))
        markup.add(KeyboardButton("📋 My Submissions"), KeyboardButton("🌐 Change Language"))
        markup.add(KeyboardButton("📊 Team Stats"), KeyboardButton("⚙️ Admin Panel"))
    else:
        markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("📦 একসাথে অনেক জমা দিন"))
        markup.add(KeyboardButton("👤 রেন্ডম নাম জেনারেট"), KeyboardButton("🖼️ ফেক পিকচার জেনারেট"))
        markup.add(KeyboardButton("📧 টেম্প মেইল নিন"), KeyboardButton("🔑 2FA কোড জেনারেট করুন"))
        markup.add(KeyboardButton("⚙️ পাসওয়ার্ড সেট করুন"), KeyboardButton("🔑 আজকের পাসওয়ার্ড"))
        markup.add(KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"), KeyboardButton("🌐 ভাষা পরিবর্তন"))
        markup.add(KeyboardButton("📊 টিমের কাজের হিসাব"), KeyboardButton("⚙️ এডমিন প্যানেল"))
    return markup

def get_cancel_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'bn')
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ Cancel" if lang == 'en' else "❌ বাতিল করুন"))
    return markup

def get_submit_type_keyboard(chat_id):
    lang = user_languages.get(chat_id, 'bn')
    markup = InlineKeyboardMarkup(row_width=2)
    btn_cookie = InlineKeyboardButton("🍪 Cookies", callback_data="type_cookie")
    btn_2fa = InlineKeyboardButton("🔐 2FA Key", callback_data="type_2fa")
    btn_cancel = InlineKeyboardButton("❌ Cancel" if lang == 'en' else "❌ বাতিল করুন", callback_data="cancel_action")
    markup.add(btn_cookie, btn_2fa, btn_cancel)
    return markup

# ================= Start & Language Selection =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 𝗔𝗽𝗻𝗮𝗸𝗲 𝗯𝗼𝘁 theke ban kora hoyeche!")
        return
    user_states.pop(message.chat.id, None)
    save_user(message.chat.id)
    
    welcome_text = (
        "🌐 **Choose Your Preferred Language / আপনার পছন্দনীয় ভাষা নির্বাচন করুন:**"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=get_language_keyboard())

@bot.callback_query_handler(func=lambda call: call.data in ["lang_bn", "lang_en"])
def set_language_callback(call):
    chat_id = call.message.chat.id
    if call.data == "lang_en":
        user_languages[chat_id] = 'en'
        text = "✅ Language set to **English**!"
    else:
        user_languages[chat_id] = 'bn'
        text = "✅ ভাষা **বাংলা** নির্বাচন করা হয়েছে!"
        
    bot.answer_callback_query(call.id, text)
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

@bot.message_handler(func=lambda msg: msg.text in ["🌐 ভাষা পরিবর্তন", "🌐 Change Language"])
def change_language_handler(message):
    bot.send_message(message.chat.id, "🌐 Choose Language / ভাষা নির্বাচন করুন:", reply_markup=get_language_keyboard())

@bot.message_handler(func=lambda msg: msg.text in ["❌ বাতিল করুন", "❌ Cancel"])
def cancel_process(message):
    user_states.pop(message.chat.id, None)
    lang = user_languages.get(message.chat.id, 'bn')
    msg_text = "🚫 Action cancelled." if lang == 'en' else "🚫 বর্তমান কাজটি বাতিল করা হয়েছে।"
    bot.send_message(message.chat.id, msg_text, reply_markup=admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id))

# ================= Temp Mail Engine =================
@bot.message_handler(func=lambda message: message.text in ["📧 টেম্প মেইল নিন", "📧 Get Temp Mail"])
def create_mail(message):
    try:
        domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
        domain = random.choice(domains)
        username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
        email = f"{username}@{domain}"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔄 Check Inbox (OTP)", callback_data=f"inbox_{username}_{domain}"))

        bot.send_message(
            message.chat.id,
            f"┌──────────────────────┐\n"
            f"  📧 **𝗧𝗘𝗠𝗣𝗢𝗥𝗔𝗥𝗬 𝗠𝗔𝗜𝗟𝗕𝗢𝗫**\n"
            f"└──────────────────────┘\n\n"
            f"📧 Temp Mail:\n\n`{email}`",
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception:
        bot.reply_to(message, "❌ Error generating email!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox_"))
def check_inbox(call):
    try:
        parts = call.data.split("_")
        username, domain = parts[1], parts[2]
        email = f"{username}@{domain}"

        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={username}&domain={domain}"
        response = requests.get(url, timeout=10)
        messages = response.json()

        if not messages:
            bot.answer_callback_query(call.id, "📭 Inbox Empty!", show_alert=True)
            return

        text = f"📬 **Inbox Messages for:** `{email}`\n\n"
        for msg in messages:
            msg_id = msg['id']
            subject = msg['subject']
            sender = msg['from']
            msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={username}&domain={domain}&id={msg_id}"
            msg_res = requests.get(msg_url, timeout=10).json()
            body = msg_res.get('textBody', 'No content')
            text += f"👤 **From:** {sender}\n📌 **Subject:** {subject}\n\n💬 **Content/OTP:**\n`{body}`\n-------------------\n"

        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
        bot.answer_callback_query(call.id, "✅ Checked Inbox!")
    except Exception:
        bot.answer_callback_query(call.id, "❌ Error checking inbox!", show_alert=True)

# ================= Generators & Details =================
@bot.message_handler(func=lambda message: message.text in ["🖼️ ফেক পিকচার জেনারেট", "🖼️ Fake Picture Gen"])
def generate_fake_picture(message):
    try:
        selected_face = random.choice(HUMAN_FACES)
        caption_text = (
            "┌──────────────────────┐\n"
            "  🖼️ **𝗥𝗘𝗔𝗟𝗜𝗦𝗧𝗜𝗖 𝗛𝗨𝗠𝗔𝗡 𝗙𝗔𝗖𝗘**\n"
            "└──────────────────────┘\n\n"
            "✨ *Use this photo for your profiles.*"
        )
        markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
        bot.send_photo(message.chat.id, selected_face, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.reply_to(message, "❌ Error loading image!")

@bot.message_handler(func=lambda message: message.text in ["👤 রেন্ডম নাম জেনারেট", "👤 Random Name Gen"])
def generate_fake_name(message):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    birth_year = random.randint(1995, 2004)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    name_text = (
        f"┌──────────────────────┐\n"
        f"  👤 **𝗙𝗔𝗞𝗘 𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗗𝗘𝗧𝗔𝗜𝗟𝗦**\n"
        f"└──────────────────────┘\n\n"
        f"🔹 **First Name:** `{first}`\n"
        f"🔹 **Last Name:** `{last}`\n"
        f"🔹 **Full Name:** `{first} {last}`\n"
        f"🔹 **DOB:** `{birth_day}-{birth_month}-{birth_year}`"
    )
    markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
    bot.reply_to(message, name_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["🔑 আজকের পাসওয়ার্ড", "🔑 Today's Password"])
def show_current_password(message):
    current_rule = get_pass_rule()
    pass_text = (
        f"┌──────────────────────┐\n"
        f"  🔑 **𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗥𝗨𝗟𝗘𝗦**\n"
        f"└──────────────────────┘\n\n"
        f"✨ Today's Password must contain:\n👉 `{current_rule}`"
    )
    markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
    bot.reply_to(message, pass_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["📋 আমার জমা দেওয়া লিস্ট", "📋 My Submissions"])
def show_my_submissions(message):
    worker_name = message.from_user.first_name
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    uids = []
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 3 and today in row[0] and worker_name == row[1]:
                    uids.append(row[2])
    if not uids:
        text = f"📋 **{worker_name}**, you haven't submitted any accounts today."
    else:
        text = f"┌──────────────────────┐\n  📋 **𝗬𝗢𝗨𝗥 𝗦𝗨𝗕𝗠𝗜𝗦𝗦𝗜𝗢𝗡𝗦** ({len(uids)})\n└──────────────────────┘\n\n"
        for i, uid in enumerate(uids, 1):
            text += f"`{i}.` UID: `{uid}`\n"
    markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

# ================= Password & TOTP Code Handlers =================
@bot.message_handler(func=lambda msg: msg.text in ["⚙️ পাসওয়ার্ড সেট করুন", "⚙️ Set Default Pass"])
def set_pass_start(message):
    lang = user_languages.get(message.chat.id, 'bn')
    user_states[message.chat.id] = {'step': 'AWAITING_NEW_PASS'}
    msg_text = "🔑 Enter default password to save:" if lang == 'en' else "🔑 আপনার সেভ করতে চাওয়া ডিফল্ট পাসওয়ার্ডটি লিখুন:"
    bot.send_message(message.chat.id, msg_text, reply_markup=get_cancel_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["🔑 2FA কোড জেনারেট করুন", "🔑 Generate 2FA Code"])
def generate_2fa_start(message):
    lang = user_languages.get(message.chat.id, 'bn')
    user_states[message.chat.id] = {'step': 'AWAITING_2FA_GEN'}
    msg_text = "📌 Enter your 2FA Secret Key (e.g., `JBSWY3DPEHPK3PXP`):" if lang == 'en' else "📌 আপনার 2FA Key/Secret Key-টি দিন (যেমন: `JBSWY3DPEHPK3PXP`):"
    bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

# ================= Bulk Submission Flow =================
@bot.message_handler(func=lambda message: message.text in ["📦 একসাথে অনেক জমা দিন", "📦 Bulk Submit IDs"])
def bulk_submit_start(message):
    if is_banned(message.chat.id):
        return
    lang = user_languages.get(message.chat.id, 'bn')
    user_states[message.chat.id] = {'step': 'AWAITING_BULK_DATA'}
    
    msg_text = (
        "📦 **Bulk Submission Format:**\n\n"
        "Send multiple IDs line by line using this format:\n"
        "`UID | Password | Cookies/2FA`\n\n"
        "Example:\n"
        "`100084728192 | Pass123 | datr=abc...`\n"
        "`100084728193 | Pass123 | JBSWY3D...`"
    ) if lang == 'en' else (
        "📦 **একসাথে একাধিক ডাটা জমা দিন:**\n\n"
        "নিচের ফরম্যাটে প্রতি লাইনে একটি করে ডাটা পেস্ট করুন:\n"
        "`UID | Password | Cookies/2FA`\n\n"
        "উদাহরণ:\n"
        "`100084728192 | Pass123 | datr=abc...`\n"
        "`100084728193 | Pass123 | JBSWY3D...`"
    )
    bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

# ================= Admin Functions =================
@bot.message_handler(func=lambda message: message.text in ["📊 টিমের কাজের হিসাব", "📊 Team Stats"])
def team_stats(message):
    if message.chat.id != ADMIN_ID:
        return
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    total, workers = 0, {}
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 5 and today in row[0]:
                    total += 1
                    w_name = row[1]
                    workers[w_name] = workers.get(w_name, 0) + 1
    if total == 0:
        bot.reply_to(message, "⚠️ No accounts submitted today.", reply_markup=admin_menu(message.chat.id))
        return
    reply_msg = f"┌──────────────────────┐\n  📊 **𝗧𝗘𝗔𝗠 𝗥𝗘𝗣𝗢𝗥𝗧**\n└──────────────────────┘\n\n🔥 Total: **{total}** Accounts\n\n"
    for w, c in workers.items():
        reply_msg += f"• 👤 `{w}` — **{c}** pcs\n"
    bot.reply_to(message, reply_msg, parse_mode="Markdown", reply_markup=admin_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text in ["⚙️ এডমিন প্যানেল", "⚙️ Admin Panel"])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📥 Download Excel", callback_data="download_excel"),
        InlineKeyboardButton("📄 Download Buyer TXT", callback_data="download_txt"),
        InlineKeyboardButton("📢 Broadcast Notice", callback_data="send_notice"),
        InlineKeyboardButton("🔑 Change Password Rule", callback_data="change_pass"),
        InlineKeyboardButton("🚫 Ban Worker", callback_data="ban_user"),
        InlineKeyboardButton("🗑️ Reset Data", callback_data="reset_data")
    )
    bot.reply_to(message, "⚙️ **𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: not call.data.startswith("inbox_") and call.data not in ["type_cookie", "type_2fa", "cancel_action", "lang_bn", "lang_en"])
def handle_admin_query(call):
    if call.message.chat.id != ADMIN_ID:
        return
    if call.data == "download_excel":
        try:
            with open("accounts_list.csv", "rb") as file:
                bot.send_document(call.message.chat.id, file, caption="📁 Excel File")
        except Exception:
            bot.answer_callback_query(call.id, "❌ File empty!")
    elif call.data == "download_txt":
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as csv_file, open("buyer_ready.txt", "w", encoding="utf-8") as txt_file:
                reader = csv.reader(csv_file)
                for row in reader:
                    if len(row) >= 5 and row[2] != "UID":
                        txt_file.write(f"{row[2]} | {row[3]} | {row[4]}\n")
            with open("buyer_ready.txt", "rb") as file:
                bot.send_document(call.message.chat.id, file, caption="📄 TXT File")
        except Exception:
            bot.answer_callback_query(call.id, "❌ Error!")
    elif call.data == "change_pass":
        msg = bot.send_message(call.message.chat.id, "Write new password rule:")
        bot.register_next_step_handler(msg, update_pass_rule)
    elif call.data == "send_notice":
        msg = bot.send_message(call.message.chat.id, "Write broadcast message:")
        bot.register_next_step_handler(msg, process_broadcast)
    elif call.data == "ban_user":
        msg = bot.send_message(call.message.chat.id, "Enter Telegram ID to ban:")
        bot.register_next_step_handler(msg, process_ban)
    elif call.data == "reset_data":
        if os.path.isfile("accounts_list.csv"):
            os.remove("accounts_list.csv")
        bot.answer_callback_query(call.id, "✅ Reset completed!", show_alert=True)
        bot.send_message(call.message.chat.id, "🗑️ Data cleared.")

def update_pass_rule(message):
    set_pass_rule(message.text.strip())
    bot.reply_to(message, f"✅ Rule updated: `{message.text.strip()}`", parse_mode="Markdown", reply_markup=admin_menu(message.chat.id))

def process_broadcast(message):
    count = 0
    if os.path.isfile("users.txt"):
        with open("users.txt", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        bot.send_message(line.strip(), f"📢 **NOTICE:**\n\n{message.text}", parse_mode="Markdown")
                        count += 1
                    except Exception:
                        pass
    bot.reply_to(message, f"✅ Notice sent to {count} users.", reply_markup=admin_menu(message.chat.id))

def process_ban(message):
    if message.text.strip().isdigit():
        ban_user(message.text.strip())
        bot.reply_to(message, "✅ Banned successfully!", reply_markup=admin_menu(message.chat.id))

# ================= Single Submit ID Flow =================
@bot.message_handler(func=lambda message: message.text in ["📝 অ্যাকাউন্ট জমা দিন", "📥 আইডি জমা দিন", "📥 Submit Single ID"])
def submit_id_start(message):
    if is_banned(message.chat.id):
        return
    lang = user_languages.get(message.chat.id, 'bn')
    user_states[message.chat.id] = {'step': 'AWAITING_UID'}
    msg_text = "🆔 Enter **UID** (numbers only):" if lang == 'en' else "🆔 অনুগ্রহ করে আপনার **UID** দিন (কেবল মাত্র সংখ্যা):"
    bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

# ================= Inline Callbacks for Submission =================
@bot.callback_query_handler(func=lambda call: call.data in ["type_cookie", "type_2fa", "cancel_action"])
def handle_submission_callback(call):
    chat_id = call.message.chat.id
    lang = user_languages.get(chat_id, 'bn')

    if call.data == "cancel_action":
        user_states.pop(chat_id, None)
        bot.edit_message_text("🚫 Action cancelled.", chat_id=chat_id, message_id=call.message.message_id)
        bot.send_message(chat_id, "Main Menu:", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        return

    state = user_states.get(chat_id)
    if not state or state.get('step') != 'AWAITING_TYPE_SELECTION':
        bot.answer_callback_query(call.id, "Expired! Try again.")
        return

    if call.data == "type_cookie":
        state['type'] = 'COOKIE'
        state['step'] = 'AWAITING_DATA'
        msg_text = "🍪 Paste your **Cookies**:" if lang == 'en' else "🍪 আপনার **Cookies** পেস্ট করুন:"
        bot.edit_message_text(msg_text, chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

    elif call.data == "type_2fa":
        state['type'] = '2FA'
        state['step'] = 'AWAITING_DATA'
        msg_text = "🔐 Enter your **2FA Key**:" if lang == 'en' else "🔐 আপনার **2FA Key** দিন:"
        bot.edit_message_text(msg_text, chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

# ================= General Message Handler (State Machine) =================
@bot.message_handler(func=lambda msg: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)
    lang = user_languages.get(chat_id, 'bn')

    if not state:
        bot.send_message(chat_id, "Please select an option from menu:", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        return

    current_step = state.get('step')

    # ১. পাসওয়ার্ড সেভ করা
    if current_step == 'AWAITING_NEW_PASS':
        user_passwords[chat_id] = text
        user_states.pop(chat_id, None)
        save_to_sheet("User_Passwords", [str(chat_id), text])
        msg_text = f"✅ Password saved: `{text}`" if lang == 'en' else f"✅ আপনার পাসওয়ার্ড সফলভাবে সেভ করা হয়েছে: `{text}`"
        bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

    # ২. 2FA কোড জেনারেট করা
    elif current_step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if not is_valid_2fa_key(clean_key):
            bot.send_message(chat_id, "❌ Invalid 2FA Key!" if lang == 'en' else "❌ **ভুল 2FA Key!** সঠিক Key দিন।")
            return

        try:
            totp = pyotp.TOTP(clean_key)
            code = totp.now()
            bot.send_message(chat_id, f"🔑 2FA Code:\n\n`{code}`", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)
        except Exception:
            bot.send_message(chat_id, "❌ Error generating code!")

    # ৩. বাল্ক ডাটা রিসিভ করা (Bulk Submission)
    elif current_step == 'AWAITING_BULK_DATA':
        lines = text.split("\n")
        success_count = 0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worker_name = message.from_user.first_name

        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                uid, password, payload = parts[0], parts[1], parts[2]
                if is_valid_uid(uid) and not is_duplicate_uid(uid):
                    tab = "Cookies_Data" if is_valid_cookies(payload) else "2FA_Data"
                    save_to_sheet(tab, [now_str, str(chat_id), uid, password, payload])
                    with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                        writer = csv.writer(file)
                        if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                            writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                        writer.writerow([now_str, worker_name, uid, password, payload])
                    success_count += 1

        user_states.pop(chat_id, None)
        msg_text = f"🎉 Bulk Submission Complete! Successfully saved **{success_count}** accounts." if lang == 'en' else f"🎉 **একসাথে ডাটা জমা সম্পন্ন!** মোট **{success_count}** টি সঠিক অ্যাকাউন্ট সেভ হয়েছে।"
        bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

    # ৪. সিঙ্গেল UID ভ্যালিডেশন
    elif current_step == 'AWAITING_UID':
        if not is_valid_uid(text) or is_duplicate_uid(text):
            bot.send_message(chat_id, "❌ Invalid or Duplicate UID!" if lang == 'en' else "❌ **ভুল বা ডুপ্লিকেট UID!** সঠিক UID দিন।")
            return

        state['uid'] = text
        state['step'] = 'AWAITING_TYPE_SELECTION'
        msg_text = f"✅ UID Accepted: `{text}`\n\nChoose what you want to submit:" if lang == 'en' else f"✅ UID গৃহীত হয়েছে: `{text}`\n\nএখন নির্বাচন করুন আপনি কী জমা দিতে চান:"
        bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=get_submit_type_keyboard(chat_id))

    # ৫. সিঙ্গেল ডাটা সেভ করা (Cookies / 2FA)
    elif current_step == 'AWAITING_DATA':
        data_type = state.get('type')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{get_pass_rule()}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if data_type == 'COOKIE':
            if not is_valid_cookies(text):
                bot.send_message(chat_id, "❌ Invalid Cookies!" if lang == 'en' else "❌ **অকার্যকর কুকিজ!**")
                return

            save_to_sheet("Cookies_Data", [now_str, str(chat_id), uid, password, text])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, text])

            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            msg_text = f"🎉 **Cookies Submitted!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 Progress: `[{bar}]` {user_count}/{DAILY_TARGET}" if lang == 'en' else f"🎉 **Cookies সফলভাবে জমা হয়েছে!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}"
            bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)

        elif data_type == '2FA':
            clean_key = text.replace(" ", "").upper()
            if not is_valid_2fa_key(clean_key):
                bot.send_message(chat_id, "❌ Invalid 2FA Key!" if lang == 'en' else "❌ **ভুল 2FA Key!**")
                return

            save_to_sheet("2FA_Data", [now_str, str(chat_id), uid, password, clean_key])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, clean_key])

            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            msg_text = f"🎉 **2FA Key Submitted!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 Progress: `[{bar}]` {user_count}/{DAILY_TARGET}" if lang == 'en' else f"🎉 **2FA Key সফলভাবে জমা হয়েছে!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}"
            bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)

# ================= Bot Runner =================
if __name__ == "__main__":
    print("Bot Running with Language & Bulk Features...")
    bot.infinity_polling(skip_pending=True)