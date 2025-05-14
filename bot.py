import os
import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from database import Database
from admin_panel import AdminPanel

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
dp = Dispatcher(storage=MemoryStorage())

# Инициализация базы данных
db = Database()

# Инициализация админ-панели
admin_panel = AdminPanel(bot, db)

# Регистрация роутера админ-панели
dp.include_router(admin_panel.router)

# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для управления каналом @async_news_bot.\n\n"
        "Доступные команды:\n"
        "/admin - Открыть админ-панель (только для администраторов)\n"
        "/help - Показать справку"
    )

# Обработчик команды /help
@dp.message(Command(commands=["help"]))
async def cmd_help(message: Message):
    await message.answer(
        "🔍 Справка по боту @async_news_bot\n\n"
        "Этот бот предназначен для управления публикациями в канале.\n\n"
        "Команды:\n"
        "/start - Начать работу с ботом\n"
        "/admin - Открыть админ-панель (только для администраторов)\n"
        "/help - Показать эту справку\n\n"
        "Функции админ-панели:\n"
        "- Просмотр запланированных постов\n"
        "- Изменение времени публикации\n"
        "- Просмотр статистики публикаций\n"
        "- Просмотр графика публикаций"
    )

async def main():
    logger.info("Запуск бота @async_news_bot")
    try:
        # Запуск бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Закрытие соединений при завершении работы
        await bot.session.close()
        db.close()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())