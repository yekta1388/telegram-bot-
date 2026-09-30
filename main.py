import io
import asyncio
import logging
import sqlite3
import qrcode
import requests
from aiogram import Bot, Dispatcher, F, types
# حذف ایمپورت AiohttpSession زیرا پروکسی روی نسخه رایگان کاربردی ندارد
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
)

# ==================== تنظیمات لاگ‌ها ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== تنظیمات اصلی ====================
BOT_TOKEN = "8859821875:AAEroWKhDKKD5uaWpcyN9KQLmjO_EcU7oi4"
SUPPORT_GROUP_ID = -1004368111047  # شناسه جدید گروه پشتیبانی
HOMEWORK_CHANNEL_ID = -1009999999999  # شناسه گروه/کانال اختصاصی تکالیف (قابل تنظیم)
COZE_TOKEN = "pat_TVJojx3jr4tfcz3XdqNiaMMl0TpepieyKV6RR5kPFFKeu8ssE5clpY8C4hokx3yK"
COZE_BOT_ID = "7689012492886982661"
COZE_API_URL = "https://api.coze.com/v3/chat"

# مقداردهی اولیه ربات بدون استفاده از سشن پروکسیِ مسدودشده
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "academy_ultimate.db"

# حافظه موقت چت‌های کوزه، ردیاب آزمون‌ها و پاسخ به تیکت
coze_chats = {}
ai_users = set()
poll_tracker = {}

# متن پیام‌های یادآوری
MESSAGES = {
    "quiz": (
        "📝 **یادآوری کوییز**\n\n"
        "با انجام آزمون خودت رو امتحان کن و متوجه نقاط ضعفت شو تا یادگیری بهتر اتفاق بیفته! 🎯"
    ),
    "practice": (
        "📚 **یادآوری تمرین**\n\n"
        "یادت باشه که با تکرار کردن درس‌ها، اون‌ها بهتر توی ذهنت می‌مونن و سخت‌تر فراموشت میشن! 💡"
    ),
    "morning_check": (
        "☀️ **چک‌‌این صبحگاهی**\n\n"
        "یک روز از برنامه رسیدن به اهدافت گذشته، برای شروع دیر نیست؛ همین الان شروع کن! 🚀"
    )
}

