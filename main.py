import os
import uuid
import logging
from decimal import Decimal
from threading import Thread

import requests
import stripe
from flask import Flask

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- Конфиг (ENV) ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
STRIPE_SECRET_KEY  = os.getenv("STRIPE_SECRET_KEY", "").strip()   # sk_test_...
# Webhook секрет опционален (в этом сценарии не обязателен)
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
if not STRIPE_SECRET_KEY:
    raise SystemExit("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("prooftask")

# ---------- Flask: health ----------
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)

# ---------- Вспомогательное ----------
def find_pi_by_task_id(task_id: str):
    """Ищем PaymentIntent по metadata.task_id напрямую в Stripe (не зависит от перезапуска)."""
    res = stripe.PaymentIntent.search(
        query=f"metadata['task_id']:'{task_id}'",
        limit=1
    )
    items = list(res.auto_paging_iter()) if hasattr(res, "auto_paging_iter") else res.data
    if not items:
        raise ValueError("PaymentIntent not found for task_id")
    return items[0]

# ---------- Telegram-команды ----------
HELP_TEXT = (
    "Команды:\n"
    "/task <usd> <описание> — создать платёж с холдом (авто-авторизация)\n"
    "/status <task_id>      — проверить статус\n"
    "/release <task_id>     — захватить средства"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я живой.\n\n" + HELP_TEXT)

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /task <usd> <описание>")

    # 1) сумма
    try:
        amount_usd = Decimal(ctx.args[0])
    except Exception:
        return await update.message.reply_text("Первый аргумент — сумма в USD. Пример: /task 1 Test")

    # 2) описание
    description = " ".join(ctx.args[1:]).strip() or "ProofTask escrow"
    amount_cents = int(amount_usd * 100)

    # 3) task_id
    task_id = uuid.uuid4().hex[:8]

    # 4) Создаём PaymentIntent с manual capture и СРАЗУ подтверждаем тестовой картой
    try:
        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            capture_method="manual",        # холд
            confirm=True,                   # сразу подтверждаем
            payment_method="pm_card_visa",  # тестовая карта (4242)
            description=description,
            metadata={"task_id": task_id},
        )
    except Exception as e:
        log.exception("PI create failed")
        return await update.message.reply_text(f"Ошибка создания платежа: {e}")

    text = (
        f"✅ Задача `{task_id}` создана. "
        f"PI `{pi['id']}` (hold authorized).\n\n"
        f"Проверка: /status {task_id}\n"
        f"Захват: /release {task_id}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /status <task_id>")
    task_id = ctx.args[0].strip()

    try:
        pi = find_pi_by_task_id(task_id)
    except Exception as e:
        return await update.message.reply_text(f"Не найдено: {e}")

    status = pi.get("status")
    capturable = pi.get("amount_capturable", 0)
    received = pi.get("amount_received", 0)

    human = status
    if status != "succeeded" and capturable > 0:
        human = "authorized (requires_capture)"
    if status == "succeeded":
        human = "succeeded (captured)"

    await update.message.reply_text(
        f"Task: {task_id}\n"
        f"PI: {pi['id']}\n"
        f"Status: {human}\n"
        f"Capturable: {capturable}¢, Received: {received}¢"
    )

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /release <task_id>")
    task_id = ctx.args[0].strip()

    try:
        pi = find_pi_by_task_id(task_id)
    except Exception as e:
        return await update.message.reply_text(f"Не найдено: {e}")

    try:
        stripe.PaymentIntent.capture(pi["id"])
    except Exception as e:
        log.exception("capture failed")
        return await update.message.reply_text(f"Ошибка захвата: {e}")

    await update.message.reply_text("✅ Захват отправлен. Через секунду проверьте: /status " + task_id)

def delete_telegram_webhook_sync():
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
            timeout=8,
        )
    except Exception:
        pass

def run_bot():
    # На всякий случай снимем webhook, чтобы polling не конфликтовал
    delete_telegram_webhook_sync()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("task",    cmd_task))
    application.add_handler(CommandHandler("status",  cmd_status))
    application.add_handler(CommandHandler("release", cmd_release))
    application.run_polling(drop_pending_updates=True)

# ---------- Entry ----------
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    run_bot()
