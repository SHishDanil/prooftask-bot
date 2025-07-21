import os
import stripe
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

# --- Настройка ключей ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

STRIPE_KEY = os.environ.get("STRIPE_KEY", "")
stripe.api_key = STRIPE_KEY

# --- Инициализация бота и Flask ---
bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, use_context=True)

# --- Обработчики команд ---
def start(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Привет! Бот запущен и готов к работе ✅"
    )

dispatcher.add_handler(CommandHandler("start", start))

# --- HTTP‑маршруты ---
@app.route("/", methods=["GET"])
def index():
    return "✅ Сервис работает!", 200

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    """Обработка входящего update от Telegram"""
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK", 200

# --- Запуск приложения ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