# ==================== پایگاه داده جامع ====================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        # جدول کاربران و لایسنس‌ها
        c.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                license_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                telegram_id INTEGER,
                phone TEXT,
                name TEXT,
                score INTEGER DEFAULT 0,
                homeworks TEXT DEFAULT '0',
                quiz TEXT DEFAULT 'ثبت نشده'
            )
        """)

        # جدول تیکت‌های پشتیبانی
        c.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                department TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول حضور و غیاب
        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                session_number INTEGER,
                status TEXT,
                date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول محتوای جلسات (فایل‌ها و آزمون‌ها)
        c.execute("""
            CREATE TABLE IF NOT EXISTS session_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT,
                session_number INTEGER,
                content_type TEXT,
                content_value TEXT,
                UNIQUE(term, session_number, content_type)
            )
        """)

        # جدول پیشرفت تحصیلی و قفل/باز بودن جلسات
        c.execute("""
            CREATE TABLE IF NOT EXISTS student_progress (
                user_id INTEGER,
                term TEXT,
                max_allowed_session INTEGER DEFAULT 1,
                PRIMARY KEY(user_id, term)
            )
        """)

        # جدول تکالیف ارسال شده توسط فراگیران
        c.execute("""
            CREATE TABLE IF NOT EXISTS student_homeworks (
                user_id INTEGER,
                session_id TEXT,
                file_id TEXT,
                PRIMARY KEY(user_id, session_id)
            )
        """)

        # جدول نظرسنجی‌ها برای جلوگیری از ثبت تکراری و اعطای امتیاز
        c.execute("""
            CREATE TABLE IF NOT EXISTS surveys (
                user_id INTEGER,
                session_id TEXT,
                rating TEXT,
                PRIMARY KEY(user_id, session_id)
            )
        """)

        # درج اولیه کاربران و لایسنس‌ها
        initial_users = [
            ("LIC-MM9490", "student", None, "+989134959490", "مهدیه مهدیزاده"),
            ("LIC-RG9338", "student", None, "+989050719338", "رضا قلی پور"),
            ("LIC-FK4312", "student", None, "+989137444312", "فاضل کارگر"),
            ("LIC-HH6216", "student", None, "+989133406216", "حکیمه حسینی نسب"),
            ("LIC-FD1172", "student", None, "+989136311172", "فاطمه دانایی"),
            ("LIC-FA4349", "student", None, "+989132984349", "فاطمه اسدی"),
            ("LIC-ST2301", "student", None, "+989393212301", "سمیه طباخی"),
            ("LIC-MI0510", "student", None, "+989138630510", "محمد اسلامی"),
            ("LIC-ES7757", "student", None, "+989369137757", "احسان سعیدی"),
            ("LIC-FT7146", "student", None, "+989135007146", "فاطمه تاج الدینی"),
            ("LIC-FZ0969", "student", None, "+989132400969", "فریبا زنگی ابادی"),
            ("LIC-MP2631", "student", None, "+989138352631", "محمدجواد پورجعفری"),
            ("LIC-MS1137", "student", None, "+989131971137", "محمد رضا شهابی"),
            ("LIC-RN1580", "student", None, "+989139411580", "رضوان نجمی زاده"),
            ("LIC-ME8930", "student", None, "+989133998930", "محدثه ابراهیمی"),
            ("LIC-BZ2280", "student", None, "+989131492280", "بتول ذاکری"),
            ("LIC-PN9935", "student", None, "+989132999935", "پروین نیک سرشت"),
            ("LIC-FZ2581", "student", None, "+989133402581", "فخری زنگی ابادی"),
            ("LIC-MB8236", "student", None, "+989380288236", "مهدیه بزکان"),
            ("LIC-FM1041", "student", None, "+989133951041", "فاطمه محمدی"),
            ("LIC-HA2922", "student", None, "+989136112922", "هانیه احمدی نژاد"),
            ("LIC-MM9094", "student", None, "+989131449094", "مطهره معین الدینی"),
            ("LIC-HA9872", "student", None, "+989367499872", "حدیث عاشور زاده"),
            ("LIC-MH8265", "student", None, "+989393658265", "مهدیه هفت وادی"),
            ("LIC-MA4274", "student", None, "+989132954274", "منصوره عبدالعلی زاده"),
            ("LIC-MM6860", "student", None, "+989134926860", "مبینا محمدی"),
            ("LIC-FI9467", "student", None, "+989140539467", "فاطمه اسلامی"),
            ("LIC-FS2692", "student", None, "+989035082692", "فاطمه شفیعی"),
            ("LIC-FH3501", "student", None, "+989930583501", "فاطمه محمد حسینی"),
            ("LIC-FN7828", "student", None, "+989136647828", "فاطمه نصیری"),
            ("LIC-MN2426", "student", None, "+989136152426", "مرجان نگارستانی"),
            ("LIC-MM3492", "student", None, "+989135063492", "خانم محتشم"),
            ("LIC-FA2352", "student", None, "+989134832352", "فاطمه انجم‌شعاع"),
            ("LIC-TEACHER-3659", "teacher", None, "+989397503659", "استاد دانایی"),
            ("LIC-DES-101", "designer", None, "", "طراح آموزشی اول"),
            ("LIC-DES-102", "designer", None, "", "طراح آموزشی دوم"),
        ]

        for i in range(1, 10):
            initial_users.append((f"SUPP-80{i}", "support", None, "", f"پشتیبان {i}"))
        initial_users.append(("SUPP-810", "support", None, "", "پشتیبان 10"))

        for i in range(1, 10):
            initial_users.append((f"LIC-FLEX-90{i}", "student", None, "", ""))
        initial_users.append(("LIC-FLEX-910", "student", None, "", ""))

        c.executemany("""
            INSERT OR IGNORE INTO licenses (license_id, role, telegram_id, phone, name)
            VALUES (?, ?, ?, ?, ?)
        """, initial_users)
        conn.commit()

def format_phone(phone: str) -> str:
    if not phone:
        return ""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0"):
        return "+98" + phone[1:]
    elif not phone.startswith("+"):
        return "+" + phone
    return phone

async def notify_students_new_content(bot_instance: Bot, term: str, session_num: str, content_type_fa: str):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM licenses WHERE role = 'student' AND telegram_id IS NOT NULL")
        students = c.fetchall()

    term_name = "ترم اول" if term == "term_1" else "ترم دوم"
    message_text = (
        f"📢 **محتوای جدید منتشر شد!**\n\n"
        f"📚 {term_name} - جلسه {session_num}\n"
        f"📌 نوع محتوا: {content_type_fa}\n\n"
        f"هم‌اکنون از طریق منوی «📚 دروس آموزش من» می‌توانید به این بخش دسترسی پیدا کنید. ✨"
    )

    for (stu_id,) in students:
        try:
            await bot_instance.send_message(chat_id=stu_id, text=message_text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

async def send_reminder_to_all(bot_instance: Bot, reminder_type: str):
    if reminder_type not in MESSAGES:
        return 0
    
    text = MESSAGES[reminder_type]
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM licenses WHERE role = 'student' AND telegram_id IS NOT NULL")
        students = c.fetchall()

    success_count = 0
    for (stu_id,) in students:
        try:
            await bot_instance.send_message(chat_id=stu_id, text=text, parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    return success_count

# ==================== وضعیت‌های مکالمه (FSM States) ====================
class AuthFlow(StatesGroup):
    waiting_for_phone = State()
    waiting_for_license = State()
    waiting_for_name = State()

class SupportFlow(StatesGroup):
    waiting_for_dept = State()
    waiting_for_message = State()

class ContentManagerFlow(StatesGroup):
    selecting_session = State()
    selecting_type = State()
    receiving_file = State()
    quiz_question = State()
    quiz_options = State()
    quiz_correct = State()
    quiz_explanation = State()
    descriptive_question = State()

class HomeworkFlow(StatesGroup):
    waiting_for_hw_file = State()

class BroadcastFlow(StatesGroup):
    waiting_for_message = State()

class AdminReplyFlow(StatesGroup):
    waiting_for_reply = State()

class HomeworkFeedbackFlow(StatesGroup):
    waiting_for_reason = State()

# ==================== احراز هویت ====================
@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    btn = KeyboardButton(text="📱 ارسال شماره تلفن جهت احراز هویت", request_contact=True)
    kb = ReplyKeyboardMarkup(keyboard=[[btn]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(
        "سلام! به سامانه جامع آموزشی خوش آمدید. 👋\n\nلطفاً برای شروع دکمه زیر را لمس کنید:",
        reply_markup=kb
    )
    await state.set_state(AuthFlow.waiting_for_phone)

@dp.message(AuthFlow.waiting_for_phone, F.contact)
async def get_phone(message: types.Message, state: FSMContext):
    if not message.contact:
        await message.answer("لطفاً از دکمه تعبیه‌شده برای ارسال شماره استفاده کنید.")
        return

    phone = format_phone(message.contact.phone_number)
    await state.update_data(phone=phone)
    await message.answer(
        f"شماره شما ({phone}) ثبت شد. ✅\nحالا لطفاً کد لایسنس خود را ارسال کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AuthFlow.waiting_for_license)

@dp.message(AuthFlow.waiting_for_license, F.text)
async def verify_license(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    user_id = message.from_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role, status, telegram_id, phone, name FROM licenses WHERE license_id = ?", (code,))
        row = c.fetchone()

        if not row:
            await message.answer("❌ کد لایسنس نامعتبر است. لطفاً مجدداً تلاش کنید:")
            return

        role, status, bound_tg, db_phone, name = row

        if bound_tg and bound_tg != user_id:
            await message.answer("❌ این لایسنس قبلاً به حساب شخص دیگری متصل شده است!")
            return

        if code.startswith("LIC-FLEX-") and not name:
            await state.update_data(license_code=code)
            await message.answer("کد تایید شد. ✅\nلطفاً نام و نام خانوادگی خود را ارسال کنید:")
            await state.set_state(AuthFlow.waiting_for_name)
            return

        if not db_phone or code.startswith("SUPP-") or code.startswith("LIC-DES-") or role in ["teacher", "support", "designer"]:
            c.execute("UPDATE licenses SET phone = COALESCE(NULLIF(phone,''), ?), telegram_id = ? WHERE license_id = ?", (phone, user_id, code))
            conn.commit()
            await message.answer(f"🔰 احراز هویت موفقیت‌آمیز!\nنقش شما: **{role}**", parse_mode="Markdown")
            await show_main_menu(message, role)
            await state.clear()
            return

        if format_phone(db_phone) == phone:
            c.execute("UPDATE licenses SET telegram_id = ? WHERE license_id = ?", (user_id, code))
            conn.commit()
            await message.answer(f"🌸 سلام {name} عزیز، خوش آمدید!\nنقش شما: **{role}**", parse_mode="Markdown")
            await show_main_menu(message, role)
            await state.clear()
        else:
            await message.answer("❌ شماره تلفن با این لایسنس مطابقت ندارد. مجدداً تلاش کنید:")

@dp.message(AuthFlow.waiting_for_name, F.text)
async def save_flex_student(message: types.Message, state: FSMContext):
    name = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    code = data.get("license_code")
    user_id = message.from_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("UPDATE licenses SET name = ?, phone = ?, telegram_id = ? WHERE license_id = ?", (name, phone, user_id, code))
        conn.commit()

    await message.answer(f"🌸 سلام {name} عزیز، پروفایل شما با موفقیت ثبت شد!")
    await show_main_menu(message, "student")
    await state.clear()

# ==================== منوهای اصلی ====================
async def show_main_menu(message: types.Message, role: str):
    if role == "student":
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👤 پروفایل من"), KeyboardButton(text="📚 دروس آموزش من")],
                [KeyboardButton(text="📤 ارسال تکالیف"), KeyboardButton(text="⭐ نظرسنجی و امتیازات")],
                [KeyboardButton(text="🏆 نفرات برتر"), KeyboardButton(text="📞 ارسال تیکت پشتیبانی")],
                [KeyboardButton(text="🤖 هوش مصنوعی")]
            ],
            resize_keyboard=True
        )
    elif role in ["designer", "teacher", "support"]:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📚 بارگذاری فایل یا طراحی آزمون جلسات")],
                [KeyboardButton(text="⚙️️ باز کردن دستی جلسات فراگیران"), KeyboardButton(text="🏆 نفرات برتر")],
                [KeyboardButton(text="📞 ارسال تیکت پشتیبانی"), KeyboardButton(text="🤖 هوش مصنوعی")]
            ],
            resize_keyboard=True
        )
        if role in ["teacher", "admin"]:
            kb.keyboard.insert(1, [KeyboardButton(text="👥 لیست فراگیران و امتیازات"), KeyboardButton(text="⏰ ارسال یادآوری‌ها")])
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="👥 لیست فراگیران و امتیازات"), KeyboardButton(text="🏆 نفرات برتر")],
                [KeyboardButton(text="📢 ارسال اطلاع‌‌رسانی همگانی"), KeyboardButton(text="⏰ ارسال یادآوری‌ها")],
                [KeyboardButton(text="📞 ارسال تیکت پشتیبانی"), KeyboardButton(text="🤖 هوش مصنوعی")]
            ],
            resize_keyboard=True
        )
    await message.answer("منوی اصلی سامانه:", reply_markup=kb)

# ==================== بخش نفرات برتر (Leaderboard) ====================
@dp.message(F.text == "🏆 نفرات برتر")
async def leaderboard_handler(message: types.Message):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT name, score FROM licenses WHERE role = 'student' ORDER BY score DESC LIMIT 10")
        top_students = c.fetchall()

    text = "🏆 **جدول نفرات برتر آکادمی** (بر اساس مجموع امتیازات)\n\n"
    if not top_students:
        text += "هنوز امتیازی ثبت نشده است."
    else:
        medals = ["🥇", "🥈", "🥉"]
        for idx, (name, score) in enumerate(top_students, 1):
            badge = medals[idx - 1] if idx <= 3 else f"{idx}."
            display_name = name if name else "فراگیر"
            text += f"{badge} **{display_name}** — {score} امتیاز\n"

    await message.answer(text, parse_mode="Markdown")

# ==================== بخش لیست فراگیران و امتیازات (مختص کادر) ====================
@dp.message(F.text == "👥 لیست فراگیران و امتیازات")
async def students_list_handler(message: types.Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()

    if not res or res[0] not in ["teacher", "admin"]:
        await message.answer("❌ شما دسترسی به این بخش ندارید.")
        return

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT name, phone, score, license_id FROM licenses WHERE role = 'student'")
        students = c.fetchall()

    text = "👥 **لیست فراگیران و امتیازات آن‌ها:**\n\n"
    for idx, (name, phone, score, lic) in enumerate(students, 1):
        display_name = name if name else "ثبت‌نشده"
        display_phone = phone if phone else "بدون شماره"
        text += f"{idx}. **{display_name}** | {display_phone} | امتیاز: {score}\n"

    await message.answer(text, parse_mode="Markdown")

# ==================== بخش ارسال اطلاع‌رسانی همگانی ====================
@dp.message(F.text == "📢 ارسال اطلاع‌‌رسانی همگانی")
async def broadcast_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()

    if not res or res[0] not in ["teacher", "admin"]:
        await message.answer("❌ شما دسترسی به این بخش ندارید.")
        return

    await message.answer("📢 لطفاً متن اطلاع‌رسانی همگانی خود را برای ارسال به تمامی کاربران ارسال کنید:")
    await state.set_state(BroadcastFlow.waiting_for_message)

@dp.message(BroadcastFlow.waiting_for_message)
async def broadcast_send(message: types.Message, state: FSMContext):
    text = message.text
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM licenses WHERE telegram_id IS NOT NULL")
        users = c.fetchall()

    success = 0
    for (uid,) in users:
        try:
            await bot.send_message(chat_id=uid, text=f"📢 **اطلاع‌رسانی مهم:**\n\n{text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await state.clear()
    await message.answer(f"✅ پیام همگانی با موفقیت به **{success}** کاربر ارسال شد.")

# ==================== بخش نظرسنجی و امتیازات تشویقی ====================
@dp.message(F.text == "⭐ نظرسنجی و امتیازات")
async def survey_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ترم اول (۲۶ جلسه)", callback_data="survey_term_term_1"),
         InlineKeyboardButton(text="ترم دوم (۶۰ جلسه)", callback_data="survey_term_term_2")]
    ])
    await message.answer("⭐ **بخش نظرسنجی بات**\n\nبرای ثبت نظر درباره هر جلسه و دریافت **۵ امتیاز تشویقی**، ترم مربوطه را انتخاب کنید:", reply_markup=kb)

@dp.callback_query(F.data.startswith("survey_term_"))
async def survey_select_session(callback: types.CallbackQuery):
    term = callback.data.replace("survey_term_", "")
    max_sessions = 26 if term == "term_1" else 60
    
    kb = []
    row = []
    for i in range(1, max_sessions + 1):
        row.append(InlineKeyboardButton(text=f"جلسه {i}", callback_data=f"surv_sess_{term}_{i}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    await callback.message.edit_text("جلسه مورد نظر جهت ثبت نظرسنجی را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("surv_sess_"))
async def survey_options_callback(callback: types.CallbackQuery):
    _, _, term, session = callback.data.split("_")
    session_id = f"{term}_l{session}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤩 عالی (چرا عالی بود؟)", callback_data=f"rate_{session_id}_great")],
        [InlineKeyboardButton(text="😊 خوب (چرا خوب بود؟)", callback_data=f"rate_{session_id}_good")],
        [InlineKeyboardButton(text="😐 متوسط (چرا متوسط؟)", callback_data=f"rate_{session_id}_medium")]
    ])
    await callback.message.edit_text(f"نظر شما درباره جلسه {session} ({term}) چیست؟\n(ثبت نظر معادل ۵ امتیاز هدیه است):", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("rate_"))
async def save_survey_rating(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    term = parts[1]
    session_num = parts[2]
    session_id = f"{term}_{session_num}"
    rating = parts[3]
    user_id = callback.from_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM surveys WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        if c.fetchone():
            await callback.answer("⚠️ شما قبلاً برای این جلسه نظرسنجی را ثبت کرده‌اید و امتیاز آن را دریافت کرده‌اید.", show_alert=True)
            return

        c.execute("INSERT INTO surveys (user_id, session_id, rating) VALUES (?, ?, ?)", (user_id, session_id, rating))
        c.execute("UPDATE licenses SET score = score + 5 WHERE telegram_id = ?", (user_id,))
        conn.commit()

    await callback.message.edit_text("✅ نظر شما با موفقیت ثبت شد!\n🎁 **۵ امتیاز** به حساب شما اضافه شد. سپاس از بازخورد سازنده شما 🙏")
    await callback.answer()

# ==================== بخش باز کردن دستی جلسات توسط کادر ====================
@dp.message(F.text == "⚙️ باز کردن دستی جلسات فراگیران")
async def manual_unlock_menu(message: types.Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()

    if not res or res[0] not in ["teacher", "designer", "support", "admin"]:
        await message.answer("❌ شما دسترسی به این بخش ندارید.")
        return

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id, name, license_id FROM licenses WHERE role = 'student' AND telegram_id IS NOT NULL")
        students = c.fetchall()

    if not students:
        await message.answer("⚠ هیچ فراگیر فعال متصل به تلگرامی یافت نشد.")
        return

    kb = []
    for stu_tg, name, lic in students:
        display_name = name if name else lic
        kb.append([InlineKeyboardButton(text=f"👤 {display_name}", callback_data=f"unlock_stu_{stu_tg}")])

    await message.answer("⚙️ **بخش باز کردن دستی جلسات**\n\nفراگیر مورد نظر خود را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("unlock_stu_"))
async def unlock_select_term(callback: types.CallbackQuery):
    stu_tg = callback.data.split("_")[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ترم اول (۲۶ جلسه)", callback_data=f"unlock_t_{stu_tg}_term_1"),
         InlineKeyboardButton(text="ترم دوم (۶۰ جلسه)", callback_data=f"unlock_t_{stu_tg}_term_2")]
    ])
    await callback.message.edit_text("ترم مورد نظر برای باز کردن جلسات را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("unlock_t_"))
async def unlock_select_session_count(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    stu_tg = parts[2]
    term = f"{parts[3]}_{parts[4]}"
    
    max_sessions = 26 if term == "term_1" else 60
    kb = []
    row = []
    for i in range(1, max_sessions + 1):
        row.append(InlineKeyboardButton(text=f"جلسه {i}", callback_data=f"do_unlock_{stu_tg}_{term}_{i}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    await callback.message.edit_text("تا چه جلسه‌ای باید برای این فراگیر باز شود؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("do_unlock_"))
async def apply_manual_unlock(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    stu_tg = int(parts[2])
    term = f"{parts[3]}_{parts[4]}"
    session_num = int(parts[5])
    
    allowed_session = session_num + 1

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO student_progress (user_id, term, max_allowed_session)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, term) DO UPDATE SET max_allowed_session = MAX(max_allowed_session, ?)
        """, (stu_tg, term, allowed_session, allowed_session))
        conn.commit()

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM licenses WHERE telegram_id = ?", (stu_tg,))
        res = c.fetchone()
        stu_name = res[0] if res and res[0] else "فراگیر"

    await callback.message.edit_text(f"✅ با موفقیت جلسات تا جلسه شماره {session_num} برای **{stu_name}** باز شد.")
    try:
        term_fa = "ترم اول" if term == "term_1" else "ترم دوم"
        await bot.send_message(
            chat_id=stu_tg,
            text=f"🎉 **خبر خوب!**\n\nتوسط کادر آموزشی، دسترسی شما تا **جلسه {session_num}** در {term_fa} به صورت دستی باز شد. 🚀",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await callback.answer()

# ==================== بخش یادآوری‌ها ====================
@dp.message(F.text == "⏰ ارسال یادآوری‌ها")
async def reminders_menu(message: types.Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()

    if not res or res[0] not in ["teacher", "admin"]:
        await message.answer("❌ شما دسترسی به این بخش ندارید.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 ارسال یادآوری کوییز", callback_data="remind_quiz")],
        [InlineKeyboardButton(text="📚 ارسال یادآوری تمرین", callback_data="remind_practice")],
        [InlineKeyboardButton(text="☀ ارسال چک‌‌این صبحگاهی", callback_data="remind_morning_check")]
    ])
    await message.answer("⏰ لطفاً نوع پیام یادآوری جهت ارسال به تمام فراگیران را انتخاب کنید:", reply_markup=kb)

