# Используем официальный образ Python 3.12 (включает imghdr и всё stdlib)
FROM python:3.12-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Сначала скопируем только список зависимостей,
# чтобы Docker‑кеш держал вёрстку слоёв
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь ваш код
COPY . .

# Порт, на котором Render ждёт HTTP‑сервис
ENV PORT=5000

# Запускаем бота
CMD ["python", "bot.py"]
