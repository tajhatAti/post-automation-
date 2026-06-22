"""
╔══════════════════════════════════════════════════╗
║     POST AUTOMATION BOT — Render.com Edition     ║
║     Single Admin | Schedule | Multi-Channel      ║
╚══════════════════════════════════════════════════╝
"""

import os
import json
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "8768764605"))
DB_FILE   = "data.json"
BDT       = timezone(timedelta(hours=6))

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

db_lock = threading.Lock()

DEFAULT_DB = {
    "queue": [], "schedules": [], "dest_channels": [],
    "caption": "", "buttons": [], "total_posted": 0,
    "last_check_min": -1, "state": {}
}

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_DB.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception as e:
            log.error(f"DB load error: {e}")
    return dict(DEFAULT_DB)

def save_db(data):
    with db_lock:
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"DB save error: {e}")

def get_db():
    return load_db()

def update_db(key, value):
    data = load_db()
    data[key] = value
    save_db(data)

def bdt_now():
    return datetime.now(BDT)

def bdt_time_str():
    n = bdt_now()
    return f"{n.hour:02d}:{n.minute:02d}"

def bdt_minutes():
    n = bdt_now()
    return n.hour * 60 + n.minute

def build_keyboard(buttons):
    if not buttons:
        return None
    kb = types.InlineKeyboardMarkup()
    for b in buttons:
        kb.add(types.InlineKeyboardButton(b["text"], url=b["url"]))
    return kb

def admin_only(fn):
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "⛔ Admin only.")
            return
        return fn(message, *args, **kwargs)
    return wrapper

def set_state(key, val):
    data = get_db()
    data["state"][key] = val
    save_db(data)

def get_state(key):
    return get_db()["state"].get(key)

def clear_state(key):
    data = get_db()
    data["state"].pop(key, None)
    save_db(data)

