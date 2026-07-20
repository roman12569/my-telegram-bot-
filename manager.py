import telebot
import datetime
import csv
import os
import random
import requests
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# আপনার টোকেন এবং অ্যাডমিন আইডি
TOKEN = '8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4'
ADMIN_ID = 6257034751  

bot = telebot.TeleBot(TOKEN)
user_data = {}
DAILY_TARGET = 20

# ছেলে ও মেয়ে উভয়ের সুন্দর কমন নাম ও পদবি
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

def get_pass_rule():
    if not os.path.isfile("pass_rule.txt"):
        with open("pass_rule.txt", "w") as f: f.write("20")
    with open("pass_rule.txt", "r") as f: return f.read().strip()

def set_pass_rule(new_rule):
    with open("pass_rule.txt", "w") as f: f.write(new_rule)

def save_user(chat_id):
    users = set()
    if os.path.isfile("users.txt"):
        with open("users.txt", "r") as f:
            for line in f:
                if line.strip(): users.add(line.strip())
    if str(chat_id) not in users:
        with open("users.txt", "a") as f: f.write(f"{chat_id}\n")

def is_banned(chat_id):
    if not os.path.isfile("banned.txt"): return False
    with open("banned.txt", "r") as f:
        banned_users = f.read().splitlines()
    return str(chat_id) in banned_users

def ban_user(chat_id):
    with open("banned.txt", "a") as f: f.write(f"{chat_id}\n")

def is_duplicate_uid(uid):
    if not os.path.isfile("accounts_list.csv"): return False
    with open("accounts_list.csv", "r", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) > 2 and row[2] == uid: return True
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

# ================= বাটন মেনু =================
def worker_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📝 অ্যাকাউন্ট জমা দিন"), KeyboardButton("👤 রেন্ডম নাম জেনারেট"))
    markup.add(KeyboardButton("🖼️ ফেক পিকচার জেনারেট"), KeyboardButton("📧 টেম্প মেইল নিন"))
    markup.add(KeyboardButton("🔑 আজকের পাসওয়ার্ড"), KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"))
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📝 অ্যাকাউন্ট জমা দিন"), KeyboardButton("👤 রেন্ডম নাম জেনারেট"))
    markup.add(KeyboardButton("🖼️ ফেক পিকচার জেনারেট"), KeyboardButton("📧 টেম্প মেইল নিন"))
    markup.add(KeyboardButton("🔑 আজকের পাসওয়ার্ড"), KeyboardButton("📋 আমার জমা দেওয়া লিস্ট"))
    markup.add(KeyboardButton("📊 টিমের কাজের হিসাব"), KeyboardButton("⚙️ এডমিন প্যানেল"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "🚫 𝗔𝗽𝗻𝗮𝗸𝗲 𝗯𝗼𝘁 theke ban kora hoyeche!")
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
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

# ================= ১০০% কার্যকর টেম্প মেইল সিস্টেম (1secmail ভিত্তিক) =================
@bot.message_handler(func=lambda message: message.text == "📧 টেম্প মেইল নিন")
def create_mail(message):
    try:
        domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
        domain = random.choice(domains)
        username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
        email = f"{username}@{domain}"

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "🔄 Inbox Check (OTP দেখুন)",
                callback_data=f"inbox_{username}_{domain}"
            )
        )

        bot.send_message(
            message.chat.id,
            f"┌──────────────────────┐\n"
            f"  📧 **𝗧𝗘𝗠𝗣𝗢𝗥𝗔𝗥𝗬 𝗠𝗔𝗜𝗟𝗕𝗢𝗫**\n"
            f"└──────────────────────┘\n\n"
            f"📧 Temp Mail:\n\n`{email}`",
            parse_mode="Markdown",
            reply_markup=markup
        )

    except Exception as e:
        bot.reply_to(message, f"❌ মেইল তৈরি করতে সমস্যা হয়েছে। আবার চেষ্টা করুন!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox_"))