@dp.callback_query(F.data.startswith("remind_"))
async def trigger_reminder_callback(callback: types.CallbackQuery):
    remind_type = callback.data.replace("remind_", "")
    if remind_type not in MESSAGES:
        await callback.answer("نوع یادآوری نامعتبر است.", show_alert=True)
        return

    await callback.message.edit_text("⏳ در حال ارسال یادآوری به فراگیران...")
    count = await send_reminder_to_all(bot, remind_type)
    await callback.message.answer(f"✅ یادآوری مورد نظر با موفقیت به **{count}** فراگیر ارسال شد.")
    await callback.answer()

# ==================== پروفایل من & QR کد ====================
@dp.message(F.text == "👤 پروفایل من")
async def profile_handler(message: types.Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT license_id, name, phone, score FROM licenses WHERE telegram_id = ?", (user_id,))
        info = c.fetchone()

    if not info:
        await message.answer("❌ اطلاعاتی یافت نشد.")
        return

    lic_id, name, phone, score = info
    text = (
        f"👤 **پروفایل کاربری**\n\n"
        f"▫️ نام و نام خانوادگی: {name}\n"
        f"▫ شماره تماس: {phone}\n"
        f"▫️ لایسنس: {lic_id}\n"
        f"🏆 امتیاز کل: {score}\n\n"
        f"🆔 شناسه حضور و غیاب شما روی QR کد درج شده است."
    )
    await message.answer(text, parse_mode="Markdown")

    qr_img = qrcode.make(f"STU-ID:{user_id}")
    bio = io.BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)
    await message.answer_photo(photo=BufferedInputFile(bio.read(), filename="qr.png"), caption="🔲 کد QR اختصاصی شما")

