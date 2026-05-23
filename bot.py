import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta

from config import (
    BOT_TOKEN, BOT_NAME, ADMIN_IDS, HAPP_PROVIDER_CODE, HAPP_AUTH_KEY,
    HAPP_DEVICE_LIMIT, MINIAPP_URL, SETUP_DOMAIN, SUPPORT_URL,
    SBER_CARD, CARD_HOLDER, USDT_ADDRESS, USDT_RATE,
    REFERRAL_BONUS_DAYS, PLANS
)
from db import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database()

# Цена в Stars (1 звезда ≈ 0.013$, ~1.2₽)
STARS_RATE = 1.7  # ₽ за 1 звезду

class PaymentStates(StatesGroup):
    waiting_screenshot = State()
    waiting_usdt_hash = State()

# ── Happ API ───────────────────────────────────────────────

async def happ_create_key(user_id: int, days: int):
    url = "https://api.happproxy.com/v1/keys"
    headers = {"Authorization": f"Bearer {HAPP_AUTH_KEY}", "Content-Type": "application/json"}
    payload = {
        "provider_code": HAPP_PROVIDER_CODE,
        "user_id": str(user_id),
        "device_limit": HAPP_DEVICE_LIMIT,
        "expires_at": (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("key") or data.get("access_url")
                logger.error(f"Happ API error {resp.status}: {await resp.text()}")
                return None
    except Exception as e:
        logger.error(f"Happ API exception: {e}")
        return None

async def happ_extend_key(key_id: str, days: int) -> bool:
    url = f"https://api.happproxy.com/v1/keys/{key_id}/extend"
    headers = {"Authorization": f"Bearer {HAPP_AUTH_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"days": days}, headers=headers) as resp:
                return resp.status == 200
    except Exception as e:
        logger.error(f"Happ extend: {e}")
        return False

# ── Клавиатуры ─────────────────────────────────────────────

def main_menu_kb(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="🔑 Мой VPN", callback_data="my_vpn")],
        [InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="👥 Реферальная программа", callback_data="referral")],
        [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def plans_kb():
    buttons = []
    for plan in PLANS:
        stars = 1
        buttons.append([InlineKeyboardButton(
            text=f"{plan['emoji']} {plan['name']} — {plan['price']}₽",
            callback_data=f"plan_{plan['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def payment_kb(plan_id: str, stars: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐ Оплатить {stars} Stars (мгновенно)", callback_data=f"pay_stars_{plan_id}")],
        [InlineKeyboardButton(text="💳 Картой (СБП)", callback_data=f"pay_card_{plan_id}")],
        [InlineKeyboardButton(text="₿ USDT TRC-20", callback_data=f"pay_usdt_{plan_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")],
    ])

def back_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_main")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])

def setup_kb(key: str, days_left: int, total_days: int):
    miniapp_link = f"{MINIAPP_URL}?token={key}&days={days_left}&max={total_days}&support={SUPPORT_URL}"
    setup_link = f"{SETUP_DOMAIN}?temporary_token={key}&supportUrl={SUPPORT_URL}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настроить VPN", web_app=WebAppInfo(url=miniapp_link))],
        [InlineKeyboardButton(text="🔗 Открыть инструкцию", url=setup_link)],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_main")],
    ])

# ── Хендлеры ──────────────────────────────────────────────

@dp.message(CommandStart())
async def start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    ref_id = int(args[1].replace("ref", "")) if len(args) > 1 and args[1].startswith("ref") else None
    is_new = await db.add_user(user.id, user.username or user.first_name, ref_id)
    if is_new and ref_id and ref_id != user.id:
        await db.add_referral_bonus(ref_id, REFERRAL_BONUS_DAYS)
        try:
            await bot.send_message(ref_id, f"🎉 По вашей реферальной ссылке зарегистрировался новый пользователь!\n+{REFERRAL_BONUS_DAYS} дней к подписке.")
        except:
            pass
    sub = await db.get_subscription(user.id)
    if sub and sub['expires_at'] and sub['expires_at'] > datetime.utcnow():
        days_left = (sub['expires_at'] - datetime.utcnow()).days
        text = f"👋 Привет, {user.first_name}!\n\n✅ Ваш VPN активен\n⏳ Осталось: **{days_left} дней**\n\nВыберите действие:"
    else:
        text = f"👋 Привет, {user.first_name}!\n\n🔐 Добро пожаловать в **{BOT_NAME}**\n\nБыстрый надёжный VPN — настройка за 1 минуту.\nВыберите действие:"
    await message.answer(text, reply_markup=main_menu_kb(user.id), parse_mode="Markdown")

