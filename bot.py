import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import httpx
from aiogram.client.session.aiohttp import AiohttpSession

# Читаем токен из окружения (в коде самого токена НЕТ)
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "ОШИБКА: Переменная BOT_TOKEN не найдена в окружении системы!"
    )

session = AiohttpSession(proxy="http://proxy.server:3128")
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

# Хранилище подписок: {user_id: {"regions": set(), "night_mode": False, "filter": "all"}}
users_data = {}

# Хранилище текущих активных тревог: {"регион": "тип_тревоги"}
current_active_alerts = {}


# -------------------------------------------------------------------
# Парсинг данных с radar-map.ru / API
# -------------------------------------------------------------------
async def fetch_active_alerts() -> dict:
    """
    Возвращает словарь формата:
    {'ульяновская область': 'bpla', 'белгородская область': 'missile'}
    """
    url = "https://radar-map.ru/api/alerts"
    active_alerts = {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                for item in data.get("alerts", []):
                    region = item.get("region", "").strip().lower()
                    # Тип угрозы: bpla, missile, air, etc. (по умолчанию bpla)
                    alert_type = item.get("type", "bpla").strip().lower()
                    if region:
                        active_alerts[region] = alert_type
    except Exception as e:
        logging.error(f"Ошибка запроса к API: {e}")

    return active_alerts


# -------------------------------------------------------------------
# Вспомогательные функции форматирования
# -------------------------------------------------------------------
def get_alert_text(alert_type: str) -> str:
    types_map = {
        "bpla": "🛸 **Опасность атаки БПЛА!**",
        "missile": "🚀 **Ракетная опасность!**",
        "air": "✈️ **Воздушная тревога (Авиаудар)!**",
    }
    return types_map.get(
        alert_type, "⚠️ **Объявлена тревога (повышенная опасность)!**"
    )


def is_night_time() -> bool:
    current_hour = datetime.now().hour
    return current_hour >= 23 or current_hour < 7


# -------------------------------------------------------------------
# Фоновый цикл проверки
# -------------------------------------------------------------------
async def alert_checker_loop():
    global current_active_alerts

    while True:
        try:
            new_alerts = await fetch_active_alerts()

            # Регионы, где тревога ТОЛЬКО ЧТО началась
            started_regions = set(new_alerts.keys()) - set(
                current_active_alerts.keys()
            )
            # Регионы, где тревога ТОЛЬКО ЧТО закончилась
            ended_regions = set(current_active_alerts.keys()) - set(
                new_alerts.keys()
            )

            current_active_alerts = new_alerts

            # 1. Отправка уведомлений о НАЧАЛЕ тревоги
            for region in started_regions:
                alert_type = new_alerts[region]
                alert_title = get_alert_text(alert_type)

                for user_id, udata in users_data.items():
                    if region in udata.get("regions", set()):
                        # Проверка ночного режима
                        if udata.get("night_mode") and is_night_time():
                            continue

                        # Проверка фильтра угроз
                        user_filter = udata.get("filter", "all")
                        if user_filter != "all" and user_filter != alert_type:
                            continue

                        text = (
                            f"🚨 **ВНИМАНИЕ! СРОЧНОЕ ОПОВЕЩЕНИЕ**\n\n"
                            f"Регион: **{region.title()}**\n"
                            f"Тип угрозы: {alert_title}\n\n"
                            f"🕒 Время: {datetime.now().strftime('%H:%M')}\n"
                            f"📍 *Соблюдайте меры безопасности и пройдите в укрытие!*"
                        )
                        await bot.send_message(
                            chat_id=user_id, text=text, parse_mode="Markdown"
                        )

            # 2. Отправка уведомлений об ОТМЕНЕ тревоги
            for region in ended_regions:
                for user_id, udata in users_data.items():
                    if region in udata.get("regions", set()):
                        if udata.get("night_mode") and is_night_time():
                            continue

                        text = (
                            f"✅ **ОТМЕНА ТРЕВОГИ**\n\n"
                            f"Регион: **{region.title()}**\n"
                            f"🕒 Время: {datetime.now().strftime('%H:%M')}\n"
                            f"🟢 *Опасность миновала. Можно покинуть укрытие.*"
                        )
                        await bot.send_message(
                            chat_id=user_id, text=text, parse_mode="Markdown"
                        )

        except Exception as e:
            logging.error(f"Ошибка в цикле мониторинга: {e}")

        await asyncio.sleep(30)


# -------------------------------------------------------------------
# Клавиатуры и Кнопки
# -------------------------------------------------------------------
def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Мои подписки", callback_data="my_subs")
    builder.button(text="📊 Сводка тревог", callback_data="status_all")
    builder.button(text="⚙️ Настройки", callback_data="settings")
    builder.button(text="❓ Помощь", callback_data="help")
    builder.adjust(2, 2)
    return builder.as_markup()


# -------------------------------------------------------------------
# Обработчики команд
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {
            "regions": set(),
            "night_mode": False,
            "filter": "all",
        }

    text = (
        f"👋 Привет, **{message.from_user.first_name}**!\n\n"
        f"Я бот оперативности и отслеживания воздушных угроз (БПЛА, ракетная опасность).\n\n"
        f"📌 **Как пользоваться:**\n"
        f"Отправь команду `/subscribe <город/область>`, чтобы подписаться на регион.\n"
        f"Пример: `/subscribe ульяновская область`\n\n"
        f"Используй меню ниже для быстрого управления:"
    )
    await message.answer(
        text, parse_mode="Markdown", reply_markup=get_main_keyboard()
    )


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {
            "regions": set(),
            "night_mode": False,
            "filter": "all",
        }

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "⚠️ Укажите область или город.\nПример: `/subscribe ульяновская область`",
            parse_mode="Markdown",
        )
        return

    region = args[1].strip().lower()
    users_data[user_id]["regions"].add(region)
    await message.answer(
        f"✅ Вы подписались на регион: **{region.title()}**\n"
        f"Бот оповестит вас при первой же угрозе!",
        parse_mode="Markdown",
    )


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "Укажите область для отписки. Пример: `/unsubscribe ульяновская область`",
            parse_mode="Markdown",
        )
        return

    region = args[1].strip().lower()
    if (
        user_id in users_data
        and region in users_data[user_id].get("regions", set())
    ):
        users_data[user_id]["regions"].remove(region)
        await message.answer(
            f"❌ Вы отписались от: **{region.title()}**", parse_mode="Markdown"
        )
    else:
        await message.answer("Вы не были подписаны на этот регион.")


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not current_active_alerts:
        await message.answer(
            "🟢 **На текущий момент тревог по регионам не зафиксировано.**",
            parse_mode="Markdown",
        )
    else:
        text = "🚨 **ТЕКУЩИЕ АКТИВНЫЕ ТРЕВОГИ В РФ:**\n\n"
        for region, alert_type in current_active_alerts.items():
            text += f"• **{region.title()}**: {get_alert_text(alert_type)}\n"
        await message.answer(text, parse_mode="Markdown")


