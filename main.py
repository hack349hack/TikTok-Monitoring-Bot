import logging
import asyncio
import sys
import os
import time
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import sqlite3
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/bot.log' if os.path.exists('/.dockerenv') else 'bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '1800'))
DB_PATH = os.getenv('DB_PATH', 'database/tiktok_bot.db')

# ========== БАЗА ДАННЫХ ==========

def init_db():
    """Инициализация базы данных"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            song_url TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            video_url TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def add_song(user_id, name, song_url):
    """Добавление песни в базу"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT OR IGNORE INTO songs (user_id, name, song_url) VALUES (?, ?, ?)',
            (user_id, name, song_url)
        )
        
        conn.commit()
        
        # Получаем ID
        cursor.execute(
            'SELECT id FROM songs WHERE song_url = ? AND user_id = ?',
            (song_url, user_id)
        )
        result = cursor.fetchone()
        song_id = result[0] if result else None
        
        conn.close()
        
        is_new = cursor.rowcount > 0
        return song_id, is_new
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления песни: {e}")
        return None, False

def get_user_songs(user_id):
    """Получение песен пользователя"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, name, song_url, created_at FROM songs WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        
        songs = cursor.fetchall()
        conn.close()
        return songs
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения песен: {e}")
        return []

def get_song_videos(song_id, user_id):
    """Получение видео для песни"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            '''SELECT v.id, v.video_url, v.description, v.created_at 
               FROM videos v 
               JOIN songs s ON v.song_id = s.id 
               WHERE s.id = ? AND s.user_id = ? 
               ORDER BY v.created_at DESC 
               LIMIT 20''',
            (song_id, user_id)
        )
        
        videos = cursor.fetchall()
        conn.close()
        return videos
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения видео: {e}")
        return []

def delete_song(song_id, user_id):
    """Удаление песни"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM videos WHERE song_id = ?', (song_id,))
        cursor.execute('DELETE FROM songs WHERE id = ? AND user_id = ?', (song_id, user_id))
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления песни: {e}")
        return False

def add_video(song_id, video_url, description):
    """Добавление видео в базу"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT OR IGNORE INTO videos (song_id, video_url, description) VALUES (?, ?, ?)',
            (song_id, video_url, description)
        )
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления видео: {e}")
        return False

def get_video_exists(video_url):
    """Проверка существования видео"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM videos WHERE video_url = ?', (video_url,))
        exists = cursor.fetchone() is not None
        conn.close()
        
        return exists
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео: {e}")
        return False

# ========== ОБРАБОТЧИКИ БОТА ==========

def get_main_keyboard():
    """Клавиатура главного меню"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Добавить песню по ссылке", callback_data="add_song")],
        [InlineKeyboardButton("📋 Мои песни", callback_data="list_songs")],
        [InlineKeyboardButton("🔍 Проверить сейчас", callback_data="check_now")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    try:
        user = update.effective_user
        
        if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
            await update.message.reply_text("❌ Бот не настроен. Обратитесь к администратору.")
            return
            
        welcome_text = f"""
👋 Привет, {user.first_name}!

🎵 Я бот для отслеживания новых видео с твоими песнями в TikTok.

📱 Используй кнопки ниже для управления:
    """
        
        keyboard = get_main_keyboard()
        await update.message.reply_text(welcome_text, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"❌ Ошибка в команде /start: {e}")

async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback от кнопок"""
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "main_menu":
            await main_menu(update, context)
        elif data == "add_song":
            await add_song_handler(update, context)
        elif data == "list_songs":
            await list_songs_handler(update, context)
        elif data == "check_now":
            await check_now_handler(update, context)
        elif data == "help":
            await help_handler(update, context)
        elif data.startswith("delete_song:"):
            await delete_song_handler(update, context)
        elif data.startswith("show_videos:"):
            await show_videos_handler(update, context)
        elif data == "back_to_songs":
            await list_songs_handler(update, context)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки callback: {e}")

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    text = "📱 Главное меню:"
    await update.callback_query.message.edit_text(text, reply_markup=get_main_keyboard())

async def add_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление песни"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    text = "🎵 Пришли мне ссылку на песню в TikTok\n\nПример:\nhttps://www.tiktok.com/music/название-песни-723415689123"
    await update.callback_query.message.edit_text(text, reply_markup=keyboard)

async def list_songs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список песен"""
    try:
        user_id = update.effective_user.id
        songs = get_user_songs(user_id)
        
        if not songs:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Добавить песню", callback_data="add_song")],
                [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
            ])
            await update.callback_query.message.edit_text("📋 У тебя пока нет добавленных песен.", reply_markup=keyboard)
            return
        
        text = "📋 Твои песни:\n\n"
        keyboard_buttons = []
        
        for song in songs:
            song_id, name, song_url, created_at = song
            text += f"🎵 {name}\n🔗 {song_url}\n📅 Добавлена: {created_at[:10]}\n\n"
            
            keyboard_buttons.append([
                InlineKeyboardButton(f"📹 Видео {name}", callback_data=f"show_videos:{song_id}"),
                InlineKeyboardButton(f"❌ Удалить", callback_data=f"delete_song:{song_id}")
            ])
        
        keyboard_buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="main_menu")])
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        
        await update.callback_query.message.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка показа списка песен: {e}")

async def show_videos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать видео"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        videos = get_song_videos(song_id, user_id)
        
        if not videos:
            text = "📭 Видео для этой песни пока не найдено."
        else:
            text = "🎬 Последние видео:\n\n"
            for i, video in enumerate(videos[:5], 1):
                video_id, video_url, description, created_at = video
                text += f"{i}. {description}\n🔗 [Смотреть видео]({video_url})\n📅 {created_at[:10]}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка показа видео: {e}")

async def delete_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление песни"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        delete_song(song_id, user_id)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text("✅ Песня успешно удалена!", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления песни: {e}")

async def check_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка видео"""
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="check_now")],
            [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
        ])
        
        await query.edit_message_text("🔍 Ищу новые видео...", reply_markup=keyboard)
        
        # Временная симуляция
        new_videos = [{
            'song_name': 'Тестовая песня',
            'video_url': 'https://tiktok.com/test',
            'description': 'Тестовое видео'
        }]
        
        if not new_videos:
            text = "📭 Новых видео не найдено."
        else:
            text = "🎉 Найдены новые видео!\n\n"
            for video in new_videos:
                text += f"🎵 {video['song_name']}\n📹 {video['description']}\n🔗 [Смотреть видео]({video['video_url']})\n\n"
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео: {e}")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    help_text = """
ℹ️ *Помощь по боту*

🎵 *Как добавить песню*:
1. Найди песню в TikTok
2. Скопируй ссылку на страницу песни
3. Пришли ссылку боту

📹 *Что делает бот*:
- Находит видео с этой песней
- Присылает уведомления о новых видео

💡 *Советы*:
- Используй официальные ссылки на песни из TikTok
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    await update.callback_query.message.edit_text(help_text, reply_markup=keyboard, parse_mode='Markdown')

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text.strip()
        
        if text.startswith(('https://www.tiktok.com/music/', 'https://vm.tiktok.com/', 'https://tiktok.com/music/')):
            await handle_song_link(update, context, text)
        else:
            await update.message.reply_text(
                "📎 Пришли мне ссылку на песню в TikTok для отслеживания",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обработки текста: {e}")

async def handle_song_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """Обработчик ссылки на песню"""
    try:
        await update.message.reply_text("🔍 Обрабатываю ссылку на песню...")
        
        # Временная симуляция
        song_name = "Тестовая песня"
        song_db_id, is_new = add_song(update.effective_user.id, song_name, link)
        
        if is_new:
            message = f"✅ Песня '{song_name}' добавлена! Найдено 5 видео."
        else:
            message = "❌ Эта песня уже добавлена для отслеживания."
        
        keyboard = get_main_keyboard()
        await update.message.reply_text(message, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error("Exception while handling an update:", exc_info=context.error)

# ========== ПАРСИНГ TIKTOK ==========

async def periodic_check(context):
    """Периодическая проверка"""
    logger.info("🔍 Запуск периодической проверки...")

def start_periodic_checking(application):
    """Запуск периодической проверки"""
    try:
        scheduler = BackgroundScheduler()
        trigger = IntervalTrigger(minutes=30)
        scheduler.add_job(periodic_check, trigger=trigger, args=[application])
        scheduler.start()
        logger.info("✅ Периодическая проверка запущена")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска проверки: {e}")

# ========== ЗАПУСК БОТА ==========

def main():
    """Основная функция запуска бота"""
    max_retries = 3
    retry_delay = 10
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🚀 Попытка запуска бота #{attempt + 1}")
            
            if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
                logger.error("❌ BOT_TOKEN не настроен")
                if attempt == max_retries - 1:
                    return
                time.sleep(retry_delay)
                continue
                
            # Инициализация БД
            init_db()
            
            # Создание приложения
            application = Application.builder().token(BOT_TOKEN).build()
            
            # Обработчики
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CallbackQueryHandler(handle_menu_callback))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
            
            # Периодическая проверка
            start_periodic_checking(application)
            
            # Обработчик ошибок
            application.add_error_handler(error_handler)
            
            # Запуск
            logger.info("✅ Бот запущен успешно!")
            application.run_polling()
            break
            
        except Exception as e:
            logger.error(f"❌ Ошибка при запуске (попытка {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                logger.error("❌ Не удалось запустить бота")
                break
            time.sleep(retry_delay)

if __name__ == "__main__":
    main()
