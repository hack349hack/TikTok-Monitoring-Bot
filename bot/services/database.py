import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '../../database/tiktok_bot.db')

def init_db():
    """Инициализация базы данных"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица песен
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS songs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        song_url TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица видео
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        song_id INTEGER NOT NULL,
        video_url TEXT NOT NULL UNIQUE,
        thumbnail_url TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        posted_at TIMESTAMP,
        FOREIGN KEY (song_id) REFERENCES songs (id)
    )
    ''')
    
    # Индексы для улучшения производительности
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_songs_user_id ON songs (user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_songs_url ON songs (song_url)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_url ON videos (video_url)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_song_id ON videos (song_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_posted_at ON videos (posted_at)')
    
    conn.commit()
    conn.close()

def add_song(user_id, name, song_url):
    """Добавление песни в базу"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'INSERT INTO songs (user_id, name, song_url) VALUES (?, ?, ?)',
            (user_id, name, song_url)
        )
        conn.commit()
        song_id = cursor.lastrowid
        return song_id, True
    except sqlite3.IntegrityError:
        # Песня уже существует
        cursor.execute(
            'SELECT id FROM songs WHERE song_url = ? AND user_id = ?',
            (song_url, user_id)
        )
        existing_song = cursor.fetchone()
        return existing_song[0] if existing_song else None, False
    finally:
        conn.close()

def get_user_songs(user_id):
    """Получение песен пользователя"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        '''SELECT id, name, song_url, created_at, last_check 
           FROM songs WHERE user_id = ? 
           ORDER BY created_at DESC''',
        (user_id,)
    )
    
    songs = cursor.fetchall()
    conn.close()
    
    return songs

def get_song_videos(song_id, user_id):
    """Получение видео для песни"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        '''SELECT v.id, v.video_url, v.description, v.posted_at 
           FROM videos v 
           JOIN songs s ON v.song_id = s.id 
           WHERE s.id = ? AND s.user_id = ? 
           ORDER BY v.posted_at DESC 
           LIMIT 20''',
        (song_id, user_id)
    )
    
    videos = cursor.fetchall()
    conn.close()
    
    return videos

def delete_song(song_id, user_id):
    """Удаление песни"""
    conn = sqlite3.connect(DB_PATH)
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

def add_video(song_id, video_url, thumbnail_url, description, posted_at):
    """Добавление видео в базу"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            '''INSERT INTO videos (song_id, video_url, thumbnail_url, description, posted_at) 
               VALUES (?, ?, ?, ?, ?)''',
            (song_id, video_url, thumbnail_url, description, posted_at)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Видео уже существует
        return False
    finally:
        conn.close()

def get_video_exists(video_url):
    """Проверка существования видео"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT id FROM videos WHERE video_url = ?',
        (video_url,)
    )
    
    exists = cursor.fetchone() is not None
    conn.close()
    
    return exists

def update_song_last_check(song_id):
    """Обновление времени последней проверки"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE songs SET last_check = CURRENT_TIMESTAMP WHERE id = ?',
        (song_id,)
    )
    
    conn.commit()
    conn.close()

def get_all_songs():
    """Получение всех песен для периодической проверки"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT id, user_id, name, song_url FROM songs'
    )
    
    songs = cursor.fetchall()
    conn.close()
    
    return songs