# ==================== ارسال تکالیف ====================
@dp.message(F.text == "📤 ارسال تکالیف")
async def homework_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ترم اول (۲۶ جلسه)", callback_data="hw_term_1"),
         InlineKeyboardButton(text="ترم دوم (۶۰ جلسه)", callback_data="hw_term_2")]
    ])
    await message.answer("📤 بخش ارسال تکالیف (هر تکلیف معادل **۱۰ امتیاز**):\nترم مورد نظر را انتخاب کنید:", reply_markup=kb)

@dp.callback_query(F.data.startswith("hw_term_"))
async def hw_sessions_list(callback: types.CallbackQuery):
    term = callback.data.split("_")[2]
    total_sessions = 26 if term == "1" else 60
    
    keyboard = []
    row = []
    for i in range(1, total_sessions + 1):
        row.append(InlineKeyboardButton(text=f"جلسه {i}", callback_data=f"select_hw_t{term}_l{i}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="student_homework_back")])
    await callback.message.edit_text(f"📤 ارسال تکلیف - ترم {term}\nجلسه مورد نظر را جهت ارسال فایل انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data.startswith("select_hw_"))
async def ask_for_hw_file(callback: types.CallbackQuery, state: FSMContext):
    session_id = callback.data.replace("select_hw_", "")
    await state.update_data(uploading_hw_for=session_id)
    await state.set_state(HomeworkFlow.waiting_for_hw_file)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ انصراف", callback_data="hw_term_1")]])
    await callback.message.edit_text(
        f"📎 لطفاً فایل تکلیف خود را برای {session_id.replace('t', 'ترم ').replace('_l', ' جلسه ')} ارسال کنید.",
        reply_markup=kb
    )
    await callback.answer()

@dp.message(HomeworkFlow.waiting_for_hw_file, F.content_type.in_({'document', 'photo', 'audio', 'voice'}))
async def handle_hw_upload(message: types.Message, state: FSMContext):
    data = await state.get_data()
    session_id = data.get('uploading_hw_for')
    if not session_id:
        return
    
    user_id = message.from_user.id
    file_id = message.document.file_id if message.document else (message.photo[-1].file_id if message.photo else (message.audio.file_id if message.audio else message.voice.file_id))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()
        user_name = res[0] if res and res[0] else f"کاربر {user_id}"

        c.execute("SELECT 1 FROM student_homeworks WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        already_sent = c.fetchone()

        c.execute("""
            INSERT INTO student_homeworks (user_id, session_id, file_id)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, session_id) DO UPDATE SET file_id = ?
        """, (user_id, session_id, file_id, file_id))

        if not already_sent:
            c.execute("UPDATE licenses SET score = score + 10 WHERE telegram_id = ?", (user_id,))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ تکلیف جلسه ({session_id}) با موفقیت ثبت شد.\n➕ **۱۰ امتیاز** تکلیف به حساب شما واریز شد! 🎯")

    # ارسال خودکار تکلیف به کانال/گروه اختصاصی تکالیف برای بررسی استاد/طراح/پشتیبان
    hw_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید و واریز امتیاز", callback_data=f"hw_ok_{user_id}_{session_id}"),
         InlineKeyboardButton(text="🔄 نیاز به اصلاح", callback_data=f"hw_rev_{user_id}_{session_id}")]
    ])
    try:
        await bot.send_message(
            chat_id=HOMEWORK_CHANNEL_ID,
            text=f"📥 **تکلیف جدید دریافت شد!**\n\n👤 فراگیر: {user_name} (ID: `{user_id}`)\n📌 جلسه: {session_id}",
            parse_mode="Markdown"
        )
        await bot.copy_message(
            chat_id=HOMEWORK_CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=hw_kb
        )
    except Exception:
        pass

@dp.callback_query(F.data.startswith("hw_ok_"))
async def hw_approve_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    session_id = parts[3]

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ تکلیف کاربر `{user_id}` تایید شد.")
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"🎉 **تکلیف شما تایید شد!**\n\nاستاد تکلیف شما را برای {session_id} تایید کرد. عالی پیش می‌روید! 🌟",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("hw_rev_"))
async def hw_revision_callback(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    user_id = int(parts[2])
    session_id = parts[3]

    await state.update_data(rev_user_id=user_id, rev_session_id=session_id, original_msg_id=callback.message.message_id)
    await state.set_state(HomeworkFeedbackFlow.waiting_for_reason)
    await callback.message.answer("✍ لطفاً دلیل نیاز به اصلاح یا بازخورد خود را به صورت متن یا ویس ارسال کنید تا برای فراگیر ارسال شود:")
    await callback.answer()

@dp.message(HomeworkFeedbackFlow.waiting_for_reason)
async def send_hw_revision_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("rev_user_id")
    session_id = data.get("rev_session_id")

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"🔄 **تکلیف شما نیاز به اصلاح دارد ({session_id}):**\n\nمتن/بازخورد استاد:"
        )
        await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.answer("✅ بازخورد و درخواست اصلاحیه با موفقیت به فراگیر ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال بازخورد: {e}")

    await state.clear()

