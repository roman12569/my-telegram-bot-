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
RATE_PER_ACCOUNT = 5.0  # প্রতি অ্যাকাউন্টের টাকা/পয়েন্ট
MIN_WITHDRAW = 50.0

bot = telebot.TeleBot(TOKEN)

# In-Memory State & Settings
user_passwords = {}
user_states = {}
user_languages = {}  # 'bn' or 'en'
user_balances = {}   # chat_id: balance
user_strikes = {}    # chat_id: strike_count
user_last_submit = {} # chat_id: {'uid': ..., 'type': ..., 'data': ...}

# ================= Name & Picture Database =================
FIRST_NAMES = [
    "Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi", "Jahid", "Shohel",
    "Rashed", "Al-Amin", "Monir", "Ripon", "Sumon", "Ariful", "Nazmul", "Sujon", "Hasan", "Hossain",
    "Anik", "Parvez", "Shihab", "Rony", "Joy", "Rifat", "Akash", "Arman", "Rubel", "Mamun"
]

LAST_NAMES = [
    "Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury", "Khan", "Sarker", "Talukder", "Bhuiyan"
]

HUMAN_FACES = [
    "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop",
    "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&h=400&fit=crop"
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

def get_user_total_count(worker_name):
    count = 0
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 2 and worker_name == row[1]:
                    count += 1
    return count

def get_worker_badge(total_submissions):
    if total_submissions >= 500:
        return "🥇 Gold Master"
    elif total_submissions >= 200:
        return "🥈 Silver Worker"
    elif total_submissions >= 50:
        return "🥉 Bronze Worker"
    return "🌱 Beginner"

# ================= Validation & Extractor Helpers =================
def extract_numeric_uid(text):
    text = text.strip()
    if text.isdigit() and 8 <= len(text) <= 20:
        return text
    match = re.search(r'(?:id=|\/|profile\.php\?id=)(\d{8,20})', text)
    if match:
        return match.group(1)
    return None

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
        markup.add(KeyboardButton("👤 My Profile & Balance"), KeyboardButton("💳 Withdraw Money"))
        markup.add(KeyboardButton("🏆 Daily Leaderboard"), KeyboardButton("🔗 Referral Link"))
        markup.add(KeyboardButton("🔍 Extract UID from Link"), KeyboardButton("📄 Upload TXT File"))
        markup.add(KeyboardButton("👤 Random Name Gen"), KeyboardButton("🖼️ Fake Picture Gen"))
        markup.add(KeyboardButton("📧 Get Temp Mail"), KeyboardButton("🔑 Generate 2FA Code"))
        markup.add(KeyboardButton("⚙️ Set Default Pass"), KeyboardButton("🔑 Today's Password"))
        markup.add(KeyboardButton("📋 My Submissions"), KeyboardButton("🌐 Change Language"))
    else:
        markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("📦 একসাথে অনেক জমা দিন"))
        markup.add(KeyboardButton("👤 প্রোফাইল ও ব্যালেন্স"), KeyboardButton("💳 টাকা তুলুন (Withdraw)"))
        markup.add(KeyboardButton("🏆 আজকের সেরা লিডারবোর্ড"), KeyboardButton("🔗 রেফারেল লিংক"))
        markup.add(KeyboardButton("🔍 লিংক থেকে UID বের করুন"), KeyboardButton("📄 TXT ফাইল আপলোড"))
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
        markup.add(KeyboardButton("👤 My Profile & Balance"), KeyboardButton("💳 Withdraw Money"))
        markup.add(KeyboardButton("🏆 Daily Leaderboard"), KeyboardButton("🔗 Referral Link"))
        markup.add(KeyboardButton("🔍 Extract UID from Link"), KeyboardButton("📄 Upload TXT File"))
        markup.add(KeyboardButton("👤 Random Name Gen"), KeyboardButton("🖼️ Fake Picture Gen"))
        markup.add(KeyboardButton("📧 Get Temp Mail"), KeyboardButton("🔑 Generate 2FA Code"))
        markup.add(KeyboardButton("⚙️ Set Default Pass"), KeyboardButton("🔑 Today's Password"))
        markup.add(KeyboardButton("📋 My Submissions"), KeyboardButton("🌐 Change Language"))
        markup.add(KeyboardButton("📊 Team Stats"), KeyboardButton("⚙️ Secret Admin Panel"))
    else:
        markup.add(KeyboardButton("📥 আইডি জমা দিন"), KeyboardButton("📦 একসাথে অনেক জমা দিন"))
        markup.add(KeyboardButton("👤 প্রোফাইল ও ব্যালেন্স"), KeyboardButton("💳 টাকা তুলুন (Withdraw)"))
        markup.add(KeyboardButton("🏆 আজকের সেরা লিডারবোর্ড"), KeyboardButton("🔗 রেফারেল লিংক"))
        markup.add(KeyboardButton("🔍 লিংক থেকে UID বের করুন"), KeyboardButton("📄 TXT ফাইল আপলোড"))
        markup.add(KeyboardButton("👤 রেন্ডম নাম জেনারেট"), KeyboardButton("🖼️ ফেক পিকচার জেনারেট"))
        markup.add(KeyboardButton("📧 টেম্প মেইল নিন"), KeyboardButton("🔑 2FA কোড জেনারেট করুন"))
        markup.add(KeyboardButton("⚙️ পাসওয়ার্ড সেট করুন"), KeyboardButton("🔑 আজকের পাসওয়ার্ড"))
        markup.add(KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"), KeyboardButton("🌐 ভাষা পরিবর্তন"))
        markup.add(KeyboardButton("📊 টিমের কাজের হিসাব"), KeyboardButton("⚙️ সিক্রেট এডমিন প্যানেল"))
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

# ================= Start & Language Handler =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 𝗔𝗽𝗻𝗮𝗸𝗲 𝗯𝗼𝘁 theke ban kora hoyeche!")
        return
    
    user_states.pop(message.chat.id, None)
    save_user(message.chat.id)
    
    # Check for Referral
    command_args = message.text.split()
    if len(command_args) > 1 and command_args[1].isdigit():
        referrer_id = int(command_args[1])
        if referrer_id != message.chat.id:
            user_balances[referrer_id] = user_balances.get(referrer_id, 0.0) + 2.0  # Referral Bonus 2 Tk
            try:
                bot.send_message(referrer_id, f"🎉 আপনার রেফারেল লিংকে একজন নতুন ওয়ার্কার যুক্ত হয়েছেন! পেয়ে গেছেন ৳2.00 বোনাস।")
            except Exception:
                pass

    welcome_text = "🌐 **Choose Your Preferred Language / আপনার পছন্দনীয় ভাষা নির্বাচন করুন:**"
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

# ================= User Profile, Balance & Withdraw =================
@bot.message_handler(func=lambda msg: msg.text in ["👤 প্রোফাইল ও ব্যালেন্স", "👤 My Profile & Balance"])
def show_user_profile(message):
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    lang = user_languages.get(chat_id, 'bn')
    
    daily_c = get_user_daily_count(worker_name)
    total_c = get_user_total_count(worker_name)
    balance = user_balances.get(chat_id, 0.0)
    badge = get_worker_badge(total_c)
    strikes = user_strikes.get(chat_id, 0)

    if lang == 'en':
        text = (
            f"👤 **WORKER PROFILE**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 **Name:** `{worker_name}`\n"
            f"🔹 **Badge:** {badge}\n"
            f"🔹 **Today Submitted:** `{daily_c}` pcs\n"
            f"🔹 **Total Submitted:** `{total_c}` pcs\n"
            f"💰 **Current Balance:** `৳{balance:.2f}`\n"
            f"⚠️ **Strikes:** `{strikes}/3`"
        )
    else:
        text = (
            f"👤 **ওয়ার্কার প্রোফাইল**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 **নাম:** `{worker_name}`\n"
            f"🔹 **লেভেল ব্যাজ:** {badge}\n"
            f"🔹 **আজকের জমা:** `{daily_c}` টি\n"
            f"🔹 **সর্বমোট জমা:** `{total_c}` টি\n"
            f"💰 **বর্তমান ব্যালেন্স:** `৳{balance:.2f}`\n"
            f"⚠️ **স্ট্রাইক সংখ্যা:** `{strikes}/3`"
        )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["💳 টাকা তুলুন (Withdraw)", "💳 Withdraw Money"])
