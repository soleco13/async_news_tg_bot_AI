import os
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database import Database
from web_scraper import WebScraper

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("news_api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NewsAPI:
    def __init__(self, db):
        self.api_key = os.getenv('NEWS_API_KEY')
        self.base_url = "https://newsdata.io/api/1/news"
        self.db = db
        self.daily_limit = 1000  # Увеличенный лимит запросов в сутки (было 200)
        self.categories = ["technology"]  # Категория для поиска IT-новостей
        self.keywords = ["IT", "software", "developer", "programming", "coding", "AI", "Web3",
    "cybersecurity", "cloud", "data science", "blockchain", "DevOps",
    "machine learning", "UX", "UI", "frontend", "backend", "fullstack",
    "artificial intelligence", "tech industry", "startups"]
        self.scraper = WebScraper(db)  # Инициализация скрапера для получения полного текста статей
        self.min_content_length = 200  # Минимальная длина контента для обработки (в символах)
        self.hourly_search_limit = 20  # Лимит новостей для поиска каждый час
        self.last_notification_time = datetime.now()  # Время последнего уведомления
    
    def check_api_limit(self):
        """Проверка лимита запросов к API"""
        current_count = self.db.get_api_requests_count("newsdata.io", 24)
        logger.info(f"Текущее количество запросов к API: {current_count}/{self.daily_limit}")
        # Убираем проверку лимита, чтобы всегда возвращать True
        # return current_count < self.daily_limit
        return True
    
    def fetch_news(self, category=None, keyword=None, max_results=10):
        """Получение новостей по категории или ключевому слову"""
        if not self.check_api_limit():
            logger.warning("Достигнут дневной лимит запросов к API")
            return []
        
        params = {
            "apikey": self.api_key,
            "language": "en",  # Английский язык
            "size": max_results  # Количество результатов
        }
        
        if category:
            params["category"] = category
        
        if keyword:
            params["q"] = keyword
        
        try:
            logger.info(f"Отправка запроса к API с параметрами: {params}")
            response = requests.get(self.base_url, params=params)
            self.db.log_api_request("newsdata.io", response.status_code == 200)
            
            if response.status_code != 200:
                logger.error(f"Ошибка API: {response.status_code} - {response.text}")
                return []
            
            data = response.json()
            if data.get("status") != "success":
                logger.error(f"Ошибка в ответе API: {data}")
                return []
            
            articles = data.get("results", [])
            logger.info(f"Получено {len(articles)} новостей")
            return articles
        
        except Exception as e:
            logger.error(f"Ошибка при получении новостей: {e}")
            self.db.log_api_request("newsdata.io", False)
            return []
    
    def filter_news(self, articles):
        """Фильтрация новостей по качеству и обогащение контента"""
        filtered_articles = []
        
        for article in articles:
            # Проверка наличия необходимых полей
            if not article.get("title") or not article.get("link"):
                logger.warning(f"Пропуск статьи без необходимых полей: {article.get('title', 'Без заголовка')}")
                continue
            
            # Проверка наличия и длины контента
            content = article.get("content", "")
            url = article.get("link")
            
            # Если контент отсутствует или слишком короткий, пытаемся получить полный текст
            if not content or len(content) < self.min_content_length:
                logger.info(f"Контент статьи '{article.get('title')}' слишком короткий ({len(content)} символов). Пытаемся получить полный текст.")
                full_content = self.scraper.get_full_article_content(url)
                
                if full_content and len(full_content) > len(content):
                    logger.info(f"Успешно получен полный текст статьи ({len(full_content)} символов)")
                    article["content"] = full_content
                elif not full_content and not content:
                    logger.warning(f"Не удалось получить контент для статьи: {article.get('title')}")
                    continue
            
            # Добавление прошедшей фильтрацию и обогащение статьи
            filtered_articles.append(article)
        
        logger.info(f"После фильтрации и обогащения осталось {len(filtered_articles)} новостей")
        return filtered_articles
    
    def save_news_to_db(self, articles):
        """Сохранение новостей в базу данных"""
        saved_count = 0
        
        for article in articles:
            title = article.get("title", "")
            content = article.get("content", "")
            url = article.get("link", "")
            
            # Преобразование даты публикации
            pub_date_str = article.get("pubDate", "")
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pub_date = datetime.now()
            
            # Определение категории
            category = "technology"  # По умолчанию технологии
            for keyword in self.keywords:
                if keyword.lower() in title.lower() or keyword.lower() in content.lower():
                    category = keyword.lower()
                    break
            
            # Логирование информации о длине контента
            logger.info(f"Сохранение новости '{title}' с контентом длиной {len(content)} символов")
            
            # Сохранение в базу данных
            news_id = self.db.save_news(title, content, url, pub_date, category)
            if news_id:
                saved_count += 1
        
        logger.info(f"Сохранено {saved_count} новостей в базу данных")
        return saved_count
    
    def collect_daily_news(self):
        """Сбор ежедневных новостей по всем категориям и ключевым словам"""
        all_articles = []
        
        # Сбор по категориям
        for category in self.categories:
            articles = self.fetch_news(category=category)
            all_articles.extend(articles)
            # Пауза между запросами для избежания блокировки
            time.sleep(1)
        
        # Сбор по ключевым словам
        for keyword in self.keywords:
            articles = self.fetch_news(keyword=keyword)
            all_articles.extend(articles)
            # Пауза между запросами
            time.sleep(1)
        
        # Удаление дубликатов по URL
        unique_articles = {}
        for article in all_articles:
            url = article.get("link", "")
            if url and url not in unique_articles:
                unique_articles[url] = article
        
        # Фильтрация и сохранение
        filtered_articles = self.filter_news(list(unique_articles.values()))
        saved_count = self.save_news_to_db(filtered_articles)
        
        # Автоматическое планирование новых постов
        if saved_count > 0:
            self.schedule_new_posts()
            self.send_admin_notification(saved_count)
        
        return saved_count
        
    async def collect_hourly_news(self):
        """Асинхронный сбор новостей каждый час"""
        logger.info("Запуск часового сбора новостей")
        all_articles = []
        
        # Выбираем случайные ключевые слова для этого часа, чтобы не превышать лимиты API
        import random
        selected_keywords = random.sample(self.keywords, min(5, len(self.keywords)))
        
        # Сбор по выбранным ключевым словам
        for keyword in selected_keywords:
            if not self.check_api_limit():
                logger.warning("Достигнут дневной лимит запросов к API")
                break
                
            articles = self.fetch_news(keyword=keyword, max_results=5)
            all_articles.extend(articles)
            # Пауза между запросами
            await asyncio.sleep(1)
        
        # Удаление дубликатов по URL
        unique_articles = {}
        for article in all_articles:
            url = article.get("link", "")
            if url and url not in unique_articles:
                unique_articles[url] = article
        
        # Асинхронная обработка URL для получения полного текста
        urls_to_process = [article.get("link", "") for article in unique_articles.values()]
        if urls_to_process:
            # Обработка URL асинхронно
            processed_results = await self.scraper.process_urls_batch(urls_to_process, max_concurrent=5)
            
            # Обновление статей полным текстом
            for result in processed_results:
                url = result.get("url")
                content = result.get("content")
                if url in unique_articles and content:
                    unique_articles[url]["content"] = content
        
        # Фильтрация и сохранение
        filtered_articles = self.filter_news(list(unique_articles.values()))
        saved_count = self.save_news_to_db(filtered_articles)
        
        # Автоматическое планирование новых постов
        if saved_count > 0:
            self.schedule_new_posts()
            self.send_admin_notification(saved_count)
        
        logger.info(f"Часовой сбор новостей завершен, сохранено {saved_count} новостей")
        return saved_count
        
    def schedule_new_posts(self):
        """Автоматическое планирование новых постов"""
        try:
            # Получение необработанных новостей
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT n.id
                    FROM news n
                    LEFT JOIN scheduled_posts sp ON n.id = sp.news_id
                    WHERE n.processed = TRUE AND sp.id IS NULL
                    ORDER BY n.published_date DESC
                    LIMIT 10
                """)
                news_ids = [row[0] for row in cursor.fetchall()]
            
            if not news_ids:
                logger.info("Нет новых обработанных новостей для планирования")
                return 0
            
            # Получение настроек времени публикации
            timezone_name = self.db.get_schedule_setting('timezone') or 'Europe/Moscow'
            
            # Получение следующих доступных слотов для публикации
            now = datetime.now()
            scheduled_count = 0
            
            for news_id in news_ids:
                # Определение следующего доступного времени публикации
                # Начинаем с текущего времени + 1 час и округляем до следующего часа
                next_hour = now + timedelta(hours=1)
                scheduled_time = datetime(next_hour.year, next_hour.month, next_hour.day, 
                                         next_hour.hour, 0, 0)
                
                # Планирование публикации
                with self.db.conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO scheduled_posts (news_id, scheduled_date, status)
                        VALUES (%s, %s, 'pending')
                        ON CONFLICT (news_id) DO NOTHING
                        RETURNING id
                    """, (news_id, scheduled_time))
                    result = cursor.fetchone()
                    
                    if result:
                        scheduled_count += 1
                        # Увеличиваем время для следующего поста на 1 час
                        now = scheduled_time
                
                self.db.conn.commit()
            
            logger.info(f"Запланировано {scheduled_count} новых постов")
            return scheduled_count
            
        except Exception as e:
            logger.error(f"Ошибка при планировании новых постов: {e}")
            self.db.conn.rollback()
            return 0
            
    def send_admin_notification(self, count):
        """Отправка уведомления администраторам о новых постах"""
        try:
            # Проверяем, прошло ли достаточно времени с последнего уведомления (минимум 30 минут)
            now = datetime.now()
            if (now - self.last_notification_time).total_seconds() < 1800:  # 30 минут = 1800 секунд
                logger.debug("Слишком рано для отправки нового уведомления")
                return
            
            # Сохраняем уведомление в базе данных для отображения в админ-панели
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO admin_notifications (message, type, created_at)
                    VALUES (%s, %s, %s)
                """, (
                    f"Добавлено {count} новых постов в очередь публикации",
                    "new_posts",
                    now
                ))
                self.db.conn.commit()
            
            # Обновляем время последнего уведомления
            self.last_notification_time = now
            logger.info(f"Отправлено уведомление администраторам о {count} новых постах")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления администраторам: {e}")
            self.db.conn.rollback()
            
    async def collect_hourly_news(self):
        """Асинхронный сбор новостей каждый час"""
        # Просто вызываем асинхронный метод, так как этот метод теперь сам асинхронный
        return await self.collect_hourly_news_async()
            
    async def collect_hourly_news_async(self):
        """Асинхронный сбор новостей каждый час"""
        logger.info("Запуск часового сбора новостей")
        all_articles = []
        
        try:
            # Выбираем случайные ключевые слова для этого часа, чтобы не превышать лимиты API
            import random
            selected_keywords = random.sample(self.keywords, min(5, len(self.keywords)))
            
            # Сбор по выбранным ключевым словам
            for keyword in selected_keywords:
                if not self.check_api_limit():
                    logger.warning("Достигнут дневной лимит запросов к API")
                    break
                    
                articles = self.fetch_news(keyword=keyword, max_results=5)
                all_articles.extend(articles)
                # Пауза между запросами
                await asyncio.sleep(1)
            
            # Удаление дубликатов по URL
            unique_articles = {}
            for article in all_articles:
                url = article.get("link", "")
                if url and url not in unique_articles:
                    unique_articles[url] = article
            
            # Асинхронная обработка URL для получения полного текста
            urls_to_process = [article.get("link", "") for article in unique_articles.values()]
            if urls_to_process:
                # Обработка URL асинхронно
                processed_results = await self.scraper.process_urls_batch(urls_to_process, max_concurrent=5)
                
                # Обновление статей полным текстом
                for result in processed_results:
                    url = result.get("url")
                    content = result.get("content")
                    if url in unique_articles and content:
                        unique_articles[url]["content"] = content
            
            # Фильтрация и сохранение
            filtered_articles = self.filter_news(list(unique_articles.values()))
            saved_count = self.save_news_to_db(filtered_articles)
            
            # Автоматическое планирование новых постов
            if saved_count > 0:
                self.schedule_new_posts()
                self.send_admin_notification(saved_count)
            
            logger.info(f"Часовой сбор новостей завершен, сохранено {saved_count} новостей")
            return saved_count
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении часового сбора новостей: {e}")
            return 0