# ==================== مدیریت محتوا و آزمون‌ها ====================
@dp.message(F.text == "📚 بارگذاری فایل یا طراحی آزمون جلسات")
async def start_content_manager(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT role FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()

    if not res or res[0] not in ["designer", "teacher", "support"]:
        await message.answer("❌ شما دسترسی به این بخش ندارید.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ترم اول — ۲۶ جلسه", callback_data="cm_term_term_1"),
         InlineKeyboardButton(text="ترم دوم — ۶۰ جلسه", callback_data="cm_term_term_2")]
    ])
    await message.answer("محیط مدیریت محتوا و طراحی آزمون\nلطفاً ترم مورد نظر را انتخاب کنید:", reply_markup=kb)
    await state.set_state(ContentManagerFlow.selecting_session)

@dp.callback_query(ContentManagerFlow.selecting_session, F.data.startswith("cm_term_"))
async def cm_select_term(callback: types.CallbackQuery, state: FSMContext):
    term = callback.data.replace("cm_term_", "")
    await state.update_data(term=term)
    max_sessions = 26 if term == "term_1" else 60

    kb = []
    row = []
    for i in range(1, max_sessions + 1):
        row.append(InlineKeyboardButton(text=f"جلسه {i}", callback_data=f"cmsess_{i}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    await callback.message.edit_text(f"ترم انتخابی: {term}\nلطفاً جلسه مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(ContentManagerFlow.selecting_session, F.data.startswith("cmsess_"))
async def cm_select_session(callback: types.CallbackQuery, state: FSMContext):
    session_num = callback.data.split("_")[1]
    await state.update_data(session=session_num)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 صوت آموزشی", callback_data="ctype_audio"),
         InlineKeyboardButton(text="📄 فایل آموزشی", callback_data="ctype_file")],
        [InlineKeyboardButton(text="📝 آزمون ۴ گزینه‌ای", callback_data="ctype_quiz_4opt"),
         InlineKeyboardButton(text="⚖️ آزمون درست/غلط", callback_data="ctype_quiz_tf")],
        [InlineKeyboardButton(text="✍️ آزمون تشریحی", callback_data="ctype_desc")]
    ])
    await callback.message.edit_text(f"جلسه {session_num} - نوع محتوا یا آزمون را انتخاب کنید:", reply_markup=kb)
    await state.set_state(ContentManagerFlow.selecting_type)

