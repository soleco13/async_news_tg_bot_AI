import os
import logging
import asyncio
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import psycopg2.extras
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from database import Database
from dotenv import load_dotenv
from aiogram.types import BufferedInputFile

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("admin_panel.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Список администраторов (ID пользователей Telegram)
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]

class AdminStates(StatesGroup):
    """Состояния для FSM админ-панели"""
    waiting_for_post_id = State()  # Ожидание ID поста для просмотра деталей
    waiting_for_post_date = State()  # Ожидание даты для планирования публикации
    waiting_for_post_time = State()  # Ожидание времени для планирования публикации
    waiting_for_schedule_time = State()  # Ожидание времени для расписания публикаций
    waiting_for_timezone = State()  # Ожидание часового пояса
    waiting_for_schedule_slot = State()  # Ожидание номера слота расписания для изменения
    waiting_for_api_key = State()  # Ожидание нового значения API ключа

class AdminPanel:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.router = Router()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Настройка обработчиков команд админ-панели"""
        # Команда /admin для доступа к админ-панели
        self.router.message.register(self.cmd_admin, Command(commands=["admin"]))
        
        # Обработчики кнопок админ-панели
        self.router.callback_query.register(self.show_scheduled_posts, F.data == "show_scheduled")
        self.router.callback_query.register(self.show_post_stats, F.data == "show_stats")
        self.router.callback_query.register(self.show_post_graph, F.data == "show_graph")
        self.router.callback_query.register(self.back_to_admin_menu, F.data == "back_to_admin")
        self.router.callback_query.register(self.auto_schedule_posts, F.data == "auto_schedule")
        
        # Обработчики для просмотра деталей поста
        self.router.callback_query.register(self.view_post_details, F.data.startswith("view_post_"))
        
        # Обработчики для изменения времени публикации
        self.router.callback_query.register(self.reschedule_post, F.data.startswith("reschedule_"))
        self.router.message.register(self.process_post_date, AdminStates.waiting_for_post_date)
        self.router.message.register(self.process_post_time, AdminStates.waiting_for_post_time)
        
        # Обработчик для удаления поста из очереди
        self.router.callback_query.register(self.delete_post, F.data.startswith("delete_post_"))
        self.router.callback_query.register(self.confirm_delete_post, F.data.startswith("confirm_delete_"))
        
        # Обработчики для настройки расписания публикаций
        self.router.callback_query.register(self.show_schedule_settings, F.data == "schedule_settings")
        self.router.callback_query.register(self.edit_timezone, F.data == "edit_timezone")
        self.router.callback_query.register(self.edit_schedule_time, F.data.startswith("edit_schedule_time_"))
        self.router.message.register(self.process_timezone, AdminStates.waiting_for_timezone)
        self.router.message.register(self.process_schedule_time, AdminStates.waiting_for_schedule_time)
        
        # Обработчики для настройки API ключей
        self.router.callback_query.register(self.show_api_settings, F.data == "api_settings")
        self.router.callback_query.register(self.edit_openrouter_api_key, F.data == "edit_openrouter_api_key")
        self.router.callback_query.register(self.edit_openai_api_key, F.data == "edit_openai_api_key")
        self.router.message.register(self.process_api_key, AdminStates.waiting_for_api_key)
        
        logger.info("Обработчики команд админ-панели настроены")
    
    async def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором"""
        return user_id in ADMIN_IDS
    
    async def cmd_admin(self, message: Message):
        """Обработчик команды /admin"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            await message.answer("⛔ У вас нет доступа к админ-панели.")
            logger.warning(f"Попытка доступа к админ-панели от неавторизованного пользователя: {user_id}")
            return
        
        # Создание клавиатуры админ-панели
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Запланированные посты", callback_data="show_scheduled")],
            [InlineKeyboardButton(text="🤖 Автоматическое планирование", callback_data="auto_schedule")],
            [InlineKeyboardButton(text="⏰ Настройки расписания", callback_data="schedule_settings")],
            [InlineKeyboardButton(text="🔑 Настройки API", callback_data="api_settings")],
            [InlineKeyboardButton(text="📊 Статистика публикаций", callback_data="show_stats")],
            [InlineKeyboardButton(text="📈 График публикаций", callback_data="show_graph")]
        ])
        
        await message.answer("🔧 Админ-панель бота @async_news_bot", reply_markup=keyboard)
        logger.info(f"Пользователь {user_id} открыл админ-панель")
    
    async def show_scheduled_posts(self, callback: CallbackQuery):
        """Показать запланированные посты"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение запланированных постов из базы данных
        scheduled_posts = await self.get_scheduled_posts()
        
        if not scheduled_posts:
            await callback.message.edit_text(
                "📅 Запланированные посты отсутствуют",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                ])
            )
            await callback.answer()
            return
        
        # Формирование сообщения со списком постов
        message_text = "📅 Запланированные посты:\n\n"
        
        for post in scheduled_posts:
            pub_date = post["scheduled_date"].strftime("%d.%m.%Y %H:%M")
            message_text += f"🔹 ID: {post['id']} - {pub_date}\n"
            message_text += f"   {post['title'][:50]}...\n\n"
        
        # Добавление кнопок для каждого поста
        keyboard = []
        for post in scheduled_posts:
            keyboard.append([InlineKeyboardButton(
                text=f"Пост #{post['id']} ({post['scheduled_date'].strftime('%d.%m %H:%M')})",
                callback_data=f"view_post_{post['id']}"
            )])
        
        # Добавление кнопки "Назад"
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")])
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
    
    async def view_post_details(self, callback: CallbackQuery):
        """Показать детали конкретного поста"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение ID поста из callback_data
        post_id = int(callback.data.split("_")[-1])
        
        # Получение информации о посте
        post = await self.get_post_by_id(post_id)
        
        if not post:
            await callback.answer("❌ Пост не найден", show_alert=True)
            return
        
        # Формирование сообщения с деталями поста
        message_text = f"📝 Детали поста #{post['id']}\n\n"
        message_text += f"📅 Дата публикации: {post['scheduled_date'].strftime('%d.%m.%Y %H:%M')}\n"
        message_text += f"📋 Категория: {post['category']}\n\n"
        message_text += f"🔷 Заголовок: {post['processed_title']}\n\n"
        message_text += f"📄 Содержание:\n{post['processed_content'][:300]}...\n\n"
        message_text += f"🔗 URL: {post['url']}"
        
        # Создание клавиатуры с действиями для поста
        keyboard = [
            [InlineKeyboardButton(text="⏱ Изменить время публикации", callback_data=f"reschedule_{post['id']}")],
            [InlineKeyboardButton(text="❌ Удалить из очереди", callback_data=f"delete_post_{post['id']}")],
            [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="show_scheduled")]
        ]
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
    
    async def reschedule_post(self, callback: CallbackQuery, state: FSMContext):
        """Изменить время публикации поста"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение ID поста из callback_data
        post_id = int(callback.data.split("_")[-1])
        
        # Сохранение ID поста в состоянии
        await state.update_data(post_id=post_id)
        
        await callback.message.edit_text(
            "📅 Введите новую дату публикации в формате ДД.ММ.ГГГГ",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"view_post_{post_id}")]
            ])
        )
        
        # Установка состояния ожидания даты
        await state.set_state(AdminStates.waiting_for_post_date)
        await callback.answer()
    
    async def process_post_date(self, message: Message, state: FSMContext):
        """Обработка введенной даты публикации"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            return
        
        # Проверка формата даты
        try:
            date_str = message.text.strip()
            new_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            
            # Сохранение даты в состоянии
            await state.update_data(new_date=new_date)
            
            # Запрос времени публикации
            await message.answer(
                "⏰ Введите время публикации в формате ЧЧ:ММ",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Отмена", callback_data="show_scheduled")]
                ])
            )
            
            # Установка состояния ожидания времени
            await state.set_state(AdminStates.waiting_for_post_time)
            
        except ValueError:
            await message.answer(
                "❌ Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Отмена", callback_data="show_scheduled")]
                ])
            )
    
    async def process_post_time(self, message: Message, state: FSMContext):
        """Обработка введенного времени публикации"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            return
        
        # Получение данных из состояния
        data = await state.get_data()
        post_id = data.get("post_id")
        new_date = data.get("new_date")
        
        # Проверка формата времени
        try:
            time_str = message.text.strip()
            hour, minute = map(int, time_str.split(":"))
            
            # Создание полной даты и времени
            new_datetime = datetime.combine(new_date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
            
            # Обновление времени публикации в базе данных
            success = await self.update_post_schedule(post_id, new_datetime)
            
            if success:
                await message.answer(
                    f"✅ Время публикации поста #{post_id} изменено на {new_datetime.strftime('%d.%m.%Y %H:%M')}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 К списку постов", callback_data="show_scheduled")],
                        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_admin")]
                    ])
                )
            else:
                await message.answer(
                    "❌ Не удалось обновить время публикации",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 К списку постов", callback_data="show_scheduled")]
                    ])
                )
            
            # Сброс состояния
            await state.clear()
            
        except (ValueError, IndexError):
            await message.answer(
                "❌ Неверный формат времени. Пожалуйста, введите время в формате ЧЧ:ММ",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Отмена", callback_data="show_scheduled")]
                ])
            )
    
    async def delete_post(self, callback: CallbackQuery):
        """Удалить пост из очереди публикаций"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение ID поста из callback_data
        post_id = int(callback.data.split("_")[-1])
        
        # Подтверждение удаления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{post_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"view_post_{post_id}")]
        ])
        
        await callback.message.edit_text(
            f"⚠️ Вы уверены, что хотите удалить пост #{post_id} из очереди публикаций?",
            reply_markup=keyboard
        )
        await callback.answer()
    
    async def confirm_delete_post(self, callback: CallbackQuery):
        """Подтверждение удаления поста из очереди публикаций"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение ID поста из callback_data
        post_id = int(callback.data.split("_")[-1])
        
        try:
            # Удаление поста из таблицы scheduled_posts
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM scheduled_posts
                    WHERE news_id = %s
                    RETURNING id
                """, (post_id,))
                result = cursor.fetchone()
                self.db.conn.commit()
                
                if result:
                    await callback.message.edit_text(
                        f"✅ Пост #{post_id} успешно удален из очереди публикаций",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📅 К списку постов", callback_data="show_scheduled")],
                            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_admin")]
                        ])
                    )
                    logger.info(f"Администратор {user_id} удалил пост #{post_id} из очереди публикаций")
                else:
                    await callback.message.edit_text(
                        f"❌ Пост #{post_id} не найден в очереди публикаций",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📅 К списку постов", callback_data="show_scheduled")]
                        ])
                    )
        except Exception as e:
            self.db.conn.rollback()
            logger.error(f"Ошибка при удалении поста #{post_id}: {e}")
            await callback.message.edit_text(
                f"❌ Ошибка при удалении поста: {e}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📅 К списку постов", callback_data="show_scheduled")]
                ])
            )
        
        await callback.answer()
    
    async def show_post_stats(self, callback: CallbackQuery):
        """Показать статистику публикаций"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение статистики из базы данных
        stats = await self.get_publication_stats()
        
        # Формирование сообщения со статистикой
        message_text = "📊 Статистика публикаций:\n\n"
        
        message_text += f"📝 Всего новостей в базе: {stats['total_news']}\n"
        message_text += f"✅ Опубликовано: {stats['published']}\n"
        message_text += f"⏳ В очереди на публикацию: {stats['scheduled']}\n"
        message_text += f"🔄 Обработано AI: {stats['processed']}\n\n"
        
        message_text += "📈 По категориям:\n"
        for category, count in stats['categories'].items():
            message_text += f"- {category}: {count}\n"
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ])
        )
        await callback.answer()
    
    async def show_post_graph(self, callback: CallbackQuery):
        """Показать график публикаций"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение данных для графика
        graph_data = await self.get_graph_data()
        
        if not graph_data['dates']:
            await callback.message.edit_text(
                "📈 Недостаточно данных для построения графика",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                ])
            )
            await callback.answer()
            return
        
        # Создание графика
        plt.figure(figsize=(10, 6))
        plt.plot(graph_data['dates'], graph_data['counts'], marker='o', linestyle='-', color='#1e88e5')
        
        # Настройка графика
        plt.title('График публикаций за последние 30 дней')
        plt.xlabel('Дата')
        plt.ylabel('Количество публикаций')
        plt.grid(True, linestyle='--', alpha=0.7)
        
        # Форматирование оси X для отображения дат
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=5))
        plt.gcf().autofmt_xdate()
        
        # Сохранение графика в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()

        # Преобразование буфера в BufferedInputFile
        image_file = BufferedInputFile(buf.read(), filename="graph.png")

        await callback.message.delete()
        await self.bot.send_photo(
            chat_id=user_id,
            photo=image_file,  # Используем BufferedInputFile
            caption="📈 График публикаций за последние 30 дней",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
            ])
        )
        await callback.answer()
    
    async def back_to_admin_menu(self, callback: CallbackQuery):
        """Вернуться в главное меню админ-панели"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Запланированные посты", callback_data="show_scheduled")],
            [InlineKeyboardButton(text="🤖 Автоматическое планирование", callback_data="auto_schedule")],
            [InlineKeyboardButton(text="⏰ Настройки расписания", callback_data="schedule_settings")],
            [InlineKeyboardButton(text="🔑 Настройки API", callback_data="api_settings")],
            [InlineKeyboardButton(text="📊 Статистика публикаций", callback_data="show_stats")],
            [InlineKeyboardButton(text="📈 График публикаций", callback_data="show_graph")]
        ])
        
        await callback.message.edit_text("🔧 Админ-панель бота @async_news_bot", reply_markup=keyboard)
        await callback.answer()
        
    async def show_api_settings(self, callback: CallbackQuery):
        """Показать настройки API ключей"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение текущих значений API ключей из .env файла
        openrouter_api_key = os.getenv('OPENROUTER_API_KEY', '')
        openai_api_key = os.getenv('OPENAI_API_KEY', '')
        news_api_key = os.getenv('NEWS_API_KEY', '')
        
        # Маскировка API ключей для безопасности
        masked_openrouter = self.mask_api_key(openrouter_api_key)
        masked_openai = self.mask_api_key(openai_api_key)
        masked_news = self.mask_api_key(news_api_key)
        
        # Формирование сообщения с настройками API
        message_text = "🔑 Настройки API ключей:\n\n"
        message_text += f"🤖 OpenRouter API Key: {masked_openrouter}\n"
        message_text += f"🧠 OpenAI API Key: {masked_openai}\n"
        message_text += f"📰 News API Key: {masked_news}\n"
        
        # Создание клавиатуры с действиями
        keyboard = [
            [InlineKeyboardButton(
                text="🔄 Изменить OpenRouter API Key", 
                callback_data="edit_openrouter_api_key"
            )],
            [InlineKeyboardButton(
                text="🔄 Изменить OpenAI API Key", 
                callback_data="edit_openai_api_key"
            )],
            [InlineKeyboardButton(
                text="◀️ Назад", 
                callback_data="back_to_admin"
            )]
        ]
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
    
    def mask_api_key(self, api_key):
        """Маскировка API ключа для безопасного отображения"""
        if not api_key or len(api_key) < 8:
            return "Не установлен"
        
        # Показываем только первые 4 и последние 4 символа
        return f"{api_key[:4]}...{api_key[-4:]}"
    
    async def edit_openrouter_api_key(self, callback: CallbackQuery, state: FSMContext):
        """Изменение OpenRouter API Key"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение текущего значения API ключа
        current_key = os.getenv('OPENROUTER_API_KEY', '')
        masked_key = self.mask_api_key(current_key)
        
        await callback.message.edit_text(
            f"🔑 Текущий OpenRouter API Key: {masked_key}\n\n"
            "Введите новый API ключ для OpenRouter:\n"
            "Формат: sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="api_settings")]
            ])
        )
        
        # Установка состояния ожидания ввода API ключа и сохранение типа ключа
        await state.update_data(api_key_type='openrouter')
        await state.set_state(AdminStates.waiting_for_api_key)
        await callback.answer()
        
    async def edit_openai_api_key(self, callback: CallbackQuery, state: FSMContext):
        """Изменение OpenAI API Key"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение текущего значения API ключа
        current_key = os.getenv('OPENAI_API_KEY', '')
        masked_key = self.mask_api_key(current_key)
        
        await callback.message.edit_text(
            f"🔑 Текущий OpenAI API Key: {masked_key}\n\n"
            "Введите новый API ключ для OpenAI:\n"
            "Формат: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="api_settings")]
            ])
        )
        
        # Установка состояния ожидания ввода API ключа и сохранение типа ключа
        await state.update_data(api_key_type='openai')
        await state.set_state(AdminStates.waiting_for_api_key)
        await callback.answer()
    
    async def process_api_key(self, message: Message, state: FSMContext):
        """Обработка введенного API ключа"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            return
        
        # Получение введенного API ключа и его типа из состояния
        new_api_key = message.text.strip()
        data = await state.get_data()
        api_key_type = data.get('api_key_type', 'openrouter')
        
        # Проверка формата API ключа в зависимости от типа
        if api_key_type == 'openrouter':
            if not new_api_key.startswith('sk-or-v1-') or len(new_api_key) < 20:
                await message.answer(
                    "❌ Неверный формат API ключа. Пожалуйста, введите корректный ключ OpenRouter API.\n"
                    "Формат: sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Отмена", callback_data="api_settings")]
                    ])
                )
                return
            env_var_name = 'OPENROUTER_API_KEY'
            api_name = 'OpenRouter'
        elif api_key_type == 'openai':
            if not new_api_key.startswith('sk-') or len(new_api_key) < 20:
                await message.answer(
                    "❌ Неверный формат API ключа. Пожалуйста, введите корректный ключ OpenAI API.\n"
                    "Формат: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Отмена", callback_data="api_settings")]
                    ])
                )
                return
            env_var_name = 'OPENAI_API_KEY'
            api_name = 'OpenAI'
        else:
            await message.answer(
                "❌ Неизвестный тип API ключа",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 К настройкам API", callback_data="api_settings")]
                ])
            )
            await state.clear()
            return
        
        # Обновление API ключа в .env файле
        success = await self.update_env_variable(env_var_name, new_api_key)
        
        if success:
            # Обновление переменной окружения в текущем процессе
            os.environ[env_var_name] = new_api_key
            
            # Перезагрузка компонентов, использующих API ключ
            if api_key_type == 'openrouter':
                try:
                    # Импортируем AIProcessor для перезагрузки
                    from ai_processor import AIProcessor
                    
                    # Создаем новый экземпляр AIProcessor с обновленным ключом
                    new_ai_processor = AIProcessor(self.db)
                    
                    # Обновляем AI-процессор в базе данных, если он там есть
                    if hasattr(self.db, 'ai_processor'):
                        self.db.ai_processor = new_ai_processor
                        logger.info(f"AI-процессор в базе данных обновлен с новым ключом OpenRouter")
                    
                    # Если в проекте используется планировщик, обновляем его AI-процессор
                    try:
                        from scheduler import Scheduler
                        import sys
                        
                        # Проверяем, есть ли экземпляр планировщика в текущем процессе
                        for module_name, module in sys.modules.items():
                            if module_name == 'scheduler' and hasattr(module, 'scheduler_instance'):
                                if hasattr(module.scheduler_instance, 'ai_processor'):
                                    module.scheduler_instance.ai_processor = new_ai_processor
                                    logger.info(f"AI-процессор в планировщике обновлен с новым ключом OpenRouter")
                    except Exception as e:
                        logger.warning(f"Не удалось обновить AI-процессор в планировщике: {e}")
                    
                    reload_message = "✅ AI-процессор успешно перезагружен с новым ключом."
                    logger.info(f"AI-процессор успешно перезагружен с новым ключом OpenRouter")
                except Exception as e:
                    logger.error(f"Ошибка при перезагрузке AI-процессора: {e}")
                    reload_message = "⚠️ Не удалось перезагрузить AI-процессор. Изменения вступят в силу при следующем запуске."
            else:
                reload_message = "⚠️ Изменения вступят в силу при следующем запросе к API."
            
            # Уведомление об успешном обновлении
            masked_key = self.mask_api_key(new_api_key)
            await message.answer(
                f"✅ {api_name} API Key успешно обновлен на {masked_key}\n\n"
                f"{reload_message}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 К настройкам API", callback_data="api_settings")],
                    [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_admin")]
                ])
            )
            
            # Логирование изменения API ключа
            logger.info(f"Администратор {user_id} изменил {api_name} API Key")
        else:
            await message.answer(
                "❌ Не удалось обновить API ключ. Проверьте права доступа к файлу .env",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 К настройкам API", callback_data="api_settings")]
                ])
            )
        
        # Сброс состояния
        await state.clear()
    
    async def update_env_variable(self, variable_name, new_value):
        """Обновление переменной в файле .env"""
        try:
            # Путь к файлу .env
            env_path = os.path.join(os.getcwd(), '.env')
            
            # Чтение текущего содержимого файла
            with open(env_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
            
            # Поиск и замена нужной переменной
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(f"{variable_name}="):
                    lines[i] = f"{variable_name}={new_value}\n"
                    updated = True
                    break
            
            # Если переменная не найдена, добавляем её в конец файла
            if not updated:
                lines.append(f"{variable_name}={new_value}\n")
            
            # Запись обновленного содержимого обратно в файл
            with open(env_path, 'w', encoding='utf-8') as file:
                file.writelines(lines)
            
            logger.info(f"Переменная {variable_name} успешно обновлена в файле .env")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении переменной {variable_name} в файле .env: {e}")
            return False
    
    async def show_schedule_settings(self, callback: CallbackQuery):
        """Показать настройки расписания публикаций"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение настроек расписания из базы данных
        settings = await self.get_schedule_settings()
        
        # Формирование сообщения с настройками
        message_text = "⏰ Настройки расписания публикаций:\n\n"
        
        # Информация о часовом поясе
        timezone = next((s['value'] for s in settings if s['name'] == 'timezone'), 'Europe/Moscow')
        message_text += f"🌐 Часовой пояс: {timezone} (МСК)\n\n"
        
        # Информация о времени публикаций
        message_text += "⏱ Время публикаций (МСК):\n"
        for i in range(1, 4):
            time_value = next((s['value'] for s in settings if s['name'] == f'publish_time_{i}'), f'{8+i*3}:00')
            message_text += f"   {i}. {time_value}\n"
        
        # Создание клавиатуры с действиями
        keyboard = []
        
        # Кнопки для изменения времени публикации
        for i in range(1, 4):
            keyboard.append([InlineKeyboardButton(
                text=f"⏱ Изменить время #{i}", 
                callback_data=f"edit_schedule_time_{i}"
            )])
        
        # Кнопка для изменения часового пояса
        keyboard.append([InlineKeyboardButton(
            text="🌐 Изменить часовой пояс", 
            callback_data="edit_timezone"
        )])
        
        # Кнопка возврата в меню
        keyboard.append([InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data="back_to_admin"
        )])
        
        await callback.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await callback.answer()
    
    async def edit_timezone(self, callback: CallbackQuery, state: FSMContext):
        """Изменение часового пояса"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение текущего часового пояса
        settings = await self.get_schedule_settings()
        current_timezone = next((s['value'] for s in settings if s['name'] == 'timezone'), 'Europe/Moscow')
        
        await callback.message.edit_text(
            f"🌐 Текущий часовой пояс: {current_timezone} (МСК)\n\n"
            "Введите новый часовой пояс в формате 'Europe/Moscow'.\n"
            "Доступные часовые пояса для России:\n"
            "- Europe/Moscow (Москва, UTC+3)\n"
            "- Europe/Kaliningrad (Калининград, UTC+2)\n"
            "- Europe/Samara (Самара, UTC+4)\n"
            "- Asia/Yekaterinburg (Екатеринбург, UTC+5)\n"
            "- Asia/Omsk (Омск, UTC+6)\n"
            "- Asia/Krasnoyarsk (Красноярск, UTC+7)\n"
            "- Asia/Irkutsk (Иркутск, UTC+8)\n"
            "- Asia/Yakutsk (Якутск, UTC+9)\n"
            "- Asia/Vladivostok (Владивосток, UTC+10)\n"
            "- Asia/Magadan (Магадан, UTC+11)\n"
            "- Asia/Kamchatka (Камчатка, UTC+12)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="schedule_settings")]
            ])
        )
        
        # Установка состояния ожидания ввода часового пояса
        await state.set_state(AdminStates.waiting_for_timezone)
        await callback.answer()
    
    async def process_timezone(self, message: Message, state: FSMContext):
        """Обработка введенного часового пояса"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            return
        
        # Проверка введенного часового пояса
        timezone_name = message.text.strip()
        
        try:
            import pytz
            tz = pytz.timezone(timezone_name)
            
            # Обновление часового пояса в базе данных
            success = await self.update_schedule_setting('timezone', timezone_name)
            
            if success:
                # Уведомление о необходимости перезапуска планировщика
                await message.answer(
                    f"✅ Часовой пояс успешно изменен на {timezone_name} (МСК)"
                    f"\n\n⚠️ Для применения изменений может потребоваться перезапуск планировщика задач.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏰ К настройкам расписания", callback_data="schedule_settings")],
                        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_admin")]
                    ])
                )
                
                # Логирование изменения часового пояса
                logger.info(f"Администратор {user_id} изменил часовой пояс на {timezone_name}")
            else:
                await message.answer(
                    "❌ Не удалось обновить часовой пояс",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏰ К настройкам расписания", callback_data="schedule_settings")]
                    ])
                )
            
            # Сброс состояния
            await state.clear()
            
        except Exception as e:
            await message.answer(
                f"❌ Неверный формат часового пояса: {str(e)}\n\nПожалуйста, введите корректный часовой пояс (например, Europe/Moscow)",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Отмена", callback_data="schedule_settings")]
                ])
            )
    
    async def edit_schedule_time(self, callback: CallbackQuery, state: FSMContext):
        """Изменение времени публикации"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Получение номера слота времени из callback_data
        slot_number = int(callback.data.split("_")[-1])
        
        # Получение текущего значения времени
        settings = await self.get_schedule_settings()
        current_time = next((s['value'] for s in settings if s['name'] == f'publish_time_{slot_number}'), '09:00')
        
        # Сохранение номера слота в состоянии
        await state.update_data(slot_number=slot_number)
        
        # Получение информации о часовом поясе
        timezone = next((s['value'] for s in settings if s['name'] == 'timezone'), 'Europe/Moscow')
        
        await callback.message.edit_text(
            f"⏱ Текущее время публикации #{slot_number}: {current_time} (МСК)\n\n"
            f"🌐 Текущий часовой пояс: {timezone}\n\n"
            "Введите новое время в формате ЧЧ:ММ (например, 09:30)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="schedule_settings")]
            ])
        )
        
        # Установка состояния ожидания ввода времени
        await state.set_state(AdminStates.waiting_for_schedule_time)
        await callback.answer()
    
    async def process_schedule_time(self, message: Message, state: FSMContext):
        """Обработка введенного времени публикации"""
        user_id = message.from_user.id
        
        if not await self.is_admin(user_id):
            return
        
        # Получение данных из состояния
        data = await state.get_data()
        slot_number = data.get("slot_number")
        
        # Проверка формата времени
        try:
            time_str = message.text.strip()
            hour, minute = map(int, time_str.split(":"))
            
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValueError("Некорректное время")
            
            # Форматирование времени в формат ЧЧ:ММ
            formatted_time = f"{hour:02d}:{minute:02d}"
            
            # Обновление времени публикации в базе данных
            success = await self.update_schedule_setting(f'publish_time_{slot_number}', formatted_time)
            
            if success:
                # Уведомление о необходимости перезапуска планировщика
                await message.answer(
                    f"✅ Время публикации #{slot_number} изменено на {formatted_time} (МСК)\n\n"
                    f"⚠️ Для применения изменений может потребоваться перезапуск планировщика задач.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏰ К настройкам расписания", callback_data="schedule_settings")],
                        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_admin")]
                    ])
                )
                
                # Логирование изменения времени публикации
                logger.info(f"Администратор {user_id} изменил время публикации #{slot_number} на {formatted_time}")
            else:
                await message.answer(
                    "❌ Не удалось обновить время публикации",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏰ К настройкам расписания", callback_data="schedule_settings")]
                    ])
                )
            
            # Сброс состояния
            await state.clear()
            
        except (ValueError, IndexError):
            await message.answer(
                "❌ Неверный формат времени. Пожалуйста, введите время в формате ЧЧ:ММ (например, 09:30)",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Отмена", callback_data="schedule_settings")]
                ])
            )
    
    # Методы для работы с базой данных
    
    async def get_scheduled_posts(self):
        """Получение запланированных постов из базы данных"""
        try:
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT n.id, n.title, n.url, n.category, s.scheduled_date,
                           p.processed_title, p.processed_content, s.status, s.attempts
                    FROM news n
                    JOIN processed_news p ON n.id = p.news_id
                    JOIN scheduled_posts s ON n.id = s.news_id
                    WHERE n.processed = TRUE AND n.published = FALSE
                    ORDER BY s.scheduled_date ASC
                """)
                
                posts = [{
                    'id': row[0],
                    'title': row[1],
                    'url': row[2],
                    'category': row[3],
                    'scheduled_date': row[4],
                    'processed_title': row[5],
                    'processed_content': row[6],
                    'status': row[7],
                    'attempts': row[8]
                } for row in cursor.fetchall()]
                
                return posts
        except Exception as e:
            logger.error(f"Ошибка при получении запланированных постов: {e}")
            return []
    
    async def get_post_by_id(self, post_id):
        """Получение информации о посте по ID"""
        try:
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT n.id, n.title, n.url, n.category, 
                           COALESCE(s.scheduled_date, n.published_date) as scheduled_date,
                           p.processed_title, p.processed_content,
                           s.status, s.attempts
                    FROM news n
                    JOIN processed_news p ON n.id = p.news_id
                    LEFT JOIN scheduled_posts s ON n.id = s.news_id
                    WHERE n.id = %s
                """, (post_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return {
                    'id': row[0],
                    'title': row[1],
                    'url': row[2],
                    'category': row[3],
                    'scheduled_date': row[4],
                    'processed_title': row[5],
                    'processed_content': row[6],
                    'status': row[7],
                    'attempts': row[8]
                }
        except Exception as e:
            logger.error(f"Ошибка при получении информации о посте: {e}")
            return None
    
    async def update_post_schedule(self, post_id, new_datetime):
        """Обновление времени публикации поста"""
        try:
            # Используем метод schedule_post из класса Database
            result = self.db.schedule_post(post_id, new_datetime)
            if result:
                logger.info(f"Время публикации поста #{post_id} обновлено на {new_datetime}")
                return True
            else:
                logger.error(f"Не удалось обновить время публикации поста #{post_id}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени публикации: {e}")
            return False
    
    async def get_publication_stats(self):
        """Получение статистики публикаций"""
        try:
            stats = {
                'total_news': 0,
                'published': 0,
                'scheduled': 0,
                'processed': 0,
                'categories': {}
            }
            
            with self.db.conn.cursor() as cursor:
                # Общее количество новостей
                cursor.execute("SELECT COUNT(*) FROM news")
                stats['total_news'] = cursor.fetchone()[0]
                
                # Количество опубликованных новостей
                cursor.execute("SELECT COUNT(*) FROM news WHERE published = TRUE")
                stats['published'] = cursor.fetchone()[0]
                
                # Количество запланированных новостей
                cursor.execute("SELECT COUNT(*) FROM news WHERE processed = TRUE AND published = FALSE")
                stats['scheduled'] = cursor.fetchone()[0]
                
                # Количество обработанных новостей
                cursor.execute("SELECT COUNT(*) FROM news WHERE processed = TRUE")
                stats['processed'] = cursor.fetchone()[0]
                
                # Статистика по категориям
                cursor.execute("""
                    SELECT category, COUNT(*)
                    FROM news
                    GROUP BY category
                    ORDER BY COUNT(*) DESC
                """)
                
                for row in cursor.fetchall():
                    stats['categories'][row[0]] = row[1]
            
            return stats
        except Exception as e:
            logger.error(f"Ошибка при получении статистики публикаций: {e}")
            return {
                'total_news': 0,
                'published': 0,
                'scheduled': 0,
                'processed': 0,
                'categories': {}
            }
    
    async def get_graph_data(self):
        """Получение данных для графика публикаций"""
        try:
            # Получение данных за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DATE(created_at) as pub_date, COUNT(*)
                    FROM news
                    WHERE published = TRUE AND created_at >= %s
                    GROUP BY DATE(created_at)
                    ORDER BY pub_date
                """, (thirty_days_ago,))
                
                dates = []
                counts = []
                
                for row in cursor.fetchall():
                    dates.append(row[0])
                    counts.append(row[1])
            
            return {'dates': dates, 'counts': counts}
        except Exception as e:
            logger.error(f"Ошибка при получении данных для графика: {e}")
            return {'dates': [], 'counts': []}
            
    async def get_schedule_settings(self):
        """Получение настроек расписания публикаций из базы данных"""
        try:
            settings = self.db.get_all_schedule_settings()
            return settings
        except Exception as e:
            logger.error(f"Ошибка при получении настроек расписания: {e}")
            return []
    
    async def update_schedule_setting(self, name, value):
        """Обновление настройки расписания в базе данных"""
        try:
            success = self.db.update_schedule_setting(name, value)
            if success:
                # Попытка синхронизации с планировщиком, если это возможно
                await self.sync_scheduler_settings()
            return success
        except Exception as e:
            logger.error(f"Ошибка при обновлении настройки расписания: {e}")
            return False
            
    async def sync_scheduler_settings(self):
        """Синхронизация настроек расписания с планировщиком задач"""
        try:
            # Импортируем планировщик только при необходимости
            from scheduler import Scheduler
            import schedule
            
            # Очистка текущего расписания
            schedule.clear()
            
            # Получение настроек расписания
            settings = await self.get_schedule_settings()
            timezone_name = next((s['value'] for s in settings if s['name'] == 'timezone'), 'Europe/Moscow')
            
            # Получение времени публикации
            publish_times = []
            for i in range(1, 4):
                time_setting = next((s['value'] for s in settings if s['name'] == f'publish_time_{i}'), None)
                if time_setting:
                    publish_times.append(time_setting)
            
            # Логирование информации о синхронизации
            logger.info(f"Синхронизация настроек расписания: часовой пояс {timezone_name}, времена публикации {publish_times}")
            
            # Здесь можно добавить код для перезапуска планировщика с новыми настройками
            # Но это требует доработки архитектуры приложения
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при синхронизации настроек с планировщиком: {e}")
            return False
    
    async def auto_schedule_posts(self, callback: CallbackQuery):
        """Автоматическое планирование 10 постов"""
        user_id = callback.from_user.id
        
        if not await self.is_admin(user_id):
            await callback.answer("⛔ У вас нет доступа к этой функции", show_alert=True)
            return
        
        # Сообщаем пользователю о начале процесса
        await callback.message.edit_text(
            "🔄 Начинаю процесс автоматического планирования постов..."
        )
        await callback.answer()
        
        try:
            # Инициализация необходимых компонентов
            from news_api import NewsAPI
            from ai_processor import AIProcessor
            
            news_api = NewsAPI(self.db)
            ai_processor = AIProcessor(self.db)
            
            # Шаг 1: Сбор новостей через API
            await callback.message.edit_text("🔍 Собираю свежие новости через API...")
            
            # Получаем больше новостей, чем нужно, на случай если некоторые не пройдут обработку
            articles = []
            for keyword in news_api.keywords[:5]:  # Берем первые 5 ключевых слов для разнообразия
                batch = news_api.fetch_news(keyword=keyword, max_results=5)
                articles.extend(batch)
                # Небольшая пауза между запросами
                await asyncio.sleep(1)
            
            # Удаление дубликатов
            unique_articles = {}
            for article in articles:
                url = article.get("link", "")
                if url and url not in unique_articles:
                    unique_articles[url] = article
            
            articles = list(unique_articles.values())
            
            # Фильтрация и сохранение в БД
            filtered_articles = news_api.filter_news(articles)
            saved_count = news_api.save_news_to_db(filtered_articles)
            
            if saved_count == 0:
                await callback.message.edit_text(
                    "❌ Не удалось найти подходящие новости. Пожалуйста, попробуйте позже.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                    ])
                )
                return
            
            # Шаг 2: Обработка новостей с помощью ИИ
            await callback.message.edit_text(f"🧠 Обрабатываю {saved_count} новостей с помощью ИИ...")
            
            # Получение необработанных новостей из базы данных
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, title, content, url, category
                    FROM news
                    WHERE processed = FALSE
                    ORDER BY published_date DESC
                    LIMIT 15
                """)
                news_items = [{
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'url': row[3],
                    'category': row[4]
                } for row in cursor.fetchall()]
            
            if not news_items:
                await callback.message.edit_text(
                    "❌ Не найдено новостей для обработки.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                    ])
                )
                return
            
            # Обработка новостей через AI
            results = ai_processor.process_batch(news_items, batch_size=15)
            
            # Подсчет успешно обработанных новостей
            processed_news = [result for result in results if result.get("success", False)]
            processed_count = len(processed_news)
            
            if processed_count == 0:
                await callback.message.edit_text(
                    "❌ Не удалось обработать новости. Пожалуйста, попробуйте позже.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                    ])
                )
                return
            
            # Шаг 3: Планирование публикаций с равномерным распределением по времени
            await callback.message.edit_text(f"📅 Планирую публикацию {min(processed_count, 10)} постов...")
            
            # Получение обработанных новостей для планирования
            with self.db.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT n.id
                    FROM news n
                    JOIN processed_news p ON n.id = p.news_id
                    WHERE n.processed = TRUE AND n.published = FALSE
                    ORDER BY n.published_date ASC
                    LIMIT 10
                """)
                post_ids = [row[0] for row in cursor.fetchall()]
            
            # Определение временного интервала для публикаций (начиная с текущего времени + 1 час)
            start_time = datetime.now() + timedelta(hours=1)
            # Равномерное распределение по времени (каждые 2 часа)
            time_interval = timedelta(hours=2)
            
            scheduled_count = 0
            for i, post_id in enumerate(post_ids):
                # Расчет времени публикации для текущего поста
                publish_time = start_time + (time_interval * i)
                
                # Обновление времени публикации в базе данных
                success = await self.update_post_schedule(post_id, publish_time)
                if success:
                    scheduled_count += 1
            
            # Формирование сообщения о результатах
            message_text = f"✅ Автоматическое планирование завершено!\n\n"
            message_text += f"📊 Результаты:\n"
            message_text += f"- Собрано новостей: {saved_count}\n"
            message_text += f"- Обработано ИИ: {processed_count}\n"
            message_text += f"- Запланировано к публикации: {scheduled_count}\n\n"
            
            if scheduled_count > 0:
                message_text += f"📅 Посты будут опубликованы в течение {scheduled_count * 2} часов, начиная с {start_time.strftime('%d.%m.%Y %H:%M')}"
            
            await callback.message.edit_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📅 Посмотреть запланированные", callback_data="show_scheduled")],
                    [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_admin")]
                ])
            )
            
        except Exception as e:
            logger.error(f"Ошибка при автоматическом планировании постов: {e}")
            await callback.message.edit_text(
                f"❌ Произошла ошибка при планировании постов: {str(e)}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
                ])
            )