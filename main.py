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

# ========== РЕАЛЬНЫЙ ПАРСИНГ TIKTOK ==========

def extract_song_info_from_url(song_url):
    """Извлечение информации о песне из URL"""
    try:
        # Разные форматы ссылок TikTok
        patterns = [
            r'music/[^/]+?-(\d+)',
            r'music/[^/]+?--(\d+)', 
            r'music/[^/]+?[_-](\d+)',
            r'music/[^/?]+[?&]id=(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, song_url)
            if match:
                song_id = match.group(1)
                # Извлекаем название
                name_match = re.search(r'music/([^/?]+)', song_url)
                if name_match:
                    raw_name = name_match.group(1)
                    song_name = re.sub(r'[-_]?\d+', '', raw_name)
                    song_name = re.sub(r'[-_]+', ' ', song_name).strip().title()
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
    """Современные заголовки для обхода защиты TikTok"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.tiktok.com/',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

async def make_tiktok_request(url, max_retries=3):
    """Безопасный запрос к TikTok с повторными попытками"""
    for attempt in range(max_retries):
        try:
            headers = get_tiktok_headers()
            # Добавляем случайную задержку
            await asyncio.sleep(attempt * 2)
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return response
            elif response.status_code == 403:
                logger.warning(f"⚠️ Доступ запрещен (403). Попытка {attempt + 1}")
                # Меняем User-Agent
                headers['User-Agent'] = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/12{attempt}.0.0.0 Safari/537.36'
            elif response.status_code == 429:
                logger.warning(f"⚠️ Слишком много запросов (429). Пауза...")
                await asyncio.sleep(10)
                
        except requests.RequestException as e:
            logger.warning(f"⚠️ Ошибка запроса (попытка {attempt + 1}): {e}")
    
    return None

async def parse_tiktok_api(song_id, max_results=50):
    """Парсинг через неофициальное API TikTok"""
    videos = []
    
    try:
        logger.info(f"🔍 Парсим через API для песни ID: {song_id}")
        
        # Популярные эндпоинты для поиска видео по звуку
        api_endpoints = [
            f"https://www.tiktok.com/api/music/item_list/?musicId={song_id}&count=30",
            f"https://www.tiktok.com/api/sound/item_list/?soundId={song_id}&count=30",
            f"https://www.tiktok.com/node/share/music/{song_id}",
        ]
        
        for endpoint in api_endpoints:
            if len(videos) >= max_results:
                break
                
            logger.info(f"🔧 Пробуем endpoint: {endpoint}")
            response = await make_tiktok_request(endpoint)
            
            if response and response.status_code == 200:
                try:
                    data = response.json()
                    videos.extend(extract_videos_from_api_data(data, song_id))
                    logger.info(f"✅ Из endpoint получено видео: {len(videos)}")
                except json.JSONDecodeError:
                    # Пробуем парсить HTML если JSON не валидный
                    videos.extend(await parse_html_for_videos(response.text, song_id))
            
            await asyncio.sleep(2)  # Пауза между запросами
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга API: {e}")
    
    return videos[:max_results]

def extract_videos_from_api_data(data, song_id):
    """Извлечение видео из данных API"""
    videos = []
    
    try:
        # Разные структуры ответа API
        if 'itemList' in data:
            items = data['itemList']
        elif 'items' in data:
            items = data['items']
        elif 'body' in data and 'itemListData' in data['body']:
            items = data['body']['itemListData']
        else:
            # Пробуем найти видео в любой структуре
            items = find_videos_in_json(data)
        
        for item in items[:30]:  # Ограничиваем количество
            try:
                video_info = extract_video_info_from_item(item)
                if video_info:
                    videos.append(video_info)
            except Exception as e:
                logger.debug(f"⚠️ Ошибка обработки элемента: {e}")
                continue
                
    except Exception as e:
        logger.error(f"❌ Ошибка извлечения данных API: {e}")
    
    return videos

def find_videos_in_json(data):
    """Рекурсивный поиск видео в JSON структуре"""
    videos = []
    
    def search_recursive(obj):
        if isinstance(obj, dict):
            # Проверяем, есть ли признаки видео
            if any(key in obj for key in ['video', 'itemId', 'id', 'videoUrl']):
                videos.append(obj)
            for value in obj.values():
                search_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                search_recursive(item)
    
    search_recursive(data)
    return videos

def extract_video_info_from_item(item):
    """Извлечение информации о видео из элемента API"""
    try:
        # Разные форматы данных TikTok
        video_data = {}
        
        # ID видео
        if 'id' in item:
            video_id = item['id']
        elif 'itemId' in item:
            video_id = item['itemId']
        elif 'video' in item and 'id' in item['video']:
            video_id = item['video']['id']
        else:
            return None
        
        # URL видео
        if 'video' in item and 'downloadAddr' in item['video']:
            video_url = item['video']['downloadAddr']
        elif 'videoUrl' in item:
            video_url = item['videoUrl']
        else:
            video_url = f"https://www.tiktok.com/@user/video/{video_id}"
        
        # Описание
        if 'desc' in item:
            description = item['desc']
        elif 'description' in item:
            description = item['description']
        elif 'content' in item:
            description = item['content']
        else:
            description = f"Видео {video_id}"
        
        if len(description) > 200:
            description = description[:200] + '...'
        
        # Автор
        author_username = "unknown"
        author_name = "Неизвестный автор"
        
        if 'author' in item:
            author = item['author']
            if 'uniqueId' in author:
                author_username = author['uniqueId']
            if 'nickname' in author:
                author_name = author['nickname']
        
        video_data = {
            'url': video_url,
            'description': description,
            'author_username': author_username,
            'author_name': author_name,
            'video_id': video_id,
            'created_at': datetime.now()
        }
        
        return video_data
        
    except Exception as e:
        logger.debug(f"⚠️ Ошибка извлечения информации видео: {e}")
        return None

async def parse_html_for_videos(html_content, song_id):
    """Парсинг HTML страницы для поиска видео"""
    videos = []
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Ищем JSON данные в script тегах
        script_tags = soup.find_all('script', {'type': 'application/json'})
        for script in script_tags:
            try:
                data = json.loads(script.string)
                videos.extend(extract_videos_from_api_data(data, song_id))
            except:
                continue
        
        # Ищем ссылки на видео
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/video/' in href or '/@' in href:
                video_url = href if href.startswith('http') else f'https://www.tiktok.com{href}'
                video_data = {
                    'url': video_url,
                    'description': 'Видео с TikTok',
                    'author_username': 'unknown',
                    'author_name': 'TikTok пользователь',
                    'created_at': datetime.now()
                }
                videos.append(video_data)
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга HTML: {e}")
    
    return videos

async def search_videos_by_hashtag(song_name, song_id, max_results=20):
    """Поиск видео по хештегам связанным с песней"""
    videos = []
    
    try:
        # Создаем релевантные хештеги
        hashtags = [
            song_name.lower().replace(' ', ''),
            f"music{song_id}",
            f"song{song_id}",
            "тренд",
            "вирус"
        ]
        
        for hashtag in hashtags:
            if len(videos) >= max_results:
                break
                
            search_url = f"https://www.tiktok.com/tag/{hashtag}"
            logger.info(f"🔍 Ищем по хештегу: #{hashtag}")
            
            response = await make_tiktok_request(search_url)
            if response:
                videos.extend(await parse_html_for_videos(response.text, song_id))
            
            await asyncio.sleep(3)  # Пауза между запросами
            
    except Exception as e:
        logger.error(f"❌ Ошибка поиска по хештегам: {e}")
    
    return videos

async def get_videos_for_song(song_url, song_id, song_name, max_results=50):
    """Основная функция получения видео для песни"""
    all_videos = []
    
    try:
        logger.info(f"🎵 Начинаем реальный поиск видео для: {song_name}")
        
        # 1. Парсинг через API
        logger.info("🔧 Метод 1: Парсинг через API...")
        api_videos = await parse_tiktok_api(song_id, max_results//2)
        all_videos.extend(api_videos)
        logger.info(f"✅ API найдено: {len(api_videos)} видео")
        
        # 2. Поиск по хештегам
        logger.info("🔧 Метод 2: Поиск по хештегам...")
        hashtag_videos = await search_videos_by_hashtag(song_name, song_id, max_results//2)
        # Убираем дубликаты по URL
        for video in hashtag_videos:
            if not any(v['url'] == video['url'] for v in all_videos):
                all_videos.append(video)
        logger.info(f"✅ Хештеги найдено: {len(hashtag_videos)} видео")
        
        # 3. Если видео мало, пробуем дополнительные методы
        if len(all_videos) < 10:
            logger.info("🔧 Метод 3: Дополнительный поиск...")
            # Пробуем поисковую страницу
            search_url = f"https://www.tiktok.com/search?q={song_name}"
            response = await make_tiktok_request(search_url)
            if response:
                search_videos = await parse_html_for_videos(response.text, song_id)
                for video in search_videos:
                    if not any(v['url'] == video['url'] for v in all_videos):
                        all_videos.append(video)
                logger.info(f"✅ Поиск найдено: {len(search_videos)} видео")
        
        # Убираем дубликаты и ограничиваем количество
        unique_videos = []
        seen_urls = set()
        
        for video in all_videos:
            if video['url'] not in seen_urls:
                seen_urls.add(video['url'])
                unique_videos.append(video)
        
        logger.info(f"🎉 Всего найдено уникальных видео: {len(unique_videos)}")
        
        return unique_videos[:max_results]
        
    except Exception as e:
        logger.error(f"❌ Ошибка реального поиска видео: {e}")
        return []

async def process_song_link(user_id, song_url, progress_callback=None):
    """Обработка ссылки на песню с реальным парсингом"""
    try:
        if progress_callback:
            await progress_callback("🔍 Проверяю ссылку...")
        
        if not any(domain in song_url for domain in ['tiktok.com', 'vm.tiktok.com']):
            return False, "❌ Неверный формат ссылки. Используйте ссылку на песню из TikTok."
        
        if progress_callback:
            await progress_callback("🔍 Извлекаю информацию о песне...")
        
        song_name, song_id = extract_song_info_from_url(song_url)
        if not song_name or not song_id:
            return False, "❌ Не удалось распознать песню. Проверьте ссылку."
        
        # Добавляем песню в базу
        song_db_id, is_new = add_song(user_id, song_name, song_url, song_id)
        
        if not is_new:
            return False, "❌ Эта песня уже добавлена."
        
        if progress_callback:
            await progress_callback("🔍 Начинаю реальный поиск видео...")
        
        # Реальный поиск видео
        videos = await get_videos_for_song(song_url, song_id, song_name, 30)
        
        if progress_callback:
            await progress_callback(f"📹 Найдено {len(videos)} видео. Сохраняю...")
        
        # Сохраняем видео
        saved_count = 0
        for i, video in enumerate(videos):
            if add_video(song_db_id, video):
                saved_count += 1
            
            if progress_callback and i % 5 == 0 and i > 0:
                await progress_callback(f"📹 Сохранено {saved_count} из {len(videos)} видео...")
        
        update_song_last_checked(song_db_id)
        
        if saved_count > 0:
            return True, f"✅ **{song_name}** добавлена!\n\n🎵 **Найдено видео: {saved_count}**\n\n📊 Теперь я буду отслеживать новые видео с этой песней!\n\n💡 *Реальный парсинг TikTok*"
        else:
            return True, f"✅ **{song_name}** добавлена!\n\n📭 Видео пока не найдено.\n\n🔄 Попробуйте проверить позже или использовать поиск."
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ссылки: {e}")
        return False, f"❌ Ошибка: {str(e)}"

async def check_new_videos_for_user(user_id):
    """Проверка новых видео с реальным парсингом"""
    new_videos = []
    
    try:
        songs = get_user_songs(user_id)
        
        for song in songs:
            song_db_id, name, song_url, song_id, created_at, last_checked = song
            
            logger.info(f"🔍 Проверяем новые видео для: {name}")
            
            # Реальный поиск новых видео
            videos = await get_videos_for_song(song_url, song_id, name, 20)
            
            for video in videos:
                if not get_video_exists(video['url']):
                    if add_video(song_db_id, video):
                        new_videos.append({
                            'song_name': name,
                            'video_url': video['url'],
                            'description': video['description'],
                            'author': video.get('author_name', video.get('author_username', 'Неизвестный автор'))
                        })
                        logger.info(f"🎉 Новое видео для {name}")
            
            update_song_last_checked(song_db_id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки видео: {e}")
    
    return new_videos

async def search_more_videos_for_song(song_id, song_name, user_id):
    """Дополнительный поиск видео для песни"""
    try:
        logger.info(f"🔍 Дополнительный поиск для: {song_name}")
        
        songs = get_user_songs(user_id)
        song_info = next((s for s in songs if s[0] == song_id), None)
        
        if not song_info:
            return 0
            
        song_url = song_info[2]
        song_id_str = song_info[3]
        
        # Реальный поиск дополнительных видео
        videos = await get_videos_for_song(song_url, song_id_str, song_name, 15)
        
        new_videos_count = 0
        for video in videos:
            if not get_video_exists(video['url']):
                if add_video(song_id, video):
                    new_videos_count += 1
        
        update_song_last_checked(song_id)
        
        return new_videos_count
        
    except Exception as e:
        logger.error(f"❌ Ошибка дополнительного поиска: {e}")
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
            text = f"📭 Для песни '{song_name}' новых видео не найдено."
        
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
            text = f"📭 Для песни '{song_name}' новых видео не найдено."
        
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
                text += f"👤 {video.get('author', 'Неизвестный автор')}\n"  # ← ИСПРАВЛЕН ОТСТУП
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
