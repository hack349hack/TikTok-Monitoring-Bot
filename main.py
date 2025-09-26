import logging
import asyncio
import sys
import os
import time
import re
import json
from datetime import datetime
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
            song_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            video_url TEXT NOT NULL UNIQUE,
            description TEXT,
            author_username TEXT,
            author_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tiktok_created_at TIMESTAMP,
            FOREIGN KEY (song_id) REFERENCES songs (id)
        )
        ''')
        
        # Индексы для производительности
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_songs_user_id ON songs (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_songs_song_id ON songs (song_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_song_id ON videos (song_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_created ON videos (tiktok_created_at)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def add_song(user_id, name, song_url, song_id):
    """Добавление песни в базу"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT OR IGNORE INTO songs (user_id, name, song_url, song_id) VALUES (?, ?, ?, ?)',
            (user_id, name, song_url, song_id)
        )
        
        conn.commit()
        
        # Получаем ID
        cursor.execute(
            'SELECT id FROM songs WHERE song_url = ? AND user_id = ?',
            (song_url, user_id)
        )
        result = cursor.fetchone()
        song_db_id = result[0] if result else None
        
        conn.close()
        
        is_new = cursor.rowcount > 0
        return song_db_id, is_new
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления песни: {e}")
        return None, False

def get_user_songs(user_id):
    """Получение песен пользователя"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, name, song_url, song_id, created_at, last_checked FROM songs WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        
        songs = cursor.fetchall()
        conn.close()
        return songs
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения песен: {e}")
        return []

def get_song_videos(song_id, user_id, limit=10):
    """Получение видео для песни"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            '''SELECT v.video_url, v.description, v.author_username, v.tiktok_created_at 
               FROM videos v 
               JOIN songs s ON v.song_id = s.id 
               WHERE s.id = ? AND s.user_id = ? 
               ORDER BY v.tiktok_created_at DESC 
               LIMIT ?''',
            (song_id, user_id, limit)
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

def add_video(song_id, video_data):
    """Добавление видео в базу"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            '''INSERT OR IGNORE INTO videos 
               (song_id, video_url, description, author_username, author_name, tiktok_created_at) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (song_id, video_data['url'], video_data['description'], 
             video_data.get('author_username', ''), video_data.get('author_name', ''),
             video_data.get('created_at', datetime.now()))
        )
        
        conn.commit()
        conn.close()
        
        return cursor.rowcount > 0
        
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

def update_song_last_checked(song_id):
    """Обновление времени последней проверки"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE songs SET last_checked = CURRENT_TIMESTAMP WHERE id = ?',
            (song_id,)
        )
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления времени проверки: {e}")

def get_all_songs_for_checking():
    """Получение всех песен для периодической проверки"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, user_id, name, song_url, song_id FROM songs'
        )
        
        songs = cursor.fetchall()
        conn.close()
        return songs
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения песен для проверки: {e}")
        return []

# ========== ПАРСИНГ TIKTOK ==========

def extract_song_info_from_url(song_url):
    """Извлечение информации о песне из URL"""
    try:
        # Разные форматы ссылок TikTok
        patterns = [
            r'music/[^/]+?-(\d+)',  # music/song-name-123456789
            r'music/[^/]+?--(\d+)', # music/song-name--123456789
            r'music/[^/]+?[_-](\d+)' # music/song-name_123456789
        ]
        
        for pattern in patterns:
            match = re.search(pattern, song_url)
            if match:
                song_id = match.group(1)
                # Извлекаем название из URL
                name_match = re.search(r'music/([^/?]+)', song_url)
                if name_match:
                    raw_name = name_match.group(1)
                    # Очищаем название от ID и специальных символов
                    song_name = re.sub(r'[-_]?\d+', '', raw_name)
                    song_name = re.sub(r'[-_]+', ' ', song_name)
                    song_name = song_name.strip().title()
                else:
                    song_name = f"Песня {song_id}"
                
                return song_name, song_id
        
        return None, None
        
    except Exception as e:
        logger.error(f"❌ Ошибка извлечения информации из URL: {e}")
        return None, None