@dp.callback_query(ContentManagerFlow.selecting_type, F.data.startswith("ctype_"))
async def cm_select_type(callback: types.CallbackQuery, state: FSMContext):
    ctype = callback.data.replace("ctype_", "")
    await state.update_data(content_type=ctype)

    if ctype in ["audio", "file"]:
        await callback.message.edit_text("لطفاً فایل یا صوت مربوطه را ارسال کنید:")
        await state.set_state(ContentManagerFlow.receiving_file)
    elif ctype == "quiz_4opt":
        await callback.message.edit_text("📝 **طراحی آزمون ۴ گزینه‌ای**\n\nلطفاً متن سوال را ارسال کنید:")
        await state.set_state(ContentManagerFlow.quiz_question)
    elif ctype == "quiz_tf":
        await callback.message.edit_text("⚖ **طراحی آزمون درست/غلط**\n\nلطفاً متن سوال درست/غلط را ارسال کنید:")
        await state.set_state(ContentManagerFlow.quiz_question)
    elif ctype == "desc":
        await callback.message.edit_text("✍️ **طراحی آزمون تشریحی**\n\nلطفاً متن سوال تشریحی را ارسال کنید:")
        await state.set_state(ContentManagerFlow.descriptive_question)
    await callback.answer()

@dp.message(ContentManagerFlow.receiving_file, F.content_type.in_({'document', 'audio', 'voice', 'video'}))
async def cm_save_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    term = data.get("term")
    session_num = data.get("session")
    ctype = data.get("content_type")

    file_id = message.document.file_id if message.document else (message.audio.file_id if message.audio else (message.voice.file_id if message.voice else message.video.file_id))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value)
            VALUES (?, ?, ?, ?)
        """, (term, session_num, ctype, file_id))
        conn.commit()

    type_fa = "فایل آموزشی" if ctype == "file" else "صوت آموزشی"
    await message.answer(f"✅ فایل مربوط به جلسه {session_num} ذخیره و برای فراگیران فعال شد!")
    await notify_students_new_content(bot, term, session_num, type_fa)
    await state.clear()

@dp.message(ContentManagerFlow.quiz_question, F.text)
async def cm_receive_quiz_q(message: types.Message, state: FSMContext):
    await state.update_data(quiz_question=message.text)
    data = await state.get_data()
    if data.get("content_type") == "quiz_tf":
        await message.answer("گزینه صحیح را مشخص کنید:\n1. درست\n2. نادرست\n(فقط شماره 1 یا 2 را بفرستید)")
        await state.set_state(ContentManagerFlow.quiz_correct)
    else:
        await message.answer(
            "گزینه‌ها را وارد کنید و با علامت (|) از هم جدا سازید:\n"
            "مثال: گزینه اول | گزینه دوم | گزینه سوم | گزینه چهارم"
        )
        await state.set_state(ContentManagerFlow.quiz_options)

@dp.message(ContentManagerFlow.quiz_options, F.text)
async def cm_receive_quiz_opts(message: types.Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.split("|")]
    if len(options) < 2:
        await message.answer("حداقل ۲ گزینه لازم است. دوباره تلاش کنید:")
        return

    await state.update_data(quiz_options=options)
    msg = "شماره گزینه درست را مشخص کنید (به عدد):\n"
    for idx, opt in enumerate(options, 1):
        msg += f"{idx}. {opt}\n"
    await message.answer(msg)
    await state.set_state(ContentManagerFlow.quiz_correct)

@dp.message(ContentManagerFlow.quiz_correct, F.text)
async def cm_receive_quiz_correct(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get("content_type")

    if ctype == "quiz_tf":
        val = message.text.strip()
        if val not in ["1", "2"]:
            await message.answer("لطفاً فقط عدد 1 (درست) یا 2 (نادرست) را ارسال کنید:")
            return
        correct_idx = 0 if val == "1" else 1
        options = ["درست", "نادرست"]
        await state.update_data(quiz_options=options, correct_idx=correct_idx)
    else:
        try:
            correct_idx = int(message.text.strip()) - 1
            options = data.get("quiz_options")
            if correct_idx < 0 or correct_idx >= len(options):
                raise ValueError()
        except ValueError:
            await message.answer("عدد نامعتبر است. شماره گزینه صحیح را وارد کنید:")
            return
        await state.update_data(correct_idx=correct_idx)

    await message.answer("💡 حالا **توضیح پاسخ (دلیل درست بودن جواب)** را بنویسید تا اگر فراگیر اشتباه پاسخ داد، ربات به او نمایش دهد:")
    await state.set_state(ContentManagerFlow.quiz_explanation)

@dp.message(ContentManagerFlow.quiz_explanation, F.text)
async def cm_save_quiz_final(message: types.Message, state: FSMContext):
    explanation = message.text.strip()
    data = await state.get_data()
    
    term = data.get("term")
    session_num = data.get("session")
    question = data.get("quiz_question")
    options = data.get("quiz_options")
    correct_idx = data.get("correct_idx")
    opts_str = "|||".join(options)

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value) VALUES (?, ?, 'quiz_q', ?)", (term, session_num, question))
        c.execute("INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value) VALUES (?, ?, 'quiz_opts', ?)", (term, session_num, opts_str))
        c.execute("INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value) VALUES (?, ?, 'quiz_correct', ?)", (term, session_num, str(correct_idx)))
        c.execute("INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value) VALUES (?, ?, 'quiz_exp', ?)", (term, session_num, explanation))
        conn.commit()

    await message.answer(f"✅ آزمون جلسه {session_num} ثبت و در سیستم فعال شد!")
    await notify_students_new_content(bot, term, session_num, "آزمون جدید 📝")
    await state.clear()

@dp.message(ContentManagerFlow.descriptive_question, F.text)
async def cm_save_descriptive_final(message: types.Message, state: FSMContext):
    q_text = message.text.strip()
    data = await state.get_data()
    term = data.get("term")
    session_num = data.get("session")

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO session_contents (term, session_number, content_type, content_value) VALUES (?, ?, 'desc_q', ?)", (term, session_num, q_text))
        conn.commit()

    await message.answer(f"✅ سوال تشریحی جلسه {session_num} ثبت و برای فراگیران فعال شد!")
    await notify_students_new_content(bot, term, session_num, "آزمون تشریحی ✍️")
    await state.clear()

# ==================== بخش دروس آموزش من & آزمون‌ها برای فراگیر ====================
@dp.message(F.text == "📚 دروس آموزش من")
async def student_courses_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ترم اول (۲۶ جلسه)", callback_data="stu_term_term_1"),
         InlineKeyboardButton(text="ترم دوم (۶۰ جلسه)", callback_data="stu_term_term_2")]
    ])
    user_id = message.from_user.id
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT score FROM licenses WHERE telegram_id = ?", (user_id,))
        res = c.fetchone()
        score = res[0] if res else 0

    await message.answer(
        f"📚 دروس آموزش من\n"
        f"🏆 امتیاز فعلی شما: {score} امتیاز\n\n"
        f"یکی از ترم‌های زیر را انتخاب کنید:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("stu_term_"))
async def student_show_sessions(callback: types.CallbackQuery):
    term = callback.data.replace("stu_term_", "")
    user_id = callback.from_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT max_allowed_session FROM student_progress WHERE user_id = ? AND term = ?", (user_id, term))
        res = c.fetchone()
        allowed = res[0] if res else 1

    max_sessions = 26 if term == "term_1" else 60
    kb = []
    row = []
    for s in range(1, max_sessions + 1):
        if s <= allowed:
            row.append(InlineKeyboardButton(text=f"🟢 {s}", callback_data=f"sview_{term}_{s}"))
        else:
            row.append(InlineKeyboardButton(text=f"🔒 {s}", callback_data=f"slocked_{s}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    await callback.message.edit_text(f"محتوای ترم {term[-1]} (جلسات باز با 🟢 مشخص شده‌اند):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("slocked_"))
async def student_locked_click(callback: types.CallbackQuery):
    await callback.answer("🔒 این جلسه قفل است! شرط ورود به جلسه بعد کسب حداقل ۲۰ امتیاز از تکلیف و آزمون یا بازگشایی توسط استاد است.", show_alert=True)

@dp.callback_query(F.data.startswith("sview_"))
async def student_session_options(callback: types.CallbackQuery):
    _, term, session = callback.data.split("_")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 صوت", callback_data=f"get_{term}_{session}_audio"),
         InlineKeyboardButton(text="📄 فایل", callback_data=f"get_{term}_{session}_file")],
        [InlineKeyboardButton(text="📝 شرکت در آزمون تستی (۱۰ امتیاز)", callback_data=f"get_{term}_{session}_quiz")],
        [InlineKeyboardButton(text="✍ پاسخ به آزمون تشریحی", callback_data=f"get_{term}_{session}_desc")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"stu_term_{term}")]
    ])
    await callback.message.edit_text(f"ترم {term[-1]} - جلسه {session}\nمحتوای مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("get_"))
async def student_get_content(callback: types.CallbackQuery):
    _, term, session, ctype = callback.data.split("_")
    user_id = callback.from_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        if ctype == "quiz":
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'quiz_q'", (term, session))
            q_row = c.fetchone()
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'quiz_opts'", (term, session))
            opts_row = c.fetchone()
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'quiz_correct'", (term, session))
            corr_row = c.fetchone()
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'quiz_exp'", (term, session))
            exp_row = c.fetchone()

            if not q_row or not opts_row or not corr_row:
                await callback.answer("آزمون تستی برای این جلسه ثبت نشده است.", show_alert=True)
                return

            await callback.answer()
            explanation_text = exp_row[0] if exp_row else "پاسخ صحیح بود."
            
            msg = await bot.send_poll(
                chat_id=callback.message.chat_id,
                question=q_row[0],
                options=opts_row[0].split("|||"),
                type=types.PollType.QUIZ,
                correct_option_id=int(corr_row[0]),
                is_anonymous=False,
                explanation=explanation_text
            )
            poll_tracker[msg.poll.id] = {"user_id": user_id, "term": term, "session": int(session)}
        elif ctype == "desc":
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'desc_q'", (term, session))
            q_row = c.fetchone()
            if not q_row:
                await callback.answer("سوال تشریحی برای این جلسه ثبت نشده است.", show_alert=True)
                return
            await callback.answer()
            await callback.message.answer(f"✍️ **سوال تشریحی جلسه {session}:**\n\n{q_row[0]}\n\nلطفاً پاسخ خود را به صورت متن ارسال کنید:")
        else:
            c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = ?", (term, session, ctype))
            row = c.fetchone()
            if row and row[0]:
                await callback.answer("در حال ارسال...")
                await bot.send_document(chat_id=callback.message.chat_id, document=row[0])
            else:
                await callback.answer("محتوایی بارگذاری نشده است.", show_alert=True)

@dp.poll_answer()
async def handle_poll_answer(answer: types.PollAnswer):
    poll_id = answer.poll_id
    if poll_id not in poll_tracker:
        return

    info = poll_tracker[poll_id]
    user_id = answer.user.id
    selected = answer.option_ids[0]
    term = info["term"]
    session = info["session"]

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT content_value FROM session_contents WHERE term = ? AND session_number = ? AND content_type = 'quiz_correct'", (term, session))
        row = c.fetchone()

    if row and selected == int(row[0]):
        next_sess = session + 1
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO student_progress (user_id, term, max_allowed_session)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, term) DO UPDATE SET max_allowed_session = MAX(max_allowed_session, ?)
            """, (user_id, term, next_sess, next_sess))
            
            c.execute("UPDATE licenses SET score = score + 10 WHERE telegram_id = ?", (user_id,))
            conn.commit()

        await bot.send_message(chat_id=user_id, text=f"🎉 عالی! پاسخ شما کاملاً صحیح بود.\n➕ **۱۰ امتیاز** آزمون به شما تعلق گرفت.\n🟢 جلسه {next_sess} برای شما باز شد!")
        del poll_tracker[poll_id]
    else:
        await bot.send_message(chat_id=user_id, text="❌ پاسخ شما اشتباه بود.\n💡 نگران نباش! توضیح پاسخ را مطالعه کن و دوباره تلاش کن تا به جواب درست برسی و امتیاز کامل را بگیری.")

