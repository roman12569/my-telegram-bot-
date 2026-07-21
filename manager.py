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
RATE_PER_ACCOUNT = 5.0  # টাকা প্রতি একাউন্ট
MIN_WITHDRAW = 50.0

bot = telebot.TeleBot(TOKEN)

# Memory Storage
user_passwords = {}
user_states = {}
user_languages = {}
user_balances = {}
user_strikes = {}

# ================= Helpers =================
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
        return str(chat_id) in f.read().splitlines()

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

def extract_numeric_uid(text):
    text = text.strip()
    if text.isdigit() and 8 <= len(text) <= 20:
        return text
    match = re.search(r'(?:id=|\/|profile\.php\?id=)(\d{8,20})', text)
    return match.group(1) if match else None

def is_valid_2fa_key(key_str):
    cleaned = key_str.replace(" ", "").upper()
    return bool(re.match(r'^[A-Z2-7]{16,32}$', cleaned))

def is_valid_cookies(cookie_str):
    return ("c_user=" in cookie_str) or ("datr=" in cookie_str) or ("xs=" in cookie_str)

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

# ================= UI KEYBOARDS (CLEAN DESIGN) =================

def main_bottom_keyboard(chat_id):
    """মাত্র ৩-৪ টি বোতাম ওয়ালা ক্লিন বটম মেনু"""
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
        markup.add(KeyboardButton("⚙️ এডমিন প্যানেল"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    return markup

# --- Inline Category Keyboards ---

def inline_submission_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📥 সিঙ্গেল আইডি জমা", callback_data="sub_single"),
        InlineKeyboardButton("📦 একসাথে অনেক জমা (Bulk)", callback_data="sub_bulk")
    )
    markup.add(
        InlineKeyboardButton("📄 TXT ফাইল আপলোড", callback_data="sub_txt"),
        InlineKeyboardButton("⚙️ পাসওয়ার্ড সেটিংস", callback_data="sub_pass_settings")
    )
    return markup

def inline_tools_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔑 2FA কোড মেকার", callback_data="tool_2fa"),
        InlineKeyboardButton("🔍 Link to UID", callback_data="tool_uid")
    )
    markup.add(
        InlineKeyboardButton("📧 টেম্প ইমেইল", callback_data="tool_mail"),
        InlineKeyboardButton("👤 ফেক নাম জেনারেটর", callback_data="tool_name")
    )
    markup.add(
        InlineKeyboardButton("🖼️ ফেক পিকচার জেনারেটর", callback_data="tool_pic")
    )
    return markup

def inline_profile_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📋 জমা দেওয়া আইডি লিস্ট", callback_data="prof_list"),
        InlineKeyboardButton("💳 টাকা তুলুন (Withdraw)", callback_data="prof_withdraw")
    )
    markup.add(
        InlineKeyboardButton("🔗 রেফারেল লিংক", callback_data="prof_ref"),
        InlineKeyboardButton("🌐 ভাষা / Language", callback_data="prof_lang")
    )
    return markup

def inline_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📥 এক্সেল ডাউনলোড", callback_data="adm_excel"),
        InlineKeyboardButton("📄 বায়ার TXT ডাউনলোড", callback_data="adm_txt")
    )
    markup.add(
        InlineKeyboardButton("📢 সবাইকে নোটিশ দিন", callback_data="adm_notice"),
        InlineKeyboardButton("🔑 পাসওয়ার্ড রুল পরিবর্তন", callback_data="adm_pass")
    )
    markup.add(
        InlineKeyboardButton("📊 টিমের কাজের হিসাব", callback_data="adm_stats"),
        InlineKeyboardButton("🚫 ওয়ার্কার ব্যান", callback_data="adm_ban")
    )
    return markup

