
import os, gc, io, re, csv, time, random, string, hashlib, threading, collections, concurrent.futures
from datetime import datetime, timedelta, timezone
import requests, openpyxl, pyotp, telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from flask import Flask
from waitress import serve
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

# ==========================================
# 1. ENV & CONFIG
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8765437674:AAGCMs5y3_8WXduxd_kSpF_4Jm-2EovgHl4")
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://admin:W3tcfbw_EW8QfR-@cluster0.nvv6umd.mongodb.net/?appName=Cluster0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6257034751"))
BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID", "-1003943094107"))

BD_TIMEZONE = timezone(timedelta(hours=6))

UAS = [
    "Mozilla/5.0 (Linux; Android 13; SM-G973F) AppleWebKit/537.36 Chrome/114.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
]
REQUIRED_CHANNELS = [
    {"name": "Online Earning Bazar™🍀", "username": "@earningbazar0", "url": "https://t.me/earningbazar0"},
    {"name": "ONLINE EARNING METHOD", "username": "@onlineearningmethod5", "url": "https://t.me/onlineearningmethod5"},
    {"name": "Online Earning Shop🗂️", "username": "@onlineearningshop01", "url": "https://t.me/onlineearningshop01"}
]

# ==========================================
# 2. MULTI-LANGUAGE SUPPORT (BN & EN)
# ==========================================
LANG = {
    "en": {
        "welcome": "🏠 <b>Welcome to OEB NEXUS!</b>\n\n━━━━━━━━━━━━━━━━━━\n✨ Select an option below:",
        "btn_submit": "📦 Submit Tasks", "btn_tools": "🛠 Helper Tools",
        "btn_wallet": "💼 Profile & Wallet", "btn_reward": "🎁 Reward & Support",
        "btn_admin": "⚙️ Admin Center", "btn_back": "🔙 Back", "btn_cancel": "❌ Cancel",
        "btn_main": "🏠 Main Menu", "btn_balance": "💰 My Balance", "btn_withdraw": "💸 Withdraw",
        "btn_tx_history": "📜 Tx History", "btn_bonus": "🎁 Daily Bonus", "btn_support": "📞 Support",
        "btn_temp_email": "📧 Temp Email", "btn_2fa": "🔐 2FA Gen", "btn_leaderboard": "🏆 Leaderboard",
        "btn_single": "📝 Single", "btn_bulk": "📑 Bulk Text", "btn_excel": "📊 Excel/CSV",
        "btn_task_mgmt": "📋 Task Mgmt", "btn_finance": "💰 Finance", "btn_settings": "⚙️ Settings", "btn_system": "🖥 System",
        "btn_buyer_report": "📊 Buyer Report", "btn_force_close": "🚫 Force Close", "btn_export": "📥 Export Data",
        "lang_changed": "✅ Language changed to English!", "invalid_doc": "❌ Please use the menu to start a file submission first.",
        "send_uid": "✅ <b>Category Set!</b>\n\n━━━━━━━━━━━━━━━━━━\n📩 Now send the <b>UID</b>:",
        "send_payload": "📦 <b>UID Received!</b>\n\n━━━━━━━━━━━━━━━━━━\n📩 Now send the <b>Payload</b> (Cookie/2FA):",
        "send_pass": "🔐 <b>Confirmation Required</b>\n\n━━━━━━━━━━━━━━━━━━\n🔑 Enter your <b>Password</b> to confirm:",
        "balance_msg": "💼 <b>Wallet Details</b>\n\n━━━━━━━━━━━━━━━━━━\n💵 <b>Balance:</b> {balance} BDT\n🏦 <b>Hold Balance:</b> {hold} BDT\n💎 <b>Virtual Wallet:</b> {virtual} BDT",
        "bonus_claimed": "🎉 <b>Bonus Claimed!</b>\n\n━━━━━━━━━━━━━━━━━━\n💰 +1.0 BDT added to your balance.",
        "bonus_already": "⚠️ <b>Already Claimed!</b>\n\nYou have already claimed today's bonus. Come back tomorrow!",
        "support_msg": "📞 <b>Need Help?</b>\n\n━━━━━━━━━━━━━━━━━━\n👨‍💻 Contact Admin: @oeb_support",
        "no_tx": "📜 <b>No Transactions</b>\n\nYou have no recent transactions.",
        "tx_msg": "📜 <b>Recent Transactions</b>\n\n━━━━━━━━━━━━━━━━━━",
        "select_sub_type": "📦 <b>Select Submission Type:</b>", "select_tool": "🛠 <b>Select a Tool:</b>",
        "select_wallet": "💼 <b>Wallet Options:</b>", "select_reward": "🎁 <b>Rewards & Support:</b>",
        "admin_welcome": "⚙️ <b>Admin Control Center</b>\n\n━━━━━━━━━━━━━━━━━━\n👑 Select an admin module:",
        "select_cat": "📦 <b>Select Task Category:</b>\n\n💡 <i>Rates include active surge bonus.</i>",
        "withdraw_msg": "💸 <b>Withdrawal</b>\n\n━━━━━━━━━━━━━━━━━━\n⚠️ Minimum withdrawal: 50 BDT.\n📩 Send amount to withdraw:",
        "task_saved": "✅ <b>Task Saved Successfully!</b>\n\n━━━━━━━━━━━━━━━━━━\n🎫 <b>Track ID:</b> <code>{tid}</code>\n💰 <b>Rate:</b> {rate} BDT\n\n🔄 <i>Send next UID or click Cancel.</i>",
        "bulk_processing": "⏳ <b>Processing Bulk Text...</b>\n\n━━━━━━━━━━━━━━━━━━\n🔄 Please wait, this may take a few moments.",
        "bulk_done": "✅ <b>Bulk Processing Complete!</b>\n\n━━━━━━━━━━━━━━━━━━\n📥 <b>Accepted:</b> {count}\n💰 <b>Total Payout:</b> {payout} BDT",
        "file_processing": "⏳ <b>Processing File...</b>\n\n━━━━━━━━━━━━━━━━━━\n🔄 Extracting and verifying data.",
        "file_done": "✅ <b>File Processing Complete!</b>\n\n━━━━━━━━━━━━━━━━━━\n📥 <b>Accepted:</b> {count}\n💰 <b>Total Payout:</b> {payout} BDT"
    },
    "bn": {
        "welcome": "🏠 <b>OEB NEXUS এ স্বাগতম!</b>\n\n━━━━━━━━━━━━━━━━━━\n✨ নিচ থেকে একটি অপশন সিলেক্ট করুন:",
        "btn_submit": "📦 টাস্ক সাবমিট", "btn_tools": "🛠 হেল্পার টুলস",
        "btn_wallet": "💼 প্রোফাইল ও ওয়ালেট", "btn_reward": "🎁 রিওয়ার্ড ও সাপোর্ট",
        "btn_admin": "⚙️ অ্যাডমিন প্যানেল", "btn_back": "🔙 ব্যাক", "btn_cancel": "❌ ক্যান্সেল",
        "btn_main": "🏠 মেইন মেনু", "btn_balance": "💰 আমার ব্যালেন্স", "btn_withdraw": "💸 উইথড্র",
        "btn_tx_history": "📜 হিস্টরি", "btn_bonus": "🎁 ডেইলি বোনাস", "btn_support": "📞 সাপোর্ট",
        "btn_temp_email": "📧 টেম্প ইমেইল", "btn_2fa": "🔐 2FA জেনারেটর", "btn_leaderboard": "🏆 লিডারবোর্ড",
        "btn_single": "📝 সিঙ্গেল", "btn_bulk": "📑 বাল্ক টেক্সট", "btn_excel": "📊 এক্সেল ফাইল",
        "btn_task_mgmt": "📋 টাস্ক ম্যানেজ", "btn_finance": "💰 ফাইন্যান্স", "btn_settings": "⚙️ সেটিংস", "btn_system": "🖥 সিস্টেম",
        "btn_buyer_report": "📊 বায়ার রিপোর্ট", "btn_force_close": "🚫 ফোর্স ক্লোজ", "btn_export": "📥 এক্সপোর্ট",
        "lang_changed": "✅ ভাষা বাংলায় পরিবর্তন করা হয়েছে!", "invalid_doc": "❌ ফাইল সাবমিট করতে আগে মেনু থেকে অপশন নিন।",
        "send_uid": "✅ <b>ক্যাটাগরি সেট!</b>\n\n━━━━━━━━━━━━━━━━━━\n📩 এবার <b>UID</b> পাঠান:",
        "send_payload": "📦 <b>UID পেয়েছি!</b>\n\n━━━━━━━━━━━━━━━━━━\n📩 এবার <b>Payload</b> (Cookie/2FA) পাঠান:",
        "send_pass": "🔐 <b>কনফার্মেশন প্রয়োজন</b>\n\n━━━━━━━━━━━━━━━━━━\n🔑 কনফার্ম করতে আপনার <b>পাসওয়ার্ড</b> দিন:",
        "balance_msg": "💼 <b>ওয়ালেট ডিটেইলস</b>\n\n━━━━━━━━━━━━━━━━━━\n💵 <b>ব্যালেন্স:</b> {balance} BDT\n🏦 <b>হোল্ড ব্যালেন্স:</b> {hold} BDT\n💎 <b>ভার্চুয়াল ওয়ালেট:</b> {virtual} BDT",
        "bonus_claimed": "🎉 <b>বোনাস ক্লেইম!</b>\n\n━━━━━━━━━━━━━━━━━━\n💰 ১.০ BDT আপনার ব্যালেন্সে যুক্ত হয়েছে।",
        "bonus_already": "⚠️ <b>ইতিমধ্যে নেওয়া হয়েছে!</b>\n\nআপনি আজকের বোনাস নিয়েছেন। আগামীকাল আবার আসুন!",
        "support_msg": "📞 <b>সাহায্য দরকার?</b>\n\n━━━━━━━━━━━━━━━━━━\n👨‍💻 এডমিন কন্টাক্ট: @oeb_support",
        "no_tx": "📜 <b>কোনো ট্রানজাকশন নেই</b>\n\nআপনার কোনো সাম্প্রতিক ট্রানজাকশন নেই।",
        "tx_msg": "📜 <b>সাম্প্রতিক ট্রানজাকশন</b>\n\n━━━━━━━━━━━━━━━━━━",
        "select_sub_type": "📦 <b>সাবমিশন টাইপ সিলেক্ট করুন:</b>", "select_tool": "🛠 <b>একটি টুল সিলেক্ট করুন:</b>",
        "select_wallet": "💼 <b>ওয়ালেট অপশন:</b>", "select_reward": "🎁 <b>রিওয়ার্ড ও সাপোর্ট:</b>",
        "admin_welcome": "⚙️ <b>অ্যাডমিন কন্ট্রোল সেন্টার</b>\n\n━━━━━━━━━━━━━━━━━━\n👑 একটি অ্যাডমিন মডিউল সিলেক্ট করুন:",
        "select_cat": "📦 <b>টাস্ক ক্যাটাগরি সিলেক্ট করুন:</b>\n\n💡 <i>রেটের সাথে সার্জ বোনাস যুক্ত।</i>",
        "withdraw_msg": "💸 <b>উইথড্র</b>\n\n━━━━━━━━━━━━━━━━━━\n⚠️ সর্বনিম্ন উইথড্র: 50 BDT।\n📩 উইথড্র করার পরিমাণ পাঠান:",
        "task_saved": "✅ <b>টাস্ক সফলভাবে সেভ হয়েছে!</b>\n\n━━━━━━━━━━━━━━━━━━\n🎫 <b>ট্র্যাক আইডি:</b> <code>{tid}</code>\n💰 <b>রেট:</b> {rate} BDT\n\n🔄 <i>পরবর্তী UID পাঠান অথবা ক্যান্সেল করুন।</i>",
        "bulk_processing": "⏳ <b>বাল্ক টেক্সট প্রসেসিং...</b>\n\n━━━━━━━━━━━━━━━━━━\n🔄 অপেক্ষা করুন, এটি কিছুটা সময় নিতে পারে।",
        "bulk_done": "✅ <b>বাল্ক প্রসেসিং সম্পন্ন!</b>\n\n━━━━━━━━━━━━━━━━━━\n📥 <b>গৃহীত:</b> {count}\n💰 <b>মোট পেআউট:</b> {payout} BDT",
        "file_processing": "⏳ <b>ফাইল প্রসেসিং...</b>\n\n━━━━━━━━━━━━━━━━━━\n🔄 ডেটা এক্সট্রাক্ট এবং ভেরিফাই করা হচ্ছে।",
        "file_done": "✅ <b>ফাইল প্রসেসিং সম্পন্ন!</b>\n\n━━━━━━━━━━━━━━━━━━\n📥 <b>গৃহীত:</b> {count}\n💰 <b>মোট পেআউট:</b> {payout} BDT"
    }
}

