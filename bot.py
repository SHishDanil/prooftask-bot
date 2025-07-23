import os
from flask import Flask, request, Response
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler

# === ENV ===
TOKEN  = os.environ["TELEGRAM_TOKEN"]
SECRET = os.environ["WEBHOOK_SECRET"]

# === Telegram setup ===
bot = Bot(TOKEN)
dp = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

def start(update: Update, context):
    update.message.reply_text("Привет! Я живой на Render 🎉")

dp.add_handler(CommandHandler("start", start))

# === Flask ===
app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def health():
    return "ok", 200

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    # проверяем секрет
    if request.args.get("secret") != SECRET:
        return Response("Forbidden", status=403)

    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK", 200

def set_webhook():
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not host:
        return
    url = f"https://{host}/webhook/{TOKEN}?secret={SECRET}"
    try:
        bot.set_webhook(url)
        print("Webhook set to:", url)
    except Exception as e:
        print("Failed to set webhook:", e)

if __name__ == "__main__":
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