def withdraw_start(message):
    chat_id = message.chat.id
    lang = user_languages.get(chat_id, 'bn')
    balance = user_balances.get(chat_id, 0.0)

    if balance < MIN_WITHDRAW:
        msg_text = f"⚠️ Minimum withdraw amount is ৳{MIN_WITHDRAW:.2f}. Your balance is ৳{balance:.2f}." if lang == 'en' else f"⚠️ টাকা তুলতে সর্বনিম্ন ৳{MIN_WITHDRAW:.2f} লাগবে। আপনার বর্তমান ব্যালেন্স ৳{balance:.2f}।"
        bot.reply_to(message, msg_text)
        return

    user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
    msg_text = f"💳 Enter Bkash/Nagad number and Amount (e.g., `01700000000 | 100`):" if lang == 'en' else f"💳 আপনার বিকাশ/নগদ নম্বর এবং টাকার পরিমাণ লিখুন (যেমন: `01700000000 | 100`):"
    bot.send_message(chat_id, msg_text, reply_markup=get_cancel_keyboard(chat_id))

@bot.message_handler(func=lambda msg: msg.text in ["🔗 রেফারেল লিংক", "🔗 Referral Link"])
def send_referral_link(message):
    chat_id = message.chat.id
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={chat_id}"
    
    text = (
        f"🔗 **আপনার রেফারেল লিংক:**\n`{ref_link}`\n\n"
        f"🎁 আপনার লিংকে কেউ বোট স্টার্ট করলে আপনি প্রতিটি রেফারেলের জন্য পাবেন ৳২.০০ বোনাস!"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["🏆 আজকের সেরা লিডারবোর্ড", "🏆 Daily Leaderboard"])
