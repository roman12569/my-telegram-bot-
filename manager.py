import telebot
from telebot import types
import random
import json
import os

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4"
bot = telebot.TeleBot(TOKEN)

# ডাটা এবং স্ট্যাট ধরে রাখার ভ্যারিয়েবল
user_lang = {}
user_states = {}
DATA_FILE = "submissions.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ১. ভাষা নির্বাচন কিবোর্ড
def get_language_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🇧🇩 বাংলা", "🇬🇧 English")
    return markup

# ২. মূল মেনু (বাংলা)
def get_main_menu_bn():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📝 একাউন্ট জমা দিন")
    btn2 = types.KeyboardButton("👤 রেন্ডম নাম")
    btn3 = types.KeyboardButton("📱 সার্ভিস টেস্ট")
    btn4 = types.KeyboardButton("👤 প্রোফাইল")
    btn5 = types.KeyboardButton("🌐 ভাষা পরিবর্তন")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# ৩. Main Menu (English)
def get_main_menu_en():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📝 Submit Account")
    btn2 = types.KeyboardButton("👤 Random Name")
    btn3 = types.KeyboardButton("📱 Service Test")
    btn4 = types.KeyboardButton("👤 Profile")
    btn5 = types.KeyboardButton("🌐 Change Language")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# নাম ডাটাবেজ
first_names_en = ["Md.", "Nazmul", "Rakibul", "Tanvir", "Sojib", "Imran", "Farhan", "Sakib", "Mehedi"]
last_names_en = ["Hossain", "Islam", "Ahmed", "Khan", "Chowdhury", "Sarker", "Mahmud", "Ali"]

first_names_bn = ["মোঃ", "নাজমুল", "রাকিবুল", "তানভির", "সজীব", "ইমরান", "ফারহান", "সাকিব", "মেহেদী"]
last_names_bn = ["হোসেন", "ইসলাম", "আহমেদ", "খান", "চৌধুরী", "সরকার", "মাহমুদ", "আলী"]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id, 
        "👋 **Welcome to Online Earning Bazar!**\n\nদয়া করে আপনার পছন্দের ভাষা নির্বাচন করুন / Please select your language:", 
        reply_markup=get_language_keyboard(), 
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = str(message.from_user.id)
    text = message.text.strip()
    lang = user_lang.get(user_id, 'bn')

    # --- ১. জমা দেওয়া তথ্য রিসিভ করার লজিক ---
    if user_id in user_states and user_states[user_id] == "waiting_for_uid":
        data = load_data()
        if user_id not in data:
            data[user_id] = []
        data[user_id].append(text)
        save_data(data)
        
        user_states[user_id] = None # স্টেট ক্লিয়ার করা হলো
        
        if lang == 'en':
            bot.reply_to(message, "✅ Your Account UID/Data has been saved successfully!", reply_markup=get_main_menu_en())
        else:
            bot.reply_to(message, "✅ আপনার একাউন্ট UID/তথ্য সফলভাবে জমা হয়েছে!", reply_markup=get_main_menu_bn())
        return

    # --- ২. ভাষা পরিবর্তন কন্ট্রোল ---
    if text == "🇧🇩 বাংলা":
        user_lang[user_id] = 'bn'
        bot.send_message(message.chat.id, "✅ ভাষা নির্বাচন করা হয়েছে **বাংলা**।", reply_markup=get_main_menu_bn(), parse_mode="Markdown")
        
    elif text == "🇬🇧 English":
        user_lang[user_id] = 'en'
        bot.send_message(message.chat.id, "✅ Language set to **English**.", reply_markup=get_main_menu_en(), parse_mode="Markdown")
        
    elif text in ["🌐 ভাষা পরিবর্তন", "🌐 Change Language"]:
        bot.send_message(message.chat.id, "🌐 ভাষা নির্বাচন করুন / Select Language:", reply_markup=get_language_keyboard())

    # --- ৩. সার্ভিস ১: একাউন্ট জমা দিন ---
    elif text in ["📝 একাউন্ট জমা দিন", "📝 Submit Account"]:
        user_states[user_id] = "waiting_for_uid"
        if lang == 'en':
            bot.reply_to(message, "📝 Please send your Facebook Account UID or details now:")
        else:
            bot.reply_to(message, "📝 দয়া করে আপনার ফেসবুক একাউন্টের সঠিক UID বা তথ্য এখানে পাঠান:")

    # --- ৪. সার্ভিস ২: রেন্ডম নাম জেনারেটর ---
    elif text in ["👤 রেন্ডম নাম", "👤 Random Name"]:
        if lang == 'en':
            name = f"{random.choice(first_names_en)} {random.choice(last_names_en)}"
            bot.reply_to(message, f"👤 **Generated Name:**\n`{name}`", parse_mode="Markdown")
        else:
            name = f"{random.choice(first_names_bn)} {random.choice(last_names_bn)}"
            bot.reply_to(message, f"👤 **জেনারেট করা নাম:**\n`{name}`", parse_mode="Markdown")

    # --- ৫. সার্ভিস টেস্ট ও প্রোফাইল ---
    elif text in ["📱 সার্ভিস টেস্ট", "📱 Service Test"]:
        msg = "✅ সার্ভিস রান্নিং আছে!" if lang == 'bn' else "✅ Services are running fine!"
        bot.reply_to(message, msg)
        
    elif text in ["👤 প্রোফাইল", "👤 Profile"]:
        if lang == 'en':
            bot.reply_to(message, f"👤 **Name:** {message.from_user.first_name}\n🆔 **ID:** `{user_id}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"👤 **নাম:** {message.from_user.first_name}\n🆔 **আইডি:** `{user_id}`", parse_mode="Markdown")

    # --- ডিফল্ট রেসপন্স ---
    else:
        if lang == 'en':
            bot.reply_to(message, "Please select an option from the menu:", reply_markup=get_main_menu_en())
        else:
            bot.reply_to(message, "দয়া করে নিচের মেনু থেকে অপশন সিলেক্ট করুন:", reply_markup=get_main_menu_bn())

if __name__ == "__main__":
    print("Step 3 (Services Added) Bot is running...")
    bot.infinity_polling(skip_pending=True)