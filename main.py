import os
import uuid
import stripe
from flask import Flask, request, abort
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, ContextTypes

# 1) ЗАГРУЖАЕМ КОНФИГ И СЕКРЕТЫ
TELEGRAM_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
STRIPE_API_KEY       = os.environ["STRIPE_SECRET"]
STRIPE_WEBHOOK_SECRET= os.environ["STRIPE_WEBHOOK_SECRET"]
APP_URL              = os.environ["APP_URL"]  # https://your-app.onrender.com

stripe.api_key = STRIPE_API_KEY

# 2) ИНИЦИАЛИЗАЦИЯ Telegram Bot + Dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot, None, workers=0)  # без фоновых воркеров

TASKS = {}  # тестовая память

# 3) ХЭНДЛЕРЫ ТГ-КОМАНД
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>\n"
        "/status <task_id>\n"
        "/release <task_id>\n"
    )

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.message.reply_text("Пример: /task 5 Лого")
    try:
        amount = int(ctx.args[0])
    except ValueError:
        return await update.message.reply_text("Сумма должна быть целым числом")
    title = " ".join(ctx.args[1:])
    tid = uuid.uuid4().hex[:8]
    pi = stripe.PaymentIntent.create(
        amount=amount*100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": tid},
        description=title
    )
    TASKS[tid] = {"pi_id": pi.id, "status": "new"}
    await update.message.reply_text(
        f"✅ Задача `{tid}` создана (ПИ `{pi.id}`).\n"
        "Оплати его в Dashboard (4242…), дождись `authorized`, потом /release",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /status <task_id>")
    t = TASKS.get(ctx.args[0])
    await update.message.reply_text(str(t or "Не найдено"))

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /release <task_id>")
    t = TASKS.get(ctx.args[0])
    if not t:
        return await update.message.reply_text("Не найдено")
    stripe.PaymentIntent.capture(t["pi_id"])
    await update.message.reply_text("✅ Захват отправлен — ждём succeeded")

# регистрируем хэндлеры
dp.add_handler(CommandHandler("start", cmd_start))
dp.add_handler(CommandHandler("task",  cmd_task))
dp.add_handler(CommandHandler("status",cmd_status))
dp.add_handler(CommandHandler("release",cmd_release))

# 4) FLASK — два рута: для Телеграма и для Stripe
app = Flask(__name__)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dp.process_update(update)
    return "OK"

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("⚠️  Stripe webhook error:", e)
        return abort(400)
    et = event["type"]
    pi = event["data"]["object"]
    if et == "payment_intent.amount_capturable_updated":
        # можно пометить статус TASKS[...]
        print("authorize:", pi["id"])
    elif et == "payment_intent.succeeded":
        print("succeeded:", pi["id"])
    return "OK", 200

if __name__ == "__main__":
    # 5) ЗАДАЁМ WEBHOOK Telegram при старте
    bot.set_webhook(f"{APP_URL}/{TELEGRAM_TOKEN}")
    # стартуем Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
