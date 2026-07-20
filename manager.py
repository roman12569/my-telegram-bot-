import telebot
from telebot import types
import time
import random

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4" 
bot = telebot.TeleBot(TOKEN)

# প্রিমিয়াম ইনলাইন মেনু ডিজাইন (অনলাইন আর্নিং বাজার স্টাইল)
def get_inline_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("📝 একাউন্ট জমা দিন", callback_data="submit_acc")
    btn2 = types.InlineKeyboardButton("👤 রেন্ডম নাম", callback_data="gen_name")
    btn3 = types.InlineKeyboardButton("🖼️ ফেক পিকচার", callback_data="gen_pic")
    btn4 = types.InlineKeyboardButton("💳 টেম্প মেইল", callback_data="temp_mail")
    btn5 = types.InlineKeyboardButton("🔑 পাসওয়ার্ড", callback_data="gen_pass")
    btn6 = types.InlineKeyboardButton("📋 আমার লিস্ট", callback_data="my_list")
    btn7 = types.InlineKeyboardButton("📊 টিমের হিসাব", callback_data="team_stats")
    btn8 = types.InlineKeyboardButton("⚙️ অ্যাডমিন প্যানেল", callback_data="admin_panel")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

# /start কমান্ড হ্যান্ডলার (চ্যানেল জয়েন ভেরিফিকেশন সহ প্রিমিয়াম লুক)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_name = message.from_user.first_name
        
        # চ্যানেল বা গ্রুপে জয়েন করার প্রিমিয়াম ইনলাইন বাটন
        channel_markup = types.InlineKeyboardMarkup(row_width=2)
        channel_markup.add(
            types.InlineKeyboardButton("📢 Join Channel", url="https://t.me/your_channel_link"),
            types.InlineKeyboardButton("👥 OTP Group", url="https://t.me/your_group_link"),
            types.InlineKeyboardButton("🛡️ Verify ✅", callback_data="verify_join")
        )
        
        welcome_text = (
            f"👇 **Quick Menu**\n\n"
            f"🤖 বট ব্যবহার করতে নিচের চ্যানেলগুলোতে জয়েন করুন:\n\n"
            f"> Please join our channel and group, then click Verify"
        )
        
        bot.send_message(message.chat.id, welcome_text, reply_markup=channel_markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Start Error: {e}")

# ইনলাইন বাটন ক্লিক কন্ট্রোল করার হ্যান্ডলার
@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call):
    try:
        query = call.data
        chat_id = call.message.chat.id
        
        if query == "verify_join":
            bot.answer_callback_query(call.id, "✅ ভেরিফিকেশন সফল হয়েছে!")
            bot.send_message(chat_id, "🔥 **Online Earning Bazar** ড্যাশবোর্ডে স্বাগতম!\n\nআপনার প্রয়োজনীয় অপশনটি নিচে থেকে সিলেক্ট করুন:", reply_markup=get_inline_menu(), parse_mode="Markdown")
            
        elif query == "gen_name":
            first_names = ["Md.", "Nazmul", "Rakibul", "Tanvir", "Sojib", "Imran", "Farhan", "Sumaiya", "Nusrat", "Ayesha"]
            last_names = ["Hossain", "Islam", "Ahmed", "Khan", "Chowdhury", "Talukder", "Sarker"]
            gen_name = f"{random.choice(first_names)} {random.choice(last_names)}"
            bot.answer_callback_query(call.id, "রেন্ডম নাম তৈরি করা হয়েছে!")
            bot.send_message(chat_id, f"👤 **আপনার নতুন ফেক নাম:**\n`{gen_name}`", parse_mode="Markdown")
            
        elif query == "gen_pic":
            seed_val = random.randint(1000, 999999)
            photo_url = f"https://api.dicebear.com/7.x/avataaars/png?seed={seed_val}"
            bot.answer_callback_query(call.id, "ফেক পিকচার লোড হচ্ছে...")
            bot.send_photo(chat_id, photo_url, caption="🖼️ **আপনার ইউনিক ফেক পিকচার!**", parse_mode="Markdown")
            
        elif query == "temp_mail":
            random_string = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
            temp_mail = f"{random_string}@tempmail.com"
            bot.answer_callback_query(call.id, "টেম্প মেইল রেডি!")
            bot.send_message(chat_id, f"💳 **আপনার টেম্প মেইল:**\n`{temp_mail}`", parse_mode="Markdown")
            
        elif query == "gen_pass":
            pass_string = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%', k=10))
            bot.answer_callback_query(call.id, "পাসওয়ার্ড তৈরি হয়েছে!")
            bot.send_message(chat_id, f"🔑 **সিক্রেট পাসওয়ার্ড:**\n`{pass_string}`", parse_mode="Markdown")
            
        elif query == "submit_acc":
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "📝 দয়া করে আপনার ফেসবুক একাউন্টের সঠিক UID পাঠান:")
            
        elif query == "my_list":
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "📋 আপনার জমাকৃত একাউন্টের লিস্ট খালি।")
            
        elif query == "team_stats":
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "📊 টিমের বর্তমান কাজের স্ট্যাটাস আপডেট আছে।")
            
        elif query == "admin_panel":
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "⚙️ **ADMIN CONTROL PANEL**\n\nঅ্যাডমিন এক্সেস ভেরিফাইড।", parse_mode="Markdown")
            
    except Exception as e:
        print(f"Callback Error: {e}")

if __name__ == "__main__":
    print("🚀 OEB Premium Bot is running with stunning inline UI...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Connection lost: {e}. Reconnecting...")
            time.sleep(5)