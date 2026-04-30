import asyncio
import logging
import aiohttp
import sqlite3
import hashlib
import hmac
import json
import os
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command

# ================== SOZLAMALAR ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "8332077004"))
except ValueError:
    raise RuntimeError("ADMIN_ID faqat raqam bo'lishi kerak. Masalan: 8332077004")

MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID", "@Azizbekl2026").strip()

# ================== CHECKOUT.UZ SOZLAMALARI ==================
CHECKOUT_API_KEY = os.getenv("CHECKOUT_API_KEY", "").strip()
CHECKOUT_BASE_URL = os.getenv("CHECKOUT_BASE_URL", "https://checkout.uz/api/v1").strip()

if not BOT_TOKEN:
    print("❌ BOT_TOKEN topilmadi.", flush=True)
    print("Fly.io → App → Secrets bo'limiga BOT_TOKEN qo'shing.", flush=True)
    print('Terminal orqali: fly secrets set BOT_TOKEN="YANGI_TOKEN" ADMIN_ID="8332077004" MAIN_CHANNEL_ID="@Azizbekl2026"', flush=True)
    print("Secret qo'shilgach appni Restart qiling yoki fly deploy ishga tushiring.", flush=True)

# ================== SQLite BAZA ==================
DB_PATH = os.getenv("DB_PATH", "/data/bot_database.db")


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        join_date TEXT DEFAULT '',
        posted_ads INTEGER DEFAULT 0,
        paid_slots INTEGER DEFAULT 0,
        pending_approval INTEGER DEFAULT 0,
        free_ad_used INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT NOT NULL,
        url TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        video_id TEXT,
        text TEXT,
        status TEXT DEFAULT 'pending'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS uc_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uc_amount INTEGER UNIQUE,
        price INTEGER,
        position INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS uc_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        full_name TEXT,
        username TEXT,
        uc_amount INTEGER,
        price INTEGER,
        pubg_id TEXT,
        screenshot_id TEXT,
        status TEXT DEFAULT 'pending',
        payment_method TEXT DEFAULT 'manual',
        payment_id INTEGER DEFAULT 0,
        order_date TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stars_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stars_amount INTEGER UNIQUE,
        price INTEGER,
        position INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stars_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        full_name TEXT,
        username TEXT,
        stars_amount INTEGER,
        price INTEGER,
        target_type TEXT DEFAULT 'me',
        target_username TEXT DEFAULT '',
        receipt_id TEXT,
        status TEXT DEFAULT 'pending',
        payment_method TEXT DEFAULT 'manual',
        payment_id INTEGER DEFAULT 0,
        order_date TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS premium_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        duration TEXT,
        price INTEGER,
        position INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS premium_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        full_name TEXT,
        username TEXT,
        duration TEXT,
        price INTEGER,
        target_username TEXT DEFAULT '',
        receipt_id TEXT,
        status TEXT DEFAULT 'pending',
        payment_method TEXT DEFAULT 'manual',
        payment_id INTEGER DEFAULT 0,
        order_date TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER DEFAULT 0,
        user_id INTEGER,
        full_name TEXT,
        username TEXT,
        amount INTEGER,
        type TEXT DEFAULT 'ad',
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        order_data TEXT DEFAULT ''
    )""")

    # Default settings
    defaults = {
        "price": "50000",
        "card": "8600 0000 0000 0000 (Ism Familiya)",
        "start_msg": "Salom {name}! Botga xush kelibsiz!",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()


def db_execute(query, params=(), fetch=False, fetchone=False):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if fetchone:
        result = c.fetchone()
    elif fetch:
        result = c.fetchall()
    conn.commit()
    conn.close()
    return result


def get_setting(key, default=""):
    row = db_execute("SELECT value FROM settings WHERE key=?", (key,), fetchone=True)
    return row["value"] if row else default


def set_setting(key, value):
    db_execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


# ================== FSM HOLATLAR ==================
class AdForm(StatesGroup):
    video = State()
    level = State()
    guns = State()
    xsuits = State()
    rp = State()
    cars = State()
    price = State()
    phone = State()


class PaymentForm(StatesGroup):
    receipt = State()


class SupportForm(StatesGroup):
    msg = State()


class AdminForm(StatesGroup):
    start_msg = State()
    price = State()
    card = State()
    add_channel_id = State()
    add_channel_url = State()
    reply_msg = State()
    uc_price_amount = State()
    uc_price_value = State()
    stars_price_amount = State()
    stars_price_value = State()
    premium_price_duration = State()
    premium_price_value = State()
    broadcast_msg = State()


class UCOrderForm(StatesGroup):
    pubg_id_input = State()
    payment_choice = State()
    receipt = State()


class StarsOrderForm(StatesGroup):
    choose_target = State()
    friend_username = State()
    payment_choice = State()
    receipt = State()


class PremiumOrderForm(StatesGroup):
    target_username = State()
    payment_choice = State()
    receipt = State()


# ================== BOT VA ROUTER ==================
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
router = Router()


# ================== YORDAMCHI FUNKSIYALAR ==================
def get_time_tashkent():
    tz = pytz.timezone('Asia/Tashkent')
    return datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')


async def check_subscription(user_id):
    channels = db_execute("SELECT channel_id, url FROM channels", fetch=True)
    unsubbed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ['left', 'kicked']:
                unsubbed.append(ch["url"])
        except:
            pass
    return unsubbed


# ================== CHECKOUT.UZ FUNKSIYALAR ==================
async def create_checkout_payment(amount: int, description: str) -> dict:
    headers = {
        "Authorization": f"Bearer {CHECKOUT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "amount": amount,
        "description": description
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CHECKOUT_BASE_URL}/create_payment",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                logging.info(f"Checkout.uz javob: {result}")
                return result
    except Exception as e:
        logging.error(f"Checkout.uz xato: {e}")
        return {"status": "error", "error": str(e)}


async def check_payment_status(payment_id: int) -> dict:
    headers = {
        "Authorization": f"Bearer {CHECKOUT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"id": int(payment_id)}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CHECKOUT_BASE_URL}/status_payment",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                return result
    except Exception as e:
        logging.error(f"Checkout status xato: {e}")
        return {"status": "error"}


# ================== PAYMENT MONITOR (HAR 10 SONIYADA) ==================
async def wait_for_bot_token():
    logging.error("BOT_TOKEN yo'q. App restart loopga tushmasligi uchun kutish rejimida turibdi.")
    logging.error("Fly.io panelida Secrets bo'limiga BOT_TOKEN kiriting, keyin appni Restart qiling.")
    while True:
        await asyncio.sleep(3600)


async def payment_monitor():
    if bot is None:
        return
    logging.info("🚀 Avtomatik to'lov tekshiruvchi ishga tushdi...")
    while True:
        try:
            await asyncio.sleep(10)

            pending = db_execute(
                "SELECT id, payment_id, user_id, full_name, username, amount, type, order_data FROM pending_payments WHERE status='pending' AND payment_id > 0",
                fetch=True
            )
            if not pending:
                continue

            for p in pending:
                p_id = p["id"]
                payment_id = p["payment_id"]
                user_id = p["user_id"]
                full_name = p["full_name"]
                username = p["username"]
                amount = p["amount"]
                pay_type = p["type"]
                order_data_str = p["order_data"] or "{}"

                result = await check_payment_status(payment_id)
                logging.info(f"Tekshiruv payment_id={payment_id}: {result}")

                if result.get("status") == "success" and result.get("data", {}).get("status") == "paid":
                    # To'lov tasdiqlandi!
                    db_execute("UPDATE pending_payments SET status='approved' WHERE id=?", (p_id,))

                    now = get_time_tashkent()

                    try:
                        order_data = json.loads(order_data_str)
                    except:
                        order_data = {}

                    # ===== E'LON TO'LOVI =====
                    if pay_type == "ad":
                        db_execute("UPDATE users SET paid_slots = paid_slots + 1 WHERE user_id=?", (user_id,))
                        try:
                            await bot.send_message(
                                user_id,
                                "✅ <b>To'lovingiz avtomatik tasdiqlandi!</b>\n\n"
                                "Endi e'lon berishingiz mumkin.\n"
                                "👇 «📝 E'lon berish» tugmasini bosing.",
                                parse_mode="HTML", reply_markup=get_main_menu()
                            )
                        except Exception as e:
                            logging.error(f"Xabar xato: {e}")

                    # ===== UC TO'LOVI =====
                    elif pay_type == "uc":
                        uc_amount = order_data.get("uc_amount", 0)
                        pubg_id = order_data.get("pubg_id", "—")
                        price = order_data.get("price", amount)

                        db_execute(
                            "INSERT INTO uc_orders (user_id, full_name, username, uc_amount, price, pubg_id, screenshot_id, status, payment_method, payment_id, order_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (user_id, full_name, username, uc_amount, price, pubg_id, None, "payment_confirmed", "auto", payment_id, now)
                        )
                        order_row = db_execute("SELECT id FROM uc_orders WHERE payment_id=?", (payment_id,), fetchone=True)
                        order_db_id = order_row["id"] if order_row else 0

                        admin_text = (
                            f"🛒 <b>UC BUYURTMA — TO'LOV TASDIQLANDI!</b>\n\n"
                            f"👤 {full_name} | @{username}\n"
                            f"🆔 ID: <code>{user_id}</code>\n\n"
                            f"💎 UC: <b>{uc_amount} UC</b>\n"
                            f"💰 To'lov: <b>{price:,} so'm (AUTO ✅)</b>\n\n".replace(",", " ") +
                            f"🎮 PUBG ID: <code>{pubg_id}</code>\n📅 {now}"
                        )
                        btn = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="✅ UC Yuborildi", callback_data=f"uc_approve_{user_id}_{order_db_id}"),
                            InlineKeyboardButton(text="❌ Bekor", callback_data=f"uc_reject_{user_id}_{order_db_id}")
                        ]])
                        try:
                            await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=btn)
                        except:
                            pass
                        try:
                            await bot.send_message(
                                user_id,
                                f"✅ <b>To'lovingiz avtomatik tasdiqlandi!</b>\n\n"
                                f"💎 <b>{uc_amount} UC</b> tez orada profilingizga yuboriladi.\n"
                                f"🎮 PUBG ID: <code>{pubg_id}</code>\n\n⏳ Admin UC ni yuborishini kuting.",
                                parse_mode="HTML", reply_markup=get_main_menu()
                            )
                        except Exception as e:
                            logging.error(f"UC xabar xato: {e}")

                    # ===== STARS TO'LOVI =====
                    elif pay_type == "stars":
                        stars_amount = order_data.get("stars_amount", 0)
                        stars_price = order_data.get("price", amount)
                        target_type = order_data.get("target_type", "me")
                        target_username = order_data.get("target_username", "—")

                        db_execute(
                            "INSERT INTO stars_orders (user_id, full_name, username, stars_amount, price, target_type, target_username, receipt_id, status, payment_method, payment_id, order_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (user_id, full_name, username, stars_amount, stars_price, target_type, target_username, None, "payment_confirmed", "auto", payment_id, now)
                        )
                        order_row = db_execute("SELECT id FROM stars_orders WHERE payment_id=?", (payment_id,), fetchone=True)
                        order_db_id = order_row["id"] if order_row else 0

                        target_text = f"O'ziga (@{target_username})" if target_type == "me" else f"Do'stiga (@{target_username})"
                        admin_text = (
                            f"⭐ <b>STARS BUYURTMA — TO'LOV TASDIQLANDI!</b>\n\n"
                            f"👤 {full_name} | @{username}\n"
                            f"🆔 ID: <code>{user_id}</code>\n\n"
                            f"⭐ Stars: <b>{stars_amount} Stars</b>\n"
                            f"💰 To'lov: <b>{stars_price:,} so'm (AUTO ✅)</b>\n\n".replace(",", " ") +
                            f"🎯 Kimga: <b>{target_text}</b>\n📅 {now}"
                        )
                        btn = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="✅ Stars Yuborildi", callback_data=f"stars_approve_{user_id}_{order_db_id}"),
                            InlineKeyboardButton(text="❌ Bekor", callback_data=f"stars_reject_{user_id}_{order_db_id}")
                        ]])
                        try:
                            await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=btn)
                        except:
                            pass
                        try:
                            await bot.send_message(
                                user_id,
                                f"✅ <b>To'lovingiz avtomatik tasdiqlandi!</b>\n\n"
                                f"⭐ <b>{stars_amount} Stars</b> tez orada yuboriladi.\n"
                                f"🎯 Kimga: {target_text}\n\n⏳ Admin Stars ni yuborishini kuting.",
                                parse_mode="HTML", reply_markup=get_main_menu()
                            )
                        except Exception as e:
                            logging.error(f"Stars xabar xato: {e}")

                    # ===== PREMIUM TO'LOVI =====
                    elif pay_type == "premium":
                        duration = order_data.get("duration", "")
                        prem_price = order_data.get("price", amount)
                        target_username = order_data.get("target_username", "—")

                        db_execute(
                            "INSERT INTO premium_orders (user_id, full_name, username, duration, price, target_username, receipt_id, status, payment_method, payment_id, order_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (user_id, full_name, username, duration, prem_price, target_username, None, "payment_confirmed", "auto", payment_id, now)
                        )
                        order_row = db_execute("SELECT id FROM premium_orders WHERE payment_id=?", (payment_id,), fetchone=True)
                        order_db_id = order_row["id"] if order_row else 0

                        admin_text = (
                            f"💜 <b>PREMIUM BUYURTMA — TO'LOV TASDIQLANDI!</b>\n\n"
                            f"👤 {full_name} | @{username}\n"
                            f"🆔 ID: <code>{user_id}</code>\n\n"
                            f"⭐ Muddat: <b>{duration}</b>\n"
                            f"💰 To'lov: <b>{prem_price:,} so'm (AUTO ✅)</b>\n\n".replace(",", " ") +
                            f"🎯 Profil: <code>@{target_username}</code>\n📅 {now}"
                        )
                        btn = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="✅ Premium Ulandi", callback_data=f"premium_approve_{user_id}_{order_db_id}"),
                            InlineKeyboardButton(text="❌ Bekor", callback_data=f"premium_reject_{user_id}_{order_db_id}")
                        ]])
                        try:
                            await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=btn)
                        except:
                            pass
                        try:
                            await bot.send_message(
                                user_id,
                                f"✅ <b>To'lovingiz avtomatik tasdiqlandi!</b>\n\n"
                                f"💜 <b>{duration}</b> Telegram Premium tez orada ulanadi.\n"
                                f"👤 Profil: <code>@{target_username}</code>\n\n⏳ Admin Premium ni ulashini kuting.",
                                parse_mode="HTML", reply_markup=get_main_menu()
                            )
                        except Exception as e:
                            logging.error(f"Premium xabar xato: {e}")

                    logging.info(f"✅ Payment {payment_id} tasdiqlandi! User: {user_id}, Type: {pay_type}")

        except Exception as e:
            logging.error(f"⚠️ Monitor xatosi: {e}")


# ================== CHECKOUT AUTO TO'LOV YARATISH ==================
async def send_auto_payment_link(
    call_or_msg,
    amount: int,
    description: str,
    pay_type: str,
    user_id: int,
    full_name: str,
    username: str,
    order_data: dict,
    fallback_cb: str,
    is_callback: bool = True
):
    if is_callback:
        await call_or_msg.answer("⏳ To'lov havolasi yaratilmoqda...")

    result = await create_checkout_payment(amount=amount, description=description)
    logging.info(f"Checkout natija: {result}")

    if result.get("status") == "success":
        payment = result.get("payment", {})
        p_id = payment.get("_id", 0)
        p_url = payment.get("_url", "")

        if p_id and p_url:
            # Bazaga yozish
            order_data_str = json.dumps(order_data, ensure_ascii=False)
            db_execute(
                "INSERT INTO pending_payments (payment_id, user_id, full_name, username, amount, type, status, created_at, order_data) VALUES (?,?,?,?,?,?,?,?,?)",
                (p_id, user_id, full_name, username, amount, pay_type, "pending", get_time_tashkent(), order_data_str)
            )

            btn = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🟢 💳 To'lovni amalga oshirish", url=p_url)],
                [InlineKeyboardButton(text="🔵 👨‍💼 Manual to'lovga o'tish", callback_data=fallback_cb)],
            ])
            text = (
                f"✅ <b>To'lov havolasi tayyor!</b>\n\n"
                f"💰 Summa: <b>{amount:,} so'm</b>\n\n".replace(",", " ") +
                f"👇 Yashil tugmani bosib to'lovni amalga oshiring.\n"
                f"✅ To'lov tasdiqlangach bot <b>avtomatik xabar yuboradi</b>.\n\n"
                f"⏳ To'lovdan keyin 10-20 soniya kuting."
            )
            if is_callback:
                try:
                    await call_or_msg.message.edit_text(text, reply_markup=btn, parse_mode="HTML")
                except:
                    await call_or_msg.message.answer(text, reply_markup=btn, parse_mode="HTML")
            else:
                await call_or_msg.answer(text, reply_markup=btn, parse_mode="HTML")
            return True

    # Checkout ishlamasa manual fallback
    card = get_setting("card", "")
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 📸 Chek yuborish", callback_data=fallback_cb)],
    ])
    text = (
        f"⚠️ <b>Auto to'lov hozir ishlamayapti.</b>\n\n"
        f"💳 Karta raqamiga to'lang:\n<code>{card}</code>\n"
        f"💰 Summa: <b>{amount:,} so'm</b>\n\n".replace(",", " ") +
        f"To'lov qilgach 🔴 tugmani bosib chek rasmini yuboring."
    )
    if is_callback:
        try:
            await call_or_msg.message.edit_text(text, reply_markup=btn, parse_mode="HTML")
        except:
            await call_or_msg.message.answer(text, reply_markup=btn, parse_mode="HTML")
    else:
        await call_or_msg.answer(text, reply_markup=btn, parse_mode="HTML")
    return False


# ================== TO'LOV TUGMALAR (3 xil rang) ==================
def get_payment_choice_keyboard(auto_cb: str, manual_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 ⚡ Auto to'lov (Checkout.uz)", callback_data=auto_cb)],
        [InlineKeyboardButton(text="🔵 👨‍💼 Admin tasdiqlagan to'lov", callback_data=manual_cb)],
    ])


# ================== ASOSIY MENU ==================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 E'lon berish"), KeyboardButton(text="🆘 Yordam")],
            [KeyboardButton(text="🎮 PUBG MOBILE UC OLISH 💎")],
            [KeyboardButton(text="⭐ TELEGRAM PREMIUM"), KeyboardButton(text="🌟 STARS OLISH")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Quyidagi tugmalardan birini tanlang 👇"
    )


# ================== ADMIN MENYU ==================
def get_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📝 Start xabar")],
            [KeyboardButton(text="💰 E'lon narxi"), KeyboardButton(text="💳 Karta")],
            [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="➖ Kanal o'chirish")],
            [KeyboardButton(text="💎 UC sozlamalari"), KeyboardButton(text="⭐ Stars sozlamalari")],
            [KeyboardButton(text="💜 Premium sozlamalari"), KeyboardButton(text="📦 Buyurtmalar")],
            [KeyboardButton(text="📢 Hammaga xabar yuborish")],
            [KeyboardButton(text="🔙 Asosiy menyu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_uc_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ UC narxi qo'shish"), KeyboardButton(text="📋 UC narxlari")],
            [KeyboardButton(text="📦 UC buyurtmalar"), KeyboardButton(text="🗑 UC narxlarini tozalash")],
            [KeyboardButton(text="🔙 Admin menyu")],
        ],
        resize_keyboard=True,
    )


def get_stars_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Stars narxi qo'shish"), KeyboardButton(text="📋 Stars narxlari")],
            [KeyboardButton(text="📦 Stars buyurtmalar"), KeyboardButton(text="🗑 Stars narxlarini tozalash")],
            [KeyboardButton(text="🔙 Admin menyu")],
        ],
        resize_keyboard=True,
    )


def get_premium_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Premium narxi qo'shish"), KeyboardButton(text="📋 Premium narxlari")],
            [KeyboardButton(text="📦 Premium buyurtmalar"), KeyboardButton(text="🗑 Premium narxlarini tozalash")],
            [KeyboardButton(text="🔙 Admin menyu")],
        ],
        resize_keyboard=True,
    )


def get_orders_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 UC buyurtmalar"), KeyboardButton(text="📦 Stars buyurtmalar")],
            [KeyboardButton(text="📦 Premium buyurtmalar")],
            [KeyboardButton(text="🔙 Admin menyu")],
        ],
        resize_keyboard=True,
    )


# ================== UC NARXLARI KLAVIATURA ==================
def get_uc_prices_keyboard(page=0):
    prices = db_execute("SELECT * FROM uc_prices ORDER BY uc_amount ASC", fetch=True)
    if not prices:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Hozircha narxlar kiritilmagan", callback_data="uc_no_prices")]
        ])
    ITEMS_PER_PAGE = 5
    total_pages = (len(prices) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    current = prices[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]
    rows = []
    for item in current:
        rows.append([InlineKeyboardButton(
            text=f"🟡 💎 {item['uc_amount']} UC — {item['price']:,} so'm".replace(",", " "),
            callback_data=f"buy_uc_x_{item['uc_amount']}_{item['price']}"
        )])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"uc_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"uc_page_{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔴 🔙 Orqaga", callback_data="uc_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_stars_prices_keyboard(page=0):
    prices = db_execute("SELECT * FROM stars_prices ORDER BY stars_amount ASC", fetch=True)
    if not prices:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Hozircha narxlar kiritilmagan", callback_data="stars_no_prices")]
        ])
    ITEMS_PER_PAGE = 5
    total_pages = (len(prices) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    current = prices[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]
    rows = []
    for item in current:
        rows.append([InlineKeyboardButton(
            text=f"🟡 ⭐ {item['stars_amount']} Stars — {item['price']:,} so'm".replace(",", " "),
            callback_data=f"buy_stars_{item['id']}_{item['stars_amount']}_{item['price']}"
        )])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"stars_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"stars_page_{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔴 🔙 Orqaga", callback_data="stars_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_premium_prices_keyboard(page=0):
    prices = db_execute("SELECT * FROM premium_prices ORDER BY price ASC", fetch=True)
    if not prices:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Hozircha narxlar kiritilmagan", callback_data="premium_no_prices")]
        ])
    ITEMS_PER_PAGE = 5
    total_pages = (len(prices) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    current = prices[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]
    rows = []
    for item in current:
        rows.append([InlineKeyboardButton(
            text=f"🟡 💜 {item['duration']} — {item['price']:,} so'm".replace(",", " "),
            callback_data=f"buy_premium_{item['id']}_{item['price']}"
        )])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"premium_page_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"premium_page_{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔴 🔙 Orqaga", callback_data="premium_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ================== START VA OBUNA ==================
@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    user = db_execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,), fetchone=True)
    if not user:
        db_execute(
            "INSERT INTO users (user_id, full_name, username, join_date) VALUES (?,?,?,?)",
            (message.from_user.id, message.from_user.full_name, message.from_user.username or "", get_time_tashkent())
        )

    unsubbed = await check_subscription(message.from_user.id)
    if unsubbed:
        btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🟢 📢 Kanal {i + 1} — Obuna bo'lish", url=url)]
            for i, url in enumerate(unsubbed)
        ] + [[InlineKeyboardButton(text="🟡 ✅ Tasdiqlash", callback_data="check_sub")]])
        await message.answer("Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:", reply_markup=btn)
        return

    start_text = get_setting("start_msg", "Salom {name}!").replace("{name}", message.from_user.full_name)
    await message.answer(start_text, reply_markup=get_main_menu(), parse_mode="HTML")


@router.callback_query(F.data == "check_sub")
async def check_sub_cb(call: CallbackQuery):
    unsubbed = await check_subscription(call.from_user.id)
    if unsubbed:
        await call.answer("Hali hamma kanallarga obuna bo'lmadingiz!", show_alert=True)
    else:
        await call.message.delete()
        start_text = get_setting("start_msg", "Salom {name}!").replace("{name}", call.from_user.full_name)
        await call.message.answer(f"✅ Obuna tasdiqlandi!\n\n{start_text}", reply_markup=get_main_menu())


# ================== MENU HANDLERLAR ==================
@router.message(F.text == "📝 E'lon berish")
async def menu_ad_cb(message: Message, state: FSMContext):
    unsubbed = await check_subscription(message.from_user.id)
    if unsubbed:
        await message.answer("Iltimos, oldin kanallarga obuna bo'ling. /start ni bosing.")
        return

    user = db_execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,), fetchone=True)
    if not user:
        await message.answer("Iltimos, /start bosing.")
        return

    if user["pending_approval"]:
        await message.answer("⏳ Sizning oldingi e'loningiz admin tomonidan ko'rib chiqilmoqda.")
        return

    paid_slots = user["paid_slots"]
    free_ad_used = user["free_ad_used"]

    if paid_slots > 0:
        await message.answer("✅ E'loningizni boshlaymiz.\n📹 Iltimos, akkaunt obzori videosini yuboring:")
        await state.set_state(AdForm.video)
        return

    if not free_ad_used:
        db_execute("UPDATE users SET free_ad_used=1 WHERE user_id=?", (message.from_user.id,))
        await message.answer("🎁 <b>Birinchi e'lon BEPUL!</b>\n\n📹 Iltimos, akkaunt obzori videosini yuboring:", parse_mode="HTML")
        await state.set_state(AdForm.video)
        return

    price_str = get_setting("price", "50000")
    try:
        price_int = int(price_str)
    except:
        price_int = 50000

    btn = get_payment_choice_keyboard("pay_ad_auto", "pay_ad_manual_start")
    await message.answer(
        f"📝 <b>E'lon joylash</b>\n\n"
        f"💰 E'lon narxi: <b>{price_int:,} so'm</b>\n\n".replace(",", " ") +
        f"🟢 <b>Auto to'lov</b> — checkout.uz orqali avtomatik\n"
        f"🔵 <b>Admin tasdiqlagan</b> — karta orqali, chek yuborish",
        reply_markup=btn, parse_mode="HTML"
    )


@router.message(F.text == "🆘 Yordam")
async def menu_help_cb(message: Message, state: FSMContext):
    await message.answer("✍️ Adminga xabaringizni yozib qoldiring:")
    await state.set_state(SupportForm.msg)


# ================== AUTO TO'LOV (E'LON) ==================
@router.callback_query(F.data == "pay_ad_auto")
async def pay_ad_auto_cb(call: CallbackQuery, state: FSMContext):
    price_str = get_setting("price", "50000")
    try:
        price_int = int(price_str)
    except:
        price_int = 50000

    await send_auto_payment_link(
        call_or_msg=call,
        amount=price_int,
        description=f"E'lon joylash to'lovi - {call.from_user.full_name}",
        pay_type="ad",
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        username=call.from_user.username or "—",
        order_data={},
        fallback_cb="pay_ad_manual_start",
        is_callback=True
    )


# ================== MANUAL TO'LOV (E'LON) ==================
@router.callback_query(F.data == "pay_ad_manual_start")
async def pay_ad_manual_start_cb(call: CallbackQuery, state: FSMContext):
    price_str = get_setting("price", "50000")
    try:
        price_int = int(price_str)
    except:
        price_int = 50000
    card = get_setting("card", "")
    await call.message.edit_text(
        f"🔵 <b>Admin tasdiqlagan to'lov</b>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{price_int:,} so'm</b>\n\n".replace(",", " ") +
        f"To'lov qilgach <b>chek rasmini yuboring</b>:",
        parse_mode="HTML"
    )
    await state.set_state(PaymentForm.receipt)
    await call.answer()


@router.message(PaymentForm.receipt, F.photo)
async def get_ad_receipt(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Tasdiqlash", callback_data=f"app_pay_{message.from_user.id}"),
        InlineKeyboardButton(text="🔴 ❌ Bekor qilish", callback_data=f"rej_pay_{message.from_user.id}")
    ]])
    await bot.send_photo(ADMIN_ID, photo_id,
        caption=f"💰 Yangi to'lov cheki (E'lon uchun)\n"
                f"👤 {message.from_user.full_name} (@{message.from_user.username})\n"
                f"🆔 ID: {message.from_user.id}",
        reply_markup=btn)
    await message.answer("✅ Chek adminga yuborildi. Tasdiqlanishini kuting.", reply_markup=get_main_menu())
    await state.clear()


@router.message(PaymentForm.receipt)
async def get_ad_receipt_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>to'lov cheki rasmini</b> yuboring!", parse_mode="HTML")


# ================== E'LON FORMI ==================
@router.message(AdForm.video, F.video)
async def get_video(message: Message, state: FSMContext):
    await state.update_data(video=message.video.file_id)
    await message.answer("🎮 Akkaunt levelini kiriting:")
    await state.set_state(AdForm.level)


@router.message(AdForm.video)
async def get_video_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>video</b> yuboring!", parse_mode="HTML")


@router.message(AdForm.level)
async def get_level(message: Message, state: FSMContext):
    await state.update_data(level=message.text)
    await message.answer("🔫 Nechta qurol (upgradable) bor?")
    await state.set_state(AdForm.guns)


@router.message(AdForm.guns)
async def get_guns(message: Message, state: FSMContext):
    await state.update_data(guns=message.text)
    await message.answer("👔 Nechta X-suit bor?")
    await state.set_state(AdForm.xsuits)


@router.message(AdForm.xsuits)
async def get_xsuits(message: Message, state: FSMContext):
    await state.update_data(xsuits=message.text)
    await message.answer("🏆 Nechta RP olingan?")
    await state.set_state(AdForm.rp)


@router.message(AdForm.rp)
async def get_rp(message: Message, state: FSMContext):
    await state.update_data(rp=message.text)
    await message.answer("🚗 Nechta mashina (skin) bor?")
    await state.set_state(AdForm.cars)


@router.message(AdForm.cars)
async def get_cars(message: Message, state: FSMContext):
    await state.update_data(cars=message.text)
    await message.answer("💰 Narxini so'mda kiriting (masalan: 150000):")
    await state.set_state(AdForm.price)


@router.message(AdForm.price)
async def get_price_ad(message: Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer("📞 Telefon raqamingizni kiriting (+998901234567):")
    await state.set_state(AdForm.phone)


@router.message(AdForm.phone)
async def get_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    st = await state.get_data()
    text = (
        f"📋 <b>E'lon ma'lumotlari:</b>\n\n"
        f"🎮 Level: {st.get('level')}\n"
        f"🔫 Qurollar: {st.get('guns')}\n"
        f"👔 X-suitlar: {st.get('xsuits')}\n"
        f"🏆 RP: {st.get('rp')}\n"
        f"🚗 Mashinalar: {st.get('cars')}\n"
        f"💰 Narx: {st.get('price')} so'm\n"
        f"📞 Telefon: {st.get('phone')}"
    )

    db_execute(
        "INSERT INTO ads (user_id, video_id, text, status) VALUES (?,?,?,?)",
        (message.from_user.id, st.get('video'), text, "pending")
    )
    ad_row = db_execute("SELECT id FROM ads WHERE user_id=? ORDER BY id DESC LIMIT 1", (message.from_user.id,), fetchone=True)
    ad_id = ad_row["id"] if ad_row else 0

    db_execute("UPDATE users SET pending_approval=1, paid_slots=MAX(0, paid_slots-1) WHERE user_id=?", (message.from_user.id,))

    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Tasdiqlash", callback_data=f"app_ad_{ad_id}"),
        InlineKeyboardButton(text="🔴 ❌ Bekor qilish", callback_data=f"rej_ad_{ad_id}")
    ]])
    try:
        await bot.send_video(ADMIN_ID, video=st.get('video'),
            caption=f"📢 Yangi e'lon!\n👤 {message.from_user.full_name} (ID: {message.from_user.id})\n\n{text}",
            reply_markup=btn, parse_mode="HTML")
    except:
        pass
    await message.answer("✅ E'loningiz adminga yuborildi. Tasdiqlanishini kuting.", reply_markup=get_main_menu())
    await state.clear()


# ================== 🎮 PUBG MOBILE UC OLISH ==================
@router.message(F.text == "🎮 PUBG MOBILE UC OLISH 💎")
async def uc_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🎮 <b>PUBG MOBILE UC OLISH</b>\n\n"
        "💎 Quyidagi narxlardan birini tanlang!\n"
        "⚡️ To'lov tasdiqlangandan so'ng UC tez yuboriladi.\n\n👇 UC miqdorini tanlang:",
        reply_markup=get_uc_prices_keyboard(0), parse_mode="HTML"
    )


@router.callback_query(F.data == "uc_no_prices")
async def uc_no_prices(call: CallbackQuery):
    await call.answer("Admin hali UC narxlarini kiritmagan!", show_alert=True)


@router.callback_query(F.data.startswith("uc_page_"))
async def uc_page_cb(call: CallbackQuery):
    page = int(call.data.split("_")[2])
    try:
        await call.message.edit_reply_markup(reply_markup=get_uc_prices_keyboard(page))
    except:
        pass
    await call.answer()


@router.callback_query(F.data == "uc_back")
async def uc_back_cb(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


@router.callback_query(F.data.startswith("buy_uc_x_"))
async def buy_uc_cb(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    uc_amount = int(parts[3])
    price = int(parts[4])
    await state.update_data(uc_amount=uc_amount, uc_price=price)
    await call.message.edit_text(
        f"🟡 💎 <b>{uc_amount} UC — {price:,} so'm</b>\n\n".replace(",", " ") +
        f"🔢 <b>PUBG Mobile ID raqamingizni kiriting:</b>\n\n<i>Profil → o'ng tepadagi ID raqami</i>",
        parse_mode="HTML"
    )
    await state.set_state(UCOrderForm.pubg_id_input)
    await call.answer()


@router.message(UCOrderForm.pubg_id_input, F.text)
async def get_pubg_id(message: Message, state: FSMContext):
    pubg_id = message.text.strip()
    await state.update_data(pubg_id=pubg_id)
    st = await state.get_data()
    uc_amount = st['uc_amount']
    price = st['uc_price']
    btn = get_payment_choice_keyboard("uc_pay_auto", "uc_pay_manual")
    await message.answer(
        f"✅ <b>PUBG ID: <code>{pubg_id}</code></b>\n\n"
        f"💎 UC: <b>{uc_amount} UC</b>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"🟢 <b>Auto to'lov</b> — checkout.uz orqali avtomatik\n"
        f"🔵 <b>Admin tasdiqlagan</b> — karta orqali, chek yuborish",
        reply_markup=btn, parse_mode="HTML"
    )
    await state.set_state(UCOrderForm.payment_choice)


@router.message(UCOrderForm.pubg_id_input)
async def get_pubg_id_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>PUBG ID raqamingizni</b> kiriting!", parse_mode="HTML")


# UC AUTO TO'LOV
@router.callback_query(F.data == "uc_pay_auto", UCOrderForm.payment_choice)
async def uc_pay_auto_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    uc_amount = st['uc_amount']
    price = st['uc_price']
    pubg_id = st['pubg_id']

    await send_auto_payment_link(
        call_or_msg=call,
        amount=price,
        description=f"{uc_amount} UC PUBG ID:{pubg_id}",
        pay_type="uc",
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        username=call.from_user.username or "—",
        order_data={"uc_amount": uc_amount, "pubg_id": pubg_id, "price": price},
        fallback_cb="uc_pay_manual",
        is_callback=True
    )


# UC MANUAL TO'LOV
@router.callback_query(F.data == "uc_pay_manual", UCOrderForm.payment_choice)
async def uc_pay_manual_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    uc_amount = st['uc_amount']
    price = st['uc_price']
    pubg_id = st['pubg_id']
    card = get_setting("card", "")
    await call.message.edit_text(
        f"🔵 <b>Admin tasdiqlagan to'lov</b>\n\n"
        f"💎 {uc_amount} UC | PUBG ID: <code>{pubg_id}</code>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"To'lov qilgach <b>chek rasmini yuboring</b>:",
        parse_mode="HTML"
    )
    await state.set_state(UCOrderForm.receipt)
    await call.answer()


@router.message(UCOrderForm.receipt, F.photo)
async def get_uc_receipt(message: Message, state: FSMContext):
    st = await state.get_data()
    receipt_id = message.photo[-1].file_id
    pubg_id = st.get('pubg_id', '—')
    uc_amount = st['uc_amount']
    price = st['uc_price']
    now = get_time_tashkent()

    db_execute(
        "INSERT INTO uc_orders (user_id, full_name, username, uc_amount, price, pubg_id, screenshot_id, status, payment_method, order_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (message.from_user.id, message.from_user.full_name, message.from_user.username or "—",
         uc_amount, price, pubg_id, receipt_id, "pending", "manual", now)
    )
    order_row = db_execute("SELECT id FROM uc_orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (message.from_user.id,), fetchone=True)
    order_id = order_row["id"] if order_row else 0

    admin_text = (
        f"🛒 <b>YANGI UC BUYURTMA!</b>\n\n"
        f"👤 {message.from_user.full_name} | @{message.from_user.username or '—'}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"💎 UC: <b>{uc_amount} UC</b>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"🎮 PUBG ID: <code>{pubg_id}</code>\n📅 {now}"
    )
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Tasdiqlash", callback_data=f"uc_approve_{message.from_user.id}_{order_id}"),
        InlineKeyboardButton(text="🔴 ❌ Bekor qilish", callback_data=f"uc_reject_{message.from_user.id}_{order_id}")
    ]])
    await bot.send_photo(ADMIN_ID, photo=receipt_id, caption=admin_text, parse_mode="HTML", reply_markup=btn)
    await message.answer(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"💎 <b>{uc_amount} UC</b>\n"
        f"⏳ Admin chekni ko'rib, UC ni tez orada yuboradi.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    await state.clear()


@router.message(UCOrderForm.receipt)
async def get_uc_receipt_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>chek rasmini</b> yuboring!", parse_mode="HTML")


# ================== ADMIN UC TASDIQLASH ==================
@router.callback_query(F.data.startswith("uc_approve_"))
async def uc_approve_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    order = db_execute("SELECT * FROM uc_orders WHERE id=?", (order_id,), fetchone=True)
    if order:
        db_execute("UPDATE uc_orders SET status='approved' WHERE id=?", (order_id,))
        await bot.send_message(
            user_id,
            f"🎉 <b>Tabriklaymiz! UC profilingizga tushdi!</b>\n\n"
            f"💎 <b>{order['uc_amount']} UC</b> yuborildi!\n🙏 Xarid uchun rahmat!",
            parse_mode="HTML", reply_markup=get_main_menu()
        )
    caption = call.message.caption or call.message.text or ""
    try:
        if call.message.photo:
            await call.message.edit_caption(caption=caption + "\n\n✅ TASDIQLANDI — UC YUBORILDI", reply_markup=None)
        else:
            await call.message.edit_text(caption + "\n\n✅ TASDIQLANDI — UC YUBORILDI", reply_markup=None)
    except:
        pass
    await call.answer("✅ Buyurtma tasdiqlandi!", show_alert=True)


@router.callback_query(F.data.startswith("uc_reject_"))
async def uc_reject_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    db_execute("UPDATE uc_orders SET status='rejected' WHERE id=?", (order_id,))
    await bot.send_message(
        user_id,
        "❌ <b>Buyurtmangiz bekor qilindi.</b>\n\n🆘 Yordam orqali admin bilan bog'laning.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    caption = call.message.caption or call.message.text or ""
    try:
        if call.message.photo:
            await call.message.edit_caption(caption=caption + "\n\n❌ BEKOR QILINDI", reply_markup=None)
        else:
            await call.message.edit_text(caption + "\n\n❌ BEKOR QILINDI", reply_markup=None)
    except:
        pass
    await call.answer("❌ Buyurtma bekor qilindi.", show_alert=True)


# ================== 🌟 STARS OLISH ==================
@router.message(F.text == "🌟 STARS OLISH")
async def stars_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🌟 <b>TELEGRAM STARS OLISH</b>\n\n"
        "⭐ Quyidagi miqdorlardan birini tanlang!\n"
        "⚡️ To'lov tasdiqlangandan so'ng Stars tez yuboriladi.\n\n👇 Stars miqdorini tanlang:",
        reply_markup=get_stars_prices_keyboard(0), parse_mode="HTML"
    )


@router.callback_query(F.data == "stars_no_prices")
async def stars_no_prices(call: CallbackQuery):
    await call.answer("Admin hali Stars narxlarini kiritmagan!", show_alert=True)


@router.callback_query(F.data.startswith("stars_page_"))
async def stars_page_cb(call: CallbackQuery):
    page = int(call.data.split("_")[2])
    try:
        await call.message.edit_reply_markup(reply_markup=get_stars_prices_keyboard(page))
    except:
        pass
    await call.answer()


@router.callback_query(F.data == "stars_back")
async def stars_back_cb(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


@router.callback_query(F.data.startswith("buy_stars_"))
async def buy_stars_cb(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    stars_id = int(parts[2])
    stars_amount = int(parts[3])
    price = int(parts[4])
    await state.update_data(stars_amount=stars_amount, stars_price=price)
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 👤 O'ZIMGA", callback_data="stars_target_me"),
        InlineKeyboardButton(text="🔵 👫 DO'STIMGA", callback_data="stars_target_friend"),
    ]])
    await call.message.edit_text(
        f"🟡 ⭐ <b>{stars_amount} Stars — {price:,} so'm</b>\n\nStars kimga kerak?".replace(",", " "),
        reply_markup=btn, parse_mode="HTML"
    )
    await state.set_state(StarsOrderForm.choose_target)
    await call.answer()


@router.callback_query(F.data == "stars_target_me", StarsOrderForm.choose_target)
async def stars_target_me(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    stars_amount = st['stars_amount']
    price = st['stars_price']
    username = call.from_user.username or call.from_user.full_name
    await state.update_data(target_type="me", target_username=username)
    btn = get_payment_choice_keyboard("stars_pay_auto", "stars_pay_manual")
    await call.message.edit_text(
        f"⭐ <b>{stars_amount} Stars — {price:,} so'm</b>\n".replace(",", " ") +
        f"👤 O'zingizga: <code>@{username}</code>\n\nTo'lov usulini tanlang:",
        reply_markup=btn, parse_mode="HTML"
    )
    await state.set_state(StarsOrderForm.payment_choice)
    await call.answer()


@router.callback_query(F.data == "stars_target_friend", StarsOrderForm.choose_target)
async def stars_target_friend(call: CallbackQuery, state: FSMContext):
    await state.update_data(target_type="friend")
    await call.message.edit_text(
        "👫 Do'stingizning Telegram username'ini kiriting:\n\nMasalan: <code>@username</code>",
        parse_mode="HTML"
    )
    await state.set_state(StarsOrderForm.friend_username)
    await call.answer()


@router.message(StarsOrderForm.friend_username)
async def get_stars_friend_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    await state.update_data(target_username=username)
    st = await state.get_data()
    stars_amount = st['stars_amount']
    price = st['stars_price']
    btn = get_payment_choice_keyboard("stars_pay_auto", "stars_pay_manual")
    await message.answer(
        f"⭐ <b>{stars_amount} Stars — {price:,} so'm</b>\n".replace(",", " ") +
        f"👫 Do'stingizga: <code>@{username}</code>\n\nTo'lov usulini tanlang:",
        reply_markup=btn, parse_mode="HTML"
    )
    await state.set_state(StarsOrderForm.payment_choice)


# STARS AUTO TO'LOV
@router.callback_query(F.data == "stars_pay_auto", StarsOrderForm.payment_choice)
async def stars_pay_auto_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    stars_amount = st['stars_amount']
    price = st['stars_price']
    target_type = st.get('target_type', 'me')
    target_username = st.get('target_username', '—')

    await send_auto_payment_link(
        call_or_msg=call,
        amount=price,
        description=f"{stars_amount} Stars @{target_username}",
        pay_type="stars",
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        username=call.from_user.username or "—",
        order_data={"stars_amount": stars_amount, "price": price, "target_type": target_type, "target_username": target_username},
        fallback_cb="stars_pay_manual",
        is_callback=True
    )


# STARS MANUAL TO'LOV
@router.callback_query(F.data == "stars_pay_manual", StarsOrderForm.payment_choice)
async def stars_pay_manual_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    stars_amount = st['stars_amount']
    price = st['stars_price']
    target_username = st.get('target_username', '—')
    card = get_setting("card", "")
    await call.message.edit_text(
        f"🔵 <b>Admin tasdiqlagan to'lov</b>\n\n"
        f"⭐ {stars_amount} Stars → <code>@{target_username}</code>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"To'lov qilgach <b>chek rasmini yuboring</b>:",
        parse_mode="HTML"
    )
    await state.set_state(StarsOrderForm.receipt)
    await call.answer()


@router.message(StarsOrderForm.receipt, F.photo)
async def get_stars_receipt(message: Message, state: FSMContext):
    st = await state.get_data()
    receipt_id = message.photo[-1].file_id
    stars_amount = st['stars_amount']
    price = st['stars_price']
    target_type = st.get('target_type', 'me')
    target_username = st.get('target_username', '—')
    now = get_time_tashkent()

    db_execute(
        "INSERT INTO stars_orders (user_id, full_name, username, stars_amount, price, target_type, target_username, receipt_id, status, payment_method, order_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (message.from_user.id, message.from_user.full_name, message.from_user.username or "—",
         stars_amount, price, target_type, target_username, receipt_id, "pending", "manual", now)
    )
    order_row = db_execute("SELECT id FROM stars_orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (message.from_user.id,), fetchone=True)
    order_id = order_row["id"] if order_row else 0

    target_text = f"O'ziga (@{target_username})" if target_type == "me" else f"Do'stiga (@{target_username})"
    admin_text = (
        f"⭐ <b>YANGI STARS BUYURTMA!</b>\n\n"
        f"👤 {message.from_user.full_name} | @{message.from_user.username or '—'}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"⭐ Stars: <b>{stars_amount} Stars</b>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"🎯 Kimga: <b>{target_text}</b>\n📅 {now}"
    )
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Stars Yuborildi", callback_data=f"stars_approve_{message.from_user.id}_{order_id}"),
        InlineKeyboardButton(text="🔴 ❌ Bekor", callback_data=f"stars_reject_{message.from_user.id}_{order_id}")
    ]])
    await bot.send_photo(ADMIN_ID, photo=receipt_id, caption=admin_text, parse_mode="HTML", reply_markup=btn)
    await message.answer(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n⭐ <b>{stars_amount} Stars</b>\n⏳ Admin chekni ko'rib Stars ni yuboradi.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    await state.clear()


@router.message(StarsOrderForm.receipt)
async def get_stars_receipt_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>chek rasmini</b> yuboring!", parse_mode="HTML")


# ================== ADMIN STARS TASDIQLASH ==================
@router.callback_query(F.data.startswith("stars_approve_"))
async def stars_approve_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    order = db_execute("SELECT * FROM stars_orders WHERE id=?", (order_id,), fetchone=True)
    if order:
        db_execute("UPDATE stars_orders SET status='approved' WHERE id=?", (order_id,))
        await bot.send_message(
            user_id,
            f"🎉 <b>Tabriklaymiz! Stars yuborildi!</b>\n\n⭐ <b>{order['stars_amount']} Stars</b>\n🙏 Xarid uchun rahmat!",
            parse_mode="HTML", reply_markup=get_main_menu()
        )
    caption = call.message.caption or ""
    try:
        await call.message.edit_caption(caption=caption + "\n\n✅ TASDIQLANDI — STARS YUBORILDI", reply_markup=None)
    except:
        pass
    await call.answer("✅ Stars buyurtma tasdiqlandi!", show_alert=True)


@router.callback_query(F.data.startswith("stars_reject_"))
async def stars_reject_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    db_execute("UPDATE stars_orders SET status='rejected' WHERE id=?", (order_id,))
    await bot.send_message(
        user_id,
        "❌ <b>Buyurtmangiz bekor qilindi.</b>\n\n🆘 Yordam orqali admin bilan bog'laning.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    caption = call.message.caption or ""
    try:
        await call.message.edit_caption(caption=caption + "\n\n❌ BEKOR QILINDI", reply_markup=None)
    except:
        pass
    await call.answer("❌ Stars buyurtma bekor qilindi.", show_alert=True)


# ================== ⭐ TELEGRAM PREMIUM ==================
@router.message(F.text == "⭐ TELEGRAM PREMIUM")
async def premium_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⭐ <b>TELEGRAM PREMIUM OLISH</b>\n\n"
        "🚀 Premium bilan Telegram'ni to'liq imkoniyatlaridan foydalaning!\n\n👇 Muddat tanlang:",
        reply_markup=get_premium_prices_keyboard(0), parse_mode="HTML"
    )


@router.callback_query(F.data == "premium_no_prices")
async def premium_no_prices(call: CallbackQuery):
    await call.answer("Admin hali Premium narxlarini kiritmagan!", show_alert=True)


@router.callback_query(F.data.startswith("premium_page_"))
async def premium_page_cb(call: CallbackQuery):
    page = int(call.data.split("_")[2])
    try:
        await call.message.edit_reply_markup(reply_markup=get_premium_prices_keyboard(page))
    except:
        pass
    await call.answer()


@router.callback_query(F.data == "premium_back")
async def premium_back_cb(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


@router.callback_query(F.data.startswith("buy_premium_"))
async def buy_premium_cb(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    pid = int(parts[2])
    price = int(parts[3])
    row = db_execute("SELECT * FROM premium_prices WHERE id=?", (pid,), fetchone=True)
    duration = row["duration"] if row else "Noma'lum"
    await state.update_data(premium_pid=pid, premium_price=price, premium_duration=duration)
    await call.message.edit_text(
        f"🟡 💜 <b>{duration} — {price:,} so'm</b>\n\n".replace(",", " ") +
        f"Premium tushiriladigan profil username'ini kiriting:\n\nMasalan: <code>@username</code>",
        parse_mode="HTML"
    )
    await state.set_state(PremiumOrderForm.target_username)
    await call.answer()


@router.message(PremiumOrderForm.target_username)
async def get_premium_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    await state.update_data(target_username=username)
    st = await state.get_data()
    price = st['premium_price']
    duration = st['premium_duration']
    btn = get_payment_choice_keyboard("premium_pay_auto", "premium_pay_manual")
    await message.answer(
        f"💜 <b>{duration} — {price:,} so'm</b>\n".replace(",", " ") +
        f"👤 Profil: <code>@{username}</code>\n\nTo'lov usulini tanlang:",
        reply_markup=btn, parse_mode="HTML"
    )
    await state.set_state(PremiumOrderForm.payment_choice)


# PREMIUM AUTO TO'LOV
@router.callback_query(F.data == "premium_pay_auto", PremiumOrderForm.payment_choice)
async def premium_pay_auto_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    price = st['premium_price']
    duration = st['premium_duration']
    target_username = st.get('target_username', '—')

    await send_auto_payment_link(
        call_or_msg=call,
        amount=price,
        description=f"Premium {duration} @{target_username}",
        pay_type="premium",
        user_id=call.from_user.id,
        full_name=call.from_user.full_name,
        username=call.from_user.username or "—",
        order_data={"duration": duration, "price": price, "target_username": target_username},
        fallback_cb="premium_pay_manual",
        is_callback=True
    )


# PREMIUM MANUAL TO'LOV
@router.callback_query(F.data == "premium_pay_manual", PremiumOrderForm.payment_choice)
async def premium_pay_manual_cb(call: CallbackQuery, state: FSMContext):
    st = await state.get_data()
    price = st['premium_price']
    duration = st['premium_duration']
    target_username = st.get('target_username', '—')
    card = get_setting("card", "")
    await call.message.edit_text(
        f"🔵 <b>Admin tasdiqlagan to'lov</b>\n\n"
        f"💜 {duration} → <code>@{target_username}</code>\n\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"To'lov qilgach <b>chek rasmini yuboring</b>:",
        parse_mode="HTML"
    )
    await state.set_state(PremiumOrderForm.receipt)
    await call.answer()


@router.message(PremiumOrderForm.receipt, F.photo)
async def get_premium_receipt(message: Message, state: FSMContext):
    st = await state.get_data()
    receipt_id = message.photo[-1].file_id
    price = st['premium_price']
    duration = st['premium_duration']
    target_username = st.get('target_username', '—')
    now = get_time_tashkent()

    db_execute(
        "INSERT INTO premium_orders (user_id, full_name, username, duration, price, target_username, receipt_id, status, payment_method, order_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (message.from_user.id, message.from_user.full_name, message.from_user.username or "—",
         duration, price, target_username, receipt_id, "pending", "manual", now)
    )
    order_row = db_execute("SELECT id FROM premium_orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (message.from_user.id,), fetchone=True)
    order_id = order_row["id"] if order_row else 0

    admin_text = (
        f"💜 <b>YANGI PREMIUM BUYURTMA!</b>\n\n"
        f"👤 {message.from_user.full_name} | @{message.from_user.username or '—'}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"⭐ Premium: <b>{duration}</b>\n"
        f"💰 Summa: <b>{price:,} so'm</b>\n\n".replace(",", " ") +
        f"🎯 Profil: <code>@{target_username}</code>\n📅 {now}"
    )
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 ✅ Tasdiqlash", callback_data=f"premium_approve_{message.from_user.id}_{order_id}"),
            InlineKeyboardButton(text="🔴 ❌ Bekor qilish", callback_data=f"premium_reject_{message.from_user.id}_{order_id}"),
        ],
        [InlineKeyboardButton(text="🔵 👤 Foydalanuvchiga o'tish", url=f"tg://user?id={message.from_user.id}")]
    ])
    await bot.send_photo(ADMIN_ID, photo=receipt_id, caption=admin_text, parse_mode="HTML", reply_markup=btn)
    await message.answer(
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n💜 <b>{duration}</b> Telegram Premium\n⏳ Admin chekni ko'rib Premium ulanadi.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    await state.clear()


@router.message(PremiumOrderForm.receipt)
async def get_premium_receipt_wrong(message: Message):
    await message.answer("❗️ Iltimos, <b>chek rasmini</b> yuboring!", parse_mode="HTML")


# ================== ADMIN PREMIUM TASDIQLASH ==================
@router.callback_query(F.data.startswith("premium_approve_"))
async def premium_approve_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    order = db_execute("SELECT * FROM premium_orders WHERE id=?", (order_id,), fetchone=True)
    if order:
        db_execute("UPDATE premium_orders SET status='approved' WHERE id=?", (order_id,))
        await bot.send_message(
            user_id,
            f"🎉 <b>Tabriklaymiz! Telegram Premium ulandi!</b>\n\n"
            f"💜 <b>{order['duration']}</b> Premium obuna\n"
            f"👤 Profil: <code>@{order['target_username']}</code>\n\n🙏 Xarid uchun rahmat!",
            parse_mode="HTML", reply_markup=get_main_menu()
        )
    caption = call.message.caption or ""
    try:
        await call.message.edit_caption(caption=caption + "\n\n✅ TASDIQLANDI — PREMIUM ULANDI", reply_markup=None)
    except:
        pass
    await call.answer("✅ Premium buyurtma tasdiqlandi!", show_alert=True)


@router.callback_query(F.data.startswith("premium_reject_"))
async def premium_reject_cb(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[2])
    order_id = int(parts[3])

    db_execute("UPDATE premium_orders SET status='rejected' WHERE id=?", (order_id,))
    await bot.send_message(
        user_id,
        "❌ <b>Buyurtmangiz bekor qilindi.</b>\n\n🆘 Yordam orqali admin bilan bog'laning.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    caption = call.message.caption or ""
    try:
        await call.message.edit_caption(caption=caption + "\n\n❌ BEKOR QILINDI", reply_markup=None)
    except:
        pass
    await call.answer("❌ Premium buyurtma bekor qilindi.", show_alert=True)


# ================== SUPPORT ==================
@router.message(SupportForm.msg)
async def get_support_msg(message: Message, state: FSMContext):
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 💬 Javob berish", callback_data=f"reply_{message.from_user.id}")
    ]])
    await bot.send_message(ADMIN_ID,
        f"📩 Yangi xabar!\n👤 {message.from_user.full_name} (ID: {message.from_user.id})\n\n{message.text}",
        reply_markup=btn)
    await message.answer("✅ Xabaringiz adminga yetkazildi.", reply_markup=get_main_menu())
    await state.clear()


# ================== ADMIN TO'LOV MANUAL TASDIQLASH (E'LON) ==================
@router.callback_query(F.data.startswith("app_pay_"))
async def approve_pay(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    user_id = int(call.data.split("_")[2])
    db_execute("UPDATE users SET paid_slots = paid_slots + 1 WHERE user_id=?", (user_id,))
    await bot.send_message(
        user_id,
        "✅ <b>To'lovingiz tasdiqlandi!</b>\n\n👇 «📝 E'lon berish» tugmasini bosing.",
        parse_mode="HTML", reply_markup=get_main_menu()
    )
    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ TASDIQLANGAN", reply_markup=None)
    except:
        pass
    await call.answer("✅ Tasdiqlandi!", show_alert=True)


@router.callback_query(F.data.startswith("rej_pay_"))
async def reject_pay(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    user_id = int(call.data.split("_")[2])
    await bot.send_message(user_id, "❌ To'lovingiz admin tomonidan bekor qilindi.", reply_markup=get_main_menu())
    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ BEKOR QILINGAN", reply_markup=None)
    except:
        pass
    await call.answer("❌ Bekor qilindi.", show_alert=True)


# ================== ADMIN E'LON TASDIQLASH ==================
@router.callback_query(F.data.startswith("app_ad_"))
async def approve_ad(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    ad_id = int(call.data.split("_")[2])
    ad = db_execute("SELECT * FROM ads WHERE id=?", (ad_id,), fetchone=True)
    if not ad:
        await call.answer("❌ E'lon topilmadi!", show_alert=True)
        return
    user_id = ad["user_id"]
    me = await bot.get_me()
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 👤 Sotuvchi bilan aloqa", url=f"tg://user?id={user_id}")],
        [InlineKeyboardButton(text="🔵 📢 Reklama berish", url=f"https://t.me/{me.username}?start=ad")]
    ])
    try:
        await bot.send_video(MAIN_CHANNEL_ID, video=ad["video_id"], caption=ad["text"], reply_markup=btn, parse_mode="HTML")
    except Exception as e:
        await call.answer(f"❌ Kanalga yuborishda XATO:\n{e}", show_alert=True)
        return

    db_execute("UPDATE ads SET status='approved' WHERE id=?", (ad_id,))
    db_execute("UPDATE users SET posted_ads=posted_ads+1, pending_approval=0 WHERE user_id=?", (user_id,))

    try:
        await bot.send_message(user_id, "✅ <b>E'loningiz kanalga joylandi!</b>", parse_mode="HTML", reply_markup=get_main_menu())
    except:
        pass
    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ KANALGA JOYLANDI", reply_markup=None)
    except:
        pass
    await call.answer("✅ E'lon kanalga joylandi!", show_alert=True)


@router.callback_query(F.data.startswith("rej_ad_"))
async def reject_ad(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    ad_id = int(call.data.split("_")[2])
    ad = db_execute("SELECT * FROM ads WHERE id=?", (ad_id,), fetchone=True)
    if not ad:
        await call.answer("❌ E'lon topilmadi!", show_alert=True)
        return
    user_id = ad["user_id"]
    db_execute("UPDATE ads SET status='rejected' WHERE id=?", (ad_id,))
    db_execute("UPDATE users SET pending_approval=0 WHERE user_id=?", (user_id,))
    try:
        await bot.send_message(user_id, "❌ E'loningiz admin tomonidan rad etildi.", reply_markup=get_main_menu())
    except:
        pass
    try:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ BEKOR QILINGAN", reply_markup=None)
    except:
        pass
    await call.answer("❌ E'lon bekor qilindi.", show_alert=True)


# ================== ADMIN JAVOB ==================
@router.callback_query(F.data.startswith("reply_"))
async def reply_support_cb(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    user_id = int(call.data.split("_")[1])
    await state.update_data(reply_to=user_id)
    await call.message.answer("✍️ Foydalanuvchiga javob matnini kiriting:")
    await state.set_state(AdminForm.reply_msg)
    await call.answer()


@router.message(AdminForm.reply_msg)
async def send_reply(message: Message, state: FSMContext):
    st = await state.get_data()
    user_id = st.get('reply_to')
    try:
        await bot.send_message(user_id, f"👨‍💻 <b>Admin javobi:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("✅ Javob yuborildi.", reply_markup=get_admin_menu())
    except Exception as e:
        await message.answer(f"❌ Xato: {e}", reply_markup=get_admin_menu())
    await state.clear()


# ================== HAMMAGA XABAR YUBORISH (BROADCAST) ==================
@router.message(F.text == "📢 Hammaga xabar yuborish", F.from_user.id == ADMIN_ID)
async def broadcast_start(message: Message, state: FSMContext):
    await message.answer(
        "📢 <b>Hammaga xabar yuborish</b>\n\n"
        "Yuboriladigan xabarni kiriting (matn, rasm, video — bari ishlaydi).\n\n"
        "❌ Bekor qilish uchun /cancel bosing.",
        parse_mode="HTML"
    )
    await state.set_state(AdminForm.broadcast_msg)


@router.message(Command("cancel"), F.from_user.id == ADMIN_ID)
async def cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_menu())


@router.message(AdminForm.broadcast_msg)
async def do_broadcast(message: Message, state: FSMContext):
    await state.clear()
    users = db_execute("SELECT user_id FROM users", fetch=True)
    total = len(users)
    sent = 0
    failed = 0

    status_msg = await message.answer(
        f"⏳ <b>Xabar yuborilmoqda...</b>\n\n"
        f"👥 Jami: <b>{total}</b>\n✅ Yuborildi: <b>0</b>\n❌ Xato: <b>0</b>",
        parse_mode="HTML"
    )

    for i, user in enumerate(users):
        uid = user["user_id"]
        try:
            if message.photo:
                await bot.send_photo(uid, photo=message.photo[-1].file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video:
                await bot.send_video(uid, video=message.video.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.document:
                await bot.send_document(uid, document=message.document.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.sticker:
                await bot.send_sticker(uid, sticker=message.sticker.file_id)
            elif message.animation:
                await bot.send_animation(uid, animation=message.animation.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.text:
                await bot.send_message(uid, message.text, parse_mode="HTML")
            sent += 1
        except:
            failed += 1

        if (i + 1) % 20 == 0 or (i + 1) == total:
            try:
                await status_msg.edit_text(
                    f"⏳ <b>Xabar yuborilmoqda...</b>\n\n"
                    f"👥 Jami: <b>{total}</b>\n"
                    f"✅ Yuborildi: <b>{sent}</b>\n"
                    f"❌ Xato: <b>{failed}</b>\n"
                    f"📊 Progress: <b>{i + 1}/{total}</b>",
                    parse_mode="HTML"
                )
            except:
                pass
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Broadcast yakunlandi!</b>\n\n"
        f"👥 Jami: <b>{total}</b>\n✅ Muvaffaqiyatli: <b>{sent}</b>\n❌ Yuborilmadi: <b>{failed}</b>",
        parse_mode="HTML"
    )


# ================== ADMIN PANEL ==================
@router.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel_cmd(message: Message):
    await message.answer("⚙️ Admin panelga xush kelibsiz!", reply_markup=get_admin_menu())


@router.message(F.text == "📊 Statistika", F.from_user.id == ADMIN_ID)
async def admin_stats_btn(message: Message):
    users_count = db_execute("SELECT COUNT(*) as cnt FROM users", fetchone=True)["cnt"]
    ads_count = db_execute("SELECT COUNT(*) as cnt FROM ads", fetchone=True)["cnt"]
    ads_approved = db_execute("SELECT COUNT(*) as cnt FROM ads WHERE status='approved'", fetchone=True)["cnt"]
    uc_count = db_execute("SELECT COUNT(*) as cnt FROM uc_orders", fetchone=True)["cnt"]
    uc_approved = db_execute("SELECT COUNT(*) as cnt FROM uc_orders WHERE status='approved'", fetchone=True)["cnt"]
    stars_count = db_execute("SELECT COUNT(*) as cnt FROM stars_orders", fetchone=True)["cnt"]
    premium_count = db_execute("SELECT COUNT(*) as cnt FROM premium_orders", fetchone=True)["cnt"]

    await message.answer(
        f"📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users_count} ta</b>\n"
        f"📝 E'lonlar: <b>{ads_count} ta</b> (tasdiqlangan: {ads_approved})\n"
        f"💎 UC buyurtmalar: <b>{uc_count} ta</b> (tasdiqlangan: {uc_approved})\n"
        f"⭐ Stars buyurtmalar: <b>{stars_count} ta</b>\n"
        f"💜 Premium buyurtmalar: <b>{premium_count} ta</b>\n"
        f"🕐 Vaqt: {get_time_tashkent()}",
        parse_mode="HTML"
    )


@router.message(F.text == "📝 Start xabar", F.from_user.id == ADMIN_ID)
async def admin_startmsg_btn(message: Message, state: FSMContext):
    await message.answer("Yangi start xabarini kiriting ({name} — foydalanuvchi ismi):")
    await state.set_state(AdminForm.start_msg)


@router.message(AdminForm.start_msg)
async def save_start(message: Message, state: FSMContext):
    set_setting("start_msg", message.text)
    await message.answer("✅ Start xabar yangilandi!", reply_markup=get_admin_menu())
    await state.clear()


@router.message(F.text == "💰 E'lon narxi", F.from_user.id == ADMIN_ID)
async def admin_price_btn(message: Message, state: FSMContext):
    await message.answer("Yangi e'lon narxini kiriting (faqat raqam, so'mda):")
    await state.set_state(AdminForm.price)


@router.message(AdminForm.price)
async def save_price(message: Message, state: FSMContext):
    set_setting("price", message.text)
    await message.answer(f"✅ E'lon narxi yangilandi: {message.text} so'm", reply_markup=get_admin_menu())
    await state.clear()


@router.message(F.text == "💳 Karta", F.from_user.id == ADMIN_ID)
async def admin_card_btn(message: Message, state: FSMContext):
    await message.answer("Yangi karta raqamini kiriting:")
    await state.set_state(AdminForm.card)


@router.message(AdminForm.card)
async def save_card(message: Message, state: FSMContext):
    set_setting("card", message.text)
    await message.answer("✅ Karta yangilandi!", reply_markup=get_admin_menu())
    await state.clear()


@router.message(F.text == "➕ Kanal qo'shish", F.from_user.id == ADMIN_ID)
async def add_ch_btn(message: Message, state: FSMContext):
    await message.answer("Kanal ID sini kiriting (@kanal yoki -100...):")
    await state.set_state(AdminForm.add_channel_id)


@router.message(AdminForm.add_channel_id)
async def add_ch_url(message: Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal ssilkasini kiriting (https://t.me/...):")
    await state.set_state(AdminForm.add_channel_url)


@router.message(AdminForm.add_channel_url)
async def save_ch(message: Message, state: FSMContext):
    st = await state.get_data()
    db_execute("INSERT INTO channels (channel_id, url) VALUES (?,?)", (st['ch_id'], message.text))
    await message.answer("✅ Kanal qo'shildi!", reply_markup=get_admin_menu())
    await state.clear()


@router.message(F.text == "➖ Kanal o'chirish", F.from_user.id == ADMIN_ID)
async def del_ch_btn(message: Message):
    channels = db_execute("SELECT * FROM channels", fetch=True)
    if not channels:
        await message.answer("Kanallar yo'q.")
        return
    btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔴 🗑 O'chirish: {ch['channel_id']}", callback_data=f"delch_{ch['id']}")]
        for ch in channels
    ])
    await message.answer("Qaysi kanalni o'chirasiz?", reply_markup=btn)


@router.callback_query(F.data.startswith("delch_"))
async def del_ch_action(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    c_id = int(call.data.split("_")[1])
    db_execute("DELETE FROM channels WHERE id=?", (c_id,))
    await call.message.edit_text("✅ Kanal o'chirildi.")
    await call.answer()


# ================== UC SOZLAMALARI ==================
@router.message(F.text == "💎 UC sozlamalari", F.from_user.id == ADMIN_ID)
async def uc_settings_btn(message: Message):
    await message.answer("💎 UC sozlamalari:", reply_markup=get_uc_admin_menu())


@router.message(F.text == "➕ UC narxi qo'shish", F.from_user.id == ADMIN_ID)
async def add_uc_price_btn(message: Message, state: FSMContext):
    await message.answer("💎 <b>UC miqdorini kiriting</b>\n\nMasalan: <code>60</code>", parse_mode="HTML")
    await state.set_state(AdminForm.uc_price_amount)


@router.message(AdminForm.uc_price_amount)
async def add_uc_price_step2(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting!")
        return
    await state.update_data(uc_amount=int(message.text))
    await message.answer(f"💰 <b>{message.text} UC narxini kiriting (so'mda)</b>", parse_mode="HTML")
    await state.set_state(AdminForm.uc_price_value)


@router.message(AdminForm.uc_price_value)
async def add_uc_price_save(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting!")
        return
    st = await state.get_data()
    uc_amount = st['uc_amount']
    price = int(message.text)
    existing = db_execute("SELECT * FROM uc_prices WHERE uc_amount=?", (uc_amount,), fetchone=True)
    if existing:
        db_execute("UPDATE uc_prices SET price=? WHERE uc_amount=?", (price, uc_amount))
        await message.answer(f"✅ <b>{uc_amount} UC</b> narxi yangilandi: <b>{price:,} so'm</b>".replace(",", " "), parse_mode="HTML", reply_markup=get_uc_admin_menu())
    else:
        db_execute("INSERT INTO uc_prices (uc_amount, price) VALUES (?,?)", (uc_amount, price))
        await message.answer(f"✅ <b>{uc_amount} UC — {price:,} so'm</b> qo'shildi!".replace(",", " "), parse_mode="HTML", reply_markup=get_uc_admin_menu())
    await state.clear()


@router.message(F.text == "📋 UC narxlari", F.from_user.id == ADMIN_ID)
async def admin_uc_list_btn(message: Message):
    prices = db_execute("SELECT * FROM uc_prices ORDER BY uc_amount ASC", fetch=True)
    if not prices:
        await message.answer("❌ Hozircha UC narxlari kiritilmagan.")
        return
    text = "💎 <b>UC NARXLARI:</b>\n\n"
    rows = []
    for item in prices:
        text += f"• {item['uc_amount']} UC — {item['price']:,} so'm\n".replace(",", " ")
        rows.append([
            InlineKeyboardButton(text=f"🟡 💎 {item['uc_amount']} UC", callback_data="uc_info"),
            InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_uc_price_{item['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 UC buyurtmalar", F.from_user.id == ADMIN_ID)
async def admin_uc_orders_btn(message: Message):
    orders = db_execute("SELECT * FROM uc_orders ORDER BY id DESC LIMIT 20", fetch=True)
    if not orders:
        await message.answer("📦 Hozircha UC buyurtmalar yo'q.")
        return
    text = "📦 <b>OXIRGI 20 UC BUYURTMA:</b>\n\n"
    for o in orders:
        emoji = "⏳" if o["status"] == "pending" else ("✅" if o["status"] in ("approved", "payment_confirmed") else "❌")
        method = "🤖" if o["payment_method"] == "auto" else "👤"
        text += f"{emoji}{method} #{o['id']} | {o['full_name']} | {o['uc_amount']} UC | {o['price']:,} so'm | {o['order_date']}\n".replace(",", " ")
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🗑 UC narxlarini tozalash", F.from_user.id == ADMIN_ID)
async def admin_clear_uc_btn(message: Message):
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Ha, o'chirish", callback_data="confirm_clear_uc"),
        InlineKeyboardButton(text="🔴 ❌ Yo'q", callback_data="close_list"),
    ]])
    await message.answer("⚠️ <b>Barcha UC narxlarini o'chirasizmi?</b>", parse_mode="HTML", reply_markup=btn)


# ================== STARS SOZLAMALARI ==================
@router.message(F.text == "⭐ Stars sozlamalari", F.from_user.id == ADMIN_ID)
async def stars_settings_btn(message: Message):
    await message.answer("⭐ Stars sozlamalari:", reply_markup=get_stars_admin_menu())


@router.message(F.text == "➕ Stars narxi qo'shish", F.from_user.id == ADMIN_ID)
async def add_stars_price_btn(message: Message, state: FSMContext):
    await message.answer("⭐ <b>Stars miqdorini kiriting</b>\n\nMasalan: <code>50</code>", parse_mode="HTML")
    await state.set_state(AdminForm.stars_price_amount)


@router.message(AdminForm.stars_price_amount)
async def add_stars_price_step2(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting!")
        return
    await state.update_data(stars_amount=int(message.text))
    await message.answer(f"💰 <b>{message.text} Stars narxini kiriting (so'mda)</b>", parse_mode="HTML")
    await state.set_state(AdminForm.stars_price_value)


@router.message(AdminForm.stars_price_value)
async def add_stars_price_save(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting!")
        return
    st = await state.get_data()
    stars_amount = st['stars_amount']
    price = int(message.text)
    existing = db_execute("SELECT * FROM stars_prices WHERE stars_amount=?", (stars_amount,), fetchone=True)
    if existing:
        db_execute("UPDATE stars_prices SET price=? WHERE stars_amount=?", (price, stars_amount))
        await message.answer(f"✅ <b>{stars_amount} Stars</b> narxi yangilandi: <b>{price:,} so'm</b>".replace(",", " "), parse_mode="HTML", reply_markup=get_stars_admin_menu())
    else:
        db_execute("INSERT INTO stars_prices (stars_amount, price) VALUES (?,?)", (stars_amount, price))
        await message.answer(f"✅ <b>{stars_amount} Stars — {price:,} so'm</b> qo'shildi!".replace(",", " "), parse_mode="HTML", reply_markup=get_stars_admin_menu())
    await state.clear()


@router.message(F.text == "📋 Stars narxlari", F.from_user.id == ADMIN_ID)
async def admin_stars_list_btn(message: Message):
    prices = db_execute("SELECT * FROM stars_prices ORDER BY stars_amount ASC", fetch=True)
    if not prices:
        await message.answer("❌ Hozircha Stars narxlari kiritilmagan.")
        return
    text = "⭐ <b>STARS NARXLARI:</b>\n\n"
    rows = []
    for item in prices:
        text += f"• {item['stars_amount']} Stars — {item['price']:,} so'm\n".replace(",", " ")
        rows.append([
            InlineKeyboardButton(text=f"🟡 ⭐ {item['stars_amount']} Stars", callback_data="stars_info"),
            InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_stars_price_{item['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 Stars buyurtmalar", F.from_user.id == ADMIN_ID)
async def admin_stars_orders_btn(message: Message):
    orders = db_execute("SELECT * FROM stars_orders ORDER BY id DESC LIMIT 20", fetch=True)
    if not orders:
        await message.answer("⭐ Hozircha Stars buyurtmalar yo'q.")
        return
    text = "⭐ <b>OXIRGI 20 STARS BUYURTMA:</b>\n\n"
    for o in orders:
        emoji = "⏳" if o["status"] == "pending" else ("✅" if o["status"] in ("approved", "payment_confirmed") else "❌")
        method = "🤖" if o["payment_method"] == "auto" else "👤"
        text += f"{emoji}{method} #{o['id']} | {o['full_name']} | {o['stars_amount']} Stars | @{o['target_username']} | {o['order_date']}\n"
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🗑 Stars narxlarini tozalash", F.from_user.id == ADMIN_ID)
async def admin_clear_stars_btn(message: Message):
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Ha, o'chirish", callback_data="confirm_clear_stars"),
        InlineKeyboardButton(text="🔴 ❌ Yo'q", callback_data="close_list"),
    ]])
    await message.answer("⚠️ <b>Barcha Stars narxlarini o'chirasizmi?</b>", parse_mode="HTML", reply_markup=btn)


# ================== PREMIUM SOZLAMALARI ==================
@router.message(F.text == "💜 Premium sozlamalari", F.from_user.id == ADMIN_ID)
async def premium_settings_btn(message: Message):
    await message.answer("💜 Premium sozlamalari:", reply_markup=get_premium_admin_menu())


@router.message(F.text == "➕ Premium narxi qo'shish", F.from_user.id == ADMIN_ID)
async def add_premium_price_btn(message: Message, state: FSMContext):
    await message.answer("⭐ <b>Premium muddatini kiriting</b>\n\nMasalan: <code>1 oylik</code>", parse_mode="HTML")
    await state.set_state(AdminForm.premium_price_duration)


@router.message(AdminForm.premium_price_duration)
async def add_premium_price_step2(message: Message, state: FSMContext):
    await state.update_data(premium_duration=message.text)
    await message.answer(f"💰 <b>«{message.text}» narxini kiriting (so'mda)</b>", parse_mode="HTML")
    await state.set_state(AdminForm.premium_price_value)


@router.message(AdminForm.premium_price_value)
async def add_premium_price_save(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❗️ Faqat raqam kiriting!")
        return
    st = await state.get_data()
    duration = st['premium_duration']
    price = int(message.text)
    db_execute("INSERT INTO premium_prices (duration, price) VALUES (?,?)", (duration, price))
    await message.answer(f"✅ <b>{duration} — {price:,} so'm</b> qo'shildi!".replace(",", " "), parse_mode="HTML", reply_markup=get_premium_admin_menu())
    await state.clear()


@router.message(F.text == "📋 Premium narxlari", F.from_user.id == ADMIN_ID)
async def admin_premium_list_btn(message: Message):
    prices = db_execute("SELECT * FROM premium_prices ORDER BY price ASC", fetch=True)
    if not prices:
        await message.answer("❌ Hozircha Premium narxlari kiritilmagan.")
        return
    text = "💜 <b>PREMIUM NARXLARI:</b>\n\n"
    rows = []
    for item in prices:
        text += f"• {item['duration']} — {item['price']:,} so'm\n".replace(",", " ")
        rows.append([
            InlineKeyboardButton(text=f"🟡 💜 {item['duration']}", callback_data="premium_info"),
            InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_premium_price_{item['id']}"),
        ])
    rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 Premium buyurtmalar", F.from_user.id == ADMIN_ID)
async def admin_premium_orders_btn(message: Message):
    orders = db_execute("SELECT * FROM premium_orders ORDER BY id DESC LIMIT 20", fetch=True)
    if not orders:
        await message.answer("💜 Hozircha Premium buyurtmalar yo'q.")
        return
    text = "💜 <b>OXIRGI 20 PREMIUM BUYURTMA:</b>\n\n"
    for o in orders:
        emoji = "⏳" if o["status"] == "pending" else ("✅" if o["status"] in ("approved", "payment_confirmed") else "❌")
        method = "🤖" if o["payment_method"] == "auto" else "👤"
        text += f"{emoji}{method} #{o['id']} | {o['full_name']} | {o['duration']} | @{o['target_username']} | {o['order_date']}\n"
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🗑 Premium narxlarini tozalash", F.from_user.id == ADMIN_ID)
async def admin_clear_premium_btn(message: Message):
    btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ✅ Ha, o'chirish", callback_data="confirm_clear_premium"),
        InlineKeyboardButton(text="🔴 ❌ Yo'q", callback_data="close_list"),
    ]])
    await message.answer("⚠️ <b>Barcha Premium narxlarini o'chirasizmi?</b>", parse_mode="HTML", reply_markup=btn)


@router.message(F.text == "📦 Buyurtmalar", F.from_user.id == ADMIN_ID)
async def admin_orders_btn(message: Message):
    await message.answer("📦 Buyurtmalar bo'limi:", reply_markup=get_orders_admin_menu())


@router.message(F.text == "🔙 Admin menyu", F.from_user.id == ADMIN_ID)
async def back_to_admin_menu(message: Message):
    await message.answer("⚙️ Admin panel:", reply_markup=get_admin_menu())


@router.message(F.text == "🔙 Asosiy menyu", F.from_user.id == ADMIN_ID)
async def back_to_main_menu(message: Message):
    await message.answer("Asosiy menyu:", reply_markup=get_main_menu())


# ================== INLINE CALLBACK HANDLERLAR ==================
@router.callback_query(F.data == "close_list")
async def close_list_cb(call: CallbackQuery):
    try:
        await call.message.delete()
    except:
        pass
    await call.answer()


@router.callback_query(F.data.in_({"uc_info", "stars_info", "premium_info"}))
async def info_cb(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data.startswith("del_uc_price_"))
async def del_uc_price(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    pid = int(call.data.split("_")[3])
    item = db_execute("SELECT * FROM uc_prices WHERE id=?", (pid,), fetchone=True)
    if item:
        db_execute("DELETE FROM uc_prices WHERE id=?", (pid,))
        await call.answer(f"✅ {item['uc_amount']} UC narxi o'chirildi!", show_alert=True)
        # Yangilash
        prices = db_execute("SELECT * FROM uc_prices ORDER BY uc_amount ASC", fetch=True)
        if not prices:
            try:
                await call.message.edit_text("❌ Barcha UC narxlari o'chirildi.")
            except:
                pass
            return
        text = "💎 <b>UC NARXLARI:</b>\n\n"
        rows = []
        for p in prices:
            text += f"• {p['uc_amount']} UC — {p['price']:,} so'm\n".replace(",", " ")
            rows.append([
                InlineKeyboardButton(text=f"🟡 💎 {p['uc_amount']} UC", callback_data="uc_info"),
                InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_uc_price_{p['id']}"),
            ])
        rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except:
            pass
    else:
        await call.answer("Topilmadi!", show_alert=True)


@router.callback_query(F.data.startswith("del_stars_price_"))
async def del_stars_price(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    pid = int(call.data.split("_")[3])
    item = db_execute("SELECT * FROM stars_prices WHERE id=?", (pid,), fetchone=True)
    if item:
        db_execute("DELETE FROM stars_prices WHERE id=?", (pid,))
        await call.answer(f"✅ {item['stars_amount']} Stars narxi o'chirildi!", show_alert=True)
        prices = db_execute("SELECT * FROM stars_prices ORDER BY stars_amount ASC", fetch=True)
        if not prices:
            try:
                await call.message.edit_text("❌ Barcha Stars narxlari o'chirildi.")
            except:
                pass
            return
        text = "⭐ <b>STARS NARXLARI:</b>\n\n"
        rows = []
        for p in prices:
            text += f"• {p['stars_amount']} Stars — {p['price']:,} so'm\n".replace(",", " ")
            rows.append([
                InlineKeyboardButton(text=f"🟡 ⭐ {p['stars_amount']} Stars", callback_data="stars_info"),
                InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_stars_price_{p['id']}"),
            ])
        rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except:
            pass
    else:
        await call.answer("Topilmadi!", show_alert=True)


@router.callback_query(F.data.startswith("del_premium_price_"))
async def del_premium_price(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    pid = int(call.data.split("_")[3])
    item = db_execute("SELECT * FROM premium_prices WHERE id=?", (pid,), fetchone=True)
    if item:
        db_execute("DELETE FROM premium_prices WHERE id=?", (pid,))
        await call.answer(f"✅ {item['duration']} narxi o'chirildi!", show_alert=True)
        prices = db_execute("SELECT * FROM premium_prices ORDER BY price ASC", fetch=True)
        if not prices:
            try:
                await call.message.edit_text("❌ Barcha Premium narxlari o'chirildi.")
            except:
                pass
            return
        text = "💜 <b>PREMIUM NARXLARI:</b>\n\n"
        rows = []
        for p in prices:
            text += f"• {p['duration']} — {p['price']:,} so'm\n".replace(",", " ")
            rows.append([
                InlineKeyboardButton(text=f"🟡 💜 {p['duration']}", callback_data="premium_info"),
                InlineKeyboardButton(text="🔴 🗑", callback_data=f"del_premium_price_{p['id']}"),
            ])
        rows.append([InlineKeyboardButton(text="🔵 🔙 Yopish", callback_data="close_list")])
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except:
            pass
    else:
        await call.answer("Topilmadi!", show_alert=True)


@router.callback_query(F.data == "confirm_clear_uc")
async def confirm_clear_uc(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    db_execute("DELETE FROM uc_prices")
    await call.answer("✅ Barcha UC narxlari o'chirildi!", show_alert=True)
    try:
        await call.message.delete()
    except:
        pass


@router.callback_query(F.data == "confirm_clear_stars")
async def confirm_clear_stars(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    db_execute("DELETE FROM stars_prices")
    await call.answer("✅ Barcha Stars narxlari o'chirildi!", show_alert=True)
    try:
        await call.message.delete()
    except:
        pass


@router.callback_query(F.data == "confirm_clear_premium")
async def confirm_clear_premium(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Ruxsat yo'q!", show_alert=True)
        return
    db_execute("DELETE FROM premium_prices")
    await call.answer("✅ Barcha Premium narxlari o'chirildi!", show_alert=True)
    try:
        await call.message.delete()
    except:
        pass


# ================== CHECKBOT ==================
@router.message(Command("checkbot"), F.from_user.id == ADMIN_ID)
async def check_bot_status(message: Message):
    me = await bot.get_me()
    try:
        member = await bot.get_chat_member(MAIN_CHANNEL_ID, me.id)
        can_post = getattr(member, 'can_post_messages', False)
        await message.answer(
            f"🤖 Bot: @{me.username}\n"
            f"📢 Kanal: {MAIN_CHANNEL_ID}\n"
            f"📋 Status: {member.status}\n"
            f"✍️ Post yuborish: {'Ha ✅' if can_post else 'Yo`q ❌'}\n\n"
            f"{'✅ Hammasi yaxshi!' if can_post else '⚠️ Botni kanalga ADMIN qilib qo`shing!'}"
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


# ================== ASOSIY ISHGA TUSHIRISH ==================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    if bot is None:
        await wait_for_bot_token()
        return

    print("⏳ SQLite baza tayyorlanmoqda...")
    init_db()
    print("✅ Baza tayyor!")

    dp.include_router(router)

    # Payment monitor — orqa fonda ishlaydi
    asyncio.create_task(payment_monitor())
    print("✅ Avtomatik to'lov tekshiruvchi ishga tushdi!")

    print("✅ Bot ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
