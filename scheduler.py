import time
import logging
import schedule
import asyncio
import pytz
import psycopg2.extras
from datetime import datetime, timedelta
from database import Database
from news_api import NewsAPI
from ai_processor import AIProcessor
from telegram_publisher import TelegramPublisher

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self):
        self.db = Database()
        self.news_api = NewsAPI(self.db)
        self.ai_processor = AIProcessor(self.db)
        self.publisher = TelegramPublisher(self.db)
        
        # Настройка расписания
        self.setup_schedule()
    
    def setup_schedule(self):
        """Настройка расписания задач с учетом часового пояса"""
        # Получение часового пояса из настроек
        timezone_name = self.db.get_schedule_setting('timezone') or 'Europe/Moscow'
        try:
            tz = pytz.timezone(timezone_name)
            logger.info(f"Используется часовой пояс: {timezone_name}")
        except pytz.exceptions.UnknownTimeZoneError:
            logger.error(f"Неизвестный часовой пояс: {timezone_name}, используется UTC")
            tz = pytz.UTC
        
        # Сбор новостей каждый день в 6:00
        schedule.every().day.at("06:00").do(self.collect_news)
        
        # Обработка новостей каждый день в 7:00
        schedule.every().day.at("07:00").do(self.process_news)
        
        # Получение времени публикации из настроек
        publish_times = []
        for i in range(1, 4):  # Получаем 3 времени публикации
            time_setting = self.db.get_schedule_setting(f'publish_time_{i}')
            if time_setting:
                publish_times.append(time_setting)
        
        # Если настройки не найдены, используем значения по умолчанию
        if not publish_times:
            publish_times = ["09:00", "12:00", "18:00"]
            logger.warning("Не найдены настройки времени публикации, используются значения по умолчанию")
        
        # Настройка расписания публикаций
        for publish_time in publish_times:
            schedule.every().day.at(publish_time).do(self.publish_news)
            logger.info(f"Запланирована публикация новостей в {publish_time} ({timezone_name})")
        
        # Проверка запланированных постов каждые 15 минут
        schedule.every(15).minutes.do(self.check_scheduled_posts_wrapper)
        logger.info("Настроена периодическая проверка запланированных постов каждые 15 минут")
        
        # Сбор новостей каждый час
        schedule.every(1).hour.do(self.collect_hourly_news_wrapper)
        logger.info("Настроен часовой сбор новостей")
        
        logger.info("Расписание задач настроено")
    
    def collect_news(self):
        """Задача сбора новостей"""
        try:
            logger.info("Запуск задачи сбора новостей")
            saved_count = self.news_api.collect_daily_news()
            logger.info(f"Задача сбора новостей завершена, сохранено {saved_count} новостей")
            return saved_count
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи сбора новостей: {e}")
            return 0
    
    def process_news(self):
        """Задача обработки новостей"""
        try:
            logger.info("Запуск задачи обработки новостей")
            
            # Получение необработанных новостей из базы данных
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, title, content, url, category
                    FROM news
                    WHERE processed = FALSE
                    ORDER BY published_date DESC
                    LIMIT 10
                """)
                news_items = [{
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'url': row[3],
                    'category': row[4]
                } for row in cursor.fetchall()]
            
            if not news_items:
                logger.info("Нет новостей для обработки")
                return 0
            
            # Обработка новостей через AI
            results = self.ai_processor.process_batch(news_items, batch_size=5)
            
            # Подсчет успешно обработанных новостей
            success_count = sum(1 for result in results if result.get("success", False))
            
            logger.info(f"Задача обработки новостей завершена, обработано {success_count} новостей")
            return success_count
        
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи обработки новостей: {e}")
            return 0
    
    async def publish_news_async(self):
        """Асинхронная задача публикации новостей с учетом московского времени"""
        try:
            # Получение часового пояса из настроек
            timezone_name = self.db.get_schedule_setting('timezone') or 'Europe/Moscow'
            try:
                tz = pytz.timezone(timezone_name)
            except pytz.exceptions.UnknownTimeZoneError:
                logger.error(f"Неизвестный часовой пояс: {timezone_name}, используется UTC")
                tz = pytz.UTC
                
            # Текущее время в настроенном часовом поясе
            now = datetime.now(tz)
            logger.info(f"Запуск задачи публикации новостей (текущее время {timezone_name}: {now.strftime('%H:%M:%S')})")
            
            published_count = await self.publisher.publish_batch(limit=2)  # Публикация до 2 новостей за раз
            logger.info(f"Задача публикации новостей завершена, опубликовано {published_count} новостей")
            return published_count
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи публикации новостей: {e}")
            return 0
    
    def publish_news(self):
        """Обертка для запуска асинхронной задачи публикации"""
        try:
            # Создаем новый event loop для каждого вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.publish_news_async())
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи публикации новостей: {e}")
            return 0
    
    async def check_scheduled_posts(self):
        """Проверка и публикация запланированных постов"""
        try:
            # Получение часового пояса из настроек
            timezone_name = self.db.get_schedule_setting('timezone') or 'Europe/Moscow'
            try:
                tz = pytz.timezone(timezone_name)
            except pytz.exceptions.UnknownTimeZoneError:
                logger.error(f"Неизвестный часовой пояс: {timezone_name}, используется UTC")
                tz = pytz.UTC
                
            # Текущее время в настроенном часовом поясе
            now = datetime.now(tz)
            logger.info(f"Проверка запланированных постов (текущее время {timezone_name}: {now.strftime('%Y-%m-%d %H:%M:%S')})")
            
            # Получение запланированных постов, время публикации которых уже наступило
            with self.db.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute("""
                    SELECT n.id, n.title, n.content, n.url, n.published_date, n.category,
                           p.processed_title, p.processed_content, 
                           s.id as schedule_id, s.scheduled_date, s.status, s.attempts
                    FROM news n
                    JOIN processed_news p ON n.id = p.news_id
                    JOIN scheduled_posts s ON n.id = s.news_id
                    WHERE n.processed = TRUE AND n.published = FALSE
                      AND s.status = 'pending'
                      AND s.scheduled_date <= %s
                    ORDER BY s.scheduled_date ASC
                    LIMIT 5
                """, (now,))
                scheduled_posts = cursor.fetchall()
            
            if not scheduled_posts:
                logger.debug("Нет запланированных постов для публикации в данный момент")
                return 0
            
            logger.info(f"Найдено {len(scheduled_posts)} запланированных постов для публикации")
            
            # Публикация найденных постов
            published_count = 0
            for post in scheduled_posts:
                logger.info(f"Публикация запланированного поста #{post['id']} (запланирован на {post['scheduled_date']})")
                
                # Обновление статуса поста на 'publishing'
                self.db.update_post_status(post['schedule_id'], 'publishing')
                
                try:
                    # Правильный вызов асинхронной функции с await
                    success = await self.publisher.publish_news(post)
                    
                    if success:
                        # Отметка поста как опубликованного
                        self.db.mark_as_published(post['id'])
                        # Обновление статуса в таблице scheduled_posts
                        self.db.update_post_status(post['schedule_id'], 'published', increment_attempts=False)
                        published_count += 1
                        # Логируем успешную публикацию только при успехе
                        logger.info(f"Пост #{post['id']} успешно опубликован")
                    else:
                        # Если публикация не удалась, обновляем статус
                        if post['attempts'] >= 3:
                            self.db.update_post_status(post['schedule_id'], 'failed')
                            logger.error(f"Пост #{post['id']} не удалось опубликовать после {post['attempts']+1} попыток")
                        else:
                            self.db.update_post_status(post['schedule_id'], 'pending')
                            logger.warning(f"Не удалось опубликовать пост #{post['id']}, попытка {post['attempts']+1}")
                except Exception as e:
                    logger.error(f"Ошибка при публикации поста #{post['id']}: {e}")
                    # Обновление статуса и увеличение счетчика попыток
                    self.db.update_post_status(post['schedule_id'], 'error', increment_attempts=True)
                
                # Пауза между публикациями
                await asyncio.sleep(1)
            
            return published_count
            
        except Exception as e:
            logger.error(f"Ошибка при проверке запланированных постов: {e}")
            return 0
    
    def check_scheduled_posts_wrapper(self):
        """Обертка для запуска асинхронной задачи проверки запланированных постов"""
        try:
            # Создаем новый event loop для каждого вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.check_scheduled_posts())
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Ошибка при проверке запланированных постов: {e}")
            return 0
    
    def collect_hourly_news_wrapper(self):
        """Обертка для запуска асинхронной задачи часового сбора новостей"""
        try:
            logger.info("Запуск задачи часового сбора новостей")
            # Создаем новый event loop для каждого вызова
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.news_api.collect_hourly_news())
            loop.close()
            logger.info(f"Задача часового сбора новостей завершена, сохранено {result} новостей")
            return result
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи часового сбора новостей: {e}")
            return 0
    
    def run(self):
        """Запуск планировщика задач"""
        logger.info("Запуск планировщика задач")
        
        try:
            # Проверяем запланированные посты при запуске
            self.check_scheduled_posts_wrapper()
            
            # Бесконечный цикл для выполнения запланированных задач
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Планировщик задач остановлен пользователем")
        except Exception as e:
            logger.error(f"Ошибка в работе планировщика задач: {e}")
        finally:
            # Закрытие соединений
            self.db.close()
            asyncio.run(self.publisher.close())
            logger.info("Планировщик задач завершил работу")