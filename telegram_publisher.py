import os
import logging
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from database import Database

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_publisher.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TelegramPublisher:
    def __init__(self, db):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.channel_id = os.getenv('TELEGRAM_CHANNEL_ID')
        self.db = db
        self.bot = Bot(token=self.bot_token)
        self.dp = Dispatcher()
    
    async def format_message(self, news_item):
        """Форматирование новости для публикации в Telegram"""
        try:
            # Получение обработанных данных
            title = news_item['processed_title']
            content = news_item['processed_content']
            url = news_item['url']
            category = news_item['category']
            
            # Формирование хэштегов
            hashtags = "#ITNews"
            if "ai" in category.lower() or "artificial intelligence" in category.lower():
                hashtags += " #AI"
            if "web3" in category.lower():
                hashtags += " #Web3"
            if "cybersecurity" in category.lower():
                hashtags += " #Cybersecurity"
            if "ux" in category.lower() or "ui" in category.lower():
                hashtags += " #UXUI"
            
            # Формирование сообщения в формате Markdown
            message = f"{title}\n\n{content}\n\n[Подробнее]({url})\n\n{hashtags}"
            
            return message
        except Exception as e:
            logger.error(f"Ошибка при форматировании сообщения: {e}")
            return None
    
    async def publish_news(self, news_item, max_retries=3):
        """Публикация новости в Telegram-канал с поддержкой повторных попыток"""
        retries = 0
        while retries < max_retries:
            try:
                # Форматирование сообщения
                message = await self.format_message(news_item)
                if not message:
                    logger.error(f"Не удалось сформировать сообщение для новости {news_item['id']}")
                    return False
                
                # Отправка сообщения в канал
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False
                )
                
                # Отметка новости как опубликованной в базе данных
                self.db.mark_as_published(news_item['id'])
                
                logger.info(f"Новость с ID {news_item['id']} успешно опубликована в канал {self.channel_id}")
                return True
            
            except Exception as e:
                retries += 1
                logger.warning(f"Попытка {retries}/{max_retries} публикации новости {news_item['id']} не удалась: {e}")
                
                if "Event loop is closed" in str(e):
                    logger.warning("Обнаружена ошибка закрытого event loop, пересоздаем соединение с Telegram API")
                    # Пересоздаем бота при ошибке с event loop
                    self.bot = Bot(token=self.bot_token)
                
                # Пауза перед следующей попыткой
                await asyncio.sleep(2 * retries)  # Увеличиваем время ожидания с каждой попыткой
        
        logger.error(f"Не удалось опубликовать новость {news_item['id']} после {max_retries} попыток")
        return False
    
    async def publish_batch(self, limit=5):
        """Публикация пакета новостей"""
        try:
            # Получение необработанных новостей из базы данных
            news_items = self.db.get_unpublished_news(limit)
            
            if not news_items:
                logger.info("Нет новостей для публикации")
                return 0
            
            published_count = 0
            for news_item in news_items:
                success = await self.publish_news(news_item)
                if success:
                    published_count += 1
                # Пауза между публикациями
                await asyncio.sleep(1)
            
            logger.info(f"Опубликовано {published_count} новостей из {len(news_items)}")
            return published_count
        
        except Exception as e:
            logger.error(f"Ошибка при публикации пакета новостей: {e}")
            return 0
    
    async def publish_test_message(self):
        """Публикация тестового сообщения при запуске бота"""
        try:
            logger.info("Отправка тестового сообщения в Telegram-канал")
            
            # Формирование тестового сообщения
            current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            message = f"🤖 Бот AsyncNews запущен и готов к работе!\n\n📅 Дата и время запуска: {current_time}\n\n#SystemMessage"
            
            # Отправка сообщения в канал
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            
            logger.info(f"Тестовое сообщение успешно отправлено в канал {self.channel_id}")
            return True
        
        except Exception as e:
            logger.error(f"Ошибка при отправке тестового сообщения: {e}")
            return False
    
    async def close(self):
        """Закрытие соединения с Telegram API"""
        await self.bot.session.close()
        logger.info("Соединение с Telegram API закрыто")