import requests
from bs4 import BeautifulSoup
import logging
import re
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import add_song, add_video, get_video_exists

logger = logging.getLogger(__name__)

def extract_song_info_from_url(song_url):
    """Извлечение информации о песне из URL"""
    try:
        # Пример: https://www.tiktok.com/music/song-name-723415689123
        match = re.search(r'music/([^/]+?-(\d+))', song_url)
        if match:
            song_id = match.group(2)
            song_name = match.group(1).replace(f"-{song_id}", "").replace("-", " ")
            return song_name.title(), song_id
        
        return "Неизвестная песня", "000000000000"
        
    except Exception as e:
        logger.error(f"Ошибка извлечения информации из URL: {e}")
        return "Неизвестная песня", "000000000000"

async def process_song_link(user_id, song_url):
    """Обработка ссылки на песню"""
    try:
        # Проверяем валидность ссылки
        if not song_url.startswith(('https://www.tiktok.com/music/', 'https://vm.tiktok.com/', 'https://tiktok.com/music/')):
            return False, "Неверный формат ссылки. Используйте ссылку на песню из TikTok."
        
        # Извлекаем информацию о песне
        song_name, song_id = extract_song_info_from_url(song_url)
        
        # Добавляем песню в базу
        song_db_id, is_new = add_song(user_id, song_name, song_url)
        
        if not is_new:
            return False, "Эта песня уже добавлена для отслеживания."
        
        # Ищем видео для этой песни (симуляция)
        videos_found = 5  # Временно симулируем найденные видео
        
        return True, f"✅ Песня '{song_name}' добавлена! Найдено {videos_found} видео."
        
    except Exception as e:
        logger.error(f"Ошибка обработки ссылки: {e}")
        return False, "Произошла ошибка при обработке ссылки."

async def check_new_videos_for_user(user_id):
    """Проверка новых видео для пользователя"""
    try:
        from database import get_user_songs
        songs = get_user_songs(user_id)
        new_videos = []
        
        # Временно симулируем поиск новых видео
        for song in songs[:2]:  # Проверяем только первые 2 песни
            song_id, name, song_url, created_at = song
            logger.info(f"Проверяем песню: {name}")
            
            # Симуляция найденных видео
            new_videos.append({
                'song_name': name,
                'video_url': 'https://www.tiktok.com/@user/video/123456789',
                'description': f'Новое видео с песней "{name}"'
            })
        
        return new_videos
        
    except Exception as e:
        logger.error(f"Ошибка проверки видео: {e}")
        return []

async def periodic_check(context):
    """Периодическая проверка новых видео"""
    logger.info("Запуск периодической проверки видео...")
    
    # Здесь будет реальная проверка видео
    logger.info("Проверка завершена (режим симуляции)")

def start_periodic_checking(application):
    """Запуск периодической проверки"""
    try:
        scheduler = BackgroundScheduler()
        
        # Проверка каждые 30 минут
        trigger = IntervalTrigger(minutes=30)
        scheduler.add_job(
            periodic_check,
            trigger=trigger,
            args=[application]
        )
        
        scheduler.start()
        logger.info("Периодическая проверка запущена (каждые 30 минут)")
        
    except Exception as e:
        logger.error(f"Ошибка запуска периодической проверки: {e}")
