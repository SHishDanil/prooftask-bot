import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

TOKEN = os.environ['TELEGRAM_TOKEN']
bot = Bot(token=TOKEN)
dp = Dispatcher(bot, None, workers=0, use_context=True)

def start(update, context):
    update.message.reply_text("Привет! Я запущен на Render 🎉")

dp.add_handler(CommandHandler("start", start))

app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK"

if __name__ == "__main__":
    # Render задаёт своё внешнее hostname в этой переменной
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not host:
        raise RuntimeError("RENDER_EXTERNAL_HOSTNAME не задана!")
    bot.set_webhook(f"https://{host}/webhook/{TOKEN}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
