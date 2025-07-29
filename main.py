import os
import logging
import uuid
from threading import Thread

import requests
import stripe
from flask import Flask, Response

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- Логирование ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
log = logging.getLogger("prooftask")

# ---------- Env ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
STRIPE_SECRET = os.environ.get("STRIPE_SECRET") or os.environ.get("STRIPE_SECRET_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
if not STRIPE_SECRET:
    raise RuntimeError("STRIPE_SECRET (или STRIPE_SECRET_KEY) is not set")

stripe.api_key = STRIPE_SECRET

# ---------- Flask (для Render ping/health) ----------
app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def root():
    return Response("ok", status=200)

def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

# ---------- Память задач ----------
TASKS: dict[str, dict] = {}

# ---------- Команды TG ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Я держу средства в холде и отпускаю по команде.\n\n"
        "Создать тестовую задачу (USD):\n"
        "/task 1 Test\n\n"
        "Проверить статус:\n"
        "/status <task_id>\n\n"
        "Захватить (списать) средства:\n"
        "/release <task_id>"
    )
    await update.message.reply_text(text)

async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 1:
            return await update.message.reply_text("Формат: /task <amount_usd> [description]")

        amount_usd = float(context.args[0])
        desc = " ".join(context.args[1:]) or "Test"

        amount_cents = int(round(amount_usd * 100))
        task_id = uuid.uuid4().hex[:8]

        # ВАЖНО: card only + запрет редиректов, ручной захват, сразу подтверждаем тестовой картой.
        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            capture_method="manual",
            confirm=True,                         # сразу авторизуем (hold)
            payment_method="pm_card_visa",        # тестовая карта 4242…
            automatic_payment_methods={
                "enabled": True,
                "allow_redirects": "never",
            },
            description=desc,
            metadata={"task_id": task_id},
        )

        TASKS[task_id] = {"pi_id": pi.id}
        await update.message.reply_text(
            f"✅ Задача {task_id} создана.\n"
            f"PI {pi.id} (manual hold).\n"
            f"Статус: {pi.status}\n\n"
            f"Команды:\n/status {task_id}\n/release {task_id}"
        )
    except stripe.error.StripeError as e:
        log.exception("PI create failed")
        await update.message.reply_text(f"Ошибка Stripe: {e.user_message or str(e)}")
    except Exception as e:
        log.exception("cmd_task failed")
        await update.message.reply_text(f"Ошибка: {e}")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /status <task_id>")
    task_id = context.args[0]
    data = TASKS.get(task_id)
    if not data:
        return await update.message.reply_text("Не найдено")

    try:
        pi = stripe.PaymentIntent.retrieve(data["pi_id"])
        await update.message.reply_text(
            f"task_id: {task_id}\nPI: {pi.id}\nstatus: {pi.status}\n"
            f"amount: {pi.amount/100:.2f} {pi.currency.upper()}"
        )
    except Exception as e:
        log.exception("status failed")
        await update.message.reply_text(f"Ошибка: {e}")

async def cmd_release(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /release <task_id>")
    task_id = context.args[0]
    data = TASKS.get(task_id)
    if not data:
        return await update.message.reply_text("Не найдено")

    try:
        pi = stripe.PaymentIntent.capture(data["pi_id"])
        await update.message.reply_text(f"✅ Захват выполнен. PI {pi.id}\nstatus: {pi.status}")
    except Exception as e:
        log.exception("capture failed")
        await update.message.reply_text(f"Ошибка захвата: {e}")

def delete_telegram_webhook_sync():
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
            timeout=8,
        )
    except Exception:
        pass

def run_bot():
    # снимаем возможный вебхук -> включаем polling (чтобы не конфликтовало)
    delete_telegram_webhook_sync()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("task", cmd_task))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("release", cmd_release))

    # drop_pending_updates=True — на случай перезапуска и 409 при деплоях
    application.run_polling(drop_pending_updates=True)

# ---------- Entry ----------
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    run_bot()
