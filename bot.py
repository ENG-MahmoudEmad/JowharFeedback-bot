import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

# البيانات
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = "bot_database.db"

# أنواع الشكاوى
COMPLAINT_TYPES = {
    "bug": "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request": "💡 طلب جديد"
}

# ================== قاعدة البيانات (SQLite) ==================

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # جدول الأدمنز
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        role TEXT DEFAULT 'admin',
        added_date TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # جدول الشكاوى
    cur.execute("""
    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        complaint_type TEXT,
        message TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT
    )
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    print("✅ قاعدة البيانات جاهزة")

# ================== دوال مساعدة ==================

def is_admin(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except:
        return False

def add_admin(user_id, username):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)",
                   (user_id, username))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except:
        return False

def remove_admin(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except:
        return False

def save_complaint(user_id, username, complaint_type, message):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO complaints (user_id, username, complaint_type, message)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, complaint_type, message))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except:
        return False

def get_pending_complaints():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE status = 'pending' ORDER BY created_at DESC")
        result = cur.fetchall()
        cur.close()
        conn.close()
        return result
    except:
        return []

def update_complaint_status(complaint_id, status):
    try:
        conn = get_db()
        cur = conn.cursor()
        resolved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'resolved' else None
        cur.execute("""
            UPDATE complaints 
            SET status = ?, resolved_at = ? 
            WHERE id = ?
        """, (status, resolved_at, complaint_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except:
        return False

def get_stats():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM complaints")
        total = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'pending'")
        pending = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'resolved'")
        resolved = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return {"total": total, "pending": pending, "resolved": resolved}
    except:
        return {"total": 0, "pending": 0, "resolved": 0}

def get_all_admins():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins")
        result = cur.fetchall()
        cur.close()
        conn.close()
        return result
    except:
        return []

# ================== أوامر البوت ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 تقديم شكوى", callback_data="report")],
    ]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 مرحباً بك في بوت الشكاوى والملاحظات!\n\nاختر ما تريد:",
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "report":
        await report_start(query, context)
    elif query.data == "admin_panel":
        await admin_panel(query, context)
    elif query.data.startswith("type_"):
        complaint_type = query.data.split("_")[1]
        context.user_data['complaint_type'] = complaint_type
        await query.edit_message_text("📬 الآن اكتب شكايتك أو ملاحظتك:")
    elif query.data.startswith("resolve_"):
        complaint_id = int(query.data.split("_")[1])
        await update_complaint_status(complaint_id, "resolved")
        await query.edit_message_text(f"✅ تم تحديث الشكوى #{complaint_id} كـ مُحلة")
    elif query.data.startswith("inprogress_"):
        complaint_id = int(query.data.split("_")[1])
        await update_complaint_status(complaint_id, "in_progress")
        await query.edit_message_text(f"⏳ تم تحديث الشكوى #{complaint_id} قيد المراجعة")
    elif query.data == "show_pending":
        await show_pending(query, context)
    elif query.data == "show_stats":
        await show_stats(query, context)

async def report_start(query, context):
    keyboard = [[InlineKeyboardButton(v, callback_data=f"type_{k}")] for k, v in COMPLAINT_TYPES.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر نوع الشكوى:", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'complaint_type' not in context.user_data:
        return
    
    complaint_type = context.user_data.pop('complaint_type')
    message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "بدون اسم مستخدم"
    
    save_complaint(user_id, username, complaint_type, message)
    
    await update.message.reply_text("✅ تم استقبال شكايتك! شكراً لك")
    
    # إرسال للأدمن
    admins = get_all_admins()
    msg = f"""
📩 شكوى جديدة!

👤 من: @{username}
📌 النوع: {COMPLAINT_TYPES.get(complaint_type, complaint_type)}
💬 الرسالة: {message}
⏰ الوقت: {datetime.now().strftime('%H:%M - %d/%m/%Y')}
    """
    
    for admin in admins:
        try:
            await context.bot.send_message(chat_id=admin[0], text=msg)
        except:
            pass
    
    context.user_data.clear()

async def admin_panel(query, context):
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ ليس لديك صلاحية الوصول")
        return
    
    stats = get_stats()
    keyboard = [
        [InlineKeyboardButton("📋 الشكاوى المعلقة", callback_data="show_pending")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""⚙️ لوحة التحكم

📊 الإحصائيات السريعة:
• إجمالي الشكاوى: {stats['total']}
• معلقة: {stats['pending']}
• محلولة: {stats['resolved']}
    """
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_pending(query, context):
    complaints = get_pending_complaints()
    
    if not complaints:
        await query.edit_message_text("✅ لا توجد شكاوى معلقة!")
        return
    
    complaint = complaints[0]
    keyboard = [
        [InlineKeyboardButton("⏳ قيد المراجعة", callback_data=f"inprogress_{complaint[0]}")],
        [InlineKeyboardButton("✅ محلولة", callback_data=f"resolve_{complaint[0]}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
📋 شكوى #{complaint[0]}

👤 من: @{complaint[2]}
📌 النوع: {COMPLAINT_TYPES.get(complaint[3], complaint[3])}
💬 الرسالة: {complaint[4]}
⏰ الوقت: {complaint[6]}
🔴 الحالة: معلقة
    """
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_stats(query, context):
    stats = get_stats()
    text = f"""
📊 الإحصائيات الكاملة

📈 إجمالي الشكاوى: {stats['total']}
⏳ المعلقة: {stats['pending']}
✅ المحلولة: {stats['resolved']}
🔄 قيد المراجعة: {stats['total'] - stats['pending'] - stats['resolved']}
    """
    await query.edit_message_text(text)

# ================== التشغيل ==================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # تهيئة قاعدة البيانات
    init_db()
    
    # إضافة الأدمن
    add_admin(704301146, "MODYER555")
    
    # الأوامر
    app.add_handler(CommandHandler("start", start))
    
    # الرسائل والأزرار
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # التشغيل
    print("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()