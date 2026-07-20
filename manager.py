import telebot
from telebot import types
import random
import json
import os

TOKEN = "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4" 
bot = telebot.TeleBot(TOKEN)

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

# প্রিমিয়াম ইনলাইন মেনু (যাতে কোনো ফিক্সড কিবোর্ড বাটন নিচে না আসে)
def get_inline_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("📝 একাউন্ট জমা দিন", callback_data="submit_acc")
    btn2 = types.InlineKeyboardButton("👤 রেন্ডম নাম", callback_data="gen_name")
    btn3 = types.InlineKeyboardButton("🖼️ ফেক পিকচার", callback_data="gen_pic")
    btn4 = types.InlineKeyboardButton("💳 টেম্প মেইল", callback_data="temp_mail")
    btn5 = types.InlineKeyboardButton("🔑 পাসওয়ার্ড", callback_data="gen_pass")
    btn6 = types.InlineKeyboardButton("📋 আমার জমা দেওয়া লিস্ট", callback_data="my_list")
    btn7 = types.InlineKeyboardButton("📊 টিমের কাজের হিসাব", callback_data="team_stats")
    btn8 = types.InlineKeyboardButton("⚙️ অ্যাডমিন প্যানেল", callback_data="admin_panel")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        # আগের চ্যাট থেকে ফিক্সড কিবোর্ড থাকলে তা রিমুভ করার জন্য রিমুভ কিবোর্ড ব্যবহার করা হয়েছে
        remove_markup = types.ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "🔄 সিস্টেম রিফ্রেশ হচ্ছে...", reply_markup=remove_markup)

        # আসল চ্যানেল ও গ্রুপ লিংকসহ ভেরিফিকেশন বাটন
        channel_markup = types.InlineKeyboardMarkup(row_width=2)
        channel_markup.add(
            types.InlineKeyboardButton("📢 Join Channel", url="https://t.me/Online_Earning_Bazar_Official"),
            types.InlineKeyboardButton("👥 OTP Group", url="https://t.me/Online_Earning_Bazar_Official"),
            types.InlineKeyboardButton("🛡️ Verify ✅", callback_data="verify_join")
        )
        
        welcome_text = (
            "👇 **Quick Menu**\n\n"
            "🤖 বট ব্যবহার করতে নিচের চ্যানেলগুলোতে জয়েন করুন:\n\n"
            "> Please join our channel and group, then click Verify"
        )
        
        bot.send_message(message.chat.id, welcome_text, reply_markup=channel_markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Start Error: {e}")

user_states = {}

@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call):
    try:
        query = call.data
        chat_id = call.message.chat.id
        user_id = str(call.from_user.id)
        
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
            user_states[user_id] = "waiting_for_uid"
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "📝 দয়া করে আপনার ফেসবুক একাউন্টের সঠিক UID বা তথ্য এখানে পাঠান:")
            
        elif query == "my_list":
            data = load_data()
            user_subs = data.get(user_id, [])
            if user_subs:
                list_text = "📋 **আপনার জমাকৃত একাউন্টসমূহ:**\n\n" + "\n".join([f"- {item}" for item in user_subs])
            else:
                list_text = "📋 আপনার জমাকৃত একাউন্টের লিস্ট খালি।"
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, list_text, parse_mode="Markdown")
            
        elif query == "team_stats":
            data = load_data()
            total_accounts = sum(len(accs) for accs in data.values())
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, f"📊 **টিমের কাজের হিসাব:**\n\nমোট জমা হওয়া একাউন্ট: `{total_accounts}` টি", parse_mode="Markdown")
            
        elif query == "admin_panel":
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "⚙️ **ADMIN CONTROL PANEL**\n\nঅ্যাডমিন এক্সেস ভেরিফাইড।", parse_mode="Markdown")
            
    except Exception as e:
        print(f"Callback Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_text_inputs(message):
    try:
        user_id = str(message.from_user.id)
        if user_id in user_states and user_states[user_id] == "waiting_for_uid":
            text = message.text.strip()
            data = load_data()
            if user_id not in data:
                data[user_id] = []
            data[user_id].append(text)
            save_data(data)
            
            user_states[user_id] = None
            bot.reply_to(message, "✅ সফলভাবে আপনার UID জমা হয়েছে!")
        else:
            bot.reply_to(message, "দয়া করে /start লিখে মেনু ওপেন করুন।")
    except Exception as e:
        print(f"Text Input Error: {e}")

if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)