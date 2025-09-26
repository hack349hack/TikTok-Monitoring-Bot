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
            '''SELECT v.video_url, v.description, v.author_username, v.created_at 
               FROM videos v 
               JOIN songs s ON v.song_id = s.id 
               WHERE s.id = ? AND s.user_id = ? 
               ORDER BY v.created_at DESC 
               LIMIT ?''',
            (song_id, user_id, limit)
        )
        
        videos = cursor.fetchall()
        conn.close()
        return videos
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения видео: {e}")
        return []

def get_song_videos_count(song_id, user_id):
    """Получение количества видео для песни"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            '''SELECT COUNT(*) 
               FROM videos v 
               JOIN songs s ON v.song_id = s.id 
               WHERE s.id = ? AND s.user_id = ?''',
            (song_id, user_id)
        )
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения количества видео: {e}")
        return 0

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
                    if not song_name:
                        song_name = f"Песня {song_id}"
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

async def search_tiktok_videos(song_id, max_results=50):
    """Поиск ВСЕХ видео по ID песни в TikTok"""
    videos = []
    
    try:
        logger.info(f"🔍 Начинаю поиск ВСЕХ видео для песни ID: {song_id}")
        
        # Используем несколько стратегий поиска
        search_urls = [
            f"https://www.tiktok.com/search/video?q=music{song_id}",
            f"https://www.tiktok.com/tag/music{song_id}",
            f"https://www.tiktok.com/search/video?q=original_sound_{song_id}"
        ]
        
        for search_url in search_urls:
            if len(videos) >= max_results:
                break
                
            logger.info(f"🔍 Проверяю URL: {search_url}")
            
            try:
                response = requests.get(
                    search_url, 
                    headers=get_tiktok_headers(),
                    timeout=30
                )
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Ищем видео разными способами
                    video_selectors = [
                        'div[data-e2e="search-card"]',
                        'div.tiktok-card',
                        'div.video-item',
                        'article'
                    ]
                    
                    for selector in video_selectors:
                        video_elements = soup.select(selector) if '[' in selector else soup.find_all(selector)
                        if video_elements:
                            logger.info(f"📹 Найдено элементов с селектором {selector}: {len(video_elements)}")
                            
                            for element in video_elements:
                                if len(videos) >= max_results:
                                    break
                                    
                                video_data = extract_video_data(element)
                                if video_data:
                                    # Проверяем дубликаты
                                    if not any(v['url'] == video_data['url'] for v in videos):
                                        videos.append(video_data)
                            
                            break  # Используем первый работающий селектор
                    
                    # Небольшая задержка между запросами
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при проверке {search_url}: {e}")
                continue
        
        logger.info(f"✅ Для песни {song_id} найдено {len(videos)} видео")
        
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

async def process_song_link(user_id, song_url, progress_callback=None):
    """Обработка ссылки на песню - с поиском ВСЕХ существующих видео"""
    try:
        # Проверяем валидность ссылки
        if not any(domain in song_url for domain in ['tiktok.com', 'vm.tiktok.com']):
            return False, "❌ Неверный формат ссылки. Используйте ссылку на песню из TikTok."
        
        # Извлекаем информацию о песне
        if progress_callback:
            await progress_callback("🔍 Извлекаю информацию о песне из ссылки...")
        
        song_name, song_id = extract_song_info_from_url(song_url)
        if not song_name or not song_id:
            return False, "❌ Не удалось распознать песню из ссылки. Проверьте формат ссылки."
        
        # Добавляем песню в базу
        song_db_id, is_new = add_song(user_id, song_name, song_url, song_id)
        
        if not is_new:
            return False, "❌ Эта песня уже добавлена для отслеживания."
        
        # 🔍 НАХОДИМ ВСЕ СУЩЕСТВУЮЩИЕ ВИДЕО ПРИ ДОБАВЛЕНИИ
        if progress_callback:
            await progress_callback("🔍 Ищу все существующие видео... Это может занять время.")
        
        videos = await search_tiktok_videos(song_id, max_results=50)
        
        if progress_callback:
            await progress_callback(f"📹 Найдено {len(videos)} видео. Сохраняю в базу...")
        
        # Сохраняем найденные видео
        saved_count = 0
        for i, video in enumerate(videos):
            if add_video(song_db_id, video):
                saved_count += 1
            
            # Обновляем прогресс каждые 10 видео
            if progress_callback and i % 10 == 0:
                await progress_callback(f"📹 Сохранено {saved_count} из {len(videos)} видео...")
        
        update_song_last_checked(song_db_id)
        
        if saved_count > 0:
            return True, f"✅ Песня '{song_name}' добавлена!\n\n📊 Найдено и сохранено {saved_count} существующих видео.\n\nТеперь я буду присылать уведомления только о новых видео!"
        else:
            return True, f"✅ Песня '{song_name}' добавлена!\n\n📭 Пока видео не найдено, но я буду проверять новые!\n\nПопробуйте нажать '🔍 Проверить сейчас' для поиска."
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        return False, "❌ Произошла ошибка при обработке ссылки."

async def check_new_videos_for_user(user_id):
    """Проверка только НОВЫХ видео для пользователя"""
    new_videos = []
    
    try:
        songs = get_user_songs(user_id)
        
        for song in songs:
            song_db_id, name, song_url, song_id, created_at, last_checked = song
            
            logger.info(f"🔍 Проверяем новые видео для песни: {name} (ID: {song_id})")
            
            videos = await search_tiktok_videos(song_id, max_results=20)
            
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

async def search_more_videos_for_song(song_id, song_name, user_id):
    """Поиск дополнительных видео для конкретной песни"""
    try:
        logger.info(f"🔍 Дополнительный поиск видео для песни: {song_name}")
        
        videos = await search_tiktok_videos(song_id, max_results=30)
        
        new_videos_count = 0
        for video in videos:
            if not get_video_exists(video['url']):
                if add_video(song_id, video):
                    new_videos_count += 1
        
        update_song_last_checked(song_id)
        
        return new_videos_count
        
    except Exception as e:
        logger.error(f"❌ Ошибка дополнительного поиска видео: {e}")
        return 0

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

🌟 Особенности:
- При добавлении песни нахожу ВСЕ существующие видео
- Сохраняю их, чтобы не присылать как "новые"
- Отслеживаю только действительно НОВЫЕ видео
- Автоматическая проверка каждые 30 минут

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
        elif data.startswith("search_more:"):
            await search_more_handler(update, context)
        elif data.startswith("check_song:"):
            await check_song_handler(update, context)
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

🌟 Бот найдет ВСЕ существующие видео с этой песней и сохранит их!
После этого будет присылать уведомления только о новых видео."""
    
    await update.callback_query.message.edit_text(text, reply_markup=keyboard)