# -------------------------------------------------------------------
# Интерактивная обработка Callback-кнопок
# -------------------------------------------------------------------
@dp.callback_query(F.data == "my_subs")
async def callback_my_subs(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    regions = users_data.get(user_id, {}).get("regions", set())

    if not regions:
        await callback.message.edit_text(
            "У вас нет активных подписок.\nИспользуйте `/subscribe <название>`, чтобы добавить регион.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    builder = InlineKeyboardBuilder()
    for reg in regions:
        # Кнопка для удаления конкретного региона в 1 клик
        builder.button(
            text=f"❌ Удалить {reg.title()}", callback_data=f"del_{reg}"
        )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)

    await callback.message.edit_text(
        "📍 **Ваши подписки:**\nНажмите на область ниже, чтобы удалить её из списка:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data.startswith("del_"))
async def callback_delete_region(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    region_to_del = callback.data.replace("del_", "")

    if (
        user_id in users_data
        and region_to_del in users_data[user_id]["regions"]
    ):
        users_data[user_id]["regions"].remove(region_to_del)
        await callback.answer(f"Регион {region_to_del.title()} удален!")

    # Возвращаемся в список подписок
    await callback_my_subs(callback)


@dp.callback_query(F.data == "status_all")
async def callback_status(callback: types.CallbackQuery):
    if not current_active_alerts:
        text = "🟢 **На текущий момент активных тревог в РФ не зафиксировано.**"
    else:
        text = "🚨 **АКТИВНЫЕ ТРЕВОГИ ПРЯМО СЕЙЧАС:**\n\n"
        for region, alert_type in current_active_alerts.items():
            text += f"• **{region.title()}**: {get_alert_text(alert_type)}\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="status_all")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)

    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "settings")
async def callback_settings(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    udata = users_data.get(
        user_id, {"regions": set(), "night_mode": False, "filter": "all"}
    )

    night_status = "🌙 Включен (Без звука 23:00-07:00)" if udata.get("night_mode") else "☀️ Выключен"
    filter_status = udata.get("filter", "all").upper()

    text = (
        f"⚙️ **НАСТРОЙКИ УВЕДОМЛЕНИЙ**\n\n"
        f"• Ночной режим: **{night_status}**\n"
        f"• Фильтр угроз: **{filter_status}**\n\n"
        f"Нажмите на кнопку ниже, чтобы изменить:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text="🌙 Переключить Ночной режим", callback_data="toggle_night"
    )
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)

    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "toggle_night")
async def callback_toggle_night(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in users_data:
        users_data[user_id]["night_mode"] = not users_data[user_id].get(
            "night_mode", False
        )

    await callback_settings(callback)


@dp.callback_query(F.data == "back_main")
async def callback_back_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Главное меню управления ботом:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


# -------------------------------------------------------------------
# Запуск
# -------------------------------------------------------------------
async def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.create_task(alert_checker_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    
