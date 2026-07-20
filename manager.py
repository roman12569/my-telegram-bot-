import telebot
from telebot import types
import time

# আপনার বটের টোকেন
TOKEN = "7917724816:AAGVqFq-w3l13u7bQY6k18p19yZ2X5c8b0A" 
bot = telebot.TeleBot(TOKEN)

# মেনু বাটন তৈরির ফাংশন
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

# /start কমান্ড হ্যান্ডলার
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        bot.reply_to(
            message, 
            "🔥 **Online Earning Bazar** ম্যানেজমেন্ট বটে আপনাকে স্বাগতম!\n\nনিচের অপশনগুলো থেকে আপনার প্রয়োজনীয় কাজটি সিলেক্ট করুন:", 
            reply_markup=main_menu(), 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Start Error: {e}")

# সকল মেসেজ এবং বাটন কন্ট্রোল করার মাস্টার হ্যান্ডলার
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        if not message.text:
            return
            
        text = message.text.strip()
        
        # মেনু বাটনগুলোর সঠিক লিস্ট
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
        
        # যদি ব্যবহারকারী মেনুর কোনো বাটন চাপে
        if text in menu_buttons:
            if text == "📝 একাউন্ট জমা দিন":
                bot.reply_to(message, "📝 দয়া করে আপনার ফেসবুক একাউন্টের সঠিক UID এখানে দিন:")
            elif text == "👤 রেন্ডম নাম জেনারেট":
                bot.reply_to(message, "👤 আপনার জেনারেট করা নাম: `Rakibul Islam` (উদাহরণ)", parse_mode="Markdown")
            elif text == "🖼️ ফেক পিকচার জেনারেটর":
                bot.reply_to(message, "🖼️ পিকচার জেনারেট করার কাজ চলছে...")
            elif text == "💳 টেম্প মেইল নিন":
                bot.reply_to(message, "💳 আপনার টেম্প মেইল: `example123@tempmail.com`", parse_mode="Markdown")
            elif text == "🔑 আজকের পাসওয়ার্ড":
                bot.reply_to(message, "🔑 আজকের সিক্রেট পাসওয়ার্ড: `OEB@2026#secure`", parse_mode="Markdown")
            elif text == "📋 আমার জমা দেওয়া লিস্ট":
                bot.reply_to(message, "📋 আপনার জমাকৃত একাউন্টের তালিকা ফাঁকা।")
            elif text == "📊 টিমের কাজের হিসাব":
                bot.reply_to(message, "📊 বর্তমান টিমের কাজের মোট হিসাব দেখতে অ্যাডমিন প্যানেলে যান।")
            elif text == "⚙️ অ্যাডমিন প্যানেল":
                bot.reply_to(message, "⚙️ আপনি অ্যাডমিন প্যানেলে প্রবেশ করেছেন।")
            else:
                bot.reply_to(message, f"✅ আপনি সিলেক্ট করেছেন: {text}", reply_markup=main_menu())
        else:
            # যদি কেউ UID বা অন্য কিছু ইনপুট দেয় (যা মেনু বাটন নয়)
            # এখানে আপনার আসল UID চেকিং লজিক বসবে
            bot.reply_to(message, "❌ ভুল বা ডুপ্লিকেট UID! দয়া করে সঠিক UID আবার দিন:")
            
    except Exception as e:
        print(f"Message Handler Error: {e}")

# ব্রাশফায়ার সেফটি লুপ (বট কখনো অফ হবে না, নেট চলে গেলেও অটো রিকানেক্ট করবে)
if __name__ == "__main__":
    print("🚀 OEB Manager Bot is fully loaded and running...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Connection lost: {e}. Reconnecting in 5 seconds...")
            time.sleep(5)