def get_text(key, chat_id):
    user = get_user_data(chat_id)
    lang = user.get("lang", "bn")
    return LANG.get(lang, LANG["bn"]).get(key, key)

# ==========================================
# 3. DB & CACHE SETUP
# ==========================================
bot = telebot.TeleBot(BOT_TOKEN)
mongo_client = MongoClient(MONGO_URL, maxPoolSize=20, minPoolSize=5, socketTimeoutMS=10000, connect=False)
db = mongo_client["earning_bazar_advanced"]
users_col, submissions_col, settings_col = db["users"], db["submissions"], db["settings"]
withdrawals_col, blacklisted_payloads_col, ai_logs_col = db["withdrawals"], db["blacklisted_payloads"], db["ai_logs"]
submissions_col.create_index([("track_id", 1)], unique=True, background=True)
submissions_col.create_index([("uid", 1)], background=True)

class GuaranteedBoundedExecutor:
    def __init__(self, max_workers, max_queue_size=None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.sem = threading.Semaphore(max_queue_size) if max_queue_size else None
    def submit(self, fn, *args, **kwargs):
        if self.sem and not self.sem.acquire(blocking=False): return None
        return self.executor.submit(self._wrap, fn, *args, **kwargs)
    def _wrap(self, fn, *args, **kwargs):
        try: return fn(*args, **kwargs)
        finally:
            if self.sem: self.sem.release()

background_executor = GuaranteedBoundedExecutor(3, 100)
heavy_task_executor = GuaranteedBoundedExecutor(2, 50)
live_check_executor = GuaranteedBoundedExecutor(2, 100)
cache_executor = concurrent.futures.ThreadPoolExecutor(2)

class FastSettingsCache:
    def __init__(self):
        self.lock, self.cache = threading.Lock(), {}
        for doc in settings_col.find(): self.cache[doc['key']] = doc['value']
    def get(self, key, default=None):
        with self.lock:
            if key in self.cache: return self.cache[key]
        doc = settings_col.find_one({"key": key})
        if doc: 
            with self.lock: self.cache[key] = doc['value']
            return doc['value']
        return default
    def set(self, key, value):
        with self.lock: self.cache[key] = value
        cache_executor.submit(lambda: settings_col.update_one({"key": key}, {"$set": {"value": value}}, upsert=True))

class MongoDict:
    def __init__(self, col, max_size=2000):
        self.col, self.max, self.lock = col, max_size, threading.Lock()
        self.cache = collections.OrderedDict()
    def get(self, key, default=None):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key); return self.cache[key]
        doc = self.col.find_one({"_id": key})
        if doc and 'value' in doc:
            with self.lock:
                self.cache[key] = doc['value']; self.cache.move_to_end(key)
                if len(self.cache) > self.max: self.cache.popitem(last=False)
            return doc['value']
        return default
    def __setitem__(self, key, value):
        with self.lock:
            self.cache[key] = value; self.cache.move_to_end(key)
            if len(self.cache) > self.max: self.cache.popitem(last=False)
        cache_executor.submit(lambda: self.col.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True))
    def pop(self, key, default=None):
        with self.lock: val = self.cache.pop(key, default)
        if val is not default: cache_executor.submit(lambda: self.col.delete_one({"_id": key}))
        return val

