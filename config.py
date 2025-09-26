import os
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

logger = logging.getLogger(__name__)

def get_env_var(name, default=None):
    """Безопасное получение переменной окружения"""
    value = os.getenv(name)
    if value is None:
        if default is not None:
            logger.warning(f"Переменная {name} не найдена, используется значение по умолчанию: {default}")
            return default
        else:
            logger.error(f"Обязательная переменная {name} не найдена!")
            return None
    return value

# Обязательные переменные
BOT_TOKEN = get_env_var('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Создайте файл .env с переменной BOT_TOKEN=your_bot_token")

# Опциональные переменные
CHECK_INTERVAL = int(get_env_var('CHECK_INTERVAL', '1800'))  # 30 минут по умолчанию
DB_PATH = get_env_var('DB_PATH', 'database/tiktok_bot.db')

logger.info("Настройки успешно загружены")
