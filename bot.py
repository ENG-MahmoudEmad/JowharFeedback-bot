import os
import sqlite3
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError
from dotenv import load_dotenv

# ================== الإعدادات ==================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH = "bot_database.db"
GROUP_ID = -1003731398016
TOPIC_ID = 5488

# الحالات المتقدمة
COMPLAINT_STATUS = {
    "pending": ("🟡 معلقة", "pending"),
    "in_progress": ("🔵 قيد المراجعة", "in_progress"),
    "replied": ("🟢 تم الرد", "replied"),
    "closed": ("✅ مغلقة", "closed"),
}

COMPLAINT_TYPES = {
    "bug": "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request": "💡 طلب جديد"
}

# ================== قاعدة البيانات المحسّنة ==================

class DatabaseManager:
    """إدارة قاعدة البيانات بشكل احترافي"""
    
    @staticmethod
    def get_db():
        """الحصول على اتصال قاعدة البيانات مع sqlite3.Row"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    @staticmethod
    def init_db():
        """تهيئة قاعدة البيانات مع جداول متقدمة"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            
            # جدول الأدمنز
            cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # جدول الشكاوى المحسّن
            cur.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                complaint_type TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                admin_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (admin_id) REFERENCES admins(user_id)
            )
            """)
            
            # جدول سجل الردود (Conversation Log)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS complaint_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL,
                admin_id INTEGER,
                reply_text TEXT NOT NULL,
                reply_type TEXT DEFAULT 'admin',
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            )
            """)
            
            # جدول إحصائيات
            cur.execute("""
            CREATE TABLE IF NOT EXISTS complaint_stats (
                date TEXT PRIMARY KEY,
                total_complaints INTEGER DEFAULT 0,
                resolved_complaints INTEGER DEFAULT 0,
                avg_response_time REAL DEFAULT 0
            )
            """)

            cur.execute("PRAGMA table_info(complaints)")
            complaint_columns = {row[1] for row in cur.fetchall()}
            if "admin_id" not in complaint_columns:
                cur.execute("ALTER TABLE complaints ADD COLUMN admin_id INTEGER")
                logger.info("✅ تمت إضافة عمود admin_id إلى جدول complaints")
            if "updated_at" not in complaint_columns:
                cur.execute("ALTER TABLE complaints ADD COLUMN updated_at TEXT")
                logger.info("✅ تمت إضافة عمود updated_at إلى جدول complaints")

            cur.execute("PRAGMA table_info(complaint_replies)")
            reply_columns = {row[1] for row in cur.fetchall()}
            if reply_columns and "reply_type" not in reply_columns:
                cur.execute("ALTER TABLE complaint_replies ADD COLUMN reply_type TEXT DEFAULT 'admin'")
                logger.info("✅ تمت إضافة عمود reply_type إلى جدول complaint_replies")
            
            conn.commit()
            conn.close()
            logger.info("✅ قاعدة البيانات تم تهيئتها بنجاح")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
            return False
    
    @staticmethod
    def save_complaint(user_id: int, username: str, complaint_type: str, message: str) -> Optional[int]:
        """حفظ شكوى جديدة"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cur.execute("""
                INSERT INTO complaints (user_id, username, complaint_type, message, created_at, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (user_id, username, complaint_type, message, created_at))
            
            conn.commit()
            complaint_id = cur.lastrowid
            conn.close()
            
            logger.info(f"✅ تم حفظ شكوى جديدة #{complaint_id}")
            return complaint_id
        except Exception as e:
            logger.error(f"❌ خطأ في حفظ الشكوى: {e}")
            return None
    
    @staticmethod
    def add_reply(complaint_id: int, admin_id: int, reply_text: str) -> bool:
        """إضافة رد إلى الشكوى"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cur.execute("""
                INSERT INTO complaint_replies (complaint_id, admin_id, reply_text, created_at)
                VALUES (?, ?, ?, ?)
            """, (complaint_id, admin_id, reply_text, created_at))
            
            cur.execute("""
                UPDATE complaints
                SET status = 'closed', admin_id = ?, updated_at = ?
                WHERE id = ?
            """, (admin_id, created_at, complaint_id))
            affected = cur.rowcount
            
            conn.commit()
            conn.close()

            if affected == 0:
                logger.error(f"❌ لم يتم العثور على الشكوى #{complaint_id} لإغلاقها بعد الرد")
                return False
            
            logger.info(f"✅ تم إضافة رد وإغلاق الشكوى #{complaint_id}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة الرد: {e}")
            return False
    
    @staticmethod
    def get_complaint(complaint_id: int) -> Optional[sqlite3.Row]:
        """جلب شكوى بواسطة الرقم"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
            result = cur.fetchone()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الشكوى: {e}")
            return None
    
    @staticmethod
    def get_pending_complaints(filter_status: str = None) -> List[sqlite3.Row]:
        """جلب الشكاوى مع إمكانية الفلترة"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            
            if filter_status:
                cur.execute("""
                    SELECT * FROM complaints 
                    WHERE status = ? 
                    ORDER BY created_at DESC
                """, (filter_status,))
            else:
                cur.execute("""
                    SELECT * FROM complaints
                    ORDER BY created_at DESC
                """)
            
            result = cur.fetchall()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الشكاوى: {e}")
            return []
    
    @staticmethod
    def get_complaint_replies(complaint_id: int) -> List[sqlite3.Row]:
        """جلب جميع ردود الشكوى"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM complaint_replies
                WHERE complaint_id = ?
                ORDER BY created_at ASC
            """, (complaint_id,))
            result = cur.fetchall()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الردود: {e}")
            return []
    
    @staticmethod
    def update_complaint_status(complaint_id: int, status: str) -> bool:
        """تحديث حالة الشكوى"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cur.execute("""
                UPDATE complaints
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (status, updated_at, complaint_id))
            affected = cur.rowcount
            
            conn.commit()
            conn.close()

            if affected == 0:
                logger.error(f"❌ لم يتم تحديث الشكوى #{complaint_id}: غير موجودة")
                return False
            
            logger.info(f"✅ تم تحديث حالة الشكوى #{complaint_id} إلى {status}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في تحديث الشكوى: {e}")
            return False
    
    @staticmethod
    def get_stats() -> dict:
        """جلب الإحصائيات"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            
            cur.execute("SELECT COUNT(*) FROM complaints")
            total = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'pending'")
            pending = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'in_progress'")
            in_progress = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'replied'")
            replied = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM complaints WHERE status = 'closed'")
            closed = cur.fetchone()[0]
            
            conn.close()
            return {
                "total": total,
                "pending": pending,
                "in_progress": in_progress,
                "replied": replied,
                "closed": closed
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الإحصائيات: {e}")
            return {"total": 0, "pending": 0, "in_progress": 0, "replied": 0, "closed": 0}
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        """التحقق من كون المستخدم أدمن"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
            result = cur.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الأدمن: {e}")
            return False
    
    @staticmethod
    def add_admin(user_id: int, username: str) -> bool:
        """إضافة أدمن"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO admins (user_id, username)
                VALUES (?, ?)
            """, (user_id, username))
            conn.commit()
            conn.close()
            logger.info(f"✅ تم إضافة أدمن: {username}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة أدمن: {e}")
            return False
    
    @staticmethod
    def get_all_admins() -> List[sqlite3.Row]:
        """جلب جميع الأدمنز"""
        try:
            conn = DatabaseManager.get_db()
            cur = conn.cursor()
            cur.execute("SELECT * FROM admins")
            result = cur.fetchall()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"❌ خطأ في جلب الأدمنز: {e}")
            return []

