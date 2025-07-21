import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

# Инициализация
TOKEN = os.environ["TELEGRAM_TOKEN"]
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, None, use_context=True)

# Команда /start
def start(update, context):
    update.message.reply_text("Привет! Я запущен на Render 🎉")

dp.add_handler(CommandHandler("start", start))

# Flask-приложение
app = Flask(__name__)

# Опциональный корневой маршрут, чтобы не было 404 на /
@app.route("/", methods=["GET"])
def home():
    return "Bot is running"

# Точка входа для webhook'а
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