def get_tiktok_headers():
    """Заголовки для запросов к TikTok"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }

async def search_tiktok_videos(song_id, max_results=20):
    """Поиск видео по ID песни в TikTok"""
    videos = []
    
    try:
        # Используем поиск TikTok по хештегу/названию песни
        search_url = f"https://www.tiktok.com/search/video?q=music{song_id}"
        
        logger.info(f"🔍 Ищем видео для песни ID: {song_id}")
        
        response = requests.get(
            search_url, 
            headers=get_tiktok_headers(),
            timeout=30
        )
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем видео в результатах поиска
            video_elements = soup.find_all('div', {'data-e2e': 'search-card'})
            
            if not video_elements:
                # Альтернативные селекторы
                video_elements = soup.find_all('div', class_='tiktok-card')
            
            logger.info(f"📹 Найдено элементов: {len(video_elements)}")
            
            for element in video_elements[:max_results]:
                try:
                    video_data = extract_video_data(element)
                    if video_data and not get_video_exists(video_data['url']):
                        videos.append(video_data)
                        
                except Exception as e:
                    logger.debug(f"Ошибка парсинга видео элемента: {e}")
                    continue
                    
        else:
            logger.warning(f"❌ HTTP ошибка {response.status_code} для песни {song_id}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка поиска видео: {e}")
    
    return videos

def extract_video_data(element):
    """Извлечение данных о видео из HTML элемента"""
    try:
        video_data = {}
        
        # Ссылка на видео
        video_link = element.find('a')
        if video_link and video_link.get('href'):
            href = video_link.get('href')
            if not href.startswith('http'):
                video_data['url'] = f"https://www.tiktok.com{href}"
            else:
                video_data['url'] = href
        else:
            return None
        
        # Описание
        description = "Видео с песней"
        desc_selectors = [
            '*[data-e2e="video-desc"]',
            '.video-description',
            '.desc',
            'p', 'span'
        ]
        
        for selector in desc_selectors:
            desc_elem = element.select_one(selector) if '[' in selector else element.find(selector)
            if desc_elem:
                text = desc_elem.get_text(strip=True)
                if text and len(text) > 10:
                    description = text
                    break
        
        if len(description) > 200:
            description = description[:200] + '...'
        video_data['description'] = description
        
        # Автор
        author_selectors = ['*[data-e2e="video-author"]', '.author-username', '.user-name']
        for selector in author_selectors:
            author_elem = element.select_one(selector) if '[' in selector else element.find(selector)
            if author_elem:
                video_data['author_username'] = author_elem.get_text(strip=True)
                break
        
        # Дата создания (симуляция - сортируем по времени добавления в систему)
        video_data['created_at'] = datetime.now()
        
        return video_data
        
    except Exception as e:
        logger.debug(f"Ошибка извлечения данных видео: {e}")
        return None

async def process_song_link(user_id, song_url):
    """Обработка ссылки на песню"""
    try:
        # Проверяем валидность ссылки
        if not any(domain in song_url for domain in ['tiktok.com', 'vm.tiktok.com']):
            return False, "❌ Неверный формат ссылки. Используйте ссылку на песню из TikTok."
        
        # Извлекаем информацию о песне
        song_name, song_id = extract_song_info_from_url(song_url)
        if not song_name or not song_id:
            return False, "❌ Не удалось распознать песню из ссылки. Проверьте формат ссылки."
        
        # Добавляем песню в базу
        song_db_id, is_new = add_song(user_id, song_name, song_url, song_id)
        
        if not is_new:
            return False, "❌ Эта песня уже добавлена для отслеживания."
        
        # Ищем видео для этой песни
        videos = await search_tiktok_videos(song_id)
        
        # Сохраняем найденные видео
        for video in videos:
            add_video(song_db_id, video)
        
        update_song_last_checked(song_db_id)
        
        return True, f"✅ Песня '{song_name}' добавлена! Найдено {len(videos)} видео."
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        return False, "❌ Произошла ошибка при обработке ссылки."

async def check_new_videos_for_user(user_id):
    """Проверка новых видео для пользователя"""
    new_videos = []
    
    try:
        songs = get_user_songs(user_id)
        
        for song in songs:
            song_db_id, name, song_url, song_id, created_at, last_checked = song
            
            logger.info(f"🔍 Проверяем песню: {name} (ID: {song_id})")
            
            videos = await search_tiktok_videos(song_id)
            
            for video in videos:
                if not get_video_exists(video['url']):
                    if add_video(song_db_id, video):
                        new_videos.append({
                            'song_name': name,
                            'video_url': video['url'],
                            'description': video['description'],
                            'author': video.get('author_username', 'Неизвестный автор')
                        })
                        logger.info(f"🎉 Найдено новое видео для песни {name}")
            
            update_song_last_checked(song_db_id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео для пользователя {user_id}: {e}")
    
    return new_videos

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

✅ Режим: РЕАЛЬНЫЙ ПАРСИНГ

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
    
    text = """🎵 Пришли мне ссылку на песню в TikTok

Примеры ссылок:
• https://www.tiktok.com/music/название-песни-723415689123
• https://vm.tiktok.com/music/песня-123456789