# ==================== تیکت‌ها و پشتیبانی ====================
@dp.message(F.text == "📞 ارسال تیکت پشتیبانی")
async def support_start(message: types.Message, state: FSMContext):
    builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 پشتیبانی فنی", callback_data="dept_tech"),
         InlineKeyboardButton(text="📚 پشتیبانی آموزشی", callback_data="dept_edu")]
    ])
    await message.answer("دپارتمان مورد نظر را انتخاب کنید:", reply_markup=builder)
    await state.set_state(SupportFlow.waiting_for_dept)

@dp.callback_query(F.data.startswith("dept_"))
async def dept_chosen(callback: types.CallbackQuery, state: FSMContext):
    dept = "فنی" if callback.data == "dept_tech" else "آموزشی"
    await state.update_data(dept=dept)
    await callback.message.edit_text(f"بخش انتخابی: {dept}\n\nپیام خود را ارسال کنید:")
    await state.set_state(SupportFlow.waiting_for_message)
    await callback.answer()

@dp.message(SupportFlow.waiting_for_message)
async def submit_ticket(message: types.Message, state: FSMContext):
    data = await state.get_data()
    dept = data.get("dept", "عمومی")
    user = message.from_user

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO tickets (user_id, department) VALUES (?, ?)", (user.id, dept))
        ticket_id = c.lastrowid
        conn.commit()

    await message.answer(f"✅ تیکت شما با شماره #{ticket_id} ثبت شد.")
    await state.clear()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ پاسخ", callback_data=f"adm_reply_{ticket_id}"),
         InlineKeyboardButton(text="🔒 بستن", callback_data=f"adm_close_{ticket_id}")]
    ])
    try:
        await bot.send_message(chat_id=SUPPORT_GROUP_ID, text=f"📩 تیکت جدید: #{ticket_id}\nکاربر: {user.id}\nدپارتمان: {dept}")
        await bot.copy_message(chat_id=SUPPORT_GROUP_ID, from_chat_id=message.chat.id, message_id=message.message_id, reply_markup=admin_kb)
    except Exception:
        pass