# ================= START & MAIN CATEGORY HANDLERS =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।")
        return
    
    user_states.pop(message.chat.id, None)
    save_user(message.chat.id)

    welcome_text = (
        "╔═════════════════════════╗\n"
        "   👑 **ONLINE EARNING BAZAR** 👑\n"
        "╚═════════════════════════╝\n\n"
        "✨ **স্বাগতম আমাদের প্রফেশনাল বট প্যানেলে!**\n"
        "নিচের ক্লিন মেনু থেকে আপনার কাঙ্ক্ষিত অপশন নির্বাচন করুন:"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=main_bottom_keyboard(message.chat.id))

@bot.message_handler(func=lambda msg: msg.text == "❌ বাতিল করুন")
def cancel_action(message):
    user_states.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "🚫 বর্তমান কাজটি বাতিল করা হয়েছে।", reply_markup=main_bottom_keyboard(message.chat.id))

# Bottom Button Click Listeners (Show Inline Category Boxes)

@bot.message_handler(func=lambda msg: msg.text == "📥 আইডি সাবমিশন")
def category_submission(message):
    text = "📥 **আইডি সাবমিশন সেন্টার**\n━━━━━━━━━━━━━━━━━━━━\nকীভাবে কাজ জমা দিতে চান নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_submission_menu())

@bot.message_handler(func=lambda msg: msg.text == "🛠️ হেল্পার টুলস")
def category_tools(message):
    text = "🛠️ **ওয়ার্কার হেল্পার টুলস**\n━━━━━━━━━━━━━━━━━━━━\nআপনার প্রয়োজনীয় টুলটি বেছে নিন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_tools_menu())

@bot.message_handler(func=lambda msg: msg.text == "👤 আমার প্রোফাইল")
def category_profile(message):
    chat_id = message.chat.id
    worker_name = message.from_user.first_name
    daily_c = get_user_daily_count(worker_name)
    balance = user_balances.get(chat_id, 0.0)

    text = (
        f"👤 **আপনার প্রোফাইল সামারি**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔹 **নাম:** `{worker_name}`\n"
        f"🔹 **আজকের জমা:** `{daily_c}` টি\n"
        f"💰 **বর্তমান ব্যালেন্স:** `৳{balance:.2f}`\n\n"
        f"নিচের মেনু থেকে বিস্তারিত দেখুন:"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=inline_profile_menu())

@bot.message_handler(func=lambda msg: msg.text == "🏆 লিডারবোর্ড")
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
    
    text = "🏆 **আজকের টপ ৫ ওয়ার্কার**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not sorted_workers:
        text += "আজ এখনো কোনো আইডি জমা হয়নি।"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, count) in enumerate(sorted_workers):
            text += f"{medals[idx]} `{name}` — **{count}** টি\n"

    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "⚙️ এডমিন প্যানেল")
def category_admin(message):
    if message.chat.id != ADMIN_ID:
        return
    text = "⚙️ **এডমিন কন্ট্রোল প্যানেল**\n━━━━━━━━━━━━━━━━━━━━\nআপনার পছন্দের অ্যাকশন নির্বাচন করুন:"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=inline_admin_menu())

