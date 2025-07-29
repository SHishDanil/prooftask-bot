import os
import json
import logging
import secrets
from threading import Thread

from flask import Flask, request, jsonify
import requests
import stripe

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- Логирование ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("prooftask-bot")

# ---------- Конфиг из ENV ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
STRIPE_SECRET = os.environ.get("STRIPE_SECRET", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
if not STRIPE_SECRET:
    raise RuntimeError("STRIPE_SECRET is not set")

stripe.api_key = STRIPE_SECRET

# Память задач на время жизни процесса
TASK_TO_PI: dict[str, str] = {}

# ---------- Flask ----------
app = Flask(__name__)

@app.get("/")
def health():
    return "ok", 200

@app.post("/webhook/stripe")
def stripe_webhook():
    # В тесте этот вебхук не обязателен, но пусть будет.
    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        log.exception("webhook error: %s", e)
        return "bad", 400

    t = event.get("type")
    if t in ("payment_intent.succeeded", "payment_intent.amount_capturable_updated"):
        pi = event["data"]["object"]
        task_id = (pi.get("metadata") or {}).get("task_id")
        if task_id:
            TASK_TO_PI[task_id] = pi["id"]
        log.info("Stripe event: %s for %s", t, pi.get("id"))
    return "ok", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ---------- Stripe helpers ----------
def create_payment_intent(amount_cents: int, description: str, task_id: str):
    """
    Создаём PaymentIntent без редиректных методов, с ручным захватом.
    """
    pi = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        capture_method="manual",
        description=description,
        metadata={"task_id": task_id},
        # Критично: запретить redirect‑методы, чтобы не требовался return_url
        automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
    )
    return pi

def get_pi_by_task(task_id: str):
    """
    Возвращает PaymentIntent по task_id. Сначала локальный кэш, потом Stripe Search.
    """
    pi_id = TASK_TO_PI.get(task_id)
    if pi_id:
        try:
            return stripe.PaymentIntent.retrieve(pi_id)
        except Exception:
            pass
    # fallback через Search API
    try:
        res = stripe.PaymentIntent.search(query=f"metadata['task_id']:'{task_id}'", limit=1)
        if res and res.data:
            TASK_TO_PI[task_id] = res.data[0].id
            return res.data[0]
    except Exception:
        pass
    return None

def delete_telegram_webhook_sync():
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook", timeout=8)
    except Exception:
        pass

# ---------- Telegram commands ----------
HELP_TEXT = (
    "Команды:\n"
    "/task <сумма_в_$> <описание> — создать задачу (пример: /task 1 Test)\n"
    "/status <task_id> — статус платежа\n"
    "/release <task_id> — захватить (capture), когда в Stripe статус authorized\n"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Это тест-бот оплаты через Stripe.\n" + HELP_TEXT)

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.split(maxsplit=2)
        amount_usd = int(args[1]) if len(args) > 1 else 1
        description = args[2] if len(args) > 2 else "Test"
    except Exception:
        return await update.message.reply_text("Формат: /task 1 Test")

    task_id = secrets.token_hex(4)
    amount_cents = amount_usd * 100
    try:
        pi = create_payment_intent(amount_cents, description, task_id)
        TASK_TO_PI[task_id] = pi.id
        text = (
            f"✅ Задача {task_id} создана. PI {pi.id} (manual hold).\n\n"
            f"1) В Stripe Dashboard (Test Mode) откройте платёж и добавьте карту 4242… (или через Shell командой ниже).\n"
            f"2) Дождитесь статуса authorized / uncaptured.\n"
            f"3) Пришлите: /release {task_id}\n\n"
            f"Shell для привязки карты:\n"
            f"stripe payment_intents confirm {pi.id} --payment_method pm_card_visa"
        )
        await update.message.reply_text(text)
    except Exception as e:
        log.exception("create PI failed")
        await update.message.reply_text(f"Ошибка создания платежа: {e}")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await update.message.reply_text("Формат: /status <task_id>")
    task_id = parts[1].strip()
    pi = get_pi_by_task(task_id)
    if not pi:
        return await update.message.reply_text("Не найдено")
    await update.message.reply_text(f"{pi.id}: status={pi.status}, capturable={pi.amount_capturable}")

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await update.message.reply_text("Формат: /release <task_id>")
    task_id = parts[1].strip()

    pi = get_pi_by_task(task_id)
    if not pi:
        return await update.message.reply_text("Не найдено")

    try:
        # если уже захвачен — просто подтвердим
        if pi.status in ("succeeded", "processing"):
            return await update.message.reply_text(f"✅ Уже {pi.status}. PI {pi.id}")

        # Authorized (requires_capture) — захватываем
        if pi.status == "requires_capture":
            pi = stripe.PaymentIntent.capture(pi.id)
            return await update.message.reply_text(f"✅ Захвачен. Статус: {pi.status}. PI {pi.id}")

        return await update.message.reply_text(f"Статус {pi.status}. Сначала добавьте карту и авторизуйте платёж.")
    except Exception as e:
        log.exception("capture failed")
        return await update.message.reply_text(f"Ошибка захвата: {e}")

def run_bot():
    # снимаем webhook, чтобы polling не конфликтовал
    delete_telegram_webhook_sync()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("task", cmd_task))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("release", cmd_release))
    application.run_polling(drop_pending_updates=True)

# ---------- entry ----------
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    run_bot()
