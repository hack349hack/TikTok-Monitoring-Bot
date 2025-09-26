import os
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение переменных окружения
def get_env_var(name, default=None):
    value = os.getenv(name, default)
    if value is None:
        logger.warning(f"Переменная окружения {name} не найдена")
    return value

BOT_TOKEN = get_env_var('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

CHECK_INTERVAL = int(get_env_var('CHECK_INTERVAL', '1800'))  # 30 минут по умолчанию

# Настройки базы данных
DB_PATH = get_env_var('DB_PATH', '/app/database/tiktok_bot.db')

logger.info("Настройки загружены успешно")
