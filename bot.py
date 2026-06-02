import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = "bot_database.db"
GROUP_ID = -1003731398016  # قسم الإنتاج
TOPIC_ID = 5488  # توبيك الشكاوى

COMPLAINT_TYPES = {
    "bug": "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request": "💡 طلب جديد"
}

# ================== قاعدة البيانات ==================

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
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
        admin_reply TEXT,
        created_at TEXT
    )
    """)
    
    conn.commit()
    conn.close()
    print("✅ قاعدة البيانات جاهزة")

# ================== دوال مساعدة ==================

def is_admin(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return result is not None
    except:
        return False

def add_admin(user_id, username):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def save_complaint(user_id, username, complaint_type, message):
    try:
        conn = get_db()
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
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE status = 'pending' ORDER BY id DESC")
        result = cur.fetchall()
        conn.close()
        return result
    except:
        return []

def get_complaint(complaint_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
        result = cur.fetchone()
        conn.close()
        return result
    except:
        return None

def update_complaint(complaint_id, status, admin_reply=None):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE complaints 
            SET status = ?, admin_reply = ? 
            WHERE id = ?
        """, (status, admin_reply, complaint_id))
        conn.commit()
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
        conn.close()
        return result
    except:
        return []

# ================== أوامر البوت ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📝 تقديم شكوى", callback_data="report")]]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    
    await update.message.reply_text("👋 مرحباً بك!\n\nاختر ما تريد:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "report":
        keyboard = [
            [InlineKeyboardButton("🐛 خلل تقني", callback_data="type_bug")],
            [InlineKeyboardButton("💬 ملاحظة", callback_data="type_feedback")],
            [InlineKeyboardButton("💡 طلب جديد", callback_data="type_request")]
        ]
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
        keyboard = [[InlineKeyboardButton("📋 الشكاوى المعلقة", callback_data="show_pending")]]
        text = f"⚙️ لوحة التحكم\n\n• إجمالي: {stats['total']}\n• معلقة: {stats['pending']}\n• محلولة: {stats['resolved']}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "show_pending":
        complaints = get_pending_complaints()
        if not complaints:
            await query.edit_message_text("✅ لا توجد شكاوى معلقة!")
            return
        
        complaint = complaints[0]
        context.user_data['current_complaint_id'] = complaint[0]
        keyboard = [[InlineKeyboardButton("💬 الرد", callback_data="reply_complaint")]]
        text = f"📋 شكوى #{complaint[0]}\n\n👤 من: @{complaint[2]}\n📌 النوع: {COMPLAINT_TYPES.get(complaint[3])}\n💬 الرسالة: {complaint[4]}\n⏰ الوقت: {complaint[8]}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "reply_complaint":
        context.user_data['mode'] = 'reply'
        await query.edit_message_text("📝 اكتب ردك على الشكوى:")
    
    elif query.data == "publish_complaint":
        complaint_id = context.user_data.get('current_complaint_id')
        complaint = get_complaint(complaint_id)
        admin_reply = context.user_data.get('admin_reply')
        
        if complaint and admin_reply:
            msg = f"""
📋 شكوى #{complaint[0]}

👤 من: @{complaint[2]}
📌 النوع: {COMPLAINT_TYPES.get(complaint[3])}
💬 الشكوى: {complaint[4]}

✅ الرد من الفريق:
{admin_reply}
"""
            try:
                await context.bot.send_message(chat_id=GROUP_ID, text=msg, message_thread_id=TOPIC_ID)
                await query.edit_message_text("✅ تم نشر الشكوى والرد في المجموعة!")
                update_complaint(complaint_id, 'resolved', admin_reply)
            except Exception as e:
                await query.edit_message_text(f"❌ خطأ في النشر: {str(e)}")
    
    elif query.data == "mark_resolved":
        complaint_id = context.user_data.get('current_complaint_id')
        admin_reply = context.user_data.get('admin_reply')
        update_complaint(complaint_id, 'resolved', admin_reply)
        await query.edit_message_text("✅ تم تحديث الشكوى كـ محلولة!")
    
    elif query.data == "mark_inprogress":
        complaint_id = context.user_data.get('current_complaint_id')
        update_complaint(complaint_id, 'in_progress')
        await query.edit_message_text("⏳ تم تحديث الشكوى كـ قيد المراجعة!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    
    if mode == 'reply':
        # الأدمن يرد على الشكوى
        admin_reply = update.message.text
        complaint_id = context.user_data.get('current_complaint_id')
        complaint = get_complaint(complaint_id)
        
        if complaint:
            context.user_data['admin_reply'] = admin_reply
            context.user_data['mode'] = None
            
            # إرسال الرد للعضو
            reply_msg = f"""
✅ تم الرد على شكايتك!

📋 شكويتك (#{complaint_id}): {complaint[4]}

📝 الرد: {admin_reply}
"""
            try:
                await context.bot.send_message(chat_id=complaint[1], text=reply_msg)
            except:
                pass
            
            # عرض أزرار النشر والحالة
            keyboard = [
                [InlineKeyboardButton("📤 نشر في المجموعة", callback_data="publish_complaint")],
                [InlineKeyboardButton("✅ محلولة", callback_data="mark_resolved")],
                [InlineKeyboardButton("⏳ قيد المراجعة", callback_data="mark_inprogress")]
            ]
            await update.message.reply_text("✅ تم حفظ الرد!\n\nاختر الإجراء:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif 'complaint_type' in context.user_data:
        # عضو عادي يرسل شكوى
        complaint_type = context.user_data.pop('complaint_type')
        message = update.message.text
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        
        save_complaint(user_id, username, complaint_type, message)
        await update.message.reply_text("✅ تم استقبال شكايتك!")
        
        # إشعار الأدمن
        admins = get_all_admins()
        for admin in admins:
            try:
                await context.bot.send_message(
                    chat_id=admin[0],
                    text=f"📩 شكوى جديدة!\n\n👤 من: @{username}\n📌 النوع: {COMPLAINT_TYPES.get(complaint_type)}\n💬 الرسالة: {message}"
                )
            except:
                pass

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    init_db()
    add_admin(7043011146, "MODYER555")
    add_admin(8496647096, "Medoma")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()