# ================== وظائف مساعدة ==================

async def is_group_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """التحقق من كون المستخدم عضو في المجموعة"""
    try:
        member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من العضوية: {e}")
        return False

def format_complaint_detail(complaint: sqlite3.Row) -> str:
    """تنسيق تفاصيل الشكوى بشكل احترافي"""
    status_emoji, _ = COMPLAINT_STATUS.get(complaint['status'], ('❓', 'unknown'))
    complaint_type = COMPLAINT_TYPES.get(complaint['complaint_type'], complaint['complaint_type'])
    
    return f"""
📋 رقم الشكوى: #{complaint['id']}

👤 من: @{complaint['username']}
📌 النوع: {complaint_type}
💬 الشكوى: {complaint['message']}
⏰ التاريخ: {complaint['created_at']}
{status_emoji} الحالة: {status_emoji.split()[0]} {complaint['status']}
"""

def format_complaint_for_group(complaint: sqlite3.Row, replies: List[sqlite3.Row] = None) -> str:
    """تنسيق الشكوى للنشر في المجموعة"""
    status_emoji, _ = COMPLAINT_STATUS.get(complaint['status'], ('❓', 'unknown'))
    complaint_type = COMPLAINT_TYPES.get(complaint['complaint_type'], complaint['complaint_type'])
    
    msg = f"""
📋 الشكوى #{complaint['id']}

👤 من: @{complaint['username']}
📌 النوع: {complaint_type}
💬 تفاصيل الشكوى:
{complaint['message']}

⏰ تاريخ الإنشاء: {complaint['created_at']}
{status_emoji} الحالة: {complaint['status']}
"""
    
    if replies:
        msg += "\n📝 الردود:\n"
        for reply in replies:
            msg += f"\n✅ {reply['reply_text']}\n"
    
    return msg

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("📨 تقديم شكوى جديدة", callback_data="report")]]
    if DatabaseManager.is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    keyboard.append([InlineKeyboardButton("إنهاء", callback_data="end_session")])
    return InlineKeyboardMarkup(keyboard)