@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    sub = await db.get_subscription(call.from_user.id)
    if sub and sub['expires_at'] and sub['expires_at'] > datetime.utcnow():
        days_left = (sub['expires_at'] - datetime.utcnow()).days
        text = f"🏠 Главное меню\n\n✅ VPN активен — осталось **{days_left} дней**"
    else:
        text = "🏠 Главное меню\n\n❌ Подписка не активна"
    await call.message.edit_text(text, reply_markup=main_menu_kb(call.from_user.id), parse_mode="Markdown")

@dp.callback_query(F.data == "my_vpn")
async def my_vpn(call: types.CallbackQuery):
    sub = await db.get_subscription(call.from_user.id)
    if not sub or not sub['expires_at'] or sub['expires_at'] <= datetime.utcnow():
        await call.message.edit_text(
            "❌ У вас нет активной подписки.\n\nКупите подписку, чтобы получить доступ к VPN:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
            ])
        )
        return
    days_left = (sub['expires_at'] - datetime.utcnow()).days
    key = sub['happ_key']
    await call.message.edit_text(
        f"🔑 **Ваш VPN**\n\n✅ Статус: Активен\n⏳ Осталось: **{days_left} дней**\n📱 Устройств: до {HAPP_DEVICE_LIMIT}\n\nНажмите кнопку для настройки на вашем устройстве:",
        reply_markup=setup_kb(key, days_left, sub['total_days']),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "buy")
async def buy(call: types.CallbackQuery):
    await call.message.edit_text(
        "💳 **Выберите план подписки:**\n\n"
        "✅ До 5 устройств одновременно\n"
        "✅ Безлимитный трафик · Высокая скорость\n"
        "✅ Оплата Stars — мгновенная активация\n",
        reply_markup=plans_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("plan_"))
async def select_plan(call: types.CallbackQuery):
    plan_id = call.data.replace("plan_", "")
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        return
    stars = 1
    await call.message.edit_text(
        f"{plan['emoji']} **{plan['name']} — {plan['price']}₽**\n\n"
        f"📅 Срок: {plan['days']} дней\n"
        f"📱 Устройств: до {HAPP_DEVICE_LIMIT}\n"
        f"⭐ Stars: {stars} (мгновенная активация)\n\n"
        f"_{plan['description']}_\n\n"
        f"Выберите способ оплаты:",
        reply_markup=payment_kb(plan_id, stars),
        parse_mode="Markdown"
    )

# ── Оплата Stars ──────────────────────────────────────────

@dp.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars(call: types.CallbackQuery):
    plan_id = call.data.replace("pay_stars_", "")
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        return
    stars = 1
    await call.message.delete()
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"VPN {plan['name']}",
        description=f"VPN подписка на {plan['days']} дней · до {HAPP_DEVICE_LIMIT} устройств · безлимит",
        payload=f"vpn_{plan_id}_{call.from_user.id}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=f"VPN {plan['name']}", amount=stars)],
        protect_content=False,
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    # payload: vpn_PLANID_USERID
    parts = payload.split("_")
    if len(parts) < 3 or parts[0] != "vpn":
        return
    plan_id = parts[1]
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        return

    user_id = message.from_user.id
    stars_paid = message.successful_payment.total_amount

    logger.info(f"Stars payment: user={user_id} plan={plan_id} stars={stars_paid}")

    # Создаём или продлеваем ключ
    sub = await db.get_subscription(user_id)
    key = None
    if sub and sub.get('happ_key_id'):
        ok = await happ_extend_key(sub['happ_key_id'], plan['days'])
        if ok:
            await db.extend_subscription(user_id, plan['days'])
            sub = await db.get_subscription(user_id)
            key = sub['happ_key']
        else:
            # fallback — создаём новый
            key = await happ_create_key(user_id, plan['days'])
            if key:
                await db.create_subscription(user_id, key, plan['days'])
    else:
        key = await happ_create_key(user_id, plan['days'])
        if key:
            await db.create_subscription(user_id, key, plan['days'])

    if not key:
        # Ключ не создался — уведомляем админа вручную
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ **Оплата Stars прошла, но ключ не создан!**\n\n"
                    f"👤 @{message.from_user.username or message.from_user.first_name} (ID: `{user_id}`)\n"
                    f"📦 {plan['name']} · {stars_paid}⭐\n\n"
                    f"Выдай вручную: /approve_{user_id}_{plan_id}",
                    parse_mode="Markdown"
                )
            except:
                pass
        await message.answer(
            "✅ Оплата получена!\n\n⏳ Ключ создаётся вручную — обычно до 5 минут.\nМы пришлём уведомление.",
            reply_markup=back_main_kb()
        )
        return

    # Успех — отправляем ключ сразу
    sub = await db.get_subscription(user_id)
    days_left = (sub['expires_at'] - datetime.utcnow()).days

    # Уведомляем админа
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⭐ **Stars оплата**\n\n"
                f"👤 @{message.from_user.username or message.from_user.first_name} (ID: `{user_id}`)\n"
                f"📦 {plan['name']} · {stars_paid}⭐\n"
                f"✅ Ключ выдан автоматически",
                parse_mode="Markdown"
            )
        except:
            pass

    await message.answer(
        f"🎉 **Оплата прошла! VPN активирован.**\n\n"
        f"📦 План: {plan['name']}\n"
        f"⏳ Действует: **{plan['days']} дней**\n"
        f"📱 Устройств: до {HAPP_DEVICE_LIMIT}\n\n"
        f"Нажмите кнопку ниже — настройка займёт 1 минуту:",
        reply_markup=setup_kb(key, days_left, plan['days']),
        parse_mode="Markdown"
    )

