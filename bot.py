import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

# 1. Читаем токен из переменной окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Переменная окружения TELEGRAM_TOKEN не установлена")

# 2. Инициализируем Bot и Dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot, None, use_context=True)

# 3. Определяем команду /start
def start(update, context):
    update.message.reply_text("Привет! Я работаю на Render 🎉")

dp.add_handler(CommandHandler("start", start))

# 4. Создаём Flask‑приложение
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running"

# 5. Вебхук‑эндпоинт должен совпадать с тем, что мы поставим ниже
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK"

if __name__ == "__main__":
    # 6. Получаем внешний hostname от Render
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not host:
        raise RuntimeError("Переменная RENDER_EXTERNAL_HOSTNAME не установлена")
    webhook_url = f"https://{host}/webhook/{TELEGRAM_TOKEN}"
    # Устанавливаем webhook в Telegram
    bot.set_webhook(webhook_url)

    # 7. Запускаем Flask на нужном порту
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