# ================= INLINE CALLBACK HANDLERS =================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    code = call.data

    # --- Submission Options ---
    if code == "sub_single":
        user_states[chat_id] = {'step': 'AWAITING_UID'}
        bot.send_message(chat_id, "🆔 **UID দিন (কেবল মাত্র সংখ্যা):**", reply_markup=cancel_keyboard())

    elif code == "sub_bulk":
        user_states[chat_id] = {'step': 'AWAITING_BULK_DATA'}
        text = "📦 **একসাথে অনেক ডাটা জমা দিন:**\n\nফরম্যাট:\n`UID | Password | Cookies/2FA`\n(প্রতি লাইনে একটি করে দিন)"
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "sub_txt":
        user_states[chat_id] = {'step': 'AWAITING_TXT_FILE'}
        bot.send_message(chat_id, "📄 আপনার IDs থাকা `.txt` ফাইলটি মেসেজে আপলোড করে পাঠান:", reply_markup=cancel_keyboard())

    elif code == "sub_pass_settings":
        rule = get_pass_rule()
        text = f"🔑 **পাসওয়ার্ড সেটিংস**\n\n👉 আজকের পাসওয়ার্ড শর্ত: `{rule}`\n\nআপনি কি ডিফল্ট পাসওয়ার্ড সেভ করতে চান?"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("⚙️ ডিফল্ট পাসওয়ার্ড সেট করুন", callback_data="set_def_pass"))
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

    elif code == "set_def_pass":
        user_states[chat_id] = {'step': 'AWAITING_NEW_PASS'}
        bot.send_message(chat_id, "🔑 আপনার সেভ করতে চাওয়া পাসওয়ার্ডটি টাইপ করুন:", reply_markup=cancel_keyboard())

    # --- Helper Tools Options ---
    elif code == "tool_2fa":
        user_states[chat_id] = {'step': 'AWAITING_2FA_GEN'}
        bot.send_message(chat_id, "📌 আপনার 2FA Key-টি দিন (যেমন: `JBSWY3DPEHPK3PXP`):", parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif code == "tool_uid":
        user_states[chat_id] = {'step': 'AWAITING_FB_LINK'}
        bot.send_message(chat_id, "🔍 ফেসবুক প্রোফাইল লিংক দিন (যেমন: `https://facebook.com/zuck`):", reply_markup=cancel_keyboard())

    elif code == "tool_mail":
        try:
            domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
            domain = random.choice(domains)
            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
            email = f"{username}@{domain}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔄 Inbox Check (OTP)", callback_data=f"inbox_{username}_{domain}"))
            bot.send_message(chat_id, f"📧 **Temp Mail:**\n\n`{email}`", parse_mode="Markdown", reply_markup=markup)
        except Exception:
            bot.send_message(chat_id, "❌ ইমেইল তৈরিতে সমস্যা হয়েছে।")

    elif code.startswith("inbox_"):
        parts = code.split("_")
        username, domain = parts[1], parts[2]
        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={username}&domain={domain}"
        try:
            res = requests.get(url, timeout=10).json()
            if not res:
                bot.answer_callback_query(call.id, "📭 ইনবক্স খালি!", show_alert=True)
                return
            msg_id = res[0]['id']
            msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={username}&domain={domain}&id={msg_id}"
            msg_res = requests.get(msg_url, timeout=10).json()
            body = msg_res.get('textBody', 'No content')
            bot.send_message(chat_id, f"💬 **Content/OTP:**\n`{body}`", parse_mode="Markdown")
        except Exception:
            bot.answer_callback_query(call.id, "❌ এরর হয়েছে!", show_alert=True)

    elif code == "tool_name":
        firsts = ["Md", "Tanvir", "Rakib", "Imran", "Sakib", "Fahim", "Nayeem", "Mehedi"]
        lasts = ["Ahmed", "Hossain", "Islam", "Rahman", "Uddin", "Chowdhury"]
        text = f"👤 **ফেক প্রোফাইল নাম:**\n\n🔹 **Name:** `{random.choice(firsts)} {random.choice(lasts)}`\n🔹 **DOB Year:** `{random.randint(1996, 2004)}`"
        bot.send_message(chat_id, text, parse_mode="Markdown")

    elif code == "tool_pic":
        faces = [
            "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&h=400&fit=crop",
            "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"
        ]
        bot.send_photo(chat_id, random.choice(faces), caption="🖼️ **প্রোফাইল পিকচারের ছবি**")

    # --- Profile Options ---
    elif code == "prof_list":
        worker_name = call.from_user.first_name
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        uids = []
        if os.path.isfile("accounts_list.csv"):
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) >= 3 and today in row[0] and worker_name == row[1]:
                        uids.append(row[2])
        text = f"📋 **আজকের জমা তালিকা ({len(uids)}টি):**\n\n" + "\n".join([f"`{i+1}.` {u}" for i, u in enumerate(uids)]) if uids else "আজ এখনো কিছু জমা দেননি।"
        bot.send_message(chat_id, text, parse_mode="Markdown")

    elif code == "prof_withdraw":
        balance = user_balances.get(chat_id, 0.0)
        if balance < MIN_WITHDRAW:
            bot.send_message(chat_id, f"⚠️ টাকা তুলতে সর্বনিম্ন ৳{MIN_WITHDRAW:.2f} লাগবে। আপনার আছে ৳{balance:.2f}")
        else:
            user_states[chat_id] = {'step': 'AWAITING_WITHDRAW_DETAILS'}
            bot.send_message(chat_id, "💳 বিকাশ/নগদ নম্বর এবং পরিমাণ দিন (যেমন: `01700000000 | 100`):", reply_markup=cancel_keyboard())

    elif code == "prof_ref":
        bot_uname = bot.get_me().username
        bot.send_message(chat_id, f"🔗 **আপনার রেফারেল লিংক:**\n`https://t.me/{bot_uname}?start={chat_id}`", parse_mode="Markdown")

    # --- Admin Options ---
    elif code == "adm_excel" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "rb") as f:
                bot.send_document(chat_id, f, caption="📁 Excel File")
        except Exception:
            bot.answer_callback_query(call.id, "❌ ফাইল খালি!")

    elif code == "adm_txt" and chat_id == ADMIN_ID:
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as csv_file, open("buyer_ready.txt", "w", encoding="utf-8") as txt_file:
                reader = csv.reader(csv_file)
                for row in reader:
                    if len(row) >= 5 and row[2] != "UID":
                        txt_file.write(f"{row[2]} | {row[3]} | {row[4]}\n")
            with open("buyer_ready.txt", "rb") as f:
                bot.send_document(chat_id, f, caption="📄 Buyer Ready TXT File")
        except Exception:
            bot.answer_callback_query(call.id, "❌ এরর হয়েছে!")

    elif code == "adm_pass" and chat_id == ADMIN_ID:
        msg = bot.send_message(chat_id, "নতুন পাসওয়ার্ড নিয়ম টাইপ করুন:")
        bot.register_next_step_handler(msg, lambda m: set_pass_rule(m.text.strip()))

    elif code == "adm_stats" and chat_id == ADMIN_ID:
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
        reply_msg = f"📊 **আজকের মোট জমা:** **{total}** টি\n\n" + "\n".join([f"• `{w}`: {c}টি" for w, c in workers.items()])
        bot.send_message(chat_id, reply_msg, parse_mode="Markdown")