fast_settings = FastSettingsCache()
user_states = MongoDict(db['user_states'])
def get_setting(k, d=None): return fast_settings.get(k, d)
def update_setting(k, v): fast_settings.set(k, v)

def get_bd_time(): return datetime.now(BD_TIMEZONE)
def parse_iso(dt):
    if not dt: return None
    try:
        d = datetime.fromisoformat(dt) if isinstance(dt, str) else dt
        return d.replace(tzinfo=BD_TIMEZONE) if d.tzinfo is None else d.astimezone(BD_TIMEZONE)
    except: return None

# ==========================================
# 4. CORE UTILITIES & SECURITY
# ==========================================
def sanitize_html(text):
    if not text: return "User"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_user_data(cid):
    u = users_col.find_one({"_id": cid})
    if not u:
        nu = {"_id": cid, "username": "", "first_name": "Worker", "balance": 0.0, "hold_balance": 0.0, 
              "banned": False, "custom_password": "", "role": "member", "virtual_wallet": 0.0, "lang": "bn", "last_bonus_date": None}
        try: users_col.insert_one(nu); return nu
        except DuplicateKeyError: return users_col.find_one({"_id": cid})
    return u

def update_user_field(cid, f, v):
    if f == "_id": return
    background_executor.submit(lambda: users_col.update_one({"_id": cid}, {"$set": {f: v}}, upsert=True))

def is_user_banned(cid): 
    u = users_col.find_one({"_id": cid}, {"banned": 1})
    return u.get("banned", False) if u else False

def check_force_join(uid):
    if uid == ADMIN_ID: return True
    for ch in REQUIRED_CHANNELS:
        try:
            m = bot.get_chat_member(ch["username"], uid)
            if m.status in ['left', 'kicked']: return False
        except: return False
    return True

def validate_strict_password(p, r):
    if not r or str(r).strip().lower() == "none": return True
    return str(p).strip().endswith(str(r).strip()) if p else False