def show_leaderboard(message):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    workers = {}
    if os.path.isfile("accounts_list.csv"):
        with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 5 and today in row[0]:
                    w_name = row[1]
                    workers[w_name] = workers.get(w_name, 0) + 1

    sorted_workers = sorted(workers.items(), key=lambda x: x[1], reverse=True)[:5]
    
    text = "🏆 **আজকের টপ ওয়ার্কার লিডারবোর্ড**\n━━━━━━━━━━━━━━━━━━━\n\n"
    if not sorted_workers:
        text += "আজ এখনো কোনো আইডি জমা হয়নি।"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, count) in enumerate(sorted_workers):
            text += f"{medals[idx]} `{name}` — **{count}** টি আইডি\n"

    bot.reply_to(message, text, parse_mode="Markdown")

# ================= Extract UID & TXT Upload =================
@bot.message_handler(func=lambda msg: msg.text in ["🔍 লিংক থেকে UID বের করুন", "🔍 Extract UID from Link"])
def extract_uid_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_FB_LINK'}
    bot.send_message(message.chat.id, "📌 ফেসবুক প্রোফাইল লিংক দিন (যেমন: `https://facebook.com/zuck`):", reply_markup=get_cancel_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["📄 TXT ফাইল আপলোড", "📄 Upload TXT File"])
def upload_txt_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_TXT_FILE'}
    bot.send_message(message.chat.id, "📄 আপনার IDs থাকা `.txt` ফাইলটি মেসেজে আপলোড করে পাঠান:", reply_markup=get_cancel_keyboard(message.chat.id))

