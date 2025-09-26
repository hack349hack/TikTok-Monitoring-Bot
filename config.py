import os
import logging

# Настройка логирования для продакшена
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_env_var(name, default=None):
    """Безопасное получение переменной окружения"""
    value = os.getenv(name)
    if value is None:
        if default is not None:
            logger.info(f"Переменная {name} не найдена, используется значение по умолчанию: {default}")
            return default
        else:
            logger.error(f"Обязательная переменная {name} не найдена!")
            return None
    return value

# Обязательные переменные
BOT_TOKEN = get_env_var('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не найден! Установите переменную окружения BOT_TOKEN")
    # В продакшене не падаем, а ждем настройки
    BOT_TOKEN = "not_configured"

# Опциональные переменные
CHECK_INTERVAL = int(get_env_var('CHECK_INTERVAL', '1800'))
DB_PATH = get_env_var('DB_PATH', '/app/database/tiktok_bot.db')

# Проверяем, запущены ли в контейнере
IS_DOCKER = os.path.exists('/.dockerenv')

if IS_DOCKER:
    logger.info("Запущено в Docker контейнере")
else:
    logger.info("Запущено в локальном окружении")

logger.info("Конфигурация загружена")
