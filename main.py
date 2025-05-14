import os
import logging
import asyncio
from dotenv import load_dotenv
from scheduler import Scheduler
from news_api import NewsAPI
from ai_processor import AIProcessor
from database import Database

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("main.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def check_environment():
    """Проверка наличия необходимых переменных окружения"""
    required_vars = [
        'NEWS_API_KEY',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHANNEL_ID',
        'DB_HOST',
        'DB_PORT',
        'DB_NAME',
        'DB_USER',
        'DB_PASSWORD',
        'OPENAI_API_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")
        return False
    
    logger.info("Все необходимые переменные окружения найдены")
    return True

async def publish_news_on_startup():
    """Функция для немедленной публикации новости при запуске"""
    try:
        logger.info("Запуск процесса немедленной публикации новости")
        
        # Инициализация компонентов
        db = Database()
        news_api = NewsAPI(db)
        ai_processor = AIProcessor(db)
        
        # Сбор новостей
        logger.info("Сбор новостей для немедленной публикации")
        articles = news_api.fetch_news(max_results=5)  # Получаем 5 последних новостей
        
        if not articles:
            logger.warning("Не удалось получить новости для немедленной публикации")
            return False
        
        # Фильтрация и сохранение новостей
        filtered_articles = news_api.filter_news(articles)
        if not filtered_articles:
            logger.warning("После фильтрации не осталось подходящих новостей")
            return False
            
        saved_count = news_api.save_news_to_db(filtered_articles)
        logger.info(f"Сохранено {saved_count} новостей для немедленной публикации")
        
        # Получение сохраненных новостей из базы данных
        with db.conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, title, content, url, category
                FROM news
                WHERE processed = FALSE
                ORDER BY published_date DESC
                LIMIT 1
            """)
            news_items = [{
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'url': row[3],
                'category': row[4]
            } for row in cursor.fetchall()]
        
        if not news_items:
            logger.warning("Не найдено новостей в базе данных для обработки")
            return False
        
        # Обработка новости через AI
        logger.info(f"Обработка новости '{news_items[0]['title']}' с помощью AI")
        processed_result = ai_processor.process_news(news_items[0])
        
        if not processed_result.get("success", False):
            logger.error(f"Не удалось обработать новость: {processed_result.get('error', 'Неизвестная ошибка')}")
            return False
        
        # Получение обработанной новости для публикации
        with db.conn.cursor() as cursor:
            cursor.execute("""
                SELECT n.id, n.title, n.content, n.url, n.published_date, n.category,
                       p.processed_title, p.processed_content
                FROM news n
                JOIN processed_news p ON n.id = p.news_id
                WHERE n.id = %s
            """, (news_items[0]['id'],))
            row = cursor.fetchone()
            
            if not row:
                logger.error("Не удалось получить обработанную новость для публикации")
                return False
            
            news_to_publish = {
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'url': row[3],
                'published_date': row[4],
                'category': row[5],
                'processed_title': row[6],
                'processed_content': row[7]
            }
        
        # Публикация новости в Telegram
        logger.info("Публикация обработанной новости в Telegram-канал")
        scheduler = Scheduler()
        published = await scheduler.publisher.publish_news(news_to_publish)
        
        if published:
            logger.info(f"Новость успешно опубликована при запуске: {news_to_publish['processed_title']}")
            return True
        else:
            logger.error("Не удалось опубликовать новость при запуске")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при публикации новости при запуске: {e}")
        return False

def main():
    """Основная функция приложения"""
    logger.info("Запуск приложения Telegram-бота для публикации IT-новостей")
    
    # Проверка переменных окружения
    if not check_environment():
        logger.error("Приложение не может быть запущено из-за отсутствия необходимых переменных окружения")
        return
    
    try:
        # Создание планировщика
        scheduler = Scheduler()
        
        # Отправка тестового сообщения при запуске
        asyncio.run(scheduler.publisher.publish_test_message())
        logger.info("Тестовое сообщение отправлено при запуске")
        
        # Немедленная публикация новости при запуске
        result = asyncio.run(publish_news_on_startup())
        if result:
            logger.info("Немедленная публикация новости при запуске выполнена успешно")
        else:
            logger.warning("Не удалось выполнить немедленную публикацию новости при запуске")
        
        # Запуск планировщика
        scheduler.run()
    
    except Exception as e:
        logger.error(f"Критическая ошибка в работе приложения: {e}")
    
    finally:
        logger.info("Приложение завершило работу")

if __name__ == "__main__":
    main()