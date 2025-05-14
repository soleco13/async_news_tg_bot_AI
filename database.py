import os
import logging
import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("database.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Установка соединения с базой данных PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST'),
                port=os.getenv('DB_PORT'),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD')
            )
            logger.info("Успешное подключение к базе данных PostgreSQL")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise
    
    def create_tables(self):
        """Создание необходимых таблиц, если они не существуют"""
        try:
            with self.conn.cursor() as cursor:
                # Таблица для хранения новостей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS news (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        url TEXT NOT NULL,
                        published_date TIMESTAMP NOT NULL,
                        category TEXT NOT NULL,
                        processed BOOLEAN DEFAULT FALSE,
                        published BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Таблица для хранения обработанных новостей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_news (
                        id SERIAL PRIMARY KEY,
                        news_id INTEGER REFERENCES news(id),
                        processed_title TEXT NOT NULL,
                        processed_content TEXT NOT NULL,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Таблица для отслеживания запросов к API
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_requests (
                        id SERIAL PRIMARY KEY,
                        api_name TEXT NOT NULL,
                        request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        success BOOLEAN NOT NULL
                    )
                """)
                
                # Таблица для хранения настроек расписания
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schedule_settings (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(50) UNIQUE NOT NULL,
                        value VARCHAR(255) NOT NULL,
                        description TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Таблица для хранения запланированных постов
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_posts (
                        id SERIAL PRIMARY KEY,
                        news_id INTEGER REFERENCES news(id),
                        scheduled_date TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status VARCHAR(20) DEFAULT 'pending',
                        attempts INTEGER DEFAULT 0,
                        last_attempt TIMESTAMP,
                        UNIQUE(news_id)
                    )
                """)
                
                # Таблица для хранения уведомлений администраторов
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS admin_notifications (
                        id SERIAL PRIMARY KEY,
                        message TEXT NOT NULL,
                        type VARCHAR(50) NOT NULL,
                        is_read BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Добавление настроек часового пояса и времени публикации, если их нет
                cursor.execute("""
                    INSERT INTO schedule_settings (name, value, description)
                    VALUES 
                    ('timezone', 'Europe/Moscow', 'Часовой пояс для планирования публикаций (например, Europe/Moscow)')
                    ON CONFLICT (name) DO NOTHING
                """)
                
                cursor.execute("""
                    INSERT INTO schedule_settings (name, value, description)
                    VALUES 
                    ('publish_time_1', '09:00', 'Первое время публикации (формат ЧЧ:ММ)'),
                    ('publish_time_2', '12:00', 'Второе время публикации (формат ЧЧ:ММ)'),
                    ('publish_time_3', '18:00', 'Третье время публикации (формат ЧЧ:ММ)')
                    ON CONFLICT (name) DO NOTHING
                """)
                
                self.conn.commit()
                logger.info("Таблицы успешно созданы или уже существуют")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise
    
    def save_news(self, title, content, url, published_date, category):
        """Сохранение новости в базу данных"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return False
                
            with self.conn.cursor() as cursor:
                # Проверка, существует ли уже новость с таким URL
                cursor.execute("SELECT id FROM news WHERE url = %s", (url,))
                if cursor.fetchone() is not None:
                    logger.info(f"Новость с URL {url} уже существует в базе данных")
                    return False
                
                # Вставка новой новости
                cursor.execute("""
                    INSERT INTO news (title, content, url, published_date, category)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (title, content, url, published_date, category))
                news_id = cursor.fetchone()[0]
                self.conn.commit()
                logger.info(f"Новость с ID {news_id} успешно сохранена")
                return news_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при сохранении новости: {e}")
            return False
    
    def save_processed_news(self, news_id, processed_title, processed_content):
        """Сохранение обработанной новости"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return False
                
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO processed_news (news_id, processed_title, processed_content)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (news_id, processed_title, processed_content))
                processed_id = cursor.fetchone()[0]
                
                # Обновление статуса обработки в таблице news
                cursor.execute("""
                    UPDATE news SET processed = TRUE
                    WHERE id = %s
                """, (news_id,))
                
                self.conn.commit()
                logger.info(f"Обработанная новость с ID {processed_id} успешно сохранена")
                return processed_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при сохранении обработанной новости: {e}")
            return False
    
    def mark_as_published(self, news_id):
        """Отметка новости как опубликованной"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return False
                
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE news SET published = TRUE
                    WHERE id = %s
                """, (news_id,))
                self.conn.commit()
                logger.info(f"Новость с ID {news_id} отмечена как опубликованная")
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при отметке новости как опубликованной: {e}")
            return False
    
    def get_unpublished_news(self, limit=5):
        """Получение необработанных новостей для публикации"""
        try:
            with self.conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT n.id, n.title, n.content, n.url, n.published_date, n.category,
                           p.processed_title, p.processed_content
                    FROM news n
                    JOIN processed_news p ON n.id = p.news_id
                    WHERE n.processed = TRUE AND n.published = FALSE
                    ORDER BY n.published_date DESC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении необработанных новостей: {e}")
            return []
    
    def log_api_request(self, api_name, success):
        """Логирование запроса к API"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO api_requests (api_name, success)
                    VALUES (%s, %s)
                """, (api_name, success))
                self.conn.commit()
                logger.info(f"Запрос к API {api_name} успешно залогирован")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при логировании запроса к API: {e}")
    
    def get_api_requests_count(self, api_name, hours=24):
        """Получение количества запросов к API за последние hours часов"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return 0
                
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM api_requests
                    WHERE api_name = %s AND request_time > NOW() - INTERVAL '%s hours'
                """, (api_name, hours))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка при получении количества запросов к API: {e}")
            return 0
    
    def close(self):
        """Закрытие соединения с базой данных"""
        if self.conn:
            self.conn.close()
            logger.info("Соединение с базой данных закрыто")
    
    def ensure_connection(self):
        """Проверка соединения с базой данных и переподключение при необходимости"""
        try:
            # Проверяем, закрыто ли соединение
            if self.conn is None or self.conn.closed:
                logger.warning("Соединение с базой данных закрыто, выполняется переподключение")
                self.connect()
                return True
            
            # Проверяем работоспособность соединения
            with self.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception as e:
            logger.warning(f"Ошибка при проверке соединения с базой данных: {e}")
            try:
                # Пытаемся переподключиться
                self.connect()
                return True
            except Exception as reconnect_error:
                logger.error(f"Не удалось переподключиться к базе данных: {reconnect_error}")
                return False
    
    def get_schedule_setting(self, name):
        """Получение значения настройки расписания"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return None
                
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT value FROM schedule_settings
                    WHERE name = %s
                """, (name,))
                result = cursor.fetchone()
                if result:
                    return result[0]
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении настройки расписания {name}: {e}")
            return None
    
    def update_schedule_setting(self, name, value):
        """Обновление значения настройки расписания"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return False
                
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE schedule_settings
                    SET value = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE name = %s
                    RETURNING id
                """, (value, name))
                result = cursor.fetchone()
                self.conn.commit()
                if result:
                    logger.info(f"Настройка расписания {name} обновлена на {value}")
                    return True
                return False
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при обновлении настройки расписания {name}: {e}")
            return False
    
    def get_all_schedule_settings(self):
        """Получение всех настроек расписания"""
        try:
            # Проверяем соединение перед выполнением запроса
            if not self.ensure_connection():
                logger.error("Не удалось установить соединение с базой данных")
                return []
                
            with self.conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT name, value, description, updated_at
                    FROM schedule_settings
                    ORDER BY id
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении всех настроек расписания: {e}")
            return []
    
    def schedule_post(self, news_id, scheduled_date):
        """Запланировать публикацию поста на определенное время"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO scheduled_posts (news_id, scheduled_date)
                    VALUES (%s, %s)
                    ON CONFLICT (news_id) DO UPDATE
                    SET scheduled_date = EXCLUDED.scheduled_date,
                        status = 'pending',
                        attempts = 0,
                        last_attempt = NULL
                    RETURNING id
                """, (news_id, scheduled_date))
                post_id = cursor.fetchone()[0]
                self.conn.commit()
                logger.info(f"Пост с ID {news_id} запланирован на {scheduled_date}")
                return post_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при планировании поста: {e}")
            return False
    
    def get_scheduled_posts(self, limit=10):
        """Получение запланированных постов"""
        try:
            with self.conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT s.id, s.news_id, s.scheduled_date, s.status, s.attempts,
                           n.title, n.category, n.url
                    FROM scheduled_posts s
                    JOIN news n ON s.news_id = n.id
                    WHERE s.status = 'pending' AND n.published = FALSE
                    ORDER BY s.scheduled_date ASC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении запланированных постов: {e}")
            return []
    
    def update_post_status(self, post_id, status, increment_attempts=True):
        """Обновление статуса запланированного поста"""
        try:
            with self.conn.cursor() as cursor:
                if increment_attempts:
                    cursor.execute("""
                        UPDATE scheduled_posts
                        SET status = %s, attempts = attempts + 1, last_attempt = CURRENT_TIMESTAMP
                        WHERE id = %s
                        RETURNING id
                    """, (status, post_id))
                else:
                    cursor.execute("""
                        UPDATE scheduled_posts
                        SET status = %s, last_attempt = CURRENT_TIMESTAMP
                        WHERE id = %s
                        RETURNING id
                    """, (status, post_id))
                result = cursor.fetchone()
                self.conn.commit()
                if result:
                    logger.info(f"Статус поста с ID {post_id} обновлен на {status}")
                    return True
                return False
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при обновлении статуса поста: {e}")
            return False
    
    def close(self):
        """Закрытие соединения с базой данных"""
        if self.conn is not None:
            self.conn.close()
            logger.info("Соединение с базой данных закрыто")