def done_keyboard(include_admin_panel: bool = True) -> InlineKeyboardMarkup:
    keyboard = []
    if include_admin_panel:
        keyboard.append([InlineKeyboardButton("⚙️ العودة للوحة التحكم", callback_data="admin_panel")])
    keyboard.append([InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="back_main")])
    keyboard.append([InlineKeyboardButton("إنهاء", callback_data="end_session")])
    return InlineKeyboardMarkup(keyboard)

def complaint_id_from_callback(callback_data: str, context: ContextTypes.DEFAULT_TYPE, query=None) -> Optional[int]:
    if ":" in callback_data:
        try:
            return int(callback_data.split(":", 1)[1])
        except (TypeError, ValueError):
            pass

    complaint_id = context.user_data.get('current_complaint_id')
    if complaint_id:
        return complaint_id

    message_text = getattr(getattr(query, "message", None), "text", "") or ""
    match = re.search(r"#(\d+)", message_text)
    if match:
        return int(match.group(1))

    return None

# ================== معالجات التيليجرام ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    try:
        user_id = update.effective_user.id
        
        if not await is_group_member(context, user_id):
            await update.message.reply_text(
                "❌ عذراً!\n\n"
                "هذا البوت متاح فقط لأعضاء المجموعة.\n"
                "يرجى الانضمام إلى المجموعة أولاً."
            )
            return
        
        await update.message.reply_text(
            "👋 أهلاً وسهلاً!\n\n"
            "هذا البوت مخصص لاستقبال شكاواكم وملاحظاتكم.\n"
            "اختر ما تريد:",
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"❌ خطأ في /start: {e}")
        await update.message.reply_text("❌ حدث خطأ ما. حاول لاحقاً.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج جميع الأزرار"""
    query = update.callback_query
    callback_data = query.data
    
    logger.info(f"📍 Callback: {callback_data} من المستخدم {query.from_user.id}")
    
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"❌ خطأ في query.answer(): {e}")
    
    try:
        # ========== تقديم شكوى ==========
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
            await query.edit_message_text("📬 اكتب تفاصيل الشكوى الآن:")
        
        # ========== لوحة التحكم ==========
        elif callback_data == "admin_panel":
            if not DatabaseManager.is_admin(query.from_user.id):
                await query.edit_message_text("❌ ليس لديك صلاحيات")
                return
            
            stats = DatabaseManager.get_stats()
            keyboard = [
                [InlineKeyboardButton("📂 جميع الشكاوى", callback_data="filter_all")],
                [InlineKeyboardButton("🟡 المعلقة", callback_data="filter_pending"),
                 InlineKeyboardButton("🔵 المراجعة", callback_data="filter_inprogress")],
                [InlineKeyboardButton("🟢 المحلولة", callback_data="filter_replied"),
                 InlineKeyboardButton("✅ المغلقة", callback_data="filter_closed")],
                [InlineKeyboardButton("« رجوع", callback_data="back_main")]
            ]
            
            text = f"""⚙️ لوحة التحكم

📊 الإحصائيات:
━━━━━━━━━━━━━━━━
📈 الإجمالي: {stats['total']}
🟡 المعلقة: {stats['pending']}
🔵 المراجعة: {stats['in_progress']}
🟢 المحلولة: {stats['replied']}
✅ المغلقة: {stats['closed']}
━━━━━━━━━━━━━━━━

اختر فئة للعرض:"""
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        # ========== الفلترة ==========
        elif callback_data.startswith("filter_"):
            filter_type = callback_data.split("_")[1]
            status_map = {
                "all": None,
                "pending": "pending",
                "inprogress": "in_progress",
                "replied": "replied",
                "closed": "closed"
            }
            
            complaints = DatabaseManager.get_pending_complaints(status_map.get(filter_type))
            
            if not complaints:
                keyboard = [[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]
                await query.edit_message_text("✅ لا توجد شكاوى في هذه الفئة", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            context.user_data['current_complaints'] = [dict(c) for c in complaints]
            context.user_data['current_index'] = 0
            
            complaint = complaints[0]
            await show_complaint_detail(query, context, complaint)
        
        # ========== التنقل بين الشكاوى ==========
        elif callback_data in ["next_complaint", "prev_complaint"]:
            complaints = context.user_data.get('current_complaints', [])
            if not complaints:
                return
            
            current_index = context.user_data.get('current_index', 0)
            
            if callback_data == "next_complaint":
                current_index = (current_index + 1) % len(complaints)
            else:
                current_index = (current_index - 1) % len(complaints)
            
            context.user_data['current_index'] = current_index
            complaint_dict = complaints[current_index]
            
            await show_complaint_detail(query, context, complaint_dict)
        
        # ========== الرد على الشكوى ==========
        elif callback_data.startswith("reply_complaint"):
            complaint_id = complaint_id_from_callback(callback_data, context, query)
            if not complaint_id or not DatabaseManager.get_complaint(complaint_id):
                await query.edit_message_text("❌ لم يتم تحديد الشكوى", reply_markup=done_keyboard())
                return
            context.user_data['current_complaint_id'] = complaint_id
            context.user_data['mode'] = 'reply'
            await query.edit_message_text("📝 اكتب ردك على الشكوى:")
        
        # ========== نشر في المجموعة ==========
        elif callback_data.startswith("publish_complaint"):
            complaint_id = complaint_id_from_callback(callback_data, context, query)
            complaint = DatabaseManager.get_complaint(complaint_id)
            replies = DatabaseManager.get_complaint_replies(complaint_id)
            
            if complaint:
                msg = format_complaint_for_group(complaint, replies)
                try:
                    if TOPIC_ID:
                        await context.bot.send_message(
                            chat_id=GROUP_ID,
                            text=msg,
                            message_thread_id=TOPIC_ID
                        )
                    else:
                        await context.bot.send_message(chat_id=GROUP_ID, text=msg)
                    
                    logger.info(f"✅ تم نشر الشكوى #{complaint_id} في المجموعة")
                    await query.edit_message_text(
                        "✅ تم نشر الشكوى في المجموعة بنجاح!",
                        reply_markup=done_keyboard()
                    )
                except TelegramError as e:
                    logger.error(f"❌ خطأ في النشر: {e}")
                    await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
            else:
                await query.edit_message_text("❌ لم يتم العثور على الشكوى", reply_markup=done_keyboard())
        
        # ========== تحديث الحالة ==========
        elif callback_data.startswith("close_complaint"):
            complaint_id = complaint_id_from_callback(callback_data, context, query)
            if not complaint_id:
                await query.edit_message_text("❌ لم أستطع تحديد رقم الشكوى. افتحها من لوحة التحكم مرة أخرى.", reply_markup=done_keyboard())
                return
            if DatabaseManager.update_complaint_status(complaint_id, 'closed'):
                await query.edit_message_text(
                    f"✅ تم إغلاق الشكوى #{complaint_id}",
                    reply_markup=done_keyboard()
                )
            else:
                await query.edit_message_text("❌ فشل إغلاق الشكوى. تأكد أنها موجودة ثم حاول مرة أخرى.", reply_markup=done_keyboard())
        
        elif callback_data.startswith("inprogress_complaint"):
            complaint_id = complaint_id_from_callback(callback_data, context, query)
            if not complaint_id:
                await query.edit_message_text("❌ لم أستطع تحديد رقم الشكوى. افتحها من لوحة التحكم مرة أخرى.", reply_markup=done_keyboard())
                return
            if DatabaseManager.update_complaint_status(complaint_id, 'in_progress'):
                await query.edit_message_text(
                    f"⏳ الشكوى #{complaint_id} أصبحت قيد المراجعة",
                    reply_markup=done_keyboard()
                )
            else:
                await query.edit_message_text("❌ فشل تحديث الحالة. تأكد أن الشكوى موجودة ثم حاول مرة أخرى.", reply_markup=done_keyboard())
        
        # ========== الرجوع ==========
        elif callback_data == "back_main":
            await query.edit_message_text(
                "👋 أهلاً وسهلاً!\n\nاختر ما تريد:",
                reply_markup=main_menu_keyboard(query.from_user.id)
            )
        
        elif callback_data == "end_session":
            context.user_data.clear()
            await query.edit_message_text("تم إنهاء القائمة. اكتب /start إذا احتجت ترجع.")
        
        elif callback_data == "noop":
            pass
    
    except Exception as e:
        logger.error(f"❌ خطأ في handle_callback: {e}")
        try:
            await query.edit_message_text(f"❌ حدث خطأ: {str(e)[:100]}")
        except:
            pass

async def show_complaint_detail(query, context, complaint):
    """عرض تفاصيل الشكوى مع الخيارات"""
    complaint_id = complaint.get('id') if isinstance(complaint, dict) else complaint['id']
    
    complaint_obj = DatabaseManager.get_complaint(complaint_id)
    if not complaint_obj:
        await query.edit_message_text("❌ لم يتم العثور على الشكوى")
        return
    
    context.user_data['current_complaint_id'] = complaint_id
    
    # الحصول على عدد الردود
    replies = DatabaseManager.get_complaint_replies(complaint_id)
    has_reply = len(replies) > 0
    
    # الزر الديناميكي للرد
    reply_button_text = "✏️ تعديل الرد" if has_reply else "💬 الرد على الشكوى"
    
    keyboard = [
        [InlineKeyboardButton(reply_button_text, callback_data=f"reply_complaint:{complaint_id}")],
        [InlineKeyboardButton("📤 نشر في المجموعة", callback_data=f"publish_complaint:{complaint_id}")],
        [InlineKeyboardButton("⏳ قيد المراجعة", callback_data=f"inprogress_complaint:{complaint_id}"),
         InlineKeyboardButton("🔒 إغلاق", callback_data=f"close_complaint:{complaint_id}")],
        [InlineKeyboardButton("⬅ السابقة", callback_data="prev_complaint"),
         InlineKeyboardButton(f"({context.user_data.get('current_index', 0) + 1})", callback_data="noop"),
         InlineKeyboardButton("التالية ➡", callback_data="next_complaint")],
        [InlineKeyboardButton("« رجوع", callback_data="admin_panel")]
    ]
    
    text = format_complaint_detail(complaint_obj)
    
    if has_reply:
        text += "\n🟢 الردود:\n━━━━━━━━━━━━━━━━\n"
        for reply in replies:
            text += f"✅ {reply['reply_text']}\n"
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    try:
        user_id = update.effective_user.id
        
        if not await is_group_member(context, user_id):
            await update.message.reply_text("❌ هذا البوت متاح فقط لأعضاء المجموعة")
            return
        
        mode = context.user_data.get('mode')
        
        # ========== وضع الرد ==========
        if mode == 'reply':
            admin_reply = update.message.text
            complaint_id = context.user_data.get('current_complaint_id')
            complaint = DatabaseManager.get_complaint(complaint_id)
            
            if complaint:
                # إضافة الرد وتحديث الحالة تلقائياً
                if DatabaseManager.add_reply(complaint_id, user_id, admin_reply):
                    context.user_data['mode'] = None
                    
                    # إرسال رسالة استقبال احترافية للمستخدم
                    user_msg = f"""
✅ تم الرد على الشكوى

━━━━━━━━━━━━━━━━
📋 رقم الشكوى: #{complaint_id}
📌 النوع: {COMPLAINT_TYPES.get(complaint['complaint_type'])}
💬 الشكوى: {complaint['message']}
━━━━━━━━━━━━━━━━

📝 الرد:
{admin_reply}

━━━━━━━━━━━━━━━━
شكراً لك على تواصلك معنا.
"""
                    try:
                        await context.bot.send_message(chat_id=complaint['user_id'], text=user_msg)
                        logger.info(f"✅ تم إرسال الرد للمستخدم {complaint['user_id']}")
                    except Exception as e:
                        logger.error(f"❌ خطأ في إرسال الرد: {e}")
                    
                    await update.message.reply_text(
                        f"✅ تم حفظ الرد وإرساله للمستخدم!\n\n"
                        f"🔒 الشكوى #{complaint_id} أصبحت مغلقة تلقائياً.",
                        reply_markup=done_keyboard()
                    )
            else:
                context.user_data['mode'] = None
                await update.message.reply_text("❌ الشكوى غير موجودة.", reply_markup=done_keyboard())
        
        # ========== تقديم شكوى جديدة ==========
        elif 'complaint_type' in context.user_data:
            complaint_type = context.user_data.pop('complaint_type')
            message = update.message.text
            username = update.effective_user.username or "مستخدم"
            
            complaint_id = DatabaseManager.save_complaint(user_id, username, complaint_type, message)
            
            if complaint_id:
                # رسالة استقبال احترافية
                confirmation_msg = f"""
✅ تم استلام الشكوى بنجاح

━━━━━━━━━━━━━━━━
📋 رقم الشكوى: #{complaint_id}
📌 النوع: {COMPLAINT_TYPES.get(complaint_type)}
⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━

سنقوم بمراجعة الشكوى والرد عليك قريباً.
شكراً لك على تواصلك معنا! 🙏
"""
                await update.message.reply_text(confirmation_msg)
                
                # إشعار الأدمنز
                admins = DatabaseManager.get_all_admins()
                logger.info(f"📢 إرسال إشعار إلى {len(admins)} أدمن")
                
                for admin in admins:
                    try:
                        await context.bot.send_message(
                            chat_id=admin['user_id'],
                            text=f"📩 شكوى جديدة #{complaint_id}\n\n"
                                 f"من: @{username}\n"
                                 f"النوع: {COMPLAINT_TYPES.get(complaint_type)}\n\n"
                                 f"افتح لوحة التحكم لمراجعتها."
                        )
                    except Exception as e:
                        logger.error(f"❌ خطأ في إرسال إشعار: {e}")
    
    except Exception as e:
        logger.error(f"❌ خطأ في handle_message: {e}")

# ================== البدء ==========

def main():
    """تشغيل البوت"""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    logger.info("🚀 بدء تهيئة البوت...")
    
    # تهيئة قاعدة البيانات
    DatabaseManager.init_db()
    
    # إضافة الأدمنز
    DatabaseManager.add_admin(7043011146, "MODYER555")
    DatabaseManager.add_admin(8496647096, "Medoma")
    
    # تسجيل المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ البوت جاهز!")
    logger.info("🚀 بدء استقبال الرسائل...")
    
    app.run_polling()

if __name__ == "__main__":
    main()