# ── Оплата картой ─────────────────────────────────────────

@dp.callback_query(F.data.startswith("pay_card_"))
async def pay_card(call: types.CallbackQuery, state: FSMContext):
    plan_id = call.data.replace("pay_card_", "")
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        return
    await state.set_state(PaymentStates.waiting_screenshot)
    await state.update_data(plan_id=plan_id)
    await call.message.edit_text(
        f"💳 **Оплата картой СБП**\n\n"
        f"Сумма: **{plan['price']}₽**\n\n"
        f"Переведите на карту:\n`{SBER_CARD}`\n"
        f"Получатель: **{CARD_HOLDER}**\n\n"
        f"После оплаты отправьте скриншот чека прямо сюда — активируем за 5–15 минут.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"plan_{plan_id}")]
        ]),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("pay_usdt_"))
async def pay_usdt(call: types.CallbackQuery, state: FSMContext):
    plan_id = call.data.replace("pay_usdt_", "")
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        return
    usdt_amount = round(plan['price'] / USDT_RATE, 2)
    await state.set_state(PaymentStates.waiting_usdt_hash)
    await state.update_data(plan_id=plan_id)
    await call.message.edit_text(
        f"₿ **Оплата USDT TRC-20**\n\n"
        f"Сумма: **{usdt_amount} USDT** (~{plan['price']}₽)\n\n"
        f"Адрес:\n`{USDT_ADDRESS}`\n\n"
        f"После оплаты отправьте хеш транзакции сюда — активируем за 5–15 минут.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"plan_{plan_id}")]
        ]),
        parse_mode="Markdown"
    )

@dp.message(PaymentStates.waiting_screenshot)
async def receive_screenshot(message: types.Message, state: FSMContext):
    if not message.photo and not message.document:
        await message.answer("📸 Пожалуйста, отправьте скриншот чека.")
        return
    data = await state.get_data()
    plan = next((p for p in PLANS if p['id'] == data['plan_id']), None)
    await state.clear()
    for admin_id in ADMIN_IDS:
        try:
            caption = (
                f"💳 **Новый платёж (карта)**\n\n"
                f"👤 @{message.from_user.username or message.from_user.first_name} (ID: `{message.from_user.id}`)\n"
                f"📦 {plan['name']} — {plan['price']}₽ ({plan['days']} дн.)\n\n"
                f"✅ Подтвердить: /approve_{message.from_user.id}_{data['plan_id']}\n"
                f"❌ Отклонить: /reject_{message.from_user.id}"
            )
            if message.photo:
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, parse_mode="Markdown")
            else:
                await bot.send_document(admin_id, message.document.file_id, caption=caption, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Admin notify error: {e}")
    await message.answer(
        "✅ Чек получен! Ожидайте подтверждения — обычно 5–15 минут.\nПришлём уведомление когда VPN будет активен.",
        reply_markup=back_main_kb()
    )

@dp.message(PaymentStates.waiting_usdt_hash)
async def receive_usdt_hash(message: types.Message, state: FSMContext):
    data = await state.get_data()
    plan = next((p for p in PLANS if p['id'] == data['plan_id']), None)
    await state.clear()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"₿ **Новый платёж (USDT)**\n\n"
                f"👤 @{message.from_user.username or message.from_user.first_name} (ID: `{message.from_user.id}`)\n"
                f"📦 {plan['name']} — {plan['price']}₽ ({plan['days']} дн.)\n"
                f"🔗 Хеш: `{message.text}`\n\n"
                f"✅ Подтвердить: /approve_{message.from_user.id}_{data['plan_id']}\n"
                f"❌ Отклонить: /reject_{message.from_user.id}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Admin notify: {e}")
    await message.answer(
        "✅ Хеш получен! Ожидайте подтверждения — обычно 5–15 минут.",
        reply_markup=back_main_kb()
    )