@dp.callback_query(F.data.startswith("adm_reply_"))
async def admin_reply_start(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = callback.data.replace("adm_reply_", "")
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
        row = c.fetchone()
    
    if not row:
        await callback.answer("تیکت یافت نشد.", show_alert=True)
        return

    await state.update_data(reply_to_user=row[0], ticket_id=ticket_id)
    await callback.message.answer(f"✍ لطفاً پاسخ خود را برای تیکت #{ticket_id} ارسال کنید:")
    await state.set_state(AdminReplyFlow.waiting_for_reply)
    await callback.answer()

@dp.message(AdminReplyFlow.waiting_for_reply)
async def admin_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_user = data.get("reply_to_user")
    ticket_id = data.get("ticket_id")

    try:
        await bot.send_message(chat_id=target_user, text=f"💬 **پاسخ پشتیبانی برای تیکت #{ticket_id}:**\n\n{message.text}")
        await message.answer(f"✅ پاسخ شما با موفقیت به کاربر ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ خطا در ارسال پاسخ به کاربر: {e}")

    await state.clear()

@dp.callback_query(F.data.startswith("adm_close_"))
async def admin_close_ticket(callback: types.CallbackQuery):
    ticket_id = callback.data.replace("adm_close_", "")
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        conn.commit()

    await callback.message.edit_text(f"{callback.message.text}\n\n🔒 **تیکت بسته شد.**")
    await callback.answer()

# ==================== هوش مصنوعی ====================
@dp.message(F.text == "🤖 هوش مصنوعی")
async def ai_menu_handler(message: types.Message):
    ai_users.add(message.from_user.id)
    coze_chats.pop(message.from_user.id, None)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ خروج از هوش مصنوعی", callback_data="exit_ai")]])
    await message.answer("🤖 وارد بخش هوش مصنوعی شدید. سؤالی بپرسید:", reply_markup=kb)

@dp.callback_query(F.data == "exit_ai")
async def exit_ai_handler(callback: types.CallbackQuery):
    ai_users.discard(callback.from_user.id)
    coze_chats.pop(callback.from_user.id, None)
    await callback.message.edit_text("✅ از هوش مصنوعی خارج شدید.")
    await callback.answer()

def ask_coze(user_id, text):
    headers = {"Authorization": f"Bearer {COZE_TOKEN}", "Content-Type": "application/json"}
    conv_id = coze_chats.get(user_id)
    payload = {
        "bot_id": COZE_BOT_ID,
        "user_id": str(user_id),
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": text, "content_type": "text"}]
    }
    if conv_id:
        payload["conversation_id"] = conv_id
    try:
        res = requests.post(COZE_API_URL, headers=headers, json=payload, timeout=60)
        if res.status_code != 200:
            return None, f"خطای سرور: {res.status_code}"
        data = res.json()
        if data.get("conversation_id"):
            coze_chats[user_id] = data["conversation_id"]
        for msg in data.get("messages", []):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg.get("content"), None
        return None, "پاسخی یافت نشد."
    except Exception as e:
        return None, str(e)

@dp.message(F.text & ~F.command)
async def ai_text_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ai_users:
        return
    wait_msg = await message.reply("🤖 در حال پردازش...")
    answer, error = await asyncio.to_thread(ask_coze, user_id, message.text)
    if error:
        await wait_msg.edit_text(f"⚠ خطا: {error}")
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ خروج از هوش مصنوعی", callback_data="exit_ai")]])
        await wait_msg.edit_text(answer, reply_markup=kb)

# ==================== راه‌‌اندازی ربات ====================
async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    print(f"ربات جامع آکادمی @{me.username} با موفقیت اجرا شد!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