def send_media(chat_id, item, caption, keyboard):
    fid   = item["file_id"]
    ftype = item.get("type", "video")
    if ftype == "photo":
        return bot.send_photo(chat_id, fid, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    elif ftype == "document":
        return bot.send_document(chat_id, fid, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    elif ftype == "audio":
        return bot.send_audio(chat_id, fid, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    elif ftype == "animation":
        return bot.send_animation(chat_id, fid, caption=caption, parse_mode="HTML", reply_markup=keyboard)
    else:
        return bot.send_video(chat_id, fid, caption=caption, parse_mode="HTML", reply_markup=keyboard)

def send_dashboard(chat_id):
    db = get_db()
    q  = len(db["queue"])
    per = sum(s["count"] for s in db["schedules"])
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📢 চ্যানেল",      callback_data="menu_channels"),
        types.InlineKeyboardButton("🕒 শিডিউল",       callback_data="menu_schedule"),
        types.InlineKeyboardButton("🔘 বাটন",         callback_data="menu_buttons"),
        types.InlineKeyboardButton("✍️ ক্যাপশন",      callback_data="menu_caption"),
        types.InlineKeyboardButton("📦 কিউ",           callback_data="menu_queue"),
        types.InlineKeyboardButton("📊 স্ট্যাটাস",    callback_data="menu_status"),
        types.InlineKeyboardButton("🔄 ফোর্স পোস্ট", callback_data="force_post"),
    )
    bot.send_message(
        chat_id,
        f"🤖 <b>Post Automation Bot</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 কিউ: <b>{q}</b> টি\n"
        f"📅 শিডিউল: <b>{len(db['schedules'])}</b> টি স্লট\n"
        f"📢 চ্যানেল: <b>{len(db['dest_channels'])}</b> টি\n"
        f"📬 মোট পোস্ট: <b>{db['total_posted']}</b> টি\n"
        f"⏳ আনুমানিক: <b>{q // per if per else '∞'}</b> দিন\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=kb
    )

def do_post(count=1, notify=True):
    db  = get_db()
    chs = db["dest_channels"]
    cap = db["caption"] or ""
    kb  = build_keyboard(db["buttons"])

    if not chs:
        if notify:
            bot.send_message(ADMIN_ID, "❌ কোনো চ্যানেল সেট নেই। /add_channel দিয়ে যোগ করো।")
        return 0
    if not db["queue"]:
        if notify:
            bot.send_message(ADMIN_ID, "📭 কিউ খালি! মিডিয়া পাঠাও।")
        return 0

    to_send = min(count, len(db["queue"]))
    sent = 0

    for _ in range(to_send):
        if not db["queue"]:
            break
        item = db["queue"].pop(0)
        ok = True
        for ch in chs:
            try:
                send_media(ch, item, cap, kb)
                time.sleep(0.5)
            except Exception as e:
                log.error(f"Post error {ch}: {e}")
                ok = False
        if ok:
            sent += 1

    db["total_posted"] += sent
    save_db(db)

    if notify and sent > 0:
        bot.send_message(ADMIN_ID, f"✅ <b>{sent}</b> টি পোস্ট হয়েছে!\n📦 কিউতে বাকি: <b>{len(db['queue'])}</b> টি")
        if len(db["queue"]) < 5:
            bot.send_message(ADMIN_ID, f"⚠️ <b>কিউ প্রায় খালি!</b> মাত্র <b>{len(db['queue'])}</b> টি বাকি।")
    return sent

@bot.message_handler(commands=["start"])
@admin_only
def cmd_start(message):
    send_dashboard(message.chat.id)

@bot.message_handler(commands=["help"])
@admin_only
def cmd_help(message):
    bot.send_message(message.chat.id,
        "📖 <b>Command গাইড</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        "/start — ড্যাশবোর্ড\n/status — লাইভ স্ট্যাটাস\n"
        "/force [N] — এখনই N টা পোস্ট\n/queue — কিউ দেখো\n"
        "/clear_queue — কিউ খালি করো\n"
        "/add_channel @ch — চ্যানেল যোগ\n/del_channel @ch — চ্যানেল মুছো\n/channels — লিস্ট\n"
        "/add_slot 07:30 4 — শিডিউল যোগ\n/del_slot 1 — মুছো\n/schedules — লিস্ট\n"
        "/set_caption — ক্যাপশন সেট\n"
        "/add_button — বাটন যোগ\n/del_button 1 — মুছো\n/buttons — লিস্ট\n"
        "/cancel — state বাতিল\n\n"
        "📎 <b>মিডিয়া যোগ:</b> video/photo/doc সরাসরি পাঠাও"
    )

@bot.message_handler(commands=["status"])
@admin_only
def cmd_status(message):
    db  = get_db()
    per = sum(s["count"] for s in db["schedules"])
    sch_lines = "\n".join([f"  • <code>{s['time']}</code> → {s['count']} টি" for s in db["schedules"]]) or "  <i>(নেই)</i>"
    ch_lines  = "\n".join([f"  • <code>{c}</code>" for c in db["dest_channels"]]) or "  <i>(নেই)</i>"
    bot.send_message(message.chat.id,
        f"📊 <b>লাইভ স্ট্যাটাস</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 BDT: <b>{bdt_time_str()}</b>\n"
        f"📦 কিউ: <b>{len(db['queue'])}</b> টি\n"
        f"📅 প্রতিদিন: <b>{per}</b> টি\n"
        f"📬 মোট: <b>{db['total_posted']}</b> টি\n\n"
        f"📢 <b>চ্যানেল:</b>\n{ch_lines}\n\n"
        f"🕒 <b>শিডিউল:</b>\n{sch_lines}\n"
        f"🔘 বাটন: {len(db['buttons'])} টি\n━━━━━━━━━━━━━━━━━━━━━"
    )

@bot.message_handler(commands=["add_channel"])
@admin_only
def cmd_add_channel(message):
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        bot.reply_to(message, "❌ ফরম্যাট: <code>/add_channel @mychannel</code>")
        return
    ch = parts[1].lower()
    db = get_db()
    if ch in db["dest_channels"]:
        bot.reply_to(message, "⚠️ এই চ্যানেল আগেই আছে।")
        return
    db["dest_channels"].append(ch)
    save_db(db)
    bot.reply_to(message, f"✅ <code>{ch}</code> যোগ হয়েছে!")

@bot.message_handler(commands=["del_channel"])
@admin_only
def cmd_del_channel(message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ ফরম্যাট: <code>/del_channel @mychannel</code>")
        return
    ch = parts[1].lower()
    db = get_db()
    if ch not in db["dest_channels"]:
        bot.reply_to(message, "❌ এই চ্যানেল নেই।")
        return
    db["dest_channels"].remove(ch)
    save_db(db)
    bot.reply_to(message, f"✅ <code>{ch}</code> মুছে ফেলা হয়েছে।")

@bot.message_handler(commands=["channels"])
@admin_only
def cmd_channels(message):
    db  = get_db()
    chs = db["dest_channels"]
    if not chs:
        bot.reply_to(message, "📭 কোনো চ্যানেল নেই। /add_channel @ch দিয়ে যোগ করো।")
        return
    lines = [f"{i+1}. <code>{c}</code>" for i, c in enumerate(chs)]
    bot.reply_to(message, "📢 <b>চ্যানেল লিস্ট:</b>\n\n" + "\n".join(lines))

@bot.message_handler(commands=["add_slot"])
@admin_only
def cmd_add_slot(message):
    parts = message.text.strip().split()
    if len(parts) < 3:
        bot.reply_to(message, "❌ ফরম্যাট: <code>/add_slot 07:30 4</code>")
        return
    try:
        hh, mm = map(int, parts[1].split(":"))
        count  = int(parts[2])
        assert 0 <= hh <= 23 and 0 <= mm <= 59 and 1 <= count <= 50
    except:
        bot.reply_to(message, "❌ ভুল। উদাহরণ: <code>/add_slot 07:30 4</code>")
        return
    ts = f"{hh:02d}:{mm:02d}"
    db = get_db()
    for s in db["schedules"]:
        if s["time"] == ts:
            bot.reply_to(message, f"⚠️ <code>{ts}</code> আগেই আছে।")
            return
    db["schedules"].append({"time": ts, "count": count})
    db["schedules"] = sorted(db["schedules"], key=lambda x: x["time"])
    save_db(db)
    bot.reply_to(message, f"✅ শিডিউল যোগ: <code>{ts}</code> BDT → <b>{count}</b> টি")

@bot.message_handler(commands=["del_slot"])
@admin_only
def cmd_del_slot(message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ ফরম্যাট: <code>/del_slot 1</code>")
        return
    try:
        idx = int(parts[1]) - 1
    except:
        bot.reply_to(message, "❌ নম্বর দাও।")
        return
    db = get_db()
    if idx < 0 or idx >= len(db["schedules"]):
        bot.reply_to(message, "❌ সঠিক নম্বর দাও।")
        return
    removed = db["schedules"].pop(idx)
    save_db(db)
    bot.reply_to(message, f"✅ <code>{removed['time']}</code> মুছে ফেলা হয়েছে।")

@bot.message_handler(commands=["schedules"])
@admin_only
def cmd_schedules(message):
    db  = get_db()
    sch = db["schedules"]
    if not sch:
        bot.reply_to(message, "📭 শিডিউল নেই। /add_slot 07:30 4 দিয়ে যোগ করো।")
        return
    lines = [f"{i+1}. <code>{s['time']}</code> BDT → <b>{s['count']}</b> টি" for i, s in enumerate(sch)]
    bot.reply_to(message, "🕒 <b>শিডিউল লিস্ট:</b>\n\n" + "\n".join(lines))

@bot.message_handler(commands=["set_caption"])
@admin_only
def cmd_set_caption(message):
    set_state("waiting", "caption")
    bot.reply_to(message,
        "✍️ <b>ক্যাপশন লিখো</b>\n\nHTML সাপোর্টেড:\n"
        "<code>&lt;b&gt;bold&lt;/b&gt;</code>\n"
        "<code>&lt;i&gt;italic&lt;/i&gt;</code>\n"
        "<code>&lt;a href='URL'&gt;text&lt;/a&gt;</code>\n\n"
        "ক্যাপশন না চাইলে <code>-</code> পাঠাও।"
    )

@bot.message_handler(commands=["add_button"])
@admin_only
def cmd_add_button(message):
    db = get_db()
    if len(db["buttons"]) >= 3:
        bot.reply_to(message, "❌ সর্বোচ্চ ৩টা বাটন।")
        return
    set_state("waiting", "button")
    bot.reply_to(message,
        "🔘 <b>বাটন যোগ</b>\n\nফরম্যাট:\n"
        "<code>বাটনের নাম | https://link.com</code>"
    )

@bot.message_handler(commands=["del_button"])
@admin_only
def cmd_del_button(message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ ফরম্যাট: <code>/del_button 1</code>")
        return
    try:
        idx = int(parts[1]) - 1
    except:
        bot.reply_to(message, "❌ নম্বর দাও।")
        return
    db = get_db()
    if idx < 0 or idx >= len(db["buttons"]):
        bot.reply_to(message, "❌ সঠিক নম্বর দাও।")
        return
    removed = db["buttons"].pop(idx)
    save_db(db)
    bot.reply_to(message, f"✅ <b>{removed['text']}</b> মুছে ফেলা হয়েছে।")

@bot.message_handler(commands=["buttons"])
@admin_only
def cmd_buttons(message):
    db   = get_db()
    btns = db["buttons"]
    if not btns:
        bot.reply_to(message, "📭 বাটন নেই। /add_button দিয়ে যোগ করো।")
        return
    lines = [f"{i+1}. <b>{b['text']}</b> → <code>{b['url']}</code>" for i, b in enumerate(btns)]
    bot.reply_to(message, "🔘 <b>বাটন লিস্ট:</b>\n\n" + "\n".join(lines))

@bot.message_handler(commands=["queue"])
@admin_only
def cmd_queue(message):
    db  = get_db()
    per = sum(s["count"] for s in db["schedules"])
    kb  = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🗑 কিউ খালি করো", callback_data="clear_queue"))
    bot.reply_to(message,
        f"📦 <b>কিউ স্ট্যাটাস</b>\n\n"
        f"মোট: <b>{len(db['queue'])}</b> টি\n"
        f"প্রতিদিন: <b>{per}</b> টি\n"
        f"আনুমানিক: <b>{len(db['queue']) // per if per else '∞'}</b> দিন",
        reply_markup=kb
    )

@bot.message_handler(commands=["clear_queue"])
@admin_only
def cmd_clear_queue(message):
    db    = get_db()
    count = len(db["queue"])
    db["queue"] = []
    save_db(db)
    bot.reply_to(message, f"🗑 কিউ খালি! ({count} টি মুছে ফেলা হয়েছে।)")

@bot.message_handler(commands=["force"])
@admin_only
def cmd_force(message):
    parts = message.text.strip().split()
    count = 1
    if len(parts) > 1:
        try:
            count = int(parts[1])
        except:
            pass
    sent = do_post(count=count, notify=False)
    db   = get_db()
    if sent > 0:
        bot.reply_to(message, f"✅ <b>{sent}</b> টি পোস্ট হয়েছে!\n📦 বাকি: <b>{len(db['queue'])}</b> টি")
    else:
        bot.reply_to(message, "❌ পোস্ট হয়নি। কিউ বা চ্যানেল চেক করো।")

@bot.message_handler(commands=["cancel"])
@admin_only
def cmd_cancel(message):
    clear_state("waiting")
    bot.reply_to(message, "✅ বাতিল করা হয়েছে।")

@bot.message_handler(content_types=["video", "photo", "document", "audio", "animation"])
def handle_media(message):
    if message.from_user.id != ADMIN_ID:
        return
    fid = ftype = None
    if message.video:
        fid, ftype = message.video.file_id, "video"
    elif message.photo:
        fid, ftype = message.photo[-1].file_id, "photo"
    elif message.document:
        fid, ftype = message.document.file_id, "document"
    elif message.audio:
        fid, ftype = message.audio.file_id, "audio"
    elif message.animation:
        fid, ftype = message.animation.file_id, "animation"
    if not fid:
        bot.reply_to(message, "❌ Media চেনা গেল না।")
        return
    db = get_db()
    db["queue"].append({"file_id": fid, "type": ftype, "ts": bdt_now().strftime("%Y-%m-%d %H:%M")})
    save_db(db)
    bot.reply_to(message, f"✅ <b>{ftype.capitalize()}</b> কিউতে যোগ হয়েছে!\n📦 মোট: <b>{len(db['queue'])}</b> টি")

@bot.message_handler(content_types=["text"])
def handle_text(message):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text.startswith("/"):
        return
    state = get_state("waiting")
    if state == "caption":
        clear_state("waiting")
        txt = message.text.strip()
        if txt == "-":
            update_db("caption", "")
            bot.reply_to(message, "✅ ক্যাপশন মুছে ফেলা হয়েছে।")
        else:
            update_db("caption", txt)
            bot.reply_to(message, "✅ <b>ক্যাপশন সেভ!</b>\n\n🔍 <b>প্রিভিউ:</b>\n━━━━━━━━━━━━━━━━━━━━━\n" + txt + "\n━━━━━━━━━━━━━━━━━━━━━")
    elif state == "button":
        clear_state("waiting")
        txt = message.text.strip()
        if "|" not in txt:
            bot.reply_to(message, "❌ ফরম্যাট: <code>নাম | URL</code>")
            return
        parts    = txt.split("|", 1)
        btn_text = parts[0].strip()
        btn_url  = parts[1].strip()
        if not (btn_url.startswith("https://") or btn_url.startswith("http://") or btn_url.startswith("t.me/")):
            bot.reply_to(message, "❌ URL ভুল।")
            return
        if not btn_text:
            bot.reply_to(message, "❌ বাটনের নাম দাও।")
            return
        db = get_db()
        db["buttons"].append({"text": btn_text, "url": btn_url})
        save_db(db)
        bot.reply_to(message, f"✅ বাটন যোগ: <b>{btn_text}</b>")
    else:
        bot.reply_to(message, "❓ /start দিয়ে ড্যাশবোর্ডে যাও।")

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    uid = call.from_user.id
    if uid != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Admin only.")
        return
    bot.answer_callback_query(call.id)
    data = call.data
    db   = get_db()

    if data == "menu_channels":
        chs = db["dest_channels"]
        txt = "📢 <b>চ্যানেল লিস্ট</b>\n\n" + ("\n".join([f"{i+1}. <code>{c}</code>" for i, c in enumerate(chs)]) if chs else "<i>(নেই)</i>")
        txt += "\n\n<code>/add_channel @ch</code> — যোগ\n<code>/del_channel @ch</code> — মুছো"
        bot.send_message(uid, txt)
    elif data == "menu_schedule":
        sch = db["schedules"]
        txt = "🕒 <b>শিডিউল লিস্ট</b>\n\n" + ("\n".join([f"{i+1}. <code>{s['time']}</code> → {s['count']} টি" for i, s in enumerate(sch)]) if sch else "<i>(নেই)</i>")
        txt += "\n\n<code>/add_slot 07:30 4</code> — যোগ\n<code>/del_slot 1</code> — মুছো"
        bot.send_message(uid, txt)
    elif data == "menu_buttons":
        btns = db["buttons"]
        txt  = "🔘 <b>বাটন লিস্ট</b>\n\n" + ("\n".join([f"{i+1}. <b>{b['text']}</b> → <code>{b['url']}</code>" for i, b in enumerate(btns)]) if btns else "<i>(নেই)</i>")
        txt += "\n\n<code>/add_button</code> — যোগ\n<code>/del_button 1</code> — মুছো"
        bot.send_message(uid, txt)
    elif data == "menu_caption":
        cap = db["caption"] or "<i>(সেট নেই)</i>"
        bot.send_message(uid, f"✍️ <b>বর্তমান ক্যাপশন:</b>\n\n{cap}\n\n<code>/set_caption</code> দিয়ে পরিবর্তন করো।")
    elif data == "menu_queue":
        per = sum(s["count"] for s in db["schedules"])
        kb  = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🗑 কিউ খালি করো", callback_data="clear_queue"))
        bot.send_message(uid,
            f"📦 <b>কিউ স্ট্যাটাস</b>\n\n"
            f"মোট: <b>{len(db['queue'])}</b> টি\n"
            f"প্রতিদিন: <b>{per}</b> টি\n"
            f"আনুমানিক: <b>{len(db['queue']) // per if per else '∞'}</b> দিন",
            reply_markup=kb
        )
    elif data == "menu_status":
        bot.send_message(uid,
            f"📊 <b>স্ট্যাটাস</b>\n\n"
            f"📦 কিউ: <b>{len(db['queue'])}</b> টি\n"
            f"📬 মোট পোস্ট: <b>{db['total_posted']}</b> টি\n"
            f"📢 চ্যানেল: <b>{len(db['dest_channels'])}</b> টি\n"
            f"🕒 শিডিউল: <b>{len(db['schedules'])}</b> টি\n"
            f"🔘 বাটন: <b>{len(db['buttons'])}</b> টি\n"
            f"🕒 BDT: <b>{bdt_time_str()}</b>"
        )
    elif data == "force_post":
        sent = do_post(count=1, notify=False)
        db2  = get_db()
        if sent:
            bot.send_message(uid, f"✅ ফোর্স পোস্ট সফল!\n📦 বাকি: <b>{len(db2['queue'])}</b> টি")
        else:
            bot.send_message(uid, "❌ কিউ খালি বা চ্যানেল নেই।")
    elif data == "clear_queue":
        count       = len(db["queue"])
        db["queue"] = []
        save_db(db)
        bot.send_message(uid, f"🗑 কিউ খালি! ({count} টি মুছে ফেলা হয়েছে।)")
def scheduler_engine():
    log.info("✅ Scheduler engine started (BDT UTC+6)")
    while True:
        try:
            db        = get_db()
            now_min   = bdt_minutes()
            last_min  = db.get("last_check_min", -1)
            schedules = db.get("schedules", [])
            missed    = []
            for slot in schedules:
                hh, mm   = map(int, slot["time"].split(":"))
                slot_min = hh * 60 + mm
                if last_min == -1:
                    if slot_min == now_min:
                        missed.append(slot)
                elif last_min <= now_min:
                    if last_min < slot_min <= now_min:
                        missed.append(slot)
                else:
                    if slot_min > last_min or slot_min <= now_min:
                        missed.append(slot)
            if missed:
                total_count = sum(s["count"] for s in missed)
                log.info(f"[Scheduler] {len(missed)} slot(s), posting {total_count}...")
                db["last_check_min"] = now_min
                save_db(db)
                do_post(count=total_count, notify=True)
                if len(missed) > 1:
                    bot.send_message(ADMIN_ID, f"⚠️ <b>Catch-up:</b> {len(missed)} টি missed slot একসাথে পোস্ট হয়েছে।")
            else:
                db["last_check_min"] = now_min
                save_db(db)
        except Exception as e:
            log.error(f"Scheduler error: {e}")
        time.sleep(60)

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        db  = get_db()
        msg = f"Post Automation Bot ALIVE | Queue: {len(db['queue'])} | Posted: {db['total_posted']} | BDT: {bdt_time_str()}"
        self.wfile.write(msg.encode())
    def log_message(self, *a):
        pass

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    log.info(f"✅ Keep-alive server on port {port}")
    HTTPServer(("0.0.0.0", port), PingHandler).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=keep_alive,       daemon=True).start()
    threading.Thread(target=scheduler_engine, daemon=True).start()
    log.info("🤖 Post Automation Bot polling...")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