# ================= Temp Mail Engine & Generators =================
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

@bot.message_handler(func=lambda message: message.text in ["🖼️ ফেক পিকচার জেনারেট", "🖼️ Fake Picture Gen"])
def generate_fake_picture(message):
    try:
        selected_face = random.choice(HUMAN_FACES)
        caption_text = "🖼️ **REALISTIC HUMAN FACE**\n\n✨ প্রোফাইল পিকচারের জন্য এটি ব্যবহার করতে পারেন।"
        markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
        bot.send_photo(message.chat.id, selected_face, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.reply_to(message, "❌ Error loading image!")

@bot.message_handler(func=lambda message: message.text in ["👤 রেন্ডম নাম জেনারেট", "👤 Random Name Gen"])
def generate_fake_name(message):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    birth_year = random.randint(1995, 2004)
    name_text = (
        f"👤 **PROFILE DETAILS**\n\n"
        f"🔹 **First Name:** `{first}`\n"
        f"🔹 **Last Name:** `{last}`\n"
        f"🔹 **Full Name:** `{first} {last}`\n"
        f"🔹 **DOB Year:** `{birth_year}`"
    )
    markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
    bot.reply_to(message, name_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["🔑 আজকের পাসওয়ার্ড", "🔑 Today's Password"])
def show_current_password(message):
    current_rule = get_pass_rule()
    pass_text = f"🔑 **PASSWORD RULES**\n\n✨ আজকের পাসওয়ার্ডে থাকতে হবে:\n👉 `{current_rule}`"
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
        text = f"📋 **{worker_name}**, আজ আপনি এখনো কোনো অ্যাকাউন্ট জমা দেননি।"
    else:
        text = f"📋 **YOUR SUBMISSIONS TODAY** ({len(uids)})\n\n"
        for i, uid in enumerate(uids, 1):
            text += f"`{i}.` UID: `{uid}`\n"
    markup = admin_menu(message.chat.id) if message.chat.id == ADMIN_ID else worker_menu(message.chat.id)
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

# ================= Secret Admin Panel (Exclusive for Admin) =================
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
        bot.reply_to(message, "⚠️ আজ এখনো কোনো অ্যাকাউন্ট জমা হয়নি।", reply_markup=admin_menu(message.chat.id))
        return
    reply_msg = f"📊 **TEAM REPORT**\n\n🔥 Total: **{total}** Accounts\n\n"
    for w, c in workers.items():
        reply_msg += f"• 👤 `{w}` — **{c}** pcs\n"
    bot.reply_to(message, reply_msg, parse_mode="Markdown", reply_markup=admin_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text in ["⚙️ সিক্রেট এডমিন প্যানেল", "⚙️ Secret Admin Panel"])
def secret_admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📥 Download Excel File", callback_data="download_excel"),
        InlineKeyboardButton("📄 Download Buyer TXT", callback_data="download_txt"),
        InlineKeyboardButton("📢 Broadcast Message", callback_data="send_notice"),
        InlineKeyboardButton("🔑 Change Password Rule", callback_data="change_pass"),
        InlineKeyboardButton("🚫 Ban Worker", callback_data="ban_user"),
        InlineKeyboardButton("🗑️ Reset All Data", callback_data="reset_data")
    )
    bot.reply_to(message, "⚙️ **SECRET ADMIN CONTROL PANEL**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["download_excel", "download_txt", "send_notice", "change_pass", "ban_user", "reset_data"])
def handle_admin_callbacks(call):
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
        msg = bot.send_message(call.message.chat.id, "নতুন পাসওয়ার্ড নিয়ম লিখুন:")
        bot.register_next_step_handler(msg, update_pass_rule)
    elif call.data == "send_notice":
        msg = bot.send_message(call.message.chat.id, "নোটিশের মেসেজ লিখুন:")
        bot.register_next_step_handler(msg, process_broadcast)
    elif call.data == "ban_user":
        msg = bot.send_message(call.message.chat.id, "ব্যান করার টেলিগ্রাম ID দিন:")
        bot.register_next_step_handler(msg, process_ban)
    elif call.data == "reset_data":
        if os.path.isfile("accounts_list.csv"):
            os.remove("accounts_list.csv")
        bot.answer_callback_query(call.id, "✅ ডাটা রিসেট সম্পন্ন!", show_alert=True)

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

# ================= Password & 2FA Flow =================
@bot.message_handler(func=lambda msg: msg.text in ["⚙️ পাসওয়ার্ড সেট করুন", "⚙️ Set Default Pass"])
def set_pass_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_NEW_PASS'}
    bot.send_message(message.chat.id, "🔑 আপনার ডিফল্ট পাসওয়ার্ড সেভ করতে লিখুন:", reply_markup=get_cancel_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text in ["🔑 2FA কোড জেনারেট করুন", "🔑 Generate 2FA Code"])
def generate_2fa_start(message):
    user_states[message.chat.id] = {'step': 'AWAITING_2FA_GEN'}
    bot.send_message(message.chat.id, "📌 2FA Secret Key দিন:", parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

# ================= Bulk & Single Submissions =================
@bot.message_handler(func=lambda message: message.text in ["📦 একসাথে অনেক জমা দিন", "📦 Bulk Submit IDs"])
def bulk_submit_start(message):
    if is_banned(message.chat.id):
        return
    user_states[message.chat.id] = {'step': 'AWAITING_BULK_DATA'}
    msg_text = "📦 প্রতি লাইনে `UID | Password | Cookies/2FA` দিয়ে পেস্ট করুন:"
    bot.send_message(message.chat.id, msg_text, parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

@bot.message_handler(func=lambda message: message.text in ["📝 অ্যাকাউন্ট জমা দিন", "📥 আইডি জমা দিন", "📥 Submit Single ID"])
def submit_id_start(message):
    if is_banned(message.chat.id):
        return
    user_states[message.chat.id] = {'step': 'AWAITING_UID'}
    bot.send_message(message.chat.id, "🆔 **UID** দিন (কেবল সংখ্যা):", parse_mode="Markdown", reply_markup=get_cancel_keyboard(message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data in ["type_cookie", "type_2fa", "cancel_action"])
def handle_submission_callback(call):
    chat_id = call.message.chat.id

    if call.data == "cancel_action":
        user_states.pop(chat_id, None)
        bot.edit_message_text("🚫 Action cancelled.", chat_id=chat_id, message_id=call.message.message_id)
        bot.send_message(chat_id, "Main Menu:", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        return

    state = user_states.get(chat_id)
    if not state or state.get('step') != 'AWAITING_TYPE_SELECTION':
        bot.answer_callback_query(call.id, "Expired!")
        return

    if call.data == "type_cookie":
        state['type'] = 'COOKIE'
        state['step'] = 'AWAITING_DATA'
        bot.edit_message_text("🍪 আপনার **Cookies** পেস্ট করুন:", chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

    elif call.data == "type_2fa":
        state['type'] = '2FA'
        state['step'] = 'AWAITING_DATA'
        bot.edit_message_text("🔐 আপনার **2FA Key** দিন:", chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

# ================= TXT File Document Handler =================
@bot.message_handler(content_types=['document'])
def handle_txt_document(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    
    if state and state.get('step') == 'AWAITING_TXT_FILE':
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            content = downloaded_file.decode('utf-8')
            
            lines = content.splitlines()
            success_count = 0
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            worker_name = message.from_user.first_name

            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 3:
                    uid, password, payload = parts[0], parts[1], parts[2]
                    if extract_numeric_uid(uid) and not is_duplicate_uid(uid):
                        tab = "Cookies_Data" if is_valid_cookies(payload) else "2FA_Data"
                        save_to_sheet(tab, [now_str, str(chat_id), uid, password, payload])
                        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                            writer = csv.writer(file)
                            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                                writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                            writer.writerow([now_str, worker_name, uid, password, payload])
                        success_count += 1

            user_balances[chat_id] = user_balances.get(chat_id, 0.0) + (success_count * RATE_PER_ACCOUNT)
            user_states.pop(chat_id, None)
            bot.reply_to(message, f"🎉 **TXT ফাইল আপলোড সফল!** মোট **{success_count}** টি সঠিক আইডি যোগ করা হয়েছে।", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        except Exception:
            bot.reply_to(message, "❌ ফাইল প্রসেস করতে সমস্যা হয়েছে। সঠিক TXT ফাইল দিন।")

# ================= General Message Handler =================
@bot.message_handler(func=lambda msg: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    if not state:
        bot.send_message(chat_id, "নিচের বাটন থেকে অপশন নির্বাচন করুন:", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        return

    current_step = state.get('step')

    # ১. উইথড্র হ্যান্ডলার
    if current_step == 'AWAITING_WITHDRAW_DETAILS':
        parts = text.split("|")
        if len(parts) == 2 and parts[1].strip().isdigit():
            number = parts[0].strip()
            amount = float(parts[1].strip())
            current_bal = user_balances.get(chat_id, 0.0)
            
            if amount <= current_bal and amount >= MIN_WITHDRAW:
                user_balances[chat_id] -= amount
                user_states.pop(chat_id, None)
                bot.send_message(chat_id, f"✅ ৳{amount:.2f} উইথড্র রিকোয়েস্ট পাঠানো হয়েছে ({number})। অ্যাডমিন যাচাই করে পেমেন্ট করে দেবে।", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
                bot.send_message(ADMIN_ID, f"🔔 **নতুন উইথড্র রিকোয়েস্ট:**\n👤 ওয়ার্কার: {message.from_user.first_name}\n📞 নম্বর: `{number}`\n💰 পরিমাণ: ৳{amount:.2f}")
            else:
                bot.send_message(chat_id, "❌ পর্যাপ্ত ব্যালেন্স নেই অথবা ভুল ইনপুট।")
        else:
            bot.send_message(chat_id, "❌ সঠিক ফরম্যাটে দিন: `01700000000 | 100`")

    # ২. FB লিংক থেকে UID বের করা
    elif current_step == 'AWAITING_FB_LINK':
        extracted_uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if extracted_uid:
            bot.send_message(chat_id, f"✅ আপনার প্রফাইল থেকে প্রাপ্ত Numeric UID:\n\n`{extracted_uid}`", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
        else:
            bot.send_message(chat_id, "❌ কোনো সঠিক UID খুঁজে পাওয়া যায়নি।", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

    # ৩. পাসওয়ার্ড সেভ করা
    elif current_step == 'AWAITING_NEW_PASS':
        user_passwords[chat_id] = text
        user_states.pop(chat_id, None)
        save_to_sheet("User_Passwords", [str(chat_id), text])
        bot.send_message(chat_id, f"✅ আপনার ডিফল্ট পাসওয়ার্ড সেভ করা হয়েছে: `{text}`", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

    # ৪. 2FA কোড জেনারেট করা
    elif current_step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if not is_valid_2fa_key(clean_key):
            user_strikes[chat_id] = user_strikes.get(chat_id, 0) + 1
            bot.send_message(chat_id, f"❌ **ভুল 2FA Key!** (স্ট্রাইক {user_strikes[chat_id]}/3)")
            return

        try:
            totp = pyotp.TOTP(clean_key)
            code = totp.now()
            bot.send_message(chat_id, f"🔑 আপনার 2FA কোড:\n\n`{code}`", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)
        except Exception:
            bot.send_message(chat_id, "❌ কোড জেনারেট করতে সমস্যা হয়েছে।")

    # ৫. বাল্ক ডাটা রিসিভ করা
    elif current_step == 'AWAITING_BULK_DATA':
        lines = text.split("\n")
        success_count = 0
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worker_name = message.from_user.first_name

        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                uid, password, payload = parts[0], parts[1], parts[2]
                if extract_numeric_uid(uid) and not is_duplicate_uid(uid):
                    tab = "Cookies_Data" if is_valid_cookies(payload) else "2FA_Data"
                    save_to_sheet(tab, [now_str, str(chat_id), uid, password, payload])
                    with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                        writer = csv.writer(file)
                        if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                            writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                        writer.writerow([now_str, worker_name, uid, password, payload])
                    success_count += 1

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + (success_count * RATE_PER_ACCOUNT)
        user_states.pop(chat_id, None)
        bot.send_message(chat_id, f"🎉 **একসাথে ডাটা জমা সম্পন্ন!** মোট **{success_count}** টি সঠিক অ্যাকাউন্ট সেভ হয়েছে।", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))

    # ৬. সিঙ্গেল UID ভ্যালিডেশন
    elif current_step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            user_strikes[chat_id] = user_strikes.get(chat_id, 0) + 1
            bot.send_message(chat_id, f"❌ **ভুল বা ডুপ্লিকেট UID!** (স্ট্রাইক {user_strikes[chat_id]}/3)")
            return

        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_TYPE_SELECTION'
        bot.send_message(chat_id, f"✅ UID গৃহীত হয়েছে: `{numeric_uid}`\n\nকী জমা দিতে চান নির্বাচন করুন:", parse_mode="Markdown", reply_markup=get_submit_type_keyboard(chat_id))

    # ৭. সিঙ্গেল ডাটা সেভ করা (Cookies / 2FA)
    elif current_step == 'AWAITING_DATA':
        data_type = state.get('type')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{get_pass_rule()}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if data_type == 'COOKIE':
            if not is_valid_cookies(text):
                user_strikes[chat_id] = user_strikes.get(chat_id, 0) + 1
                bot.send_message(chat_id, f"❌ **অকার্যকর কুকিজ!** (স্ট্রাইক {user_strikes[chat_id]}/3)")
                return

            save_to_sheet("Cookies_Data", [now_str, str(chat_id), uid, password, text])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, text])

            user_balances[chat_id] = user_balances.get(chat_id, 0.0) + RATE_PER_ACCOUNT
            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            bot.send_message(chat_id, f"🎉 **Cookies জমা সম্পন্ন!**\n\n📌 **UID:** `{uid}`\n💰 যোগ হয়েছে: ৳{RATE_PER_ACCOUNT}\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)

        elif data_type == '2FA':
            clean_key = text.replace(" ", "").upper()
            if not is_valid_2fa_key(clean_key):
                user_strikes[chat_id] = user_strikes.get(chat_id, 0) + 1
                bot.send_message(chat_id, f"❌ **ভুল 2FA Key!** (স্ট্রাইক {user_strikes[chat_id]}/3)")
                return

            save_to_sheet("2FA_Data", [now_str, str(chat_id), uid, password, clean_key])
            with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                    writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
                writer.writerow([now_str, worker_name, uid, password, clean_key])

            user_balances[chat_id] = user_balances.get(chat_id, 0.0) + RATE_PER_ACCOUNT
            user_count = get_user_daily_count(worker_name)
            bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
            bot.send_message(chat_id, f"🎉 **2FA Key জমা সম্পন্ন!**\n\n📌 **UID:** `{uid}`\n💰 যোগ হয়েছে: ৳{RATE_PER_ACCOUNT}\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}", parse_mode="Markdown", reply_markup=admin_menu(chat_id) if chat_id == ADMIN_ID else worker_menu(chat_id))
            user_states.pop(chat_id, None)

# ================= Bot Runner =================
if __name__ == "__main__":
    print("Bot Running with All Requested Features...")
    bot.infinity_polling(skip_pending=True)