def check_inbox(call):
    try:
        parts = call.data.split("_")
        username = parts[1]
        domain = parts[2]
        email = f"{username}@{domain}"

        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={username}&domain={domain}"
        response = requests.get(url, timeout=10)
        messages = response.json()

        if not messages:
            bot.answer_callback_query(
                call.id,
                "📭 Inbox Empty! কোনো ওটিপি আসেনি।",
                show_alert=True
            )
            return

        text = f"📬 **Inbox Messages for:** `{email}`\n\n"

        for msg in messages:
            msg_id = msg['id']
            subject = msg['subject']
            sender = msg['from']
            
            # মেসেজ বা ওটিপি পড়ার জন্য রিকোয়েস্ট
            msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={username}&domain={domain}&id={msg_id}"
            msg_res = requests.get(msg_url, timeout=10).json()
            body = msg_res.get('textBody', 'No content')
            
            text += f"👤 **From:** {sender}\n📌 **Subject:** {subject}\n\n💬 **Content/OTP:**\n`{body}`\n-------------------\n"

        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
        bot.answer_callback_query(call.id, "✅ ইনবক্স চেক করা হয়েছে!")

    except Exception as e:
        bot.answer_callback_query(
            call.id,
            "❌ ইনবক্স চেক করতে সমস্যা হয়েছে!",
            show_alert=True
        )

# ================= অন্যান্য ফিচারস (ফেক পিকচার, নাম ইত্যাদি) =================
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
    except Exception as e:
        bot.reply_to(message, "❌ ছবি লোড হতে সমস্যা হয়েছে। আবার চেষ্টা করুন!")

