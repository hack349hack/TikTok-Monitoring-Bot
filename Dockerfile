FROM python:3.9-slim

WORKDIR /app

# Обновляем систему и устанавливаем зависимости для сборки
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Копируем requirements.txt первым для кэширования
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip list

# Создаем директории
RUN mkdir -p /app/database

# Копируем исходный код
COPY . .

# Проверяем, что файлы на месте
RUN ls -la && \
    echo "=== Проверка наличия файлов ===" && \
    ls -la *.py && \
    echo "=== Проверка установленных пакетов ===" && \
    pip list | grep telegram

# Создаем не-root пользователя для безопасности
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser

# Запускаем бота
CMD ["python", "main.py"]
