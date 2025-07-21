# Dockerfile

# 1) Берём официальный образ с Python 3.12 (там точно есть модуль imghdr)
FROM python:3.12-slim

# 2) Рабочая директория внутри контейнера
WORKDIR /app

# 3) Копируем только зависимости, чтобы Docker‑кэш их перезатягивал лишь при изменении
COPY requirements.txt runtime.txt ./

# 4) Обновляем pip и ставим все зависимости
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 5) Копируем остальной код приложения
COPY . .

# 6) Открываем порт (на котором Flask принимает webhook; по умолчанию 5000)
EXPOSE 5000

# 7) Команда запуска вашего бота
CMD ["python", "bot.py"]
