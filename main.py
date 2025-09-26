import logging
import asyncio
import sys
import os
import time
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

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

try:
    from config import BOT_TOKEN, IS_DOCKER
    from database import init_db, add_song, get_user_songs, delete_song, get_song_videos, add_video, get_video_exists
    from tiktok_parser import process_song_link, check_new_videos_for_user, start_periodic_checking
except ImportError as e:
    logger.error(f"Ошибка импорта модулей: {e}")
    sys.exit(1)

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
        
        # Проверка конфигурации
        if BOT_TOKEN == "not_configured":
            await update.message.reply_text("❌ Бот не настроен. Обратитесь к администратору.")
            return
            
        welcome_text = f"""
👋 Привет, {user.first_name}!

🎵 Я бот для отслеживания новых видео с твоими песнями в TikTok.

🚀 Версия: {'Production' if IS_DOCKER else 'Development'}

📱 Используй кнопки ниже для управления:
    """
        
        keyboard = get_main_keyboard()
        await update.message.reply_text(welcome_text, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")

# ... остальные функции обработчиков остаются такими же ...

def main():
    """Основная функция запуска бота"""
    max_retries = 5
    retry_delay = 10  # секунды
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка запуска бота #{attempt + 1}")
            
            # Проверка токена
            if not BOT_TOKEN or BOT_TOKEN == "not_configured":
                logger.error("BOT_TOKEN не настроен")
                if attempt == max_retries - 1:
                    logger.error("Не удалось запустить бота после нескольких попыток")
                    return
                time.sleep(retry_delay)
                continue
                
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
            logger.info("Бот успешно запущен")
            application.run_polling()
            break
            
        except Exception as e:
            logger.error(f"Ошибка при запуске бота (попытка {attempt + 1}): {e}")
            
            if attempt == max_retries - 1:
                logger.error("Не удалось запустить бота после нескольких попыток")
                break
                
            logger.info(f"Повторная попытка через {retry_delay} секунд...")
            time.sleep(retry_delay)

if __name__ == "__main__":
    main()
