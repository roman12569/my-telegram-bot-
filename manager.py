import telebot
from telebot import types

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4"
bot = telebot.TeleBot(TOKEN)

# ফিক্সড কাস্টম কিবোর্ড মেনু
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📱 সার্ভিস টেস্ট")
    btn2 = types.KeyboardButton("👤 প্রোফাইল")
    markup.add(btn1, btn2)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id, 
        "👋 **স্বাগতম!**\n\nধাপ ১ সফলভাবে কানেক্ট হয়েছে। নিচের বাটনগুলো চেপে পরীক্ষা করুন:", 
        reply_markup=get_main_menu(), 
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    if message.text == "📱 সার্ভিস টেস্ট":
        bot.reply_to(message, "✅ টেস্ট বাটন একদম পারফেক্ট কাজ করছে!")
    elif message.text == "👤 প্রোফাইল":
        bot.reply_to(message, f"👤 **নাম:** {message.from_user.first_name}\n🆔 **আইডি:** `{message.from_user.id}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "দয়া করে নিচের মেনু বাটন সিলেক্ট করুন।", reply_markup=get_main_menu())

if __name__ == "__main__":
    print("Step 1 Bot is running...")
    bot.infinity_polling(skip_pending=True)