import os, stripe, telegram, flask
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, filters

# ── переменные окружения (задаются в Render) ──────────────────────────────
TOKEN      = os.environ["BOT_TOKEN"]     # токен бота от @BotFather
STRIPE_KEY = os.environ["STRIPE_KEY"]    # sk_test_… из Stripe

stripe.api_key = STRIPE_KEY
bot  = telegram.Bot(TOKEN)
app  = flask.Flask(__name__)
dp   = Dispatcher(bot, None, workers=0, use_context=True)

# ── команда /task 50 "Описание" ───────────────────────────────────────────
def new_task(update: Update, _):
    parts = update.message.text.split(" ", 2)
    if len(parts) < 3:
        return update.message.reply_text('Usage: /task <sum> "<description>"')
    amount = int(float(parts[1]) * 100)        # доллары  -> центы
    desc   = parts[2].strip('"')

    pi = stripe.PaymentIntent.create(
        amount=amount,
        currency="usd",
        capture_method="manual",               # удерживаем холд
        description=desc,
    )
    pay_url = f"https://pay.stripe.com/pay/{pi.client_secret.split('_secret')[0]}"
    update.message.reply_text(
        f"💳 Ссылка для оплаты:\n{pay_url}\nПосле оплаты отправьте /deliver"
    )
    dp.chat_data[update.effective_chat.id] = {"pi": pi.id}

# ── команда /deliver ──────────────────────────────────────────────────────
def deliver(update: Update, _):
    update.message.reply_text("📦 Получено! Для выпуска платежа напишите /accept")

# ── команда /accept ───────────────────────────────────────────────────────
def accept(update: Update, _):
    data = dp.chat_data.get(update.effective_chat.id, {})
    if not data:
        return update.message.reply_text("Нет активной задачи.")
    stripe.PaymentIntent.capture(data["pi"])
    update.message.reply_text("✅ Платёж перечислен исполнителю. Спасибо!")

# ── регистрируем обработчики ──────────────────────────────────────────────
dp.add_handler(CommandHandler("task", new_task))
dp.add_handler(CommandHandler("deliver", deliver))
dp.add_handler(CommandHandler("accept", accept))
dp.add_handler(MessageHandler(filters.COMMAND,
              lambda u, c: u.message.reply_text("Команда не распознана.")))

# ── веб‑хук для Telegram ──────────────────────────────────────────────────
@app.route("/hook", methods=["POST"])
def webhook():
    dp.process_update(Update.de_json(flask.request.json, bot))
    return "ok"

# ── запускаем Flask на порту, который задаёт Render ───────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