# ── Реферальная ───────────────────────────────────────────

@dp.callback_query(F.data == "referral")
async def referral(call: types.CallbackQuery):
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref{call.from_user.id}"
    count = await db.get_referral_count(call.from_user.id)
    bonus = await db.get_referral_bonus(call.from_user.id)
    await call.message.edit_text(
        f"👥 **Реферальная программа**\n\n"
        f"Приглашайте друзей и получайте **+{REFERRAL_BONUS_DAYS} дней** за каждого!\n\n"
        f"🔗 Ваша ссылка:\n`{ref_link}`\n\n"
        f"👤 Приглашено: **{count} чел.**\n"
        f"🎁 Накоплено: **{bonus} дней**",
        reply_markup=back_main_kb(),
        parse_mode="Markdown"
    )

# ── Админ ─────────────────────────────────────────────────

@dp.callback_query(F.data == "admin")
async def admin_panel(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    stats = await db.get_stats()
    await call.message.edit_text(
        f"⚙️ **Админ панель**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"✅ Активных подписок: {stats['active']}\n"
        f"💰 Платежей сегодня: {stats['payments_today']}",
        reply_markup=admin_kb(), parse_mode="Markdown"
    )

@dp.callback_query(F.data == "admin_users")
async def admin_users(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    users = await db.get_all_users()
    text = "👥 **Пользователи:**\n\n"
    for u in users[:10]:
        icon = "✅" if u.get('has_active_sub') else "❌"
        text += f"{icon} {u['username']} (`{u['user_id']}`)\n"
    await call.message.edit_text(text, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    stats = await db.get_stats()
    await call.message.edit_text(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"✅ Активных: {stats['active']}\n"
        f"💰 Платежей сегодня: {stats['payments_today']}\n"
        f"👥 Рефералов: {stats['referrals']}",
        reply_markup=admin_kb(), parse_mode="Markdown"
    )

@dp.message(Command(commands=["approve"]))
async def approve_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split("_")
    if len(parts) < 3:
        await message.answer("Формат: /approve_USERID_PLANID")
        return
    try:
        user_id = int(parts[1])
        plan_id = parts[2]
    except:
        await message.answer("Неверный формат.")
        return
    plan = next((p for p in PLANS if p['id'] == plan_id), None)
    if not plan:
        await message.answer("План не найден.")
        return
    await message.answer(f"⏳ Создаю ключ для {user_id}...")
    sub = await db.get_subscription(user_id)
    if sub and sub.get('happ_key_id'):
        ok = await happ_extend_key(sub['happ_key_id'], plan['days'])
        if ok:
            await db.extend_subscription(user_id, plan['days'])
        else:
            await message.answer("❌ Ошибка продления ключа Happ.")
            return
    else:
        key = await happ_create_key(user_id, plan['days'])
        if not key:
            await message.answer("❌ Ошибка создания ключа Happ. Проверьте API.")
            return
        await db.create_subscription(user_id, key, plan['days'])
    sub = await db.get_subscription(user_id)
    days_left = (sub['expires_at'] - datetime.utcnow()).days
    key = sub['happ_key']
    try:
        await bot.send_message(
            user_id,
            f"🎉 **Оплата подтверждена! VPN активирован.**\n\n"
            f"📦 {plan['name']} · {plan['days']} дней\n\n"
            f"Нажмите кнопку для настройки:",
            reply_markup=setup_kb(key, days_left, plan['days']),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"User notify: {e}")
    await message.answer(f"✅ Подписка активирована для {user_id}!")

@dp.message(Command(commands=["reject"]))
async def reject_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split("_")
    if len(parts) < 2:
        return
    try:
        user_id = int(parts[1])
    except:
        return
    try:
        await bot.send_message(
            user_id,
            "❌ Платёж не подтверждён. Свяжитесь с поддержкой:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Поддержка", url=SUPPORT_URL)]
            ])
        )
    except:
        pass
    await message.answer(f"✅ Пользователь {user_id} уведомлён.")

async def main():
    await db.init()
    logger.info(f"🤖 {BOT_NAME} запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