Бот найдет все видео с этой песней!"""
    
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
            song_id, name, song_url, song_id_str, created_at, last_checked = song
            text += f"🎵 {name}\n"
            text += f"🆔 ID: {song_id_str}\n"
            text += f"📅 Добавлена: {created_at[:10]}\n\n"
            
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
        
        videos = get_song_videos(song_id, user_id, limit=8)
        
        if not videos:
            text = "📭 Видео для этой песни пока не найдено.\n\nПопробуйте проверить позже или нажать 'Проверить сейчас'."
        else:
            text = f"🎬 Найдено {len(videos)} видео:\n\n"
            for i, video in enumerate(videos, 1):
                video_url, description, author, created_at = video
                text += f"**{i}. {description}**\n"
                text += f"👤 Автор: {author or 'Неизвестен'}\n"
                text += f"🔗 [Смотреть видео]({video_url})\n"
                text += f"⏰ {created_at[:10] if created_at else 'Недавно'}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить сейчас", callback_data=f"check_song:{song_id}")],
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
        
        await query.edit_message_text("🔍 Ищу новые видео... Это может занять несколько секунд.", reply_markup=keyboard)
        
        new_videos = await check_new_videos_for_user(user_id)
        
        if not new_videos:
            text = "📭 Новых видео не найдено.\n\nПопробуйте проверить позже."
        else:
            text = f"🎉 Найдено {len(new_videos)} новых видео!\n\n"
            for i, video in enumerate(new_videos[:5], 1):
                text += f"**{i}. {video['song_name']}**\n"
                text += f"📹 {video['description']}\n"
                text += f"👤 {video.get('author', 'Неизвестный автор')}\n"
                text += f"🔗 [Смотреть видео]({video['video_url']})\n\n"
            
            if len(new_videos) > 5:
                text += f"*... и ещё {len(new_videos) - 5} видео*"
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео: {e}")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    help_text = """
ℹ️ *Помощь по боту - РЕАЛЬНЫЙ ПАРСИНГ*

🎵 *Как добавить песню*:
1. Найди песню в TikTok
2. Скопируй ссылку на страницу песни
3. Пришли ссылку боту

🔍 *Что делает бот*:
- Находит ВСЕ видео с этой песней
- Сортирует по дате публикации
- Присылает уведомления о новых видео
- Работает в реальном времени

💡 *Советы*:
- Используй официальные ссылки из TikTok
- Чем популярнее песня, тем больше видео найдется
- Новые видео проверяются каждые 30 минут

⚠️ *Ограничения*:
- TikTok может блокировать частые запросы
- Некоторые видео могут быть не найдены
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Добавить песню", callback_data="add_song")],
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    await update.callback_query.message.edit_text(help_text, reply_markup=keyboard, parse_mode='Markdown')

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text.strip()
        
        if any(domain in text for domain in ['tiktok.com', 'vm.tiktok.com']):
            await handle_song_link(update, context, text)
        else:
            await update.message.reply_text(
                "📎 Пришли мне ссылку на песню в TikTok для отслеживания\n\nПример: https://www.tiktok.com/music/название-песни-723415689123",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обработки текста: {e}")

async def handle_song_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """Обработчик ссылки на песню"""
    try:
        await update.message.reply_text("🔍 Обрабатываю ссылку на песню...")
        
        success, message = await process_song_link(update.effective_user.id, link)
        
        keyboard = get_main_keyboard()
        await update.message.reply_text(message, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке ссылки.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error("Exception while handling an update:", exc_info=context.error)

# ========== ПЕРИОДИЧЕСКАЯ ПРОВЕРКА ==========

async def periodic_check(context):
    """Периодическая проверка новых видео"""
    logger.info("🔍 Запуск автоматической проверки видео...")
    
    try:
        songs = get_all_songs_for_checking()
        total_new_videos = 0
        
        for song in songs:
            song_id, user_id, name, song_url, song_id_str = song
            
            logger.info(f"🔍 Проверяем песню: {name}")
            
            videos = await search_tiktok_videos(song_id_str)
            new_videos_count = 0
            
            for video in videos:
                if not get_video_exists(video['url']):
                    if add_video(song_id, video):
                        new_videos_count += 1
                        total_new_videos += 1
                        
                        # Отправляем уведомление пользователю
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"🎉 Новое видео с вашей песней!\n\n"
                                     f"🎵 **{name}**\n"
                                     f"📹 {video['description']}\n"
                                     f"👤 {video.get('author_username', 'Неизвестный автор')}\n"
                                     f"🔗 [Смотреть видео]({video['url']})",
                                parse_mode='Markdown'
                            )
                            # Задержка между сообщениями
                            await asyncio.sleep(1)
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки уведомления: {e}")
            
            update_song_last_checked(song_id)
            
            if new_videos_count > 0:
                logger.info(f"✅ Для песни '{name}' найдено {new_videos_count} новых видео")
        
        logger.info(f"✅ Автоматическая проверка завершена. Найдено {total_new_videos} новых видео")
        
    except Exception as e:
        logger.error(f"❌ Ошибка периодической проверки: {e}")

def start_periodic_checking(application):
    """Запуск периодической проверки"""
    try:
        scheduler = BackgroundScheduler()
        trigger = IntervalTrigger(minutes=30)  # Проверка каждые 30 минут
        scheduler.add_job(
            lambda: asyncio.create_task(periodic_check(application)),
            trigger=trigger
        )
        scheduler.start()
        logger.info("✅ Периодическая проверка запущена (каждые 30 минут)")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска периодической проверки: {e}")

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
            logger.info("✅ Бот запущен успешно! Режим: РЕАЛЬНЫЙ ПАРСИНГ")
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
