from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from bot.services.database import get_user_songs, delete_song, get_song_videos
from bot.services.tiktok_parser import check_new_videos_for_user

def get_main_keyboard():
    """Клавиатура главного меню"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Добавить песню по ссылке", callback_data="add_song")],
        [InlineKeyboardButton("📋 Мои песни", callback_data="list_songs")],
        [InlineKeyboardButton("🔍 Проверить сейчас", callback_data="check_now")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ])

async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback от кнопок"""
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

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню с кнопками"""
    text = "📱 Главное меню:"
    await update.callback_query.message.edit_text(text, reply_markup=get_main_keyboard())

async def add_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик добавления песни"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    text = "🎵 Пришли мне ссылку на песню в TikTok\n\nПример:\nhttps://www.tiktok.com/music/название-песни-723415689123"
    await update.callback_query.message.edit_text(text, reply_markup=keyboard)

async def list_songs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик списка песен"""
    user_id = update.effective_user.id
    songs = get_user_songs(user_id)
    
    if not songs:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Добавить песню", callback_data="add_song")],
            [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
        ])
        await update.callback_query.message.edit_text(
            "📋 У тебя пока нет добавленных песен.", 
            reply_markup=keyboard
        )
        return
    
    text = "📋 Твои песни:\n\n"
    keyboard_buttons = []
    
    for song in songs:
        song_id, name, song_url, created_at, last_check = song
        text += f"🎵 {name}\n🔗 {song_url}\n📅 Добавлена: {created_at[:10]}\n\n"
        
        keyboard_buttons.append([
            InlineKeyboardButton(f"📹 Видео {name}", callback_data=f"show_videos:{song_id}"),
            InlineKeyboardButton(f"❌ Удалить", callback_data=f"delete_song:{song_id}")
        ])
    
    keyboard_buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    await update.callback_query.message.edit_text(text, reply_markup=keyboard)

async def show_videos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать видео для песни"""
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
            text += f"{i}. {description}\n"
            text += f"🔗 [Смотреть видео]({video_url})\n"
            text += f"📅 {created_at[:10]}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ К списку песен", callback_data="list_songs")],
        [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

async def delete_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик удаления песни"""
    query = update.callback_query
    song_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    
    delete_song(song_id, user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 К списку песен", callback_data="list_songs")],
        [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
    ])
    
    await query.edit_message_text("✅ Песня успешно удалена!", reply_markup=keyboard)

async def check_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик проверки видео"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="check_now")],
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    await query.edit_message_text("🔍 Ищу новые видео...", reply_markup=keyboard)
    
    new_videos = await check_new_videos_for_user(user_id)
    
    if not new_videos:
        text = "📭 Новых видео не найдено."
    else:
        text = "🎉 Найдены новые видео!\n\n"
        for video in new_videos[:5]:
            text += f"🎵 {video['song_name']}\n"
            text += f"📹 {video['description']}\n"
            text += f"🔗 [Смотреть видео]({video['video_url']})\n\n"
        
        if len(new_videos) > 5:
            text += f"И ещё {len(new_videos) - 5} видео...\n"
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик помощи"""
    help_text = """
ℹ️ *Помощь по боту*

🎵 *Как добавить песню*:
1. Найди песню в TikTok
2. Скопируй ссылку на страницу песни
3. Пришли ссылку боту

Примеры ссылок:
• https://www.tiktok.com/music/название-песни-723415689123
• https://vm.tiktok.com/music/песня-123456789

📹 *Что делает бот*:
- Находит все видео с этой песней
- Сортирует по дате публикации
- Присылает последние видео
- Постоянно проверяет новые видео
- Присылает уведомления о новых видео

💡 *Советы*:
- Используй официальные ссылки на песни из TikTok
- Бот работает лучше с популярными песнями
- Новые видео проверяются каждые 30 минут
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ])
    
    await update.callback_query.message.edit_text(
        help_text, 
        reply_markup=keyboard, 
        parse_mode='Markdown'
    )