UID_PATTERN = re.compile(r'(?:c_user=|id=|profile\.php\?id=|/u/)(\d{8,20})|(?<!\d)(\d{8,20})(?!\d)')
def extract_numeric_uid(t):
    if not t: return None
    m = UID_PATTERN.search(str(t)); return m.group(1) or m.group(2) if m else None

def is_duplicate_uid(uid):
    if not uid: return True
    try: return submissions_col.find_one({"uid": str(uid)}, {"_id": 1}) is not None
    except: return True

def generate_payload_hash(p):
    if not p: return None
    return hashlib.sha256(re.sub(r'\s+', '', str(p)).encode('utf-8')).hexdigest()

def is_payload_blacklisted(h):
    if not h: return True
    try: return blacklisted_payloads_col.find_one({"_id": h}) is not None
    except: return True

def is_valid_cookies(c):
    if not c: return False
    lc = str(c).lower(); return any(t in lc for t in ["c_user=", "datr=", "xs=", "sessionid="])

def generate_tracking_id(): return f"SUB-{int(get_bd_time().timestamp())}-{random.randint(100,999)}"

# ==========================================
# 5. LIVE CHECKERS & PRICING
# ==========================================
def check_live_account(uid):
    c_uid = extract_numeric_uid(uid)
    if not c_uid: return False, "Invalid"
    time.sleep(random.uniform(0.5, 1.0))
    try:
        res = requests.get(f"https://m.facebook.com/profile.php?id={c_uid}", headers={"User-Agent": random.choice(UAS)}, timeout=5.0, allow_redirects=True)
        url, txt = (res.url or "").lower(), res.text.lower()
        if res.status_code == 403 or "login" in url or "checkpoint" in url:
            if "c_user" not in url and c_uid not in url: return False, "Cloud Blocked"
        if res.status_code != 200: return False, "Dead"
        if 'content="no-cache"' in txt or "not found" in txt: return False, "Checkpoint"
        if "profile_ring" in txt or "mbasic_inline_feed_composer" in txt or c_uid in url: return True, "Live"
        return False, "Suspended"
    except: return False, "Network Error"

def get_active_surge_bonus():
    sc = get_setting("surge_pricing", {"active": False, "bonus": 0.0, "expires_at": None})
    if sc.get("active"):
        exp = parse_iso(sc.get("expires_at"))
        if exp and get_bd_time() < exp: return float(sc.get("bonus", 0.0))
        if not exp: return float(sc.get("bonus", 0.0))
    return 0.0

def get_current_task_rate(cat):
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    return float(rates.get(cat, 5.0)) + get_active_surge_bonus()

def get_shift_config():
    return get_setting("shift_config", {"current_date": get_bd_time().strftime("%Y-%m-%d"), "deadlines": {"default": "23:59"}})

def is_submission_allowed(cat, rt):
    try:
        s = get_shift_config()
        if rt.strftime("%Y-%m-%d") != s.get("current_date"): return False, "⚠️ Shift not active!"
        dl = s.get("deadlines", {}).get(cat, s.get("deadlines", {}).get("default", "23:59"))
        h, m = map(int, dl.split(":"))
        if rt > rt.replace(hour=h, minute=m, second=0, microsecond=0): return False, f"⚠️ Deadline {dl} passed!"
        return True, "OK"
    except: return True, "OK"

# ==========================================
# 6. SUBMISSION LOGIC
# ==========================================
def _save_submission(cid, uid, pay, cat):
    tid, dk, rate = generate_tracking_id(), get_bd_time().strftime("%Y-%m-%d"), get_current_task_rate(cat)
    doc = {"_id": tid, "track_id": tid, "uid": str(uid), "payload": pay, "category": cat, "rate": rate, "status": "Hold", "date_key": dk, "submitted_at": get_bd_time(), "user_id": cid}
    try:
        submissions_col.insert_one(doc)
        users_col.update_one({"_id": cid}, {"$inc": {"hold_balance": rate}})
        return tid, rate
    except DuplicateKeyError: return None, 0.0

def handle_single_uid(cid, txt):
    uid = extract_numeric_uid(txt)
    if not uid or is_duplicate_uid(uid): return "❌ Invalid/Duplicate UID."
    sd = user_states.get(cid, {}); cat = sd.get("category", "fb_cookie")
    ok, msg = is_submission_allowed(cat, get_bd_time())
    if not ok: return msg
    sd["state"], sd["temp_uid"] = "AWAITING_SINGLE_DATA", uid; user_states[cid] = sd
    return get_text("send_payload", cid)

def handle_single_data(cid, pay):
    sd = user_states.get(cid, {}); uid, cat = sd.get("temp_uid"), sd.get("category", "fb_cookie")
    if not uid: return "❌ Session expired."
    gr, cp = get_setting("pass_rule", ""), get_user_data(cid).get("custom_password", "")
    if validate_strict_password(cp, gr):
        tid, r = _save_submission(cid, uid, pay, cat)
        if tid: 
            sd["state"] = "AWAITING_UID"; sd.pop("temp_uid", None); user_states[cid] = sd
            return get_text("task_saved", cid).format(tid=tid, rate=r)
        return "❌ Duplicate."
    sd["state"], sd["temp_payload"] = "AWAITING_MANUAL_PASSWORD", pay; user_states[cid] = sd
    return get_text("send_pass", cid)

def handle_manual_password(cid, pw):
    sd = user_states.get(cid, {}); uid, pay, cat = sd.get("temp_uid"), sd.get("temp_payload"), sd.get("category", "fb_cookie")
    if not uid or not pay: return "❌ Expired."
    if validate_strict_password(pw, get_setting("pass_rule", "")):
        tid, r = _save_submission(cid, uid, pay, cat)
        if tid:
            update_user_field(cid, "custom_password", pw)
            sd["state"] = "AWAITING_UID"; sd.pop("temp_uid", None); sd.pop("temp_payload", None); user_states[cid] = sd
            return get_text("task_saved", cid).format(tid=tid, rate=r) + "\n🔓 <i>Password saved for instant future submissions.</i>"
        return "❌ Duplicate."
    return "❌ Wrong password."

