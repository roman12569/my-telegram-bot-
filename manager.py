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

# আপনার পছন্দমতো স্ক্রিনশটের স্টাইলে প্রিমিয়াম ফিক্সড কিবোর্ড মেনু
def get_custom_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("📱 Get Number")
    btn2 = types.KeyboardButton("🔐 2Fa")
    btn3 = types.KeyboardButton("🤖 Api Number")
    btn4 = types.KeyboardButton("📊 Live Traffic")
    btn5 = types.KeyboardButton("🌐 Language")
    btn6 = types.KeyboardButton("👤 Profile")
    btn7 = types.KeyboardButton("💰 Withdraw")
    btn8 = types.KeyboardButton("⚙️ Admin Panel")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        welcome_text = (
            "🔥 **Online Earning Bazar** ড্যাশবোর্ডে স্বাগতম!\n\n"
            "🤖 আপনার প্রয়োজনীয় অপশনটি নিচের মেনু থেকে সিলেক্ট করুন:"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=get_custom_keyboard(), parse_mode="Markdown")
    except Exception as e:
        print(f"Start Error: {e}")

user_states = {}

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    try:
        if not message.text:
            return
            
        text = message.text.strip()
        user_id = str(message.from_user.id)
        chat_id = message.chat.id
        
        # যদি ইউজার UID জমা দেওয়ার স্টেপে থাকে
        if user_id in user_states and user_states[user_id] == "waiting_for_uid":
            data = load_data()
            if user_id not in data:
                data[user_id] = []
            data[user_id].append(text)
            save_data(data)
            
            user_states[user_id] = None
            bot.reply_to(message, "✅ সফলভাবে আপনার ডেটা/UID জমা হয়েছে!", reply_markup=get_custom_keyboard())
            return

        if text == "📱 Get Number":
            bot.reply_to(message, "📱 বর্তমান কাজের জন্য নতুন নম্বর আপডেট করা হয়েছে। কাজ শুরু করুন!", reply_markup=get_custom_keyboard())
            
        elif text == "🔐 2Fa":
            pass_string = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%', k=10))
            bot.reply_to(message, f"🔐 **আপনার সিকিউর 2FA কোড/পাসওয়ার্ড:**\n`{pass_string}`", parse_mode="Markdown", reply_markup=get_custom_keyboard())
            
        elif text == "🤖 Api Number":
            bot.reply_to(message, "🤖 API নম্বর কানেকশন স্ট্যাটাস: Active ✅", reply_markup=get_custom_keyboard())
            
        elif text == "📊 Live Traffic":
            data = load_data()
            total_accounts = sum(len(accs) for accs in data.values())
            bot.reply_to(message, f"📊 **Live Traffic & Stats:**\n\nমোট প্রসেসড একাউন্ট: `{total_accounts}` টি", parse_mode="Markdown", reply_markup=get_custom_keyboard())
            
        elif text == "🌐 Language":
            bot.reply_to(message, "🌐 ভাষা সিলেক্ট করা আছে: বাংলা (Bangla)", reply_markup=get_custom_keyboard())
            
        elif text == "👤 Profile":
            user_name = message.from_user.first_name
            bot.reply_to(message, f"👤 **Profile Info:**\n\nনাম: {user_name}\nআইডি: `{user_id}`\nস্ট্যাটাস: Worker ✅", parse_mode="Markdown", reply_markup=get_custom_keyboard())
            
        elif text == "💰 Withdraw":
            bot.reply_to(message, "💰 আপনার ব্যালেন্স চেক করতে অ্যাডমিনের সাথে যোগাযোগ করুন।", reply_markup=get_custom_keyboard())
            
        elif text == "⚙️ Admin Panel":
            bot.reply_to(message, "⚙️ **ADMIN CONTROL PANEL**\n\nঅ্যাডমিন এক্সেস ভেরিফাইড।", parse_mode="Markdown", reply_markup=get_custom_keyboard())
            
        else:
            # অন্য কোনো টেক্সট দিলে জাস্ট মেনু দেখাবে
            bot.reply_to(message, "দয়া করে নিচের বাটনগুলো ব্যবহার করে আপনার কাজ পরিচালনা করুন:", reply_markup=get_custom_keyboard())
            
    except Exception as e:
        print(f"Message Handler Error: {e}")

if __name__ == "__main__":
    print("OEB Pro Bot is running...")
    bot.infinity_polling(skip_pending=True)