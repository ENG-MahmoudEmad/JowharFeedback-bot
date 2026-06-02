import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = "bot_database.db"

COMPLAINT_TYPES = {
    "bug": "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request": "💡 طلب جديد"
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        username TEXT
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        complaint_type TEXT,
        message TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)
    
    conn.commit()
    conn.close()

def is_admin(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return result is not None
    except:
        return False

def save_complaint(user_id, username, complaint_type, message):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute("""
            INSERT INTO complaints (user_id, username, complaint_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, complaint_type, message, created_at))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_pending_complaints():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE status = 'pending' ORDER BY id DESC")
        result = cur.fetchall()
        conn.close()
        return result
    except:
        return []

def update_complaint_status(complaint_id, status):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE complaints SET status = ? WHERE id = ?", (status, complaint_id))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM complaints")
        total = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'pending'")
        pending = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'resolved'")
        resolved = cur.fetchone()[0]
        
        conn.close()
        return {"total": total, "pending": pending, "resolved": resolved}
    except:
        return {"total": 0, "pending": 0, "resolved": 0}

def get_all_admins():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins")
        result = cur.fetchall()
        conn.close()
        return result
    except:
        return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 تقديم شكوى", callback_data="report")],
    ]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 مرحباً!\n\nاختر ما تريد:", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "report":
        keyboard = [[InlineKeyboardButton(v, callback_data=f"type_{k}")] for k, v in COMPLAINT_TYPES.items()]
        await query.edit_message_text("اختر نوع الشكوى:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data.startswith("type_"):
        complaint_type = query.data.split("_")[1]
        context.user_data['complaint_type'] = complaint_type
        await query.edit_message_text("📬 اكتب شكايتك الآن:")
    
    elif query.data == "admin_panel":
        if not is_admin(query.from_user.id):
            await query.edit_message_text("❌ لا توجد صلاحية")
            return
        stats = get_stats()
        keyboard = [
            [InlineKeyboardButton("📋 الشكاوى", callback_data="show_pending")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
        ]
        text = f"⚙️ لوحة التحكم\n\n• إجمالي: {stats['total']}\n• معلقة: {stats['pending']}\n• محلولة: {stats['resolved']}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "show_pending":
        complaints = get_pending_complaints()
        if not complaints:
            await query.edit_message_text("✅ لا توجد شكاوى معلقة!")
            return
        
        complaint = complaints[0]
        keyboard = [
            [InlineKeyboardButton("✅ محلولة", callback_data=f"resolve_{complaint[0]}")],
            [InlineKeyboardButton("⏳ قيد المراجعة", callback_data=f"inprogress_{complaint[0]}")]
        ]
        text = f"📋 شكوى #{complaint[0]}\n👤 من: @{complaint[2]}\n📌 نوع: {COMPLAINT_TYPES.get(complaint[3], complaint[3])}\n💬 الرسالة: {complaint[4]}\n⏰ الوقت: {complaint[6]}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data.startswith("resolve_"):
        complaint_id = int(query.data.split("_")[1])
        update_complaint_status(complaint_id, "resolved")
        await query.edit_message_text(f"✅ تم تحديث الشكوى #{complaint_id}")
    
    elif query.data.startswith("inprogress_"):
        complaint_id = int(query.data.split("_")[1])
        update_complaint_status(complaint_id, "in_progress")
        await query.edit_message_text(f"⏳ تم تحديث الشكوى #{complaint_id}")
    
    elif query.data == "show_stats":
        stats = get_stats()
        text = f"📊 الإحصائيات\n\n📈 الإجمالي: {stats['total']}\n⏳ المعلقة: {stats['pending']}\n✅ المحلولة: {stats['resolved']}"
        await query.edit_message_text(text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'complaint_type' not in context.user_data:
        return
    
    complaint_type = context.user_data.pop('complaint_type')
    message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    
    save_complaint(user_id, username, complaint_type, message)
    await update.message.reply_text("✅ تم استقبال شكايتك!")
    
    admins = get_all_admins()
    msg = f"📩 شكوى جديدة!\n👤 من: @{username}\n📌 النوع: {COMPLAINT_TYPES.get(complaint_type)}\n💬 الرسالة: {message}"
    for admin in admins:
        try:
            await context.bot.send_message(chat_id=admin[0], text=msg)
        except:
            pass

def main():

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", (704301146, "MODYER555"))
    conn.commit()
    conn.close()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()