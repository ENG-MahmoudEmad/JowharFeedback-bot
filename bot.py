import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_PATH        = "bot_database.db"
GROUP_ID       = -1003731398016
TOPIC_ID       = 5488

COMPLAINT_TYPES = {
    "bug":      "🐛 خلل تقني",
    "feedback": "💬 ملاحظة",
    "request":  "💡 طلب جديد"
}
STATUS_LABELS = {
    "pending":     "🟡 معلقة",
    "in_progress": "🔵 قيد المراجعة",
    "replied":     "🟢 تم الرد",
    "closed":      "✅ مغلقة",
}

# ================== قاعدة البيانات ==================

class DB:
    @staticmethod
    def conn():
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def init():
        try:
            con = DB.conn(); cur = con.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY, username TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, username TEXT NOT NULL,
                complaint_type TEXT NOT NULL, message TEXT NOT NULL,
                status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS complaint_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL, admin_id INTEGER,
                reply_text TEXT NOT NULL, created_at TEXT NOT NULL)""")
            con.commit(); con.close()
            logger.info("✅ قاعدة البيانات جاهزة")
        except Exception as e:
            logger.error(f"❌ init: {e}")

    @staticmethod
    def add_admin(uid, uname):
        try:
            con = DB.conn()
            con.execute("INSERT OR IGNORE INTO admins (user_id, username) VALUES (?,?)", (uid, uname))
            con.commit(); con.close()
            logger.info(f"✅ أدمن: {uname}")
        except Exception as e:
            logger.error(f"❌ add_admin: {e}")

    @staticmethod
    def is_admin(uid):
        try:
            con = DB.conn()
            r = con.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone()
            con.close(); return r is not None
        except Exception as e:
            logger.error(f"❌ is_admin: {e}"); return False

    @staticmethod
    def get_all_admins():
        try:
            con = DB.conn()
            r = con.execute("SELECT * FROM admins").fetchall()
            con.close(); return r
        except Exception as e:
            logger.error(f"❌ get_all_admins: {e}"); return []

    @staticmethod
    def save_complaint(uid, uname, ctype, msg):
        try:
            con = DB.conn(); now = datetime.now().strftime('%Y-%m-%d %H:%M')
            cur = con.execute(
                "INSERT INTO complaints (user_id,username,complaint_type,message,created_at) VALUES (?,?,?,?,?)",
                (uid, uname, ctype, msg, now))
            con.commit(); cid = cur.lastrowid; con.close(); return cid
        except Exception as e:
            logger.error(f"❌ save_complaint: {e}"); return None

    @staticmethod
    def get_complaint(cid):
        try:
            con = DB.conn()
            r = con.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
            con.close(); return r
        except Exception as e:
            logger.error(f"❌ get_complaint: {e}"); return None

    @staticmethod
    def get_complaints(status=None):
        try:
            con = DB.conn()
            if status == "active":
                r = con.execute("SELECT * FROM complaints WHERE status IN ('pending','in_progress') ORDER BY id DESC").fetchall()
            elif status:
                r = con.execute("SELECT * FROM complaints WHERE status=? ORDER BY id DESC", (status,)).fetchall()
            else:
                r = con.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()
            con.close(); return r
        except Exception as e:
            logger.error(f"❌ get_complaints: {e}"); return []

    @staticmethod
    def update_status(cid, status):
        try:
            con = DB.conn(); now = datetime.now().strftime('%Y-%m-%d %H:%M')
            affected = con.execute(
                "UPDATE complaints SET status=?, updated_at=? WHERE id=?", (status, now, cid)
            ).rowcount
            con.commit(); con.close()
            if affected > 0:
                logger.info(f"✅ شكوى #{cid} → {status}"); return True
            logger.error(f"❌ update_status: 0 rows affected, cid={cid}"); return False
        except Exception as e:
            logger.error(f"❌ update_status: {e}"); return False

    @staticmethod
    def add_reply(cid, admin_id, text):
        try:
            con = DB.conn(); now = datetime.now().strftime('%Y-%m-%d %H:%M')
            con.execute("INSERT INTO complaint_replies (complaint_id,admin_id,reply_text,created_at) VALUES (?,?,?,?)",
                        (cid, admin_id, text, now))
            con.execute("UPDATE complaints SET status='replied', updated_at=? WHERE id=?", (now, cid))
            con.commit(); con.close()
            logger.info(f"✅ رد على #{cid}"); return True
        except Exception as e:
            logger.error(f"❌ add_reply: {e}"); return False

    @staticmethod
    def get_replies(cid):
        try:
            con = DB.conn()
            r = con.execute("SELECT * FROM complaint_replies WHERE complaint_id=? ORDER BY created_at ASC", (cid,)).fetchall()
            con.close(); return r
        except Exception as e:
            logger.error(f"❌ get_replies: {e}"); return []

    @staticmethod
    def get_stats():
        try:
            con = DB.conn()
            t  = con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
            p  = con.execute("SELECT COUNT(*) FROM complaints WHERE status='pending'").fetchone()[0]
            ip = con.execute("SELECT COUNT(*) FROM complaints WHERE status='in_progress'").fetchone()[0]
            re = con.execute("SELECT COUNT(*) FROM complaints WHERE status='replied'").fetchone()[0]
            cl = con.execute("SELECT COUNT(*) FROM complaints WHERE status='closed'").fetchone()[0]
            con.close()
            return {"total": t, "pending": p, "in_progress": ip, "replied": re, "closed": cl}
        except Exception as e:
            logger.error(f"❌ get_stats: {e}")
            return {"total":0,"pending":0,"in_progress":0,"replied":0,"closed":0}

# ================== مساعدات UI ==================

async def is_member(ctx, uid):
    try:
        m = await ctx.bot.get_chat_member(GROUP_ID, uid)
        return m.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"❌ is_member: {e}"); return False

def kb_main(is_admin_flag):
    rows = [[InlineKeyboardButton("📝 تقديم شكوى جديدة", callback_data="report")]]
    if is_admin_flag:
        rows.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def text_complaint(c, replies=None):
    status = STATUS_LABELS.get(c['status'], c['status'])
    ctype  = COMPLAINT_TYPES.get(c['complaint_type'], c['complaint_type'])
    t = (f"📋 شكوى #{c['id']}\n\n"
         f"👤 من: @{c['username']}\n"
         f"📌 النوع: {ctype}\n"
         f"💬 الشكوى: {c['message']}\n"
         f"⏰ التاريخ: {c['created_at']}\n"
         f"• الحالة: {status}")
    if replies:
        t += "\n\n🟢 الردود:\n━━━━━━━━━━━━━━━━"
        for r in replies:
            t += f"\n✅ {r['reply_text']}\n   🕐 {r['created_at']}"
    return t

def kb_complaint(has_reply, idx, total):
    reply_label = "✏️ تعديل الرد" if has_reply else "💬 الرد على الشكوى"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(reply_label,               callback_data="do_reply")],
        [InlineKeyboardButton("📤 نشر في المجموعة",      callback_data="do_publish")],
        [InlineKeyboardButton("🔵 قيد المراجعة",        callback_data="do_inprogress"),
         InlineKeyboardButton("🔒 إغلاق",               callback_data="do_close")],
        [InlineKeyboardButton("⬅ السابقة",              callback_data="nav_prev"),
         InlineKeyboardButton(f"{idx+1}/{total}",        callback_data="noop"),
         InlineKeyboardButton("التالية ➡",              callback_data="nav_next")],
        [InlineKeyboardButton("« رجوع للوحة",           callback_data="admin_panel")]
    ])

async def show_complaint(query, context, cid):
    c = DB.get_complaint(cid)
    if not c:
        await query.edit_message_text("❌ لم يتم العثور على الشكوى"); return
    context.user_data['current_cid'] = cid
    replies   = DB.get_replies(cid)
    has_reply = len(replies) > 0
    ids       = context.user_data.get('complaints', [cid])
    idx       = context.user_data.get('c_index', 0)
    await query.edit_message_text(text_complaint(c, replies), reply_markup=kb_complaint(has_reply, idx, len(ids)))

# ================== Handlers ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(context, uid):
        await update.message.reply_text("❌ هذا البوت لأعضاء المجموعة فقط."); return
    context.user_data.clear()
    await update.message.reply_text("👋 أهلاً!\n\nاختر ما تريد:", reply_markup=kb_main(DB.is_admin(uid)))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data
    uid   = query.from_user.id
    logger.info(f"📍 {data} ← {uid}")
    try: await query.answer()
    except: pass

    try:
        # رجوع للقائمة الرئيسية
        if data == "go_main":
            await query.edit_message_text("👋 أهلاً!\n\nاختر ما تريد:", reply_markup=kb_main(DB.is_admin(uid)))

        # تقديم شكوى
        elif data == "report":
            kb = [
                [InlineKeyboardButton("🐛 خلل تقني",  callback_data="type_bug")],
                [InlineKeyboardButton("💬 ملاحظة",    callback_data="type_feedback")],
                [InlineKeyboardButton("💡 طلب جديد",  callback_data="type_request")],
                [InlineKeyboardButton("« رجوع",       callback_data="go_main")]
            ]
            await query.edit_message_text("اختر نوع الشكوى:", reply_markup=InlineKeyboardMarkup(kb))

        elif data.startswith("type_"):
            context.user_data['complaint_type'] = data.split("_")[1]
            await query.edit_message_text("📬 اكتب تفاصيل الشكوى الآن:")

        # لوحة التحكم
        elif data == "admin_panel":
            if not DB.is_admin(uid):
                await query.edit_message_text("❌ ليس لديك صلاحيات"); return
            s  = DB.get_stats()
            kb = [
                [InlineKeyboardButton("📂 جميع الشكاوى",  callback_data="filter_all")],
                [InlineKeyboardButton("🟡 المعلقة",        callback_data="filter_pending"),
                 InlineKeyboardButton("🔵 المراجعة",       callback_data="filter_inprogress")],
                [InlineKeyboardButton("🟢 تم الرد",        callback_data="filter_replied"),
                 InlineKeyboardButton("✅ المغلقة",         callback_data="filter_closed")],
                [InlineKeyboardButton("« رجوع",           callback_data="go_main")]
            ]
            text = (f"⚙️ لوحة التحكم\n\n📊 الإحصائيات:\n━━━━━━━━━━━━━━━━\n"
                    f"📈 الإجمالي:  {s['total']}\n🟡 المعلقة:   {s['pending']}\n"
                    f"🔵 المراجعة:  {s['in_progress']}\n🟢 تم الرد:   {s['replied']}\n"
                    f"✅ المغلقة:   {s['closed']}\n━━━━━━━━━━━━━━━━")
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

        # الفلترة
        elif data.startswith("filter_"):
            ft = data.split("_")[1]
            sm = {"all": None, "pending": "pending", "inprogress": "in_progress", "replied": "replied", "closed": "closed"}
            complaints = DB.get_complaints(sm.get(ft))
            if not complaints:
                kb = [[InlineKeyboardButton("« رجوع", callback_data="admin_panel")]]
                await query.edit_message_text("✅ لا توجد شكاوى في هذه الفئة.", reply_markup=InlineKeyboardMarkup(kb)); return
            context.user_data['complaints'] = [c['id'] for c in complaints]
            context.user_data['c_index']    = 0
            await show_complaint(query, context, complaints[0]['id'])

        # التنقل
        elif data in ["nav_next", "nav_prev"]:
            ids = context.user_data.get('complaints', [])
            idx = context.user_data.get('c_index', 0)
            idx = (idx+1) % len(ids) if data == "nav_next" else (idx-1) % len(ids)
            context.user_data['c_index'] = idx
            await show_complaint(query, context, ids[idx])

        # الرد
        elif data == "do_reply":
            context.user_data['mode'] = 'reply'
            await query.edit_message_text("📝 اكتب ردك على الشكوى:")

        # نشر
        elif data == "do_publish":
            cid = context.user_data.get('current_cid')
            if not cid:
                await query.edit_message_text("❌ لم يتم تحديد الشكوى"); return
            c       = DB.get_complaint(cid)
            replies = DB.get_replies(cid)
            msg     = text_complaint(c, replies)
            try:
                if TOPIC_ID:
                    await context.bot.send_message(chat_id=GROUP_ID, text=msg, message_thread_id=TOPIC_ID)
                else:
                    await context.bot.send_message(chat_id=GROUP_ID, text=msg)
                kb = [[InlineKeyboardButton("« رجوع للوحة", callback_data="admin_panel")]]
                await query.edit_message_text("✅ تم النشر في المجموعة!", reply_markup=InlineKeyboardMarkup(kb))
            except TelegramError as e:
                logger.error(f"❌ نشر: {e}")
                await query.edit_message_text(f"❌ خطأ في النشر:\n{str(e)[:150]}")

        # إغلاق
        elif data == "do_close":
            cid = context.user_data.get('current_cid')
            if not cid:
                await query.edit_message_text("❌ لم يتم تحديد الشكوى"); return
            if DB.update_status(cid, 'closed'):
                kb = [[InlineKeyboardButton("« رجوع للوحة", callback_data="admin_panel")]]
                await query.edit_message_text(f"🔒 تم إغلاق الشكوى #{cid} بنجاح.", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await query.edit_message_text("❌ فشل الإغلاق، حاول مرة أخرى.")

        # قيد المراجعة
        elif data == "do_inprogress":
            cid = context.user_data.get('current_cid')
            if not cid:
                await query.edit_message_text("❌ لم يتم تحديد الشكوى"); return
            if DB.update_status(cid, 'in_progress'):
                kb = [[InlineKeyboardButton("« رجوع للوحة", callback_data="admin_panel")]]
                await query.edit_message_text(f"🔵 الشكوى #{cid} الآن قيد المراجعة.", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await query.edit_message_text("❌ فشل التحديث، حاول مرة أخرى.")

        elif data == "noop":
            pass

    except Exception as e:
        logger.error(f"❌ handle_callback: {e}")
        try: await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
        except: pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    username = update.effective_user.username or "مستخدم"

    if not await is_member(context, uid):
        await update.message.reply_text("❌ هذا البوت لأعضاء المجموعة فقط."); return

    mode = context.user_data.get('mode')

    # وضع الرد
    if mode == 'reply':
        reply_text = update.message.text
        cid        = context.user_data.get('current_cid')
        if not cid:
            await update.message.reply_text("❌ لم يتم تحديد الشكوى. ابدأ من /start"); return
        c = DB.get_complaint(cid)
        if not c:
            await update.message.reply_text("❌ الشكوى غير موجودة."); return

        if DB.add_reply(cid, uid, reply_text):
            context.user_data['mode'] = None
            # رسالة للمستخدم
            try:
                await context.bot.send_message(
                    chat_id=c['user_id'],
                    text=(f"✅ تم الرد على شكواك\n\n━━━━━━━━━━━━━━━━\n"
                          f"📋 رقم الشكوى: #{cid}\n"
                          f"📌 النوع: {COMPLAINT_TYPES.get(c['complaint_type'])}\n"
                          f"💬 شكواك: {c['message']}\n━━━━━━━━━━━━━━━━\n\n"
                          f"📝 الرد:\n{reply_text}\n\nشكراً لتواصلك معنا 🙏")
                )
            except Exception as e:
                logger.error(f"❌ إرسال للمستخدم: {e}")
            # خيارات للأدمن
            kb = [
                [InlineKeyboardButton("📤 نشر في المجموعة", callback_data="do_publish")],
                [InlineKeyboardButton("« رجوع للوحة",       callback_data="admin_panel")]
            ]
            await update.message.reply_text(
                f"✅ تم إرسال الرد!\n🟢 الشكوى #{cid} أصبحت: تم الرد\n\nهل تريد نشرها في المجموعة؟",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await update.message.reply_text("❌ فشل حفظ الرد. حاول مرة أخرى.")

    # تقديم شكوى جديدة
    elif 'complaint_type' in context.user_data:
        ctype   = context.user_data.pop('complaint_type')
        message = update.message.text
        cid     = DB.save_complaint(uid, username, ctype, message)
        if cid:
            await update.message.reply_text(
                f"✅ تم استلام شكواك بنجاح!\n\n━━━━━━━━━━━━━━━━\n"
                f"📋 رقم الشكوى: #{cid}\n"
                f"📌 النوع: {COMPLAINT_TYPES.get(ctype)}\n"
                f"⏰ الوقت: {datetime.now().strftime('%H:%M')}\n━━━━━━━━━━━━━━━━\n\n"
                f"سنقوم بمراجعتها والرد عليك قريباً 🙏"
            )
            for admin in DB.get_all_admins():
                try:
                    await context.bot.send_message(
                        chat_id=admin['user_id'],
                        text=(f"📩 شكوى جديدة #{cid}\n👤 من: @{username}\n"
                              f"📌 النوع: {COMPLAINT_TYPES.get(ctype)}\n\nافتح لوحة التحكم للمراجعة.")
                    )
                except Exception as e:
                    logger.error(f"❌ إشعار أدمن: {e}")
        else:
            await update.message.reply_text("❌ حدث خطأ. حاول مرة أخرى.")

# ================== التشغيل ==================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    DB.init()
    DB.add_admin(7043011146, "MODYER555")
    DB.add_admin(8496647096, "Medoma")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()