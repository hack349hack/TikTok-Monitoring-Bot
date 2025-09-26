import logging
import asyncio
import sys
import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

# Добавляем текущую директорию в путь Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Импортируем наши модули
from config import BOT_TOKEN
from database import init_db, add_song, get_user_songs, delete_song, get_song_videos, add_video, get_video_exists
from tiktok_parser import process_song_link, check_new_videos_for_user, start_periodic_checking

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
        welcome_text = f"""
👋 Привет, {user.first_name}!

🎵 Я бот для отслеживания новых видео с твоими песнями в TikTok.

📋 Как это работает:
1. Присылаешь мне ссылку на песню в TikTok
2. Я нахожу все видео с этой песней
3. Присылаю тебе последние видео
4. Постоянно ищу новые и присылаю уведомления

📱 Используй кнопки ниже для управления:
    """
        
        keyboard = get_main_keyboard()
        
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=keyboard)
        else:
            await update.callback_query.message.reply_text(welcome_text, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

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
        logger.error(f"Ошибка обработки callback: {e}")

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
    try:
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
        logger.error(f"Ошибка показа списка песен: {e}")

async def show_videos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать видео для песни"""
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
                text += f"{i}. {description}\n"
                text += f"🔗 [Смотреть видео]({video_url})\n"
                text += f"📅 {created_at[:10]}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ К списку песен", callback_data="list_songs")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="main_menu")]
        ])
        
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка показа видео: {e}")

async def delete_song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик удаления песни"""
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
        logger.error(f"Ошибка удаления песни: {e}")

async def check_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик проверки видео"""
    try:
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
        
    except Exception as e:
        logger.error(f"Ошибка проверки видео: {e}")

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

📹 *Что делает бот*:
- Находит все видео с этой песней
- Сортирует по дате публикации
- Присылает последние видео
- Постоянно проверяет новые видео

💡 *Советы*:
- Используй официальные ссылки на песни из TikTok
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

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text.strip()
        
        if text.startswith(('https://www.tiktok.com/music/', 'https://vm.tiktok.com/', 'https://tiktok.com/music/')):
            await handle_song_link(update, context, text)
        else:
            await update.message.reply_text(
                "📎 Пришли мне ссылку на песню в TikTok для отслеживания\n\nПример: https://www.tiktok.com/music/название-песни-723415689123",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка обработки текстового сообщения: {e}")

async def handle_song_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """Обработчик ссылки на песню"""
    try:
        await update.message.reply_text("🔍 Обрабатываю ссылку на песню...")
        
        success, message = await process_song_link(update.effective_user.id, link)
        
        if success:
            keyboard = get_main_keyboard()
            await update.message.reply_text(message, reply_markup=keyboard)
        else:
            keyboard = get_main_keyboard()
            await update.message.reply_text(f"❌ {message}", reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Ошибка обработки ссылки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке ссылки.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    """Основная функция запуска бота"""
    try:
        logger.info("Запуск инициализации бота...")
        
        # Проверка токена
        if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
            logger.error("BOT_TOKEN не настроен. Проверьте файл .env")
            return
            
        # Инициализация базы данных
        init_db()
        logger.info("База данных инициализирована")
        
        # Создание приложения
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info("Приложение создано")
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_menu_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
        
        # Запуск периодической проверки
        start_periodic_checking(application)
        logger.info("Периодическая проверка запущена")
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запуск бота
        logger.info("Бот запускается...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")

if __name__ == "__main__":
    main()
