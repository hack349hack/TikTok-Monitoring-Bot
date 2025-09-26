import logging
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

from config.settings import BOT_TOKEN
from bot.handlers.menu import handle_menu_callback
from bot.services.database import init_db
from bot.services.tiktok_parser import start_periodic_checking

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
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
    
    from bot.handlers.menu import get_main_keyboard
    keyboard = get_main_keyboard()
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=keyboard)
    else:
        await update.callback_query.message.reply_text(welcome_text, reply_markup=keyboard)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений (для быстрой отправки ссылок)"""
    text = update.message.text.strip()
    
    if text.startswith(('https://www.tiktok.com/music/', 'https://vm.tiktok.com/', 'https://tiktok.com/music/')):
        await handle_song_link(update, context, text)
    else:
        from bot.handlers.menu import get_main_keyboard
        await update.message.reply_text(
            "📎 Пришли мне ссылку на песню в TikTok для отслеживания\n\nПример: https://www.tiktok.com/music/название-песни-723415689123",
            reply_markup=get_main_keyboard()
        )

async def handle_song_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """Обработчик ссылки на песню"""
    from bot.services.tiktok_parser import process_song_link
    from bot.handlers.menu import get_main_keyboard
    
    await update.message.reply_text("🔍 Обрабатываю ссылку на песню...")
    
    success, message = await process_song_link(update.effective_user.id, link)
    
    if success:
        keyboard = get_main_keyboard()
        await update.message.reply_text(message, reply_markup=keyboard)
    else:
        keyboard = get_main_keyboard()
        await update.message.reply_text(f"❌ {message}", reply_markup=keyboard)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_menu_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Запуск периодической проверки
    start_periodic_checking(application)
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запуск бота
    logger.info("Бот запущен!")
    application.run_polling()

if __name__ == "__main__":
    main()
