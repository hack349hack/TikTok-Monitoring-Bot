FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Создание директории для базы данных
RUN mkdir -p /app/database

# Копирование requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Копирование исходного кода
COPY . .

# Запуск бота
CMD ["python", "-m", "bot.main"]
