# Dockerfile

# 1) Базовый образ с Python 3.12 (в нём точно есть стандартный модуль imghdr)
FROM python:3.12-slim

# 2) Переключаемся в рабочую директорию
WORKDIR /app

# 3) Сначала скопируем только файлы зависимостей
COPY requirements.txt runtime.txt ./

# 4) Обновим pip и установим зависимости
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 5) Скопируем остальной код приложения
COPY . .

# 6) Порт, на котором ваш Flask‑сервер слушает webhook (если он слушает 5000)
EXPOSE 5000

# 7) Команда запуска — замените на свою, если у вас другой стартап
CMD ["python", "bot.py"]