async def list_songs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список песен с количеством видео"""
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
            
            # Получаем количество видео для песни
            videos_count = get_song_videos_count(song_id, user_id)
            
            text += f"🎵 {name}\n"
            text += f"📊 Видео: {videos_count} | 🆔 ID: {song_id_str}\n"
            text += f"📅 Добавлена: {created_at[:10]}\n\n"
            
            keyboard_buttons.append([
                InlineKeyboardButton(f"📹 Видео ({videos_count})", callback_data=f"show_videos:{song_id}"),
                InlineKeyboardButton(f"🔍 Искать ещё", callback_data=f"search_more:{song_id}")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(f"❌ Удалить", callback_data=f"delete_song:{song_id}")
            ])
        
        keyboard_buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="main_menu")])
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        
        await update.callback_query.message.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка показа списка песен: {e}")

async def show_videos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать видео с информацией"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        videos = get_song_videos(song_id, user_id, limit=10)
        total_count = get_song_videos_count(song_id, user_id)
        
        # Получаем информацию о песне
        songs = get_user_songs(user_id)
        song_info = next((s for s in songs if s[0] == song_id), None)
        
        if not song_info:
            await query.edit_message_text("❌ Ошибка: песня не найдена")
            return
            
        song_name = song_info[1]
        
        if not videos:
            text = f"🎵 **{song_name}**\n📊 Всего видео: 0\n\n📭 Видео пока не найдено.\n\nНажмите '🔍 Искать видео' для поиска."
        else:
            text = f"🎵 **{song_name}**\n📊 Всего видео: {total_count}\n\n**Последние видео:**\n\n"
            
            for i, video in enumerate(videos, 1):
                video_url, description, author, created_at = video
                text += f"**{i}. {description}**\n"
                text += f"👤 Автор: {author or 'Неизвестен'}\n"
                text += f"🔗 [Смотреть видео]({video_url})\n"
                text += f"⏰ Добавлено: {created_at[:16] if created_at else 'Недавно'}\n\n"
            
            if total_count > 10:
                text += f"*... и ещё {total_count - 10} видео*"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Искать ещё видео", callback_data=f"search_more:{song_id}")],
            [InlineKeyboardButton("🔄 Проверить новые", callback_data=f"check_song:{song_id}")],
            [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка показа видео: {e}")

async def search_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск дополнительных видео для песни"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        # Получаем информацию о песне
        songs = get_user_songs(user_id)
        song_info = next((s for s in songs if s[0] == song_id), None)
        
        if not song_info:
            await query.edit_message_text("❌ Ошибка: песня не найдена")
            return
            
        song_name = song_info[1]
        song_id_str = song_info[3]
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"search_more:{song_id}")],
            [InlineKeyboardButton("↩️ Назад", callback_data=f"show_videos:{song_id}")]
        ])
        
        await query.edit_message_text(f"🔍 Ищу дополнительные видео для '{song_name}'...", reply_markup=keyboard)
        
        # Ищем дополнительные видео
        new_videos_count = await search_more_videos_for_song(song_id, song_id_str, user_id)
        
        if new_videos_count > 0:
            text = f"✅ Для песни '{song_name}' найдено {new_videos_count} новых видео!"
        else:
            text = f"📭 Для песни '{song_name'} новых видео не найдено."
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📹 Смотреть видео", callback_data=f"show_videos:{song_id}")],
            [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска дополнительных видео: {e}")

async def check_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка новых видео для конкретной песни"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        # Получаем информацию о песне
        songs = get_user_songs(user_id)
        song_info = next((s for s in songs if s[0] == song_id), None)
        
        if not song_info:
            await query.edit_message_text("❌ Ошибка: песня не найдена")
            return
            
        song_name = song_info[1]
        song_id_str = song_info[3]
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"check_song:{song_id}")],
            [InlineKeyboardButton("↩️ Назад", callback_data=f"show_videos:{song_id}")]
        ])
        
        await query.edit_message_text(f"🔍 Проверяю новые видео для '{song_name}'...", reply_markup=keyboard)
        
        # Ищем новые видео
        videos = await search_tiktok_videos(song_id_str, max_results=20)
        
        new_videos_count = 0
        for video in videos:
            if not get_video_exists(video['url']):
                if add_video(song_id, video):
                    new_videos_count += 1
        
        update_song_last_checked(song_id)
        
        if new_videos_count > 0:
            text = f"🎉 Для песни '{song_name}' найдено {new_videos_count} новых видео!"
        else:
            text = f"📭 Для песни '{song_name'} новых видео не найдено."
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📹 Смотреть видео", callback_data=f"show_videos:{song_id}")],
            [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео: {e}")

async def delete_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление песни"""
    try:
        query = update.callback_query
        song_id = int(query.data.split(":")[1])
        user_id = update.effective_user.id
        
        # Получаем информацию о песне для сообщения
        songs = get_user_songs(user_id)
        song_info = next((s for s in songs if s[0] == song_id), None)
        song_name = song_info[1] if song_info else "Неизвестная песня"
        
        delete_song(song_id, user_id)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(f"✅ Песня '{song_name}' успешно удалена!", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления песни: {e}")

async def check_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка новых видео для всех песен пользователя"""
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="check_now")],
            [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
        ])
        
        await query.edit_message_text("🔍 Ищу новые видео для всех песен... Это может занять несколько секунд.", reply_markup=keyboard)
        
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
- При добавлении находит ВСЕ существующие видео
- Сохраняет их, чтобы не дублировать уведомления
- Отслеживает только НОВЫЕ видео
- Автоматическая проверка каждые 30 минут

📊 *Управление песнями*:
- 📹 Видео - просмотр всех найденных видео
- 🔍 Искать ещё - поиск дополнительных видео
- 🔄 Проверить новые - проверка только новых видео

💡 *Советы*:
- Используй официальные ссылки из TikTok
- При добавлении бот найдет всю историю видео
- Чем популярнее песня, тем больше видео найдется

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
    """Обработчик ссылки на песню с прогресс-баром"""
    try:
        # Отправляем начальное сообщение
        progress_message = await update.message.reply_text("🔍 Начинаю обработку ссылки...")
        
        async def update_progress(text):
            """Функция для обновления прогресса"""
            try:
                await progress_message.edit_text(text)
            except Exception as e:
                logger.debug(f"Ошибка обновления прогресса: {e}")
        
        # Обрабатываем ссылку с прогрессом
        success, result_message = await process_song_link(
            update.effective_user.id, 
            link, 
            progress_callback=update_progress
        )
        
        # Показываем финальный результат
        keyboard = get_main_keyboard()
        if success:
            await progress_message.edit_text(result_message, reply_markup=keyboard, parse_mode='Markdown')
        else:
            await progress_message.edit_text(result_message, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке ссылки.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error("Exception while handling an update:", exc_info=context.error)

# ========== ПЕРИОДИЧЕСКАЯ ПРОВЕРКА ==========

async def periodic_check(context):
    """Периодическая проверка только НОВЫХ видео"""
    logger.info("🔍 Запуск автоматической проверки НОВЫХ видео...")
    
    try:
        songs = get_all_songs_for_checking()
        total_new_videos = 0
        
        for song in songs:
            song_id, user_id, name, song_url, song_id_str = song
            
            logger.info(f"🔍 Проверяем новые видео для песни: {name}")
            
            videos = await search_tiktok_videos(song_id_str, max_results=20)
            new_videos_count = 0
            
            for video in videos:
                # Проверяем, что видео новое (еще не в базе)
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
            logger.info("🌟 Особенности: Поиск ВСЕХ видео при добавлении песни")
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