@bot.message_handler(func=lambda message: message.text == "👤 রেন্ডম নাম জেনারেট")
def generate_fake_name(message):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    birth_year = random.randint(1995, 2004)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    name_text = f"┌──────────────────────┐\n  👤 **𝗙𝗔𝗞𝗘 𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗗𝗘𝗧𝗔𝗜𝗟𝗦**\n└──────────────────────┘\n\n🔹 **First Name:** `{first}`\n🔹 **Last Name:** `{last}`\n🔹 **Full Name:** `{first} {last}`\n🔹 **DOB:** `{birth_day}-{birth_month}-{birth_year}`"
    markup = admin_menu() if message.chat.id == ADMIN_ID else worker_menu()
    bot.reply_to(message, name_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔑 আজকের পাসওয়ার্ড")
def show_current_password(message):
    current_rule = get_pass_rule()
    pass_text = f"┌──────────────────────┐\n  🔑 **𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗥𝗨𝗟𝗘𝗦**\n└──────────────────────┘\n\n✨ আজকের পাসওয়ার্ডে অবশ্যই থাকতে হবে:\n👉 ` {current_rule} `"
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

@bot.message_handler(func=lambda message: message.text == "📊 টিমের কাজের হিসাব")
def team_stats(message):
    if message.chat.id != ADMIN_ID: return
    bot.clear_step_handler_by_chat_id(message.chat.id)
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
    for w, c in workers.items(): reply_msg += f"• 👤 `{w}` — **{c}** pcs\n"
    bot.reply_to(message, reply_msg, parse_mode="Markdown", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "⚙️ এডমিন প্যানেল")
def admin_panel(message):
    if message.chat.id != ADMIN_ID: return
    bot.clear_step_handler_by_chat_id(message.chat.id)
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

@bot.callback_query_handler(func=lambda call: not call.data.startswith("inbox_"))
def handle_query(call):
    if call.message.chat.id != ADMIN_ID: return
    if call.data == "download_excel":
        try:
            with open("accounts_list.csv", "rb") as file: bot.send_document(call.message.chat.id, file, caption="📁 এক্সেল ফাইল!")
        except: bot.answer_callback_query(call.id, "❌ ফাইল নেই!")
    elif call.data == "download_txt":
        try:
            with open("accounts_list.csv", "r", encoding="utf-8-sig") as csv_file, open("buyer_ready.txt", "w", encoding="utf-8") as txt_file:
                reader = csv.reader(csv_file)
                for row in reader:
                    if len(row) >= 5 and row[2] != "UID": txt_file.write(f"{row[2]} | {row[3]} | {row[4]}\n")
            with open("buyer_ready.txt", "rb") as file: bot.send_document(call.message.chat.id, file, caption="📄 TXT ফাইল!")
        except: bot.answer_callback_query(call.id, "❌ এরর!")
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
        if os.path.isfile("accounts_list.csv"): os.remove("accounts_list.csv")
        bot.answer_callback_query(call.id, "✅ রিসেট সম্পন্ন!", show_alert=True)
        bot.send_message(call.message.chat.id, "🗑️ ডাটা ক্লিয়ার করা হয়েছে।")

def update_pass_rule(message):
    set_pass_rule(message.text.strip())
    bot.reply_to(message, f"✅ শর্ত আপডেট হয়েছে: `{message.text.strip()}`", parse_mode="Markdown", reply_markup=admin_menu())

def process_broadcast(message):
    count = 0
    if os.path.isfile("users.txt"):
        with open("users.txt", "r") as f:
            for line in f:
                if line.strip():
                    try: bot.send_message(line.strip(), f"📢 **NOTICE:**\n\n{message.text}", parse_mode="Markdown"); count += 1
                    except: pass
    bot.reply_to(message, f"✅ নোটিশ পাঠানো হয়েছে {count} জনকে।", reply_markup=admin_menu())

def process_ban(message):
    if message.text.strip().isdigit():
        ban_user(message.text.strip())
        bot.reply_to(message, f"✅ ব্যান করা হয়েছে!", reply_markup=admin_menu())

# ================= অ্যাকাউন্ট জমা দেওয়ার সিস্টেম =================
@bot.message_handler(func=lambda message: message.text == "📝 অ্যাকাউন্ট জমা দিন")
def start_submission(message):
    if is_banned(message.chat.id): return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    save_user(message.chat.id)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ বাতিল করুন"))
    msg = bot.reply_to(message, "📝 **UID দিন (১০-১৬ ডিজিট):**", parse_mode="Markdown", reply_markup=markup)
    bot.register_next_step_handler(msg, process_uid_step)

def process_uid_step(message):
    if message.text == "❌ বাতিল করুন":
        bot.reply_to(message, "✅ বাতিল করা হয়েছে।", reply_markup=admin_menu() if message.chat.id == ADMIN_ID else worker_menu())
        return
    uid = message.text.strip()
    if not uid.isdigit() or len(uid) < 10 or len(uid) > 16 or is_duplicate_uid(uid):
        msg = bot.reply_to(message, "❌ ভুল বা ডুপ্লিকেট UID! আবার দিন:", reply_markup=message.reply_markup)
        bot.register_next_step_handler(msg, process_uid_step)
        return
    user_data[message.chat.id] = {'uid': uid}
    msg = bot.reply_to(message, f"✅ পাসওয়ার্ড দিন (শর্ত: `{get_pass_rule()}` থাকতে হবে):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    if message.text == "❌ বাতিল করুন":
        bot.reply_to(message, "✅ বাতিল করা হয়েছে।", reply_markup=admin_menu() if message.chat.id == ADMIN_ID else worker_menu())
        return
    password = message.text.strip()
    if get_pass_rule() not in password or len(password) < 6:
        msg = bot.reply_to(message, f"❌ ভুল পাসওয়ার্ড! `{get_pass_rule()}` থাকতে হবে। আবার দিন:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_password_step)
        return
    user_data[message.chat.id]['password'] = password
    msg = bot.reply_to(message, "✅ 2FA কোড বা Cookies দিন:")
    bot.register_next_step_handler(msg, process_2fa_step)

def process_2fa_step(message):
    if message.text == "❌ বাতিল করুন":
        bot.reply_to(message, "✅ বাতিল করা হয়েছে।", reply_markup=admin_menu() if message.chat.id == ADMIN_ID else worker_menu())
        return
    two_fa = message.text.strip()
    if not (("c_user=" in two_fa or "datr=" in two_fa) or (two_fa.replace(" ", "").isalnum() and len(two_fa.replace(" ", "")) >= 15)):
        msg = bot.reply_to(message, "❌ ভুল Cookies/2FA! সঠিক কোড দিন:")
        bot.register_next_step_handler(msg, process_2fa_step)
        return
    worker_name = message.from_user.first_name
    uid = user_data[message.chat.id]['uid']
    password = user_data[message.chat.id]['password']
    date_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("accounts_list.csv", "a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        if not os.path.isfile("accounts_list.csv") or os.stat("accounts_list.csv").st_size == 0:
            writer.writerow(["Date & Time", "Worker Name", "UID", "Password", "2FA/Cookies"])
        writer.writerow([date_time, worker_name, uid, password, two_fa])
    
    user_count = get_user_daily_count(worker_name)
    bar = "█" * min(user_count, 10) + "░" * max(10 - user_count, 0)
    bot.reply_to(message, f"🎉 **সফলভাবে জমা হয়েছে!**\n\n📊 আজকের প্রগ্রেস: `[{bar}]` {user_count}/{DAILY_TARGET}", parse_mode="Markdown", reply_markup=admin_menu() if message.chat.id == ADMIN_ID else worker_menu())

print("Bot Running with 1secmail Engine...")
bot.infinity_polling()
pyTelegramBotAPI
requests
