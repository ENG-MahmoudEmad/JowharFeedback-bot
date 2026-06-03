import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = "bot_database.db"
GROUP_ID = -1003731398016
TOPIC_ID = 5488

COMPLAINT_TYPES = {
    "bug": "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request": "💡 طلب جديد"
}

# ================== قاعدة البيانات ==================

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    try:
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
        logger.info("✅ قاعدة البيانات جاهزة")
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")

def is_admin(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من الأدمن: {e}")
        return False

def add_admin(user_id, username):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()
        logger.info(f"✅ تم إضافة أدمن: {username}")
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة أدمن: {e}")
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
        complaint_id = cur.lastrowid
        conn.close()
        logger.info(f"✅ تم حفظ شكواك #{complaint_id} من {username}")
        return complaint_id
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ الشكوى: {e}")
        return None

def get_pending_complaints():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE status = 'pending' ORDER BY id DESC")
        result = cur.fetchall()
        conn.close()
        logger.info(f"✅ تم جلب {len(result)} شكاوى معلقة")
        return result
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الشكاوى: {e}")
        return []

def get_complaint(complaint_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
        result = cur.fetchone()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الشكوى: {e}")
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
        logger.info(f"✅ تم تحديث الشكوى #{complaint_id} إلى {status}")
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في تحديث الشكوى: {e}")
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
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الإحصائيات: {e}")
        return {"total": 0, "pending": 0, "resolved": 0}

def get_all_admins():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins")
        result = cur.fetchall()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الأدمنز: {e}")
        return []

# ================== التحقق من العضوية ==================

async def is_group_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من العضوية: {e}")
        return False

# ================== أوامر البوت ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        # التحقق من العضوية
        if not await is_group_member(context, user_id):
            await update.message.reply_text("❌ عذراً، هذا البوت متاح فقط لأعضاء المجموعة!")
            return
        
        keyboard = [[InlineKeyboardButton("📝 تقديم شكواك", callback_data="report")]]
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
        
        await update.message.reply_text("👋 مرحباً بك!\n\nاختر ما تريد:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"❌ خطأ في /start: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback_data = query.data
    logger.info(f"📍 Callback: {callback_data}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"❌ خطأ في query.answer(): {e}")
    
    try:
        if callback_data == "report":
            keyboard = [
                [InlineKeyboardButton("🐛 خلل تقني", callback_data="type_bug")],
                [InlineKeyboardButton("💬 ملاحظة", callback_data="type_feedback")],
                [InlineKeyboardButton("💡 طلب جديد", callback_data="type_request")],
                [InlineKeyboardButton("« رجوع", callback_data="back_main")]
            ]
            await query.edit_message_text("اختر نوع الشكوى:", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data.startswith("type_"):
            complaint_type = callback_data.split("_")[1]
            context.user_data['complaint_type'] = complaint_type
            await query.edit_message_text("📬 اكتب شكواك الآن:")
        
        elif callback_data == "admin_panel":
            if not is_admin(query.from_user.id):
                await query.edit_message_text("❌ لا توجد صلاحية")
                return
            stats = get_stats()
            keyboard = [
                [InlineKeyboardButton("📋 الشكاوى المعلقة", callback_data="show_pending")],
                [InlineKeyboardButton("« رجوع", callback_data="back_main")]
            ]
            text = f"""⚙️ لوحة التحكم

📊 الإحصائيات:
• إجمالي: {stats['total']}
• معلقة: {stats['pending']}
• محلولة: {stats['resolved']}"""
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data == "show_pending":
            complaints = get_pending_complaints()
            
            if not complaints:
                keyboard = [[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]
                await query.edit_message_text("✅ لا توجد شكاوى معلقة!", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            complaint_index = context.user_data.get('complaint_index', 0)
            if complaint_index >= len(complaints):
                complaint_index = 0
            
            complaint = complaints[complaint_index]
            context.user_data['current_complaint_id'] = complaint[0]
            context.user_data['complaint_index'] = complaint_index
            context.user_data['complaints_list'] = complaints
            
            keyboard = [
                [InlineKeyboardButton("💬 الرد", callback_data="reply_complaint")],
                [InlineKeyboardButton("⬅ السابقة", callback_data="prev_complaint"), 
                 InlineKeyboardButton(f"{complaint_index + 1}/{len(complaints)}", callback_data="noop"),
                 InlineKeyboardButton("التالية ➡", callback_data="next_complaint")],
                [InlineKeyboardButton("« رجوع", callback_data="admin_panel")]
            ]
            
            text = f"""📋 شكواك #{complaint[0]} ({complaint_index + 1}/{len(complaints)})

👤 من: @{complaint[2]}
📌 النوع: {COMPLAINT_TYPES.get(complaint[3], complaint[3])}
💬 الشكاوى: {complaint[4]}
⏰ الوقت: {complaint[-1]}
🔴 الحالة: {complaint[5]}"""
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data in ["next_complaint", "prev_complaint"]:
            complaints = context.user_data.get('complaints_list', [])
            complaint_index = context.user_data.get('complaint_index', 0)
            
            if callback_data == "next_complaint":
                complaint_index = (complaint_index + 1) % len(complaints)
            else:
                complaint_index = (complaint_index - 1) % len(complaints)
            
            complaint = complaints[complaint_index]
            context.user_data['current_complaint_id'] = complaint[0]
            context.user_data['complaint_index'] = complaint_index
            
            keyboard = [
                [InlineKeyboardButton("💬 الرد", callback_data="reply_complaint")],
                [InlineKeyboardButton("⬅ السابقة", callback_data="prev_complaint"), 
                 InlineKeyboardButton(f"{complaint_index + 1}/{len(complaints)}", callback_data="noop"),
                 InlineKeyboardButton("التالية ➡", callback_data="next_complaint")],
                [InlineKeyboardButton("« رجوع", callback_data="admin_panel")]
            ]
            
            text = f"""📋 شكواك #{complaint[0]} ({complaint_index + 1}/{len(complaints)})

👤 من: @{complaint[2]}
📌 النوع: {COMPLAINT_TYPES.get(complaint[3], complaint[3])}
💬 الشكاوى: {complaint[4]}
⏰ الوقت: {complaint[7]}
🔴 الحالة: {complaint[5]}"""
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data == "reply_complaint":
            context.user_data['mode'] = 'reply'
            await query.edit_message_text("📝 اكتب ردك على الشكوى:")
        
        elif callback_data == "publish_complaint":
            complaint_id = context.user_data.get('current_complaint_id')
            complaint = get_complaint(complaint_id)
            admin_reply = context.user_data.get('admin_reply')
            
            if complaint and admin_reply:
                msg = f"""📋 شكواك #{complaint[0]}

👤 من: @{complaint[2]}
📌 النوع: {COMPLAINT_TYPES.get(complaint[3])}
💬 الشكوى: {complaint[4]}

✅ الرد من الفريق:
{admin_reply}"""
                try:
                    if TOPIC_ID:
                        await context.bot.send_message(chat_id=GROUP_ID, text=msg, message_thread_id=TOPIC_ID)
                    else:
                        await context.bot.send_message(chat_id=GROUP_ID, text=msg)
                    logger.info(f"✅ تم نشر الشكوى #{complaint_id} في المجموعة")
                    await query.edit_message_text("✅ تم نشر الشكوى والرد في المجموعة!", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]))
                    update_complaint(complaint_id, 'resolved', admin_reply)
                except TelegramError as e:
                    logger.error(f"❌ خطأ في النشر: {e}")
                    await query.edit_message_text(f"❌ خطأ في النشر: {str(e)[:100]}")
        
        elif callback_data == "mark_resolved":
            complaint_id = context.user_data.get('current_complaint_id')
            admin_reply = context.user_data.get('admin_reply')
            update_complaint(complaint_id, 'resolved', admin_reply)
            keyboard = [[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]
            await query.edit_message_text("✅ تم تحديث الشكوى كـ محلولة!", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data == "mark_inprogress":
            complaint_id = context.user_data.get('current_complaint_id')
            update_complaint(complaint_id, 'in_progress')
            keyboard = [[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]
            await query.edit_message_text("⏳ تم تحديث الشكوى كـ قيد المراجعة!", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data == "back_main":
            keyboard = [[InlineKeyboardButton("📝 تقديم الشكوى", callback_data="report")]]
            if is_admin(query.from_user.id):
                keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
            await query.edit_message_text("👋 مرحباً بك!\n\nاختر ما تريد:", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif callback_data == "noop":
            pass
    
    except Exception as e:
        logger.error(f"❌ خطأ عام في handle_callback: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        # التحقق من العضوية
        if not await is_group_member(context, user_id):
            await update.message.reply_text("❌ عذراً، هذا البوت متاح فقط لأعضاء المجموعة!")
            return
        
        mode = context.user_data.get('mode')
        
        if mode == 'reply':
            admin_reply = update.message.text
            complaint_id = context.user_data.get('current_complaint_id')
            complaint = get_complaint(complaint_id)
            
            if complaint:
                context.user_data['admin_reply'] = admin_reply
                context.user_data['mode'] = None
                
                # إرسال الرد للعضو
                reply_msg = f"""✅ تم الرد على الشكوى!

📋 شكواك (#{complaint[0]}): {complaint[4]}

📝 الرد: {admin_reply}"""
                try:
                    await context.bot.send_message(chat_id=complaint[1], text=reply_msg)
                    logger.info(f"✅ تم إرسال الرد للعضو {complaint[1]}")
                except Exception as e:
                    logger.error(f"❌ خطأ في إرسال الرد: {e}")
                
                # عرض أزرار النشر والحالة
                keyboard = [
                    [InlineKeyboardButton("📤 نشر في المجموعة", callback_data="publish_complaint")],
                    [InlineKeyboardButton("✅ محلولة", callback_data="mark_resolved")],
                    [InlineKeyboardButton("⏳ قيد المراجعة", callback_data="mark_inprogress")],
                    [InlineKeyboardButton("« رجوع", callback_data="admin_panel")]
                ]
                await update.message.reply_text("✅ تم حفظ الرد!\n\nاختر الإجراء:", 
                                              reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif 'complaint_type' in context.user_data:
            complaint_type = context.user_data.pop('complaint_type')
            message = update.message.text
            username = update.effective_user.username or "مستخدم"
            
            logger.info(f"💾 جاري حفظ الشكوى من {username}...")
            complaint_id = save_complaint(user_id, username, complaint_type, message)
            
            if complaint_id:
                await update.message.reply_text("✅ تم استقبال شكواك!")
                
                # إشعار الأدمن
                admins = get_all_admins()
                logger.info(f"📢 إرسال إشعار إلى {len(admins)} أدمن")
                for admin in admins:
                    try:
                        await context.bot.send_message(
                            chat_id=admin[0],
                            text="📩 شكوى جديدة! افتح لوحة التحكم لرؤيتها."
                        )
                    except Exception as e:
                        logger.error(f"❌ خطأ في إرسال إشعار للأدمن {admin[0]}: {e}")
    
    except Exception as e:
        logger.error(f"❌ خطأ عام في handle_message: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    logger.info("🚀 بدء تهيئة البوت...")
    init_db()
    add_admin(7043011146, "MODYER555")
    add_admin(8496647096, "Medoma")
    logger.info("✅ تم تهيئة الأدمنز")
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()