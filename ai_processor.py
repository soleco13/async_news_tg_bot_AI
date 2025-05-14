import os
import logging
from openai import OpenAI
from dotenv import load_dotenv
from database import Database

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_processor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AIProcessor:
    def __init__(self, db):
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        self.site_url = os.getenv('SITE_URL', 'https://async-news.ru')
        self.site_name = os.getenv('SITE_NAME', 'AsyncNews')
        self.db = db
        self.prompt_template = """
        Перепиши следующую новость в стиле Telegram-поста для IT-канала 🔧
        Требования:
        Источник указывать не нужно
        Выводи ТОЛЬКО готовый текст поста на русском языке
        Без markdown, только обычный текст
        Объём: 100–150 слов
        Каждый абзац должен содержать хотя бы один эмодзи (📱💻🔥🚀🧠👨‍💻 и другие)
        Заголовок — ЗАГЛАВНЫМИ БУКВАМИ, броский
        Стиль: лёгкий, дружелюбный, с IT-юмором
        Тон: вдохновляющий, допускается лёгкий сарказм
        В конце — ссылка на источник (если есть) и хэштеги
        Финал: интригующий вопрос или призыв к дискуссии
        Категория новости: [укажи категорию, например: ИИ, стартапы, кибербезопасность и т.д.]
        Оригинальный контент: {original_content}
        
        """

        # Инициализация клиента OpenAI с OpenRouter
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.openrouter_api_key
        )

    def process_news(self, news_item):
        """Обработка новости с помощью AI"""
        try:
            # Проверка наличия и длины контента
            content = news_item.get('content', '')
            content_length = len(content)
            
            if content_length < 50:
                logger.warning(f"Контент новости '{news_item['title']}' слишком короткий ({content_length} символов). Качество обработки может быть низким.")
            else:
                logger.info(f"Обработка новости '{news_item['title']}' с контентом длиной {content_length} символов")
            
            # Подготовка промта
            prompt = self.prompt_template.format(
                original_title=news_item['title'],
                original_content=content,
                source_url=news_item['url'],
                category=news_item['category']
            )

            logger.info(f"Отправка новости '{news_item['title']}' на обработку AI через OpenRouter")

            # Запрос к OpenRouter API с моделью Qwen3
            completion = self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": self.site_url,  # Для рейтинга на openrouter.ai
                    "X-Title": self.site_name,      # Для рейтинга на openrouter.ai
                },
                extra_body={},
                model="google/gemma-3-27b-it:free",
                messages=[
                    {"role": "system", "content": "Ты - редактор IT-новостей для Telegram-канала."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )

            # Получение ответа от AI
            ai_response = completion.choices[0].message.content.strip()

            # Разделение на заголовок и контент
            lines = ai_response.split('\n')
            processed_title = lines[0] if lines else ""
            processed_content = '\n'.join(lines[1:]) if len(lines) > 1 else ""

            # Сохранение обработанной новости в базу данных
            processed_id = self.db.save_processed_news(
                news_item['id'],
                processed_title,
                processed_content
            )

            if processed_id:
                logger.info(f"Новость успешно обработана и сохранена с ID {processed_id}")
                return {
                    "id": news_item['id'],
                    "processed_title": processed_title,
                    "processed_content": processed_content,
                    "success": True
                }
            else:
                logger.error(f"Не удалось сохранить обработанную новость в базу данных")
                return {"success": False, "error": "Database error"}

        except Exception as e:
            logger.error(f"Ошибка при обработке новости: {e}")
            return {"success": False, "error": str(e)}

    def process_batch(self, news_items, batch_size=5):
        """Обработка пакета новостей с учетом качества контента"""
        results = []
        count = 0
        skipped = 0

        for news_item in news_items:
            if count >= batch_size:
                break

            # Проверка качества контента
            content_length = len(news_item.get('content', ''))
            if content_length < 50:
                logger.warning(f"Пропуск новости '{news_item['title']}' из-за недостаточного контента ({content_length} символов)")
                results.append({
                    "id": news_item['id'],
                    "success": False,
                    "error": "Insufficient content length",
                    "content_length": content_length
                })
                skipped += 1
                continue

            # Обработка новости
            result = self.process_news(news_item)
            results.append(result)

            if result["success"]:
                count += 1
            else:
                logger.error(f"Ошибка при обработке новости '{news_item['title']}': {result.get('error', 'Неизвестная ошибка')}")

        logger.info(f"Обработано {count} новостей, пропущено {skipped} из {len(news_items)}")
        return results