def handle_bulk_text(cid, txt):
    cp, gr = get_user_data(cid).get("custom_password", ""), get_setting("pass_rule", "")
    if not validate_strict_password(cp, gr): return "❌ Invalid Password."
    bot.send_message(cid, get_text("bulk_processing", cid), parse_mode="HTML")
    def rbk():
        try:
            lines, pending = txt.strip().split('\n'), []
            for l in lines:
                l = l.strip()
                if not l: continue
                uid = extract_numeric_uid(l)
                if not uid or is_duplicate_uid(uid) or is_payload_blacklisted(generate_payload_hash(l)): continue
                cat = "fb_cookie" if is_valid_cookies(l) else "fb_2fa"
                if is_submission_allowed(cat, get_bd_time())[0]: pending.append({"uid": uid, "pay": l, "cat": cat})
            if not pending: bot.send_message(cid, "❌ No valid tasks."); return
            def chk(i): i["live"], _ = check_live_account(i["uid"]); return i
            res = live_check_executor.map(chk, pending)
            acc, tot = 0, 0.0
            for i in res:
                if i["live"]:
                    tid, r = _save_submission(cid, i["uid"], i["pay"], i["cat"])
                    if tid: acc += 1; tot += r
            bot.send_message(cid, get_text("bulk_done", cid).format(count=acc, payout=f"{tot:.2f}"), parse_mode="HTML")
        except Exception as e: print(e); bot.send_message(cid, "❌ Error.")
        finally: gc.collect()
    heavy_task_executor.submit(rbk); return None

# ==========================================
# 7. FILE & AUTO-MATCHER PROCESSORS
# ==========================================
def send_private_backup_message(content, doc_buf=None, doc_name=None):
    def task():
        try:
            safe_content = str(content)[:3750]
            if doc_buf and doc_name:
                doc_buf.seek(0)
                bot.send_document(BACKUP_CHANNEL_ID, doc_buf, caption=safe_content, parse_mode="HTML")
            else:
                bot.send_message(BACKUP_CHANNEL_ID, safe_content, parse_mode="HTML")
        except Exception as e: print(f"[Backup] Error: {e}")
    background_executor.submit(task)

def _process_document(message):
    cid = message.chat.id
    if get_setting("maintenance_mode", False): bot.send_message(cid, "🛠 Maintenance."); return
    if is_user_banned(cid): bot.send_message(cid, "🚫 Banned."); return
    
    global_rule = get_setting("pass_rule", "")
    custom_pass = get_user_data(cid).get("custom_password", "")
    if not validate_strict_password(custom_pass, global_rule):
        bot.send_message(cid, "❌ Invalid Password."); return
        
    bot.send_message(cid, get_text("file_processing", cid), parse_mode="HTML")
    original_filename = message.document.file_name or "backup_file"
    file_ext = original_filename.lower().split('.')[-1]
    
    try:
        dw = bot.download_file(bot.get_file(message.document.file_id).file_path)
        cands = []
        if file_ext == "csv":
            for row in csv.reader(dw.decode('utf-8', errors='ignore').splitlines()):
                u, p = None, None
                for v in row:
                    v = str(v).strip()
                    if not v: continue
                    if not u: u = extract_numeric_uid(v)
                    if not p and (is_valid_cookies(v) or (len(v)>20 and not v.isdigit())): p = v
                if u and p and not is_duplicate_uid(u): cands.append({"uid": u, "payload": p})
        elif file_ext in ["xlsx", "xls"]:
            wb = openpyxl.load_workbook(io.BytesIO(dw), read_only=True, data_only=True)
            for row in wb.active.iter_rows(values_only=True):
                u, p = None, None
                for v in row:
                    if v is None: continue
                    v = str(v).strip()
                    if not u: u = extract_numeric_uid(v)
                    if not p and (is_valid_cookies(v) or (len(v)>20 and not v.isdigit())): p = v
                if u and p and not is_duplicate_uid(u): cands.append({"uid": u, "payload": p})
            wb.close()
        else: bot.send_message(cid, "❌ Unsupported format."); return
        
        valid = []
        for c in cands:
            if is_payload_blacklisted(generate_payload_hash(c["payload"])): continue
            cat = "fb_cookie" if is_valid_cookies(c["payload"]) else "fb_2fa"
            if is_submission_allowed(cat, get_bd_time())[0]: valid.append({**c, "cat": cat})
            
        def chk(i): i["live"], _ = check_live_account(i["uid"]); return i
        res = live_check_executor.map(chk, valid)
        acc, tot = 0, 0.0
        for i in res:
            if i["live"]:
                tid, r = _save_submission(cid, i["uid"], i["payload"], i["cat"])
                if tid: acc += 1; tot += r
                
        doc_buf = io.BytesIO(dw)
        backup_filename = f"Backup_{get_bd_time().strftime('%Y-%m-%d')}_{original_filename}"
        caption = f"📂 <b>FILE BACKUP</b>\n\n👤 <b>ID:</b> <code>{cid}</code>\n✅ <b>Count:</b> {acc}\n💰 <b>Payout:</b> {tot:.2f} BDT"
        send_private_backup_message(caption, doc_buf=doc_buf, doc_name=backup_filename)
        
        bot.send_message(cid, get_text("file_done", cid).format(count=acc, payout=f"{tot:.2f}"), parse_mode="HTML")
        sd = user_states.get(cid, {}); sd["state"] = "AWAITING_UID"; user_states[cid] = sd
    except Exception as e: print(e); bot.send_message(cid, "❌ File Error.")
    finally: gc.collect()

