# Используем официальный образ с Python 3.12 (slim-версия уже включает модуль imghdr)
FROM python:3.12-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Сначала копируем только файл зависимостей,
# чтобы Docker‑кеш использовался при неизменных requirements
COPY requirements.txt .

# Устанавливаем зависимости без сохранения кэша pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код в контейнер
COPY . .

# По-умолчанию запускаем bot.py
CMD ["python", "bot.py"]
