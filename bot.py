import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import httpximport os

# Код считывает токен из настроек сервера
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище в памяти
user_subscriptions = {}
current_active_alerts = set()

async def fetch_active_alerts() -> set:
    """Запрос данных о тревогах"""
    url = "https://radar-map.ru/api/alerts"
    active_regions = set()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                for item in data.get("alerts", []):
                    region_name = item.get("region", "").strip().lower()
                    if region_name:
                        active_regions.add(region_name)
    except Exception as e:
        logging.error(f"Ошибка получения данных: {e}")
        
    return active_regions

async def alert_checker_loop():
    """Фоновый цикл проверки изменений тревог"""
    global current_active_alerts
    while True:
        try:
            new_alerts = await fetch_active_alerts()
            
            started_alerts = new_alerts - current_active_alerts
            ended_alerts = current_active_alerts - new_alerts
            
            current_active_alerts = new_alerts
            
            # Уведомления о начале тревоги
            for region in started_alerts:
                for user_id, regions in user_subscriptions.items():
                    if region in regions:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"🚨 **ВНИМАНИЕ! ОБЪЯВЛЕНА ТРЕВОГА!**\n\nРегион/Город: **{region.title()}**"
                        )
            
            # Уведомления об отмене тревоги
            for region in ended_alerts:
                for user_id, regions in user_subscriptions.items():
                    if region in regions:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"✅ **ТРЕВОГА СНЯТА**\n\nРегион/Город: **{region.title()}**"
                        )
                        
        except Exception as e:
            logging.error(f"Ошибка в цикле проверки: {e}")
            
        await asyncio.sleep(30)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот отслеживания тревог и БПЛА.\n\n"
        "Команды:\n"
        "• `/subscribe <город/область>` — подписаться\n"
        "• `/unsubscribe <город/область>` — отписаться\n"
        "• `/list` — мои подписки"
    )

@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите область или город. Пример: `/subscribe ульяновская область`")
        return
    
    region = args[1].strip().lower()
    user_id = message.from_user.id
    
    if user_id not in user_subscriptions:
        user_subscriptions[user_id] = set()
        
    user_subscriptions[user_id].add(region)
    await message.answer(f"✅ Вы успешно подписались на: **{region.title()}**")

@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите область или город. Пример: `/unsubscribe ульяновская область`")
        return
    
    region = args[1].strip().lower()
    user_id = message.from_user.id
    
    if user_id in user_subscriptions and region in user_subscriptions[user_id]:
        user_subscriptions[user_id].remove(region)
        await message.answer(f"❌ Вы отписались от: **{region.title()}**")
    else:
        await message.answer("Вы не были подписаны на этот регион.")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    user_id = message.from_user.id
    subs = user_subscriptions.get(user_id, set())
    if not subs:
        await message.answer("У вас нет активных подписок.")
    else:
        regions_list = "\n".join([f"• {r.title()}" for r in subs])
        await message.answer(f"Ваши подписки:\n{regions_list}")

async def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.create_task(alert_checker_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
