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

# In-Memory State & Passwords
user_passwords = {}
user_states = {}

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
def worker_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("👤 রেন্ডম নাম জেনারেট"))
    markup.add(KeyboardButton("🖼️ ফেক পিকচার জেনারেট"), KeyboardButton("📧 টেম্প মেইল নিন"))
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেট করুন"), KeyboardButton("⚙️ পাসওয়ার্ড সেট করুন"))
    markup.add(KeyboardButton("🔑 আজকের পাসওয়ার্ড"), KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"))
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("👤 রেন্ডম নাম জেনারেট"))
    markup.add(KeyboardButton("🖼️ ফেক পিকচার জেনারেট"), KeyboardButton("📧 টেম্প মেইল নিন"))
    markup.add(KeyboardButton("🔑 2FA কোড জেনারেট করুন"), KeyboardButton("⚙️ পাসওয়ার্ড সেট করুন"))
    markup.add(KeyboardButton("🔑 আজকের পাসওয়ার্ড"), KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"))
    markup.add(KeyboardButton("📊 টিমের কাজের হিসাব"), KeyboardButton("⚙️ এডমিন প্যানেল"))
    return markup

def get_cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

def get_submit_type_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    btn_cookie = InlineKeyboardButton("🍪 Cookies", callback_data="type_cookie")
    btn_2fa = InlineKeyboardButton("🔐 2FA Key", callback_data="type_2fa")
    btn_cancel = InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel_action")
    markup.add(btn_cookie, btn_2fa, btn_cancel)
    return markup

# ================= Start & Cancel Commands =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 𝗔𝗽𝗻𝗮𝗸𝗲 𝗯𝗼𝘁 theke ban kora hoyeche!")
        return
    user_states.pop(message.chat.id, None)
    save_user(message.chat.id)
    welcome_text = (
        "╔══════════════════════╗\n"
        "   👑 **ONLINE EARNING BAZAR** 👑\n"
        "╚══════════════════════╝\n\n"
        "✨ *Welcome to Professional Bot Panel*\n"
        "🚀 নিচের বাটনগুলো ব্যবহার করে আপনার কাজ দ্রুত করুন:"
    )
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=admin_menu())
    else:
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=worker_menu())

@bot.message_handler(func=lambda msg: msg.text == "❌ বাতিল করুন")
def cancel_process(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "🚫 বর্তমান কাজটি বাতিল করা হয়েছে।", reply_markup=admin_menu() if message.chat.id == ADMIN_ID else worker_menu())

# ================= Temp Mail Engine =================
@bot.message_handler(func=lambda message: message.text == "📧 টেম্প মেইল নিন")
def create_mail(message):
    try:
        domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
        domain = random.choice(domains)
        username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
        email = f"{username}@{domain}"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔄 Inbox Check (OTP দেখুন)", callback_data=f"inbox_{username}_{domain}"))

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
        bot.reply_to(message, "❌ মেইল তৈরি করতে সমস্যা হয়েছে। আবার চেষ্টা করুন!")

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
            bot.answer_callback_query(call.id, "📭 Inbox Empty! কোনো ওটিপি আসেনি।", show_alert=True)
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
        bot.answer_callback_query(call.id, "✅ ইনবক্স চেক করা হয়েছে!")
    except Exception:
        bot.answer_callback_query(call.id, "❌ ইনবক্স চেক করতে সমস্যা হয়েছে!", show_alert=True)

