# AsyncNews - Telegram-бот для автоматизированной публикации IT-новостей

## Описание проекта

AsyncNews - это автоматизированный Telegram-бот для сбора, обработки и публикации IT-новостей в публичный Telegram-канал [@async_news](https://t.me/async_news). Бот использует API новостей для парсинга, искусственный интеллект для редактирования текста под единый стиль и Telegram Bot API для публикации.

## Функциональность

- Автоматический сбор новостей по категориям: AI, Web3, кибербезопасность, UX/UI
- Обработка новостей с помощью AI для создания постов в едином стиле (100-150 слов, IT-юмор, эмодзи)
- Публикация 3-5 постов в день по расписанию (9:00, 12:00, 18:00)
- Фильтрация новостей по качеству и достоверности
- Хранение данных в PostgreSQL
- Логирование всех операций
- Админ-панель для управления публикациями

## Технологии

- Python 3.11
- Aiogram 3.x (Telegram Bot API)
- Newsdata.io API (для сбора новостей)
- OpenAI API / OpenRouter API (для обработки текста)
- PostgreSQL (для хранения данных)
- Schedule (для планирования задач)
- Matplotlib (для визуализации статистики)
- BeautifulSoup4 (для парсинга веб-страниц)

## Установка

1. Клонируйте репозиторий:

```bash
git clone <url-репозитория>
cd async_news
```

2. Создайте и активируйте виртуальное окружение:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/MacOS
source .venv/bin/activate
```

3. Установите зависимости:

```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` в корневой директории проекта со следующими переменными:

```
# API ключи и токены
NEWS_API_KEY=your_newsdata_io_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Настройки базы данных PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=news_bot
DB_USER=postgres
DB_PASSWORD=your_password

# Настройки API для ИИ
OPENAI_API_KEY=your_openai_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
SITE_URL=https://async-news.ru
SITE_NAME=AsyncNews

# Настройки Telegram-канала
TELEGRAM_CHANNEL_ID=@your_channel_id
ADMIN_IDS=123456789,987654321
```

5. Создайте базу данных PostgreSQL:

```bash
# Windows (PowerShell)
Get-Service *sql*

# Подключение к PostgreSQL
psql -U postgres
CREATE DATABASE news_bot;
```

## Запуск

### Запуск основного бота

```bash
python main.py
```

### Запуск Telegram-бота с админ-панелью

```bash
python bot.py
```

## Структура проекта

- `main.py` - Основной файл приложения
- `bot.py` - Telegram-бот с админ-панелью
- `scheduler.py` - Планировщик задач
- `news_api.py` - Модуль для работы с API новостей
- `web_scraper.py` - Модуль для парсинга веб-страниц
- `ai_processor.py` - Модуль для обработки новостей с помощью AI
- `telegram_publisher.py` - Модуль для публикации новостей в Telegram
- `database.py` - Модуль для работы с базой данных
- `admin_panel.py` - Модуль админ-панели
- `.env` - Файл с переменными окружения
- `requirements.txt` - Список зависимостей

## Админ-панель

Админ-панель предоставляет интерфейс для управления публикациями в Telegram-канале непосредственно через бота.

### Доступ к админ-панели

Отправьте команду `/admin` боту. Если ваш ID находится в списке администраторов (переменная `ADMIN_IDS` в файле `.env`), вы получите доступ к панели управления.

### Функции админ-панели

1. **Запланированные посты**
   - Просмотр списка постов, ожидающих публикации
   - Просмотр деталей каждого поста
   - Изменение времени публикации
   - Удаление постов из очереди

2. **Статистика публикаций**
   - Общее количество новостей в базе
   - Количество опубликованных новостей
   - Количество новостей в очереди на публикацию
   - Распределение новостей по категориям

3. **График публикаций**
   - Визуализация количества публикаций за последние 30 дней

## Логирование

Все логи сохраняются в файлы:
- `main.log` - Основной лог приложения
- `bot.log` - Лог Telegram-бота
- `scheduler.log` - Лог планировщика задач
- `news_api.log` - Лог API новостей
- `web_scraper.log` - Лог парсера веб-страниц
- `ai_processor.log` - Лог обработки новостей с помощью AI
- `telegram_publisher.log` - Лог публикации новостей в Telegram
- `database.log` - Лог работы с базой данных
- `admin_panel.log` - Лог админ-панели