def process_buyer_report(message):
    cid = message.chat.id
    if cid != ADMIN_ID: return
    sd = user_states.get(cid, {}); sd["state"] = "AWAITING_UID"; user_states[cid] = sd
    bot.send_message(cid, "⏳ <b>Matching...</b>", parse_mode="HTML")
    try:
        dw = bot.download_file(bot.get_file(message.document.file_id).file_path)
        ex_uids = set()
        if message.document.file_name.lower().endswith('.csv'):
            for row in csv.reader(dw.decode('utf-8', errors='ignore').splitlines()):
                for v in row:
                    v = str(v).strip().replace('.0', '')
                    if v.isdigit() and 8 <= len(v) <= 20: ex_uids.add(v)
        else:
            wb = openpyxl.load_workbook(io.BytesIO(dw), read_only=True, data_only=True)
            for row in wb.active.iter_rows(values_only=True):
                for v in row:
                    if v is None: continue
                    v = str(v).strip().replace('.0', '')
                    if v.isdigit() and 8 <= len(v) <= 20: ex_uids.add(v)
            wb.close()
        
        subs = list(submissions_col.find({"status": "Hold"}))
        appr, rej, pay = 0, 0, 0.0
        for s in subs:
            uid, amt, wid, tid = str(s.get("uid")), float(s.get("rate", 0)), s.get("user_id"), s.get("track_id")
            if not wid: continue
            if uid in ex_uids:
                submissions_col.update_one({"_id": tid}, {"$set": {"status": "Approved"}})
                role = get_user_data(wid).get("role", "member")
                wkey = "virtual_wallet" if role == "sub_admin" else "balance"
                users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {wkey: amt, "hold_balance": -amt}})
                appr += 1; pay += amt
            else:
                submissions_col.update_one({"_id": tid}, {"$set": {"status": "Rejected"}})
                users_col.update_one({"_id": wid, "hold_balance": {"$gte": amt}}, {"$inc": {"hold_balance": -amt}})
                rej += 1
        bot.send_message(ADMIN_ID, f"✅ <b>Matcher Done!</b>\n\n━━━━━━━━━━━━━━━━━━\n📊 <b>Approved:</b> {appr}\n💰 <b>Payout:</b> {pay:.2f}\n❌ <b>Rejected:</b> {rej}", parse_mode="HTML")
    except Exception as e: print(e)
    finally: gc.collect()

# ==========================================
# 8. UI & KEYBOARDS (MULTI-LANG)
# ==========================================
def main_bottom_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_submit", cid), get_text("btn_tools", cid), get_text("btn_wallet", cid), get_text("btn_reward", cid))
    if cid == ADMIN_ID or get_user_data(cid).get("role") in ["admin", "sub_admin"]: kb.add(get_text("btn_admin", cid))
    return kb

def cancel_keyboard(): return types.ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Cancel")

def submit_tasks_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_single", cid), get_text("btn_bulk", cid), get_text("btn_excel", cid), get_text("btn_back", cid))
    return kb

def helper_tools_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_temp_email", cid), get_text("btn_2fa", cid), get_text("btn_leaderboard", cid), get_text("btn_back", cid))
    return kb

def account_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_balance", cid), get_text("btn_withdraw", cid), get_text("btn_tx_history", cid), get_text("btn_back", cid))
    return kb

def bonus_support_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_bonus", cid), get_text("btn_support", cid), get_text("btn_back", cid))
    return kb

def category_bottom_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rates = get_setting("rates", {"fb_cookie": 5.0, "fb_2fa": 6.0, "ig_cookie": 8.0, "ig_2fa": 10.0})
    surge = get_active_surge_bonus()
    for c, b in rates.items(): kb.add(f"{c} ({b+surge} BDT)")
    kb.add(get_text("btn_back", cid)); return kb

def admin_bottom_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_task_mgmt", cid), get_text("btn_finance", cid), get_text("btn_settings", cid), get_text("btn_system", cid), get_text("btn_back", cid))
    return kb

def admin_sub_task_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(get_text("btn_buyer_report", cid), get_text("btn_force_close", cid), get_text("btn_export", cid), get_text("btn_back", cid))
    return kb

def admin_sub_finance_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("Pending Withdrawals", "Adjust Balance", get_text("btn_back", cid))
    return kb

def admin_sub_settings_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("Password Rule", "Base Rates", "Surge Pricing", get_text("btn_back", cid))
    return kb

