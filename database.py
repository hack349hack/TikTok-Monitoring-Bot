import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

def get_db_path():
    """Получение пути к базе данных"""
    db_path = os.path.join(os.path.dirname(__file__), 'database/tiktok_bot.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path

def init_db():
    """Инициализация базы данных"""
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Таблица песен
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            song_url TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Таблица видео
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
        logger.info("База данных инициализирована успешно")
        
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise

def add_song(user_id, name, song_url):
    """Добавление песни в базу"""
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT OR IGNORE INTO songs (user_id, name, song_url) VALUES (?, ?, ?)',
            (user_id, name, song_url)
        )
        
        conn.commit()
        
        # Получаем ID добавленной или существующей песни
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
        logger.error(f"Ошибка добавления песни: {e}")
        return None, False

def get_user_songs(user_id):
    """Получение песен пользователя"""
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id, name, song_url, created_at FROM songs WHERE user_id = ? ORDER BY created_at DESC',
            (user_id,)
        )
        
        songs = cursor.fetchall()
        conn.close()
        return songs
        
    except Exception as e:
        logger.error(f"Ошибка получения песен пользователя: {e}")
        return []

def get_song_videos(song_id, user_id):
    """Получение видео для песни"""
    try:
        conn = sqlite3.connect(get_db_path())
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
        logger.error(f"Ошибка получения видео: {e}")
        return []

def delete_song(song_id, user_id):
    """Удаление песни"""
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        # Сначала удаляем связанные видео
        cursor.execute('DELETE FROM videos WHERE song_id = ?', (song_id,))
        
        # Затем удаляем песню
        cursor.execute(
            'DELETE FROM songs WHERE id = ? AND user_id = ?',
            (song_id, user_id)
        )
        
        conn.commit()
        conn.close()
        
        return cursor.rowcount > 0
        
    except Exception as e:
        logger.error(f"Ошибка удаления песни: {e}")
        return False

def add_video(song_id, video_url, description):
    """Добавление видео в базу"""
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT OR IGNORE INTO videos (song_id, video_url, description) VALUES (?, ?, ?)',
            (song_id, video_url, description)
        )
        
        conn.commit()
        conn.close()
        
        return cursor.rowcount > 0
        
    except Exception as e:
        logger.error(f"Ошибка добавления видео: {e}")
        return False

def get_video_exists(video_url):
    """Проверка существования видео"""
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id FROM videos WHERE video_url = ?',
            (video_url,)
        )
        
        exists = cursor.fetchone() is not None
        conn.close()
        
        return exists
        
    except Exception as e:
        logger.error(f"Ошибка проверки видео: {e}")
        return False
