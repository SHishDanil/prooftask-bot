import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

# 1. Получаем токен из настроек Render (Settings → Environment → TELEGRAM_TOKEN)
TOKEN = os.environ['TELEGRAM_TOKEN']

# 2. Создаём объекты бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, None, workers=0, use_context=True)

# 3. Обработчик команды /start
def start(update, context):
    update.message.reply_text("Привет! Я работаю на Render 👍")

dp.add_handler(CommandHandler("start", start))

# 4. Flask‑приложение
app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    """Telegram пришлёт сюда JSON‑апдейт — разбираем и обрабатываем."""
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK"

if __name__ == "__main__":
    # 5. Регистрируем вебхук у Telegram — на ваш реальный домен
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not host:
        raise RuntimeError("RENDER_EXTERNAL_HOSTNAME не задан")
    webhook_url = f"https://{host}/webhook/{TOKEN}"
    bot.set_webhook(webhook_url)

    # 6. Запускаем сервер на порту из окружения (или 5000)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