def admin_sub_system_keyboard(cid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("Broadcast Message", "Maintenance Mode", get_text("btn_back", cid))
    return kb

# ==========================================
# 9. ROUTERS (START, TEXT, DOC, CALLBACK)
# ==========================================
@bot.message_handler(commands=['start', 'menu'])
def cmd_start(m):
    user_states.pop(m.chat.id, None)
    if not check_force_join(m.chat.id):
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Verify Join", callback_data="verify_join"))
        msg = "⚠️ <b>Force Join Required!</b>\n\n━━━━━━━━━━━━━━━━━━\n" + "\n".join([f"➡️ {c['name']}: {c['url']}" for c in REQUIRED_CHANNELS])
        bot.send_message(m.chat.id, msg, parse_mode="HTML", reply_markup=kb); return
    bot.send_message(m.chat.id, get_text("welcome", m.chat.id), parse_mode="HTML", reply_markup=main_bottom_keyboard(m.chat.id))

@bot.message_handler(commands=['lang'])
def cmd_lang(m):
    u = get_user_data(m.chat.id)
    nl = "en" if u.get("lang", "bn") == "bn" else "bn"
    update_user_field(m.chat.id, "lang", nl)
    bot.send_message(m.chat.id, get_text("lang_changed", m.chat.id), reply_markup=main_bottom_keyboard(m.chat.id))

@bot.message_handler(content_types=['document'])
def handle_document(m):
    cid = m.chat.id
    sd = user_states.get(cid, {})
    state = sd.get("state")
    
    # CRITICAL FIX: Route Admin Buyer Report correctly
    if state == "AWAITING_BUYER_REPORT" and cid == ADMIN_ID:
        heavy_task_executor.submit(process_buyer_report, m)
    elif state == "AWAITING_EXCEL_FILE":
        heavy_task_executor.submit(_process_document, m)
    else:
        bot.send_message(cid, get_text("invalid_doc", cid))

@bot.message_handler(content_types=['text'])
def handle_text(m):
    background_executor.submit(route_text, m)

def route_text(m):
    cid, txt = m.chat.id, m.text.strip()
    if get_setting("maintenance_mode") and cid != ADMIN_ID: bot.send_message(cid, "🛠 Maintenance."); return
    if is_user_banned(cid): bot.send_message(cid, "🚫 Banned."); return
    
    # State Reset
    if txt in [get_text("btn_main", cid), get_text("btn_back", cid), get_text("btn_cancel", cid), "❌ Cancel"]:
        user_states.pop(cid, None)
        bot.send_message(cid, get_text("welcome", cid), parse_mode="HTML", reply_markup=main_bottom_keyboard(cid)); return

    # State Handling
    sd = user_states.get(cid)
    if sd:
        st = sd.get("state")
        if st == "AWAITING_UID": bot.send_message(cid, handle_single_uid(cid, txt), parse_mode="HTML", reply_markup=cancel_keyboard()); return
        elif st == "AWAITING_SINGLE_DATA": bot.send_message(cid, handle_single_data(cid, txt), parse_mode="HTML", reply_markup=cancel_keyboard()); return
        elif st == "AWAITING_MANUAL_PASSWORD": bot.send_message(cid, handle_manual_password(cid, txt), parse_mode="HTML", reply_markup=cancel_keyboard()); return
        elif st == "AWAITING_BULK_TEXT": 
            r = handle_bulk_text(cid, txt)
            if r: bot.send_message(cid, r, parse_mode="HTML"); return
        elif st == "AWAITING_2FA_GEN":
            try: bot.send_message(cid, f"🔐 <b>Code:</b> <code>{pyotp.TOTP(txt.replace(' ','').upper()).now()}</code>", parse_mode="HTML", reply_markup=helper_tools_keyboard(cid))
            except: bot.send_message(cid, "❌ Invalid Key.", reply_markup=helper_tools_keyboard(cid))
            user_states.pop(cid, None); return
        elif st == "AWAITING_ADMIN_PASS_RULE" and cid == ADMIN_ID:
            update_setting("pass_rule", txt)
            bot.send_message(cid, f"✅ Rule updated: <code>{txt}</code>", parse_mode="HTML", reply_markup=admin_sub_settings_keyboard(cid))
            user_states.pop(cid, None); return
        elif st == "AWAITING_BROADCAST_MSG" and cid == ADMIN_ID:
            bot.send_message(cid, "🔄 Broadcasting...")
            users = list(users_col.find({"banned": False}))
            count = 0
            for u in users:
                try: bot.send_message(u["_id"], txt, parse_mode="HTML"); count += 1; time.sleep(0.04)
                except: pass
            bot.send_message(cid, f"✅ Broadcasted to {count} users.", reply_markup=admin_sub_system_keyboard(cid))
            user_states.pop(cid, None); return

    # CRITICAL FIX: Category Selection Logic
    for cat in ["fb_cookie", "fb_2fa", "ig_cookie", "ig_2fa"]:
        if txt.startswith(cat):
            sd = user_states.get(cid, {}); sd["state"], sd["category"] = "AWAITING_UID", cat; user_states[cid] = sd
            bot.send_message(cid, get_text("send_uid", cid), parse_mode="HTML", reply_markup=cancel_keyboard()); return

    # Menu Routing (Translated)
    if txt == get_text("btn_submit", cid): bot.send_message(cid, get_text("select_sub_type", cid), parse_mode="HTML", reply_markup=submit_tasks_keyboard(cid))
    elif txt == get_text("btn_tools", cid): bot.send_message(cid, get_text("select_tool", cid), parse_mode="HTML", reply_markup=helper_tools_keyboard(cid))
    elif txt == get_text("btn_wallet", cid): bot.send_message(cid, get_text("select_wallet", cid), parse_mode="HTML", reply_markup=account_keyboard(cid))
    elif txt == get_text("btn_reward", cid): bot.send_message(cid, get_text("select_reward", cid), parse_mode="HTML", reply_markup=bonus_support_keyboard(cid))
    elif txt == get_text("btn_admin", cid) and (cid == ADMIN_ID or get_user_data(cid).get("role") in ["admin", "sub_admin"]):
        bot.send_message(cid, get_text("admin_welcome", cid), parse_mode="HTML", reply_markup=admin_bottom_keyboard(cid))
        
    # Sub-menus
    elif txt == get_text("btn_single", cid): bot.send_message(cid, get_text("select_cat", cid), parse_mode="HTML", reply_markup=category_bottom_keyboard(cid))
    elif txt == get_text("btn_bulk", cid): sd = user_states.get(cid, {}); sd["state"] = "AWAITING_BULK_TEXT"; user_states[cid] = sd; bot.send_message(cid, "📝 Send bulk text:", reply_markup=cancel_keyboard())
    elif txt == get_text("btn_excel", cid): sd = user_states.get(cid, {}); sd["state"] = "AWAITING_EXCEL_FILE"; user_states[cid] = sd; bot.send_message(cid, "📂 Send file:", reply_markup=cancel_keyboard())
    
    # Wallet & Tools Actions (CRITICAL FIX: Added missing handlers)
    elif txt == get_text("btn_balance", cid):
        u = get_user_data(cid)
        msg = get_text("balance_msg", cid).format(balance=f"{u['balance']:.2f}", hold=f"{u['hold_balance']:.2f}", virtual=f"{u['virtual_wallet']:.2f}")
        bot.send_message(cid, msg, parse_mode="HTML", reply_markup=account_keyboard(cid))
    elif txt == get_text("btn_withdraw", cid):
        bot.send_message(cid, get_text("withdraw_msg", cid), parse_mode="HTML", reply_markup=account_keyboard(cid))
    elif txt == get_text("btn_tx_history", cid):
        subs = list(submissions_col.find({"user_id": cid}).sort("submitted_at", -1).limit(5))
        if not subs: bot.send_message(cid, get_text("no_tx", cid), reply_markup=account_keyboard(cid))
        else:
            msg = get_text("tx_msg", cid) + "\n"
            for s in subs: msg += f"🎫 <code>{s['track_id']}</code> | 💰 {s['rate']} | {s['status']}\n"
            bot.send_message(cid, msg, parse_mode="HTML", reply_markup=account_keyboard(cid))
    elif txt == get_text("btn_bonus", cid):
        u = get_user_data(cid); today = get_bd_time().strftime("%Y-%m-%d")
        if u.get("last_bonus_date") == today: bot.send_message(cid, get_text("bonus_already", cid), reply_markup=bonus_support_keyboard(cid))
        else: update_user_field(cid, "last_bonus_date", today); users_col.update_one({"_id": cid}, {"$inc": {"balance": 1.0}}); bot.send_message(cid, get_text("bonus_claimed", cid), parse_mode="HTML", reply_markup=bonus_support_keyboard(cid))
    elif txt == get_text("btn_support", cid): bot.send_message(cid, get_text("support_msg", cid), parse_mode="HTML", reply_markup=bonus_support_keyboard(cid))
    elif txt == get_text("btn_temp_email", cid):
        em = f"{''.join(random.choices(string.ascii_lowercase, k=8))}@1secmail.com"
        kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📥 Check Inbox", callback_data=f"chk_otp_{em}"))
        bot.send_message(cid, f"📧 <b>Temp Email:</b>\n<code>{em}</code>", parse_mode="HTML", reply_markup=kb)
    elif txt == get_text("btn_2fa", cid): sd = user_states.get(cid, {}); sd["state"] = "AWAITING_2FA_GEN"; user_states[cid] = sd; bot.send_message(cid, "🔐 Send Secret:", reply_markup=cancel_keyboard())
    elif txt == get_text("btn_leaderboard", cid):
        res = list(submissions_col.aggregate([{"$group": {"_id": "$user_id", "tot": {"$sum": "$rate"}}}, {"$sort": {"tot": -1}}, {"$limit": 5}]))
        msg = "🏆 <b>Top 5 Workers</b>\n\n━━━━━━━━━━━━━━━━━━\n" + "\n".join([f"{i+1}. <code>{r['_id']}</code> - 💰 {r['tot']:.1f} BDT" for i, r in enumerate(res)])
        bot.send_message(cid, msg, parse_mode="HTML", reply_markup=helper_tools_keyboard(cid))
        
    # Admin Actions
    elif txt == get_text("btn_task_mgmt", cid): bot.send_message(cid, "📋 <b>Task Management:</b>", parse_mode="HTML", reply_markup=admin_sub_task_keyboard(cid))
    elif txt == get_text("btn_finance", cid): bot.send_message(cid, "💰 <b>Finance:</b>", parse_mode="HTML", reply_markup=admin_sub_finance_keyboard(cid))
    elif txt == get_text("btn_settings", cid): bot.send_message(cid, "⚙️ <b>Settings:</b>", parse_mode="HTML", reply_markup=admin_sub_settings_keyboard(cid))
    elif txt == get_text("btn_system", cid): bot.send_message(cid, "🖥 <b>System:</b>", parse_mode="HTML", reply_markup=admin_sub_system_keyboard(cid))
    elif txt == get_text("btn_buyer_report", cid) and cid == ADMIN_ID:
        sd = user_states.get(cid, {}); sd["state"] = "AWAITING_BUYER_REPORT"; user_states[cid] = sd; bot.send_message(cid, "📊 Send Report (.csv/.xlsx):", reply_markup=cancel_keyboard())
    elif txt == get_text("btn_force_close", cid) and cid == ADMIN_ID:
        cnt = 0
        for s in submissions_col.find({"date_key": get_bd_time().strftime("%Y-%m-%d"), "status": "Hold"}):
            submissions_col.update_one({"_id": s["_id"]}, {"$set": {"status": "Rejected"}})
            users_col.update_one({"_id": s["user_id"], "hold_balance": {"$gte": s["rate"]}}, {"$inc": {"hold_balance": -s["rate"]}})
            cnt += 1
        bot.send_message(cid, f"✅ Closed {cnt} tasks.", reply_markup=admin_sub_task_keyboard(cid))
    elif txt == "Password Rule" and cid == ADMIN_ID:
        sd = user_states.get(cid, {}); sd["state"] = "AWAITING_ADMIN_PASS_RULE"; user_states[cid] = sd; bot.send_message(cid, "🔑 Send rule:", reply_markup=cancel_keyboard())
    elif txt == "Broadcast Message" and cid == ADMIN_ID:
        sd = user_states.get(cid, {}); sd["state"] = "AWAITING_BROADCAST_MSG"; user_states[cid] = sd; bot.send_message(cid, "📢 Send msg:", reply_markup=cancel_keyboard())

@bot.callback_query_handler(func=lambda c: True)
def handle_cb(c):
    background_executor.submit(process_cb, c)

def process_cb(c):
    cid, data = c.message.chat.id, c.data
    try:
        if data == "verify_join":
            if check_force_join(cid): 
                bot.answer_callback_query(c.id, "✅ Verified!")
                bot.send_message(cid, get_text("welcome", cid), parse_mode="HTML", reply_markup=main_bottom_keyboard(cid))
            else: bot.answer_callback_query(c.id, "❌ Not joined!", show_alert=True)
        elif data.startswith("chk_otp_"):
            em = data.replace("chk_otp_", ""); bot.answer_callback_query(c.id, "🔄 Fetching...")
            u, d = em.split('@')
            res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={u}&domain={d}", timeout=5.0).json()
            if not res: bot.send_message(cid, "📭 Empty.", reply_markup=helper_tools_keyboard(cid)); return
            msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={u}&domain={d}&id={res[-1]['id']}", timeout=5.0).json()
            bot.send_message(cid, f"📩 <b>Email Body:</b>\n\n<pre>{sanitize_html(msg.get('textBody', ''))}</pre>", parse_mode="HTML", reply_markup=helper_tools_keyboard(cid))
    except Exception as e: print(e); bot.answer_callback_query(c.id, "❌ Error", show_alert=True)

# ==========================================
# 10. DAEMON & EXECUTION
# ==========================================
def daemon():
    while True:
        time.sleep(60)
        now = get_bd_time()
        if now.hour == 0 and now.minute == 0:
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            submissions_col.delete_many({"date_key": yesterday, "status": {"$in": ["Approved", "Rejected"]}})

threading.Thread(target=daemon, daemon=True).start()

app = Flask(__name__)
@app.route('/')
def home(): return "OEB NEXUS Active"

if __name__ == "__main__":
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=10000), daemon=True).start()
    print("🚀 OEB NEXUS STARTED...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