# ================= Generators & Details =================
@bot.message_handler(func=lambda message: message.text == "🖼️ ফেক পিকচার জেনারেট")
def generate_fake_picture(message):
    try:
        selected_face = random.choice(HUMAN_FACES)
        caption_text = (
            "┌──────────────────────┐\n"
            "  🖼️ **𝗥𝗘𝗔𝗟𝗜𝗦𝗧𝗜𝗖 𝗛𝗨𝗠𝗔𝗡 𝗙𝗔𝗖𝗘**\n"
            "└──────────────────────┘\n\n"
            "✨ *নিখুঁত মানুষের মুখের রিয়াল ছবি!*\n"
            "📥 আপনি এই ছবি সেভ করে ফেসবুক প্রোফাইলে ব্যবহার করতে পারেন।"
        )
        markup = admin_menu() if message.chat.id == ADMIN_ID else worker_menu()
        bot.send_photo(message.chat.id, selected_face, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.reply_to(message, "❌ ছবি লোড হতে সমস্যা হয়েছে। আবার চেষ্টা করুন!")

@bot.message_handler(func=lambda message: message.text == "👤 রেন্ডম নাম জেনারেট")
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
    markup = admin_menu() if message.chat.id == ADMIN_ID else worker_menu()
    bot.reply_to(message, name_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔑 আজকের পাসওয়ার্ড")
def show_current_password(message):
    current_rule = get_pass_rule()
    pass_text = (
        f"┌──────────────────────┐\n"
        f"  🔑 **𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗥𝗨𝗟𝗘𝗦**\n"
        f"└──────────────────────┘\n\n"
        f"✨ আজকের পাসওয়ার্ডে অবশ্যই থাকতে হবে:\n👉 `{current_rule}`"
    )
    markup = admin_menu() if message.chat.id == ADMIN_ID else worker_menu()
    bot.reply_to(message, pass_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "📋 আমার জমা দেওয়া লিস্ট")
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
        text = f"📋 **{worker_name}**, আজ আপনি এখনো কোনো অ্যাকাউন্ট জমা দেননি।"
    else:
        text = f"┌──────────────────────┐\n  📋 **𝗬𝗢𝗨𝗥 𝗦𝗨𝗕𝗠𝗜𝗦𝗦𝗜𝗢𝗡𝗦** ({len(uids)})\n└──────────────────────┘\n\n"
        for i, uid in enumerate(uids, 1):
            text += f"`{i}.` UID: `{uid}`\n"
    markup = admin_menu() if message.chat.id == ADMIN_ID else worker_menu()
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

# ================= Password & TOTP Code Handlers =================
@bot.message_handler(func=lambda msg: msg.text == "⚙️ পাসওয়ার্ড সেট করুন")
def set_pass_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_NEW_PASS'}
    bot.send_message(
        message.chat.id, 
        "🔑 আপনার সেভ করতে চাওয়া ডিফল্ট পাসওয়ার্ডটি লিখুন:\n(পরবর্তীতে আপনাকে আর বারবার পাসওয়ার্ড টাইপ করতে হবে না)",
        reply_markup=get_cancel_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "🔑 2FA কোড জেনারেট করুন")
def generate_2fa_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_2FA_GEN'}
    bot.send_message(
        message.chat.id,
        "📌 আপনার 2FA Key/Secret Key-টি দিন (যেমন: `JBSWY3DPEHPK3PXP`):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )

# ================= Admin Functions =================
@bot.message_handler(func=lambda message: message.text == "📊 টিমের কাজের হিসাব")
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
        bot.reply_to(message, "⚠️ আজ এখনো কোনো অ্যাকাউন্ট জমা হয়নি।", reply_markup=admin_menu())
        return
    reply_msg = f"┌──────────────────────┐\n  📊 **𝗧𝗘𝗔𝗠 𝗥𝗘𝗣𝗢𝗥𝗧**\n└──────────────────────┘\n\n🔥 Total: **{total}** Accounts\n\n"
    for w, c in workers.items():
        reply_msg += f"• 👤 `{w}` — **{c}** pcs\n"
    bot.reply_to(message, reply_msg, parse_mode="Markdown", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "⚙️ এডমিন প্যানেল")
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📥 এক্সেল ফাইল ডাউনলোড", callback_data="download_excel"),
        InlineKeyboardButton("📄 বায়ার রেডি TXT ডাউনলোড", callback_data="download_txt"),
        InlineKeyboardButton("📢 সবাইকে নোটিশ দিন", callback_data="send_notice"),
        InlineKeyboardButton("🔑 পাসওয়ার্ড শর্ত পরিবর্তন", callback_data="change_pass"),
        InlineKeyboardButton("🚫 ওয়ার্কার ব্যান করুন", callback_data="ban_user"),
        InlineKeyboardButton("🗑️ ডাটা রিসেট", callback_data="reset_data")
    )
    bot.reply_to(message, "⚙️ **𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: not call.data.startswith("inbox_") and call.data not in ["type_cookie", "type_2fa", "cancel_action"])
def handle_admin_query(call):
    if call.message.chat.id != ADMIN_ID:
        return
    if call.data == "download_excel":
        try:
            with open("accounts_list.csv", "rb") as file:
                bot.send_document(call.message.chat.id, file, caption="📁 এক্সেল ফাইল!")
        except Exception:
            bot.answer_callback_query(call.id, "❌ ফাইল নেই!")
    elif call.data == "download_txt":
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as csv_file, open("buyer_ready.txt", "w", encoding="utf-8") as txt_file:
                reader = csv.reader(csv_file)
                for row in reader:
                    if len(row) >= 5 and row[2] != "UID":
                        txt_file.write(f"{row[2]} | {row[3]} | {row[4]}\n")
            with open("buyer_ready.txt", "rb") as file:
                bot.send_document(call.message.chat.id, file, caption="📄 TXT ফাইল!")
        except Exception:
            bot.answer_callback_query(call.id, "❌ এরর!")
    elif call.data == "change_pass":
        msg = bot.send_message(call.message.chat.id, "নতুন পাসওয়ার্ড শর্ত লিখুন:")
        bot.register_next_step_handler(msg, update_pass_rule)
    elif call.data == "send_notice":
        msg = bot.send_message(call.message.chat.id, "নোটিশের লেখা লিখুন:")
        bot.register_next_step_handler(msg, process_broadcast)
    elif call.data == "ban_user":
        msg = bot.send_message(call.message.chat.id, "ব্যান করার টেলিগ্রাম ID দিন:")
        bot.register_next_step_handler(msg, process_ban)
    elif call.data == "reset_data":
        if os.path.isfile("accounts_list.csv"):
            os.remove("accounts_list.csv")
        bot.answer_callback_query(call.id, "✅ রিসেট সম্পন্ন!", show_alert=True)
        bot.send_message(call.message.chat.id, "🗑️ ডাটা ক্লিয়ার করা হয়েছে।")

def update_pass_rule(message):
    set_pass_rule(message.text.strip())
    bot.reply_to(message, f"✅ শর্ত আপডেট হয়েছে: `{message.text.strip()}`", parse_mode="Markdown", reply_markup=admin_menu())

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
    bot.reply_to(message, f"✅ নোটিশ পাঠানো হয়েছে {count} জনকে।", reply_markup=admin_menu())

def process_ban(message):
    if message.text.strip().isdigit():
        ban_user(message.text.strip())
        bot.reply_to(message, "✅ ব্যান করা হয়েছে!", reply_markup=admin_menu())

# ================= Submit ID Flow =================
@bot.message_handler(func=lambda message: message.text in ["📝 অ্যাকাউন্ট জমা দিন", "📥 আইডি জমা দিন"])
def submit_id_start(message):
    if is_banned(message.chat.id):
        return
    user_states[message.chat.id] = {'step': 'AWAITING_UID'}
    bot.send_message(
        message.chat.id,
        "🆔 অনুগ্রহ করে আপনার **UID** দিন (কেবল মাত্র সংখ্যা):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )

# ================= Inline Callbacks for Submission =================
@bot.callback_query_handler(func=lambda call: call.data in ["type_cookie", "type_2fa", "cancel_action"])
def handle_submission_callback(call):
    chat_id = call.message.chat.id

    if call.data == "cancel_action":
        user_states.pop(chat_id, None)
        bot.edit_message_text("🚫 কাজটি বাতিল করা হয়েছে।", chat_id=chat_id, message_id=call.message.message_id)
        bot.send_message(chat_id, "প্রধান মেনু:", reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu())
        return

    state = user_states.get(chat_id)
    if not state or state.get('step') != 'AWAITING_TYPE_SELECTION':
        bot.answer_callback_query(call.id, "মেয়াদ শেষ! আবার চেষ্টা করুন।")
        return

    if call.data == "type_cookie":
        state['type'] = 'COOKIE'
        state['step'] = 'AWAITING_DATA'
        bot.edit_message_text("🍪 আপনার **Cookies** পেস্ট করুন:", chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

    elif call.data == "type_2fa":
        state['type'] = '2FA'
        state['step'] = 'AWAITING_DATA'
        bot.edit_message_text("🔐 আপনার **2FA Key** দিন:", chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

# ================= General Message Handler (State Machine) =================
@bot.message_handler(func=lambda msg: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    if not state:
        bot.send_message(chat_id, "অনুগ্রহ করে নিচের বাটন থেকে নির্বাচন করুন:", reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu())
        return

    current_step = state.get('step')

    # ১. ডিফল্ট পাসওয়ার্ড সেভ করা
    if current_step == 'AWAITING_NEW_PASS':
        user_passwords[chat_id] = text
        user_states.pop(chat_id, None)
        save_to_sheet("User_Passwords", [str(chat_id), text])
        bot.send_message(chat_id, f"✅ আপনার পাসওয়ার্ড সফলভাবে সেভ করা হয়েছে: `{text}`", parse_mode="Markdown", reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu())

    # ২. 2FA কোড জেনারেট করা
    elif current_step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if not is_valid_2fa_key(clean_key):
            bot.send_message(chat_id, "❌ **ভুল 2FA Key!** সঠিক ১৬-৩২ অক্ষরের Key দিন অথবা '❌ বাতিল করুন' চাপুন।")
            return

        try:
            totp = pyotp.TOTP(clean_key)
            code = totp.now()
            bot.send_message(chat_id, f"🔑 আপনার ৬-ডিজিটের 2FA কোড:\n\n`{code}`", parse_mode="Markdown", reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu())
            user_states.pop(chat_id, None)
        except Exception:
            bot.send_message(chat_id, "❌ কোড জেনারেট করতে ব্যর্থ হয়েছে। সিক্রেট কি-টি চেক করুন।")

    # ৩. UID ভ্যালিডেশন
    elif current_step == 'AWAITING_UID':
        if not is_valid_uid(text) or is_duplicate_uid(text):
            bot.send_message(chat_id, "❌ **ভুল বা ডুপ্লিকেট UID!** সঠিক সংখ্যা ভিত্তিক UID দিন অথবা '❌ বাতিল করুন' চাপুন।")
            return

        state['uid'] = text
        state['step'] = 'AWAITING_TYPE_SELECTION'
        bot.send_message(
            chat_id,
            f"✅ UID গৃহীত হয়েছে: `{text}`\n\nএখন নির্বাচন করুন আপনি কী জমা দিতে চান:",
            parse_mode="Markdown",
            reply_markup=get_submit_type_keyboard()
        )

    # ৪. ডাটা সেভ করা (Cookies / 2FA)
    elif current_step == 'AWAITING_DATA':
        data_type = state.get('type')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{get_pass_rule()}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if data_type == 'COOKIE':
            if not is_valid_cookies(text):
                bot.send_message(chat_id, "❌ **অকার্যকর কুকিজ!** নিশ্চিত করুন এতে `c_user=` বা `datr=` যুক্ত অরিজিনাল কুকিজ রয়েছে।")
                return

            # CSV ও Google Sheet উভয় জায়গায় সেভ
            save_to_sheet("Cookies_Data", [now_str, str(chat_id), uid, password, text])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, text])

            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            bot.send_message(
                chat_id,
                f"🎉 **Cookies সফলভাবে জমা হয়েছে!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}",
                parse_mode="Markdown",
                reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu()
            )
            user_states.pop(chat_id, None)

        elif data_type == '2FA':
            clean_key = text.replace(" ", "").upper()
            if not is_valid_2fa_key(clean_key):
                bot.send_message(chat_id, "❌ **ভুল 2FA Key!** সঠিক ১৬-৩২ অক্ষরের Base32 Key দিন।")
                return

            # CSV ও Google Sheet উভয় জায়গায় সেভ
            save_to_sheet("2FA_Data", [now_str, str(chat_id), uid, password, clean_key])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, clean_key])

            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            bot.send_message(
                chat_id,
                f"🎉 **2FA Key সফলভাবে জমা হয়েছে!**\n\n📌 **UID:** `{uid}`\n🔑 **Pass:** `{password}`\n\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}",
                parse_mode="Markdown",
                reply_markup=admin_menu() if chat_id == ADMIN_ID else worker_menu()
            )
            user_states.pop(chat_id, None)

# ================= Bot Runner =================
if __name__ == "__main__":
    print("Bot Running with Integrated Features...")
    bot.infinity_polling(skip_pending=True)