import requests
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.services.database import (
    add_song, add_video, get_video_exists, 
    update_song_last_check, get_all_songs
)

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
        
        # Альтернативный формат
        match = re.search(r'music/[^/]+?--(\d+)', song_url)
        if match:
            song_id = match.group(1)
            # Пытаемся извлечь название из URL
            name_match = re.search(r'music/([^/-]+)', song_url)
            song_name = name_match.group(1) if name_match else f"Песня {song_id}"
            return song_name.title(), song_id
            
        return None, None
    except Exception as e:
        logger.error(f"Ошибка извлечения информации из URL: {e}")
        return None, None

async def process_song_link(user_id, song_url):
    """Обработка ссылки на песню"""
    try:
        # Проверяем валидность ссылки
        if not song_url.startswith(('https://www.tiktok.com/music/', 'https://vm.tiktok.com/', 'https://tiktok.com/music/')):
            return False, "Неверный формат ссылки. Используйте ссылку на песню из TikTok."
        
        # Извлекаем информацию о песне
        song_name, song_id = extract_song_info_from_url(song_url)
        if not song_name or not song_id:
            return False, "Не удалось распознать песню из ссылки."
        
        # Добавляем песню в базу
        song_db_id, is_new = add_song(user_id, song_name, song_url)
        
        if not is_new:
            return False, "Эта песня уже добавлена для отслеживания."
        
        # Ищем видео для этой песни
        videos = await get_videos_for_song(song_url, song_db_id)
        
        return True, f"✅ Песня '{song_name}' добавлена! Найдено {len(videos)} видео."
        
    except Exception as e:
        logger.error(f"Ошибка обработки ссылки: {e}")
        return False, "Произошла ошибка при обработке ссылки."

async def get_videos_for_song(song_url, song_db_id):
    """Получение видео для конкретной песни"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }
        
        logger.info(f"Парсим страницу: {song_url}")
        response = requests.get(song_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            videos = []
            
            # Ищем видео на странице песни
            video_elements = soup.find_all('div', {'data-e2e': 'recommend-list-item'})
            
            # Если не нашли по data-e2e, ищем по классам
            if not video_elements:
                video_elements = soup.find_all('div', class_='tiktok-item')
            
            logger.info(f"Найдено элементов: {len(video_elements)}")
            
            for element in video_elements[:20]:
                try:
                    video_link = element.find('a')
                    if video_link and video_link.get('href'):
                        href = video_link.get('href')
                        if not href.startswith('http'):
                            video_url = f"https://www.tiktok.com{href}"
                        else:
                            video_url = href
                        
                        # Описание видео
                        description = "Видео с песней"
                        desc_elements = element.find_all(['div', 'p', 'span'])
                        for desc_elem in desc_elements:
                            text = desc_elem.get_text(strip=True)
                            if text and len(text) > 10:
                                description = text
                                break
                        
                        if len(description) > 200:
                            description = description[:200] + '...'
                        
                        # Дата публикации
                        posted_at = datetime.now()
                        
                        # Миниатюра
                        thumbnail = None
                        img = element.find('img')
                        if img and img.get('src'):
                            thumbnail = img['src']
                        
                        # Сохраняем видео, если его еще нет
                        if not get_video_exists(video_url):
                            if add_video(song_db_id, video_url, thumbnail, description, posted_at):
                                videos.append({
                                    'url': video_url,
                                    'description': description
                                })
                                logger.info(f"Добавлено видео: {description}")
                            
                except Exception as e:
                    logger.debug(f"Ошибка парсинга видео элемента: {e}")
                    continue
            
            # Обновляем время последней проверки
            update_song_last_check(song_db_id)
            
            logger.info(f"Успешно обработано видео: {len(videos)}")
            return videos
            
        else:
            logger.warning(f"HTTP ошибка {response.status_code} для песни: {song_url}")
            return []
            
    except Exception as e:
        logger.error(f"Ошибка получения видео для песни: {e}")
        return []

async def check_new_videos_for_user(user_id):
    """Проверка новых видео для пользователя"""
    from bot.services.database import get_user_songs
    songs = get_user_songs(user_id)
    new_videos = []
    
    for song in songs:
        song_id, name, song_url, created_at, last_check = song
        logger.info(f"Проверяем песню: {name}")
        
        videos = await get_videos_for_song(song_url, song_id)
        
        for video in videos:
            new_videos.append({
                'song_name': name,
                'video_url': video['url'],
                'description': video['description']
            })
            logger.info(f"Найдено новое видео для песни {name}")
    
    return new_videos

async def periodic_check(context):
    """Периодическая проверка новых видео"""
    logger.info("Запуск периодической проверки видео...")
    
    songs = get_all_songs()
    for song in songs:
        song_id, user_id, name, song_url = song
        try:
            videos = await get_videos_for_song(song_url, song_id)
            
            # Отправляем уведомления о новых видео
            for video in videos:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 Новое видео с вашей песней!\n\n"
                             f"🎵 {name}\n"
                             f"📹 {video['description']}\n"
                             f"🔗 [Смотреть видео]({video['url']})",
                        parse_mode='Markdown'
                    )
                    # Небольшая задержка между сообщениями
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка проверки песни {name}: {e}")

def start_periodic_checking(application):
    """Запуск периодической проверки"""
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