# ================= TXT FILE UPLOAD LISTENER =================

@bot.message_handler(content_types=['document'])
def handle_txt_file(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    if state and state.get('step') == 'AWAITING_TXT_FILE':
        try:
            file_info = bot.get_file(message.document.file_id)
            content = bot.download_file(file_info.file_path).decode('utf-8')
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
            bot.reply_to(message, f"🎉 **ফাইল প্রসেস সম্পন্ন!** মোট **{success_count}** টি সঠিক অ্যাকাউন্ট সেভ হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))
        except Exception:
            bot.reply_to(message, "❌ ফাইল পড়া যায়নি। সঠিক TXT ফাইল দিন।")

# ================= GENERAL STATE MESSAGE HANDLER =================

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""
    state = user_states.get(chat_id)

    if not state:
        bot.send_message(chat_id, "নিচের মেইন মেনু থেকে অপশন বেছে নিন:", reply_markup=main_bottom_keyboard(chat_id))
        return

    step = state.get('step')

    if step == 'AWAITING_FB_LINK':
        uid = extract_numeric_uid(text)
        user_states.pop(chat_id, None)
        if uid:
            bot.send_message(chat_id, f"✅ প্রফাইল থেকে প্রাপ্ত Numeric UID:\n\n`{uid}`", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))
        else:
            bot.send_message(chat_id, "❌ কোনো সঠিক UID পাওয়া যায়নি।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_2FA_GEN':
        clean_key = text.replace(" ", "").upper()
        if is_valid_2fa_key(clean_key):
            try:
                totp = pyotp.TOTP(clean_key)
                bot.send_message(chat_id, f"🔑 2FA কোড:\n\n`{totp.now()}`", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))
                user_states.pop(chat_id, None)
            except Exception:
                bot.send_message(chat_id, "❌ কোড জেনারেট করা যায়নি।")
        else:
            bot.send_message(chat_id, "❌ ভুল 2FA Key!")

    elif step == 'AWAITING_NEW_PASS':
        user_passwords[chat_id] = text
        user_states.pop(chat_id, None)
        save_to_sheet("User_Passwords", [str(chat_id), text])
        bot.send_message(chat_id, f"✅ আপনার ডিফল্ট পাসওয়ার্ড সেভ হয়েছে: `{text}`", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_UID':
        numeric_uid = extract_numeric_uid(text)
        if not numeric_uid or is_duplicate_uid(numeric_uid):
            bot.send_message(chat_id, "❌ ভুল বা ডুপ্লিকেট UID!")
            return

        state['uid'] = numeric_uid
        state['step'] = 'AWAITING_TYPE'
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🍪 Cookies", callback_data="sub_cookie_type"),
            InlineKeyboardButton("🔐 2FA Key", callback_data="sub_2fa_type")
        )
        bot.send_message(chat_id, f"✅ UID গৃহীত: `{numeric_uid}`\n\nকী জমা দিতে চান বেছে নিন:", parse_mode="Markdown", reply_markup=markup)

    elif step == 'AWAITING_BULK_DATA':
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
        bot.send_message(chat_id, f"🎉 **বাল্ক জমা সম্পন্ন!** মোট **{success_count}** টি আইডি সেভ হয়েছে।", reply_markup=main_bottom_keyboard(chat_id))

    elif step == 'AWAITING_SINGLE_DATA':
        data_type = state.get('type')
        uid = state.get('uid')
        password = user_passwords.get(chat_id, f"Pass_{get_pass_rule()}")
        worker_name = message.from_user.first_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if data_type == 'COOKIE' and not is_valid_cookies(text):
            bot.send_message(chat_id, "❌ অকার্যকর কুকিজ!")
            return
        elif data_type == '2FA' and not is_valid_2fa_key(text):
            bot.send_message(chat_id, "❌ ভুল 2FA Key!")
            return

        tab = "Cookies_Data" if data_type == 'COOKIE' else "2FA_Data"
        save_to_sheet(tab, [now_str, str(chat_id), uid, password, text])
        with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
                writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
            writer.writerow([now_str, worker_name, uid, password, text])

        user_balances[chat_id] = user_balances.get(chat_id, 0.0) + RATE_PER_ACCOUNT
        bot.send_message(chat_id, f"🎉 **জমা সফল হয়েছে!**\n📌 **UID:** `{uid}`\n💰 যোগ হয়েছে: ৳{RATE_PER_ACCOUNT}", parse_mode="Markdown", reply_markup=main_bottom_keyboard(chat_id))
        user_states.pop(chat_id, None)

@bot.callback_query_handler(func=lambda call: call.data in ["sub_cookie_type", "sub_2fa_type"])
def handle_single_type_selection(call):
    chat_id = call.message.chat.id
    state = user_states.get(chat_id)
    if state and state.get('step') == 'AWAITING_TYPE':
        state['type'] = 'COOKIE' if call.data == "sub_cookie_type" else '2FA'
        state['step'] = 'AWAITING_SINGLE_DATA'
        text = "🍪 আপনার **Cookies** পেস্ট করুন:" if call.data == "sub_cookie_type" else "🔐 আপনার **2FA Key** দিন:"
        bot.edit_message_text(text, chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown")

# ================= RUNNER =================
if __name__ == "__main__":
    print("Bot Running with Clean UI Architecture...")
    bot.infinity_polling(skip_pending=True)