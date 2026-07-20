import telebot
from telebot import types

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4"
bot = telebot.TeleBot(TOKEN)

# ইউজারের পছন্দের ভাষা ধরে রাখার জন্য ডিকশনারি
user_lang = {}

# ১. ভাষা নির্বাচন কিবোর্ড
def get_language_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("🇧🇩 বাংলা")
    btn2 = types.KeyboardButton("🇬🇧 English")
    markup.add(btn1, btn2)
    return markup

# ২. মূল মেনু (বাংলা)
def get_main_menu_bn():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📱 সার্ভিস টেস্ট")
    btn2 = types.KeyboardButton("👤 প্রোফাইল")
    btn3 = types.KeyboardButton("🌐 ভাষা পরিবর্তন")
    markup.add(btn1, btn2, btn3)
    return markup

# ৩. Main Menu (English)
def get_main_menu_en():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📱 Service Test")
    btn2 = types.KeyboardButton("👤 Profile")
    btn3 = types.KeyboardButton("🌐 Change Language")
    markup.add(btn1, btn2, btn3)
    return markup

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
    user_id = message.from_user.id
    text = message.text

    # --- ভাষা নির্বাচন কন্ট্রোল ---
    if text == "🇧🇩 বাংলা":
        user_lang[user_id] = 'bn'
        bot.send_message(
            message.chat.id, 
            "✅ ভাষা নির্বাচন করা হয়েছে **বাংলা**।\n\nনিচের মেনু থেকে অপশন বেছে নিন:", 
            reply_markup=get_main_menu_bn(),
            parse_mode="Markdown"
        )
    elif text == "🇬🇧 English":
        user_lang[user_id] = 'en'
        bot.send_message(
            message.chat.id, 
            "✅ Language set to **English**.\n\nPlease choose an option from the menu:", 
            reply_markup=get_main_menu_en(),
            parse_mode="Markdown"
        )
        
    elif text in ["🌐 ভাষা পরিবর্তন", "🌐 Change Language"]:
        bot.send_message(
            message.chat.id, 
            "🌐 ভাষা নির্বাচন করুন / Select Language:", 
            reply_markup=get_language_keyboard()
        )

    # --- বাংলা মেসেজ হ্যান্ডলিং ---
    elif text == "📱 সার্ভিস টেস্ট":
        bot.reply_to(message, "✅ টেস্ট বাটন একদম পারফেক্ট কাজ করছে!")
    elif text == "👤 প্রোফাইল":
        bot.reply_to(message, f"👤 **নাম:** {message.from_user.first_name}\n🆔 **আইডি:** `{user_id}`", parse_mode="Markdown")

    # --- English Message Handling ---
    elif text == "📱 Service Test":
        bot.reply_to(message, "✅ Service test button is working perfectly!")
    elif text == "👤 Profile":
        bot.reply_to(message, f"👤 **Name:** {message.from_user.first_name}\n🆔 **ID:** `{user_id}`", parse_mode="Markdown")

    # --- ডিফল্ট রেসপন্স ---
    else:
        lang = user_lang.get(user_id, 'bn')
        if lang == 'en':
            bot.reply_to(message, "Please choose an option from the menu:", reply_markup=get_main_menu_en())
        else:
            bot.reply_to(message, "দয়া করে নিচের মেনু থেকে অপশন সিলেক্ট করুন:", reply_markup=get_main_menu_bn())

if __name__ == "__main__":
    print("Step 2 (Multi-Language) Bot is running...")
    bot.infinity_polling(skip_pending=True)