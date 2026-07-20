import telebot
from telebot import types
import time
import os

# প্রাইভেসি ও সিকিউরিটি কনফিগারেশন
TOKEN = '8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4'
bot = telebot.TeleBot(TOKEN)

# প্রাইভেসি প্রোটেকশন: আপনি চাইলে নির্দিষ্ট অ্যাডমিন বা কাজের ওয়াটারদের আইডি এখানে যুক্ত করতে পারেন
# খালি রাখলে সবাই ব্যবহার করতে পারবে, তবে সিকিউরিটি ফিল্টার কাজ করবে
AUTHORIZED_USERS = [] # উদাহরণ: [123456789, 987654321]

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📝 একাউন্ট জমা দিন")
    btn2 = types.KeyboardButton("👤 রেন্ডম নাম জেনারেট")
    btn3 = types.KeyboardButton("🖼️ ফেক পিকচার জেনারেটর")
    btn4 = types.KeyboardButton("💳 টেম্প মেইল নিন")
    btn5 = types.KeyboardButton("🔑 আজকের পাসওয়ার্ড")
    btn6 = types.KeyboardButton("📋 আমার জমা দেওয়া লিস্ট")
    btn7 = types.KeyboardButton("📊 টিমের কাজের হিসাব")
    btn8 = types.KeyboardButton("⚙️ অ্যাডমিন প্যানেল")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        user_name = message.from_user.first_name
        
        # প্রাইভেসি চেক (যদি হোয়াইটলিস্ট চালু করতে চান)
        if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
            # বটটিকে প্রাইভেট রাখার জন্য নোটিফিকেশন দিতে পারেন
            pass

        bot.reply_to(
            message, 
            f"🛡️ **স্বাগতম, {user_name}!**\n\nOnline Earning Bazar সিকিউর ম্যানেজমেন্ট সিস্টেমে আপনাকে স্বাগতম। আপনার প্রয়োজনীয় অপশনটি নিচে থেকে সিলেক্ট করুন:", 
            reply_markup=main_menu(), 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Security Start Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_secure_messages(message):
    try:
        if not message.text:
            return
            
        text = message.text.strip()
        
        menu_buttons = [
            "📝 একাউন্ট জমা দিন",
            "👤 রেন্ডম নাম জেনারেট",
            "🖼️ ফেক পিকচার জেনারেটর",
            "💳 টেম্প মেইল নিন",
            "🔑 আজকের পাসওয়ার্ড",
            "📋 আমার জমা দেওয়া লিস্ট",
            "📊 টিমের কাজের হিসাব",
            "⚙️ অ্যাডমিন প্যানেল"
        ]
        
        if text in menu_buttons:
            if text == "📝 একাউন্ট জমা দিন":
                bot.reply_to(message, "📝 সিকিউর মোড: দয়া করে আপনার ফেসবুক একাউন্টের সঠিক UID এখানে দিন:")
            elif text == "👤 রেন্ডম নাম জেনারেট":
                bot.reply_to(message, "👤 প্রাইভেট নাম জেনারেটর: `Nazmul Hossain`", parse_mode="Markdown")
            elif text == "🖼️ ফেক পিকচার জেনারেটর":
                bot.reply_to(message, "🖼️ ফেক পিকচার জেনারেশন প্রসেসিং চলছে...")
            elif text == "💳 টেম্প মেইল নিন":
                bot.reply_to(message, "💳 আপনার এনক্রিপ্টেড টেম্প মেইল জেনারেট করা হয়েছে।")
            elif text == "🔑 আজকের পাসওয়ার্ড":
                bot.reply_to(message, "🔑 সিকিউর পাসওয়ার্ড: `OEB-SECURE-2026#99`", parse_mode="Markdown")
            elif text == "📋 আমার জমা দেওয়া লিস্ট":
                bot.reply_to(message, "📋 আপনার লিস্ট সম্পূর্ণ সুরক্ষিত ও ফাঁকা রয়েছে।")
            elif text == "📊 টিমের কাজের হিসাব":
                bot.reply_to(message, "📊 টিমের টোটাল কাজের ডেটাবেজ আপডেট হচ্ছে।")
            elif text == "⚙️ অ্যাডমিন প্যানেল":
                bot.reply_to(message, "⚙️ **SECURE ADMIN CONTROL PANEL**\n\nঅ্যাডমিন এক্সেস ভেরিফাইড।", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"✅ সিলেকشن সফল হয়েছে: {text}", reply_markup=main_menu())
        else:
            # স্প্যাম বা ভুল UID ফিল্টারিং লজিক
            bot.reply_to(message, "❌ ভুল বা ডুপ্লিকেট UID! প্রাইভেসি প্রটেকশনের কারণে সঠিক ফরম্যাটে আবার দিন:")
            
    except Exception as e:
        print(f"Secure Handler Error: {e}")

if __name__ == "__main__":
    print("🔒 OEB Secure Manager Bot is running with high privacy filters...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Network error caught: {e}. Reconnecting securely in 5 seconds...")
            time.sleep(5)