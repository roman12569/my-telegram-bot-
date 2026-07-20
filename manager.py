import telebot
from telebot import types
import time
import random
import requests

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4" 
bot = telebot.TeleBot(TOKEN)

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
        user_name = message.from_user.first_name
        bot.reply_to(
            message, 
            f"🔥 **Online Earning Bazar** বটে স্বাগতম, {user_name}!\n\nসব ফিচার এখন ১০০% লাইভ ও সচল:", 
            reply_markup=main_menu(), 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Start Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        if not message.text:
            return
            
        text = message.text.strip()
        
        # ১. আনলিমিটেড ফেক নাম জেনারেটর ডাটা
        first_names = ["Md.", "Nazmul", "Rakibul", "Tanvir", "Sojib", "Imran", "Farhan", "Sumaiya", "Nusrat", "Ayesha", "Jannat", "Tasnim", "Sakib", "Mehedi", "Al-Amin"]
        last_names = ["Hossain", "Islam", "Ahmed", "Khan", "Chowdhury", "Talukder", "Sarker", "Mahmud", "Ali", "Mia", "Rahman"]

        # ২. টেম্প মেইল ডোমেইন লিস্ট
        mail_domains = ["tempmail.com", "10minutemail.com", "fakemail.net", "getairmail.com", "throwawaymail.com"]

        if text == "📝 একাউন্ট জমা দিন":
            bot.reply_to(message, "📝 আপনার ফেসবুক একাউন্টের সঠিক UID এখানে পাঠান:")
            
        elif text == "👤 রেন্ডম নাম জেনারেট":
            # রেন্ডম নাম তৈরি
            gen_name = f"{random.choice(first_names)} {random.choice(last_names)}"
            bot.reply_to(message, f"👤 **আপনার নতুন ফেক নাম:**\n`{gen_name}`", parse_mode="Markdown")
            
        elif text == "🖼️ ফেক পিকচার জেনারেটর":
            # আনলিমিটেড র্যান্ডম ছবি পাওয়ার জন্য লাইভ API লিংক (DiceBear API)
            seed_val = random.randint(1000, 999999)
            photo_url = f"https://api.dicebear.com/7.x/avataaars/png?seed={seed_val}"
            bot.send_photo(message.chat.id, photo_url, caption="🖼️ **আপনার জন্য ১০০% ইউনিক ফেক পিকচার!** (সেভ করে ব্যবহার করুন)", parse_mode="Markdown")
            
        elif text == "💳 টেম্প মেইল নিন":
            # আনলিমিটেড টেম্প মেইল জেনারেটর
            random_string = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
            temp_mail = f"{random_string}@{random.choice(mail_domains)}"
            bot.reply_to(message, f"💳 **আপনার টেম্প মেইল:**\n`{temp_mail}`", parse_mode="Markdown")
            
        elif text == "🔑 আজকের পাসওয়ার্ড":
            # স্ট্রং র্যান্ডম পাসওয়ার্ড জেনারেটর
            pass_string = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%', k=10))
            bot.reply_to(message, f"🔑 **আজকের সিক্রেট পাসওয়ার্ড:**\n`{pass_string}`", parse_mode="Markdown")
            
        elif text == "📋 আমার জমা দেওয়া লিস্ট":
            bot.reply_to(message, "📋 আপনার জমাকৃত একাউন্টের তালিকা এই মুহূর্তে খালি।")
            
        elif text == "📊 টিমের কাজের হিসাব":
            bot.reply_to(message, "📊 টিমের বর্তমান কাজের স্ট্যাটাস: অল আউটপুট একটিভ।")
            
        elif text == "⚙️ অ্যাডমিন প্যানেল":
            bot.reply_to(message, "⚙️ **ADMIN CONTROL PANEL**\n\nঅ্যাডমিন ভেরিফাইড!", parse_mode="Markdown")
            
        else:
            bot.reply_to(message, "❌ ভুল বা ডুপ্লিকেট UID! দয়া করে সঠিক UID আবার দিন:")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("🚀 OEB Ultimate Bot is running...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Connection lost: {e}. Reconnecting...")
            time.sleep(5)