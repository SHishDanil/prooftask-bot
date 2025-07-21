# Dockerfile

# Базовый образ с Python 3.12 (именно из‑за imghdr оставляем 3.12.x)
FROM python:3.12.17-slim

# Рабочая папка приложения
WORKDIR /app

# Копируем зависимости и ставим
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё остальное
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
