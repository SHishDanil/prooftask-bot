import os
import logging
import uuid
from decimal import Decimal
from threading import Thread

import stripe
from flask import Flask, request, jsonify

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
#  Настройки/ключи из окружения
# =========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
STRIPE_SECRET_KEY  = os.getenv("STRIPE_SECRET_KEY", "").strip()   # sk_test_...
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()  # whsec_... (опционально)

if not TELEGRAM_BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
if not STRIPE_SECRET_KEY:
    raise SystemExit("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

# =========================
#  Логирование
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("prooftask")

# =========================
#  Память задач (in‑memory)
#  tid -> {"pi_id": str, "status": "new|authorized|captured|failed"}
# =========================
TASKS: dict[str, dict] = {}

# =========================
#  Flask (здоровье + вебхук Stripe)
# =========================
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

@app.post("/webhook/stripe")
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        log.warning("Stripe webhook verify failed: %s", e)
        return jsonify({"ok": False}), 400

    etype = event.get("type")
    data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}

    tid = metadata.get("task_id")
    pi_id = data.get("id")

    if etype == "payment_intent.amount_capturable_updated":
        # Авторизация (холд) прошла
        if tid and tid in TASKS:
            TASKS[tid]["status"] = "authorized"
        log.info("PI %s authorized (capturable updated), task=%s", pi_id, tid)

    elif etype == "payment_intent.succeeded":
        if tid and tid in TASKS:
            TASKS[tid]["status"] = "captured"
        log.info("PI %s captured (succeeded), task=%s", pi_id, tid)

    elif etype == "payment_intent.payment_failed":
        if tid and tid in TASKS:
            TASKS[tid]["status"] = "failed"
        log.info("PI %s failed, task=%s", pi_id, tid)

    else:
        log.info("Unhandled Stripe event: %s", etype)

    return jsonify({"ok": True}), 200


def run_flask():
    # Render слушает порт 10000 по умолчанию
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)


# =========================
#  Telegram-команды
# =========================
HELP_TEXT = (
    "Команды:\n"
    "/task <usd> <описание> — создать задачу и поставить деньги на холд\n"
    "/status <task_id>      — проверить статус\n"
    "/release <task_id>     — захватить средства\n\n"
    "Пример: /task 1 Test"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я живой 😊\n\n" + HELP_TEXT)

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /task <usd> <описание>")

    # 1) Парсим сумму и описание
    try:
        amount_usd = Decimal(ctx.args[0])
    except Exception:
        return await update.message.reply_text("Первый аргумент — сумма в USD. Пример: /task 1 Test")

    desc = " ".join(ctx.args[1:]).strip() or "Task"
    amount_cents = int(amount_usd * 100)

    # 2) Генерируем task_id
    tid = uuid.uuid4().hex[:8]

    # 3) Создаём PaymentIntent с manual capture и СРАЗУ подтверждаем тестовой картой
    #    Это избавляет от ручного прикрепления карты в Dashboard.
    try:
        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            capture_method="manual",       # холд
            confirm=True,                  # сразу подтверждаем
            payment_method="pm_card_visa", # тестовая карта Stripe
            description=desc,
            metadata={"task_id": tid},
        )
    except Exception as e:
        log.exception("create PI failed")
        return await update.message.reply_text(f"Ошибка при создании платежа: {e}")

    # 4) Сохраняем и отвечаем
    TASKS[tid] = {"pi_id": pi["id"], "status": "authorized"}
    text = (
        f"✅ Задача {tid} создана. PI {pi['id']} (hold authorized).\n\n"
        f"Далее пришлите: /release {tid} — захватить средства."
    )
    await update.message.reply_text(text)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /status <task_id>")

    tid = ctx.args[0].strip()
    t = TASKS.get(tid)
    if not t:
        return await update.message.reply_text("Не найдено")

    try:
        pi = stripe.PaymentIntent.retrieve(t["pi_id"])
        status = pi.get("status")
        capturable = pi.get("amount_capturable", 0)
        captured = pi.get("amount_received", 0)
    except Exception as e:
        return await update.message.reply_text(f"Ошибка получения статуса: {e}")

    await update.message.reply_text(
        f"Статус PI: {status}\n"
        f"Capturable: {capturable}¢, Received: {captured}¢\n"
        f"Локальный статус: {t.get('status')}"
    )

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /release <task_id>")

    tid = ctx.args[0].strip()
    t = TASKS.get(tid)
    if not t:
        return await update.message.reply_text("Не найдено")

    try:
        stripe.PaymentIntent.capture(t["pi_id"])
    except Exception as e:
        log.exception("capture failed")
        return await update.message.reply_text(f"Ошибка захвата: {e}")

    TASKS[tid]["status"] = "captured"
    await update.message.reply_text("✅ Захват отправлен — ждём succeeded")

# =========================
#  Запуск
# =========================
def run_bot():
    app_ = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app_.add_handler(CommandHandler("start",  cmd_start))
    app_.add_handler(CommandHandler("task",   cmd_task))
    app_.add_handler(CommandHandler("status", cmd_status))
    app_.add_handler(CommandHandler("release",cmd_release))

    # Важно: уникальный polling, без второго экземпляра
    app_.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Flask в отдельном потоке (для вебхука/health)
    Thread(target=run_flask, daemon=True).start()
    # Запускаем Telegram-бот
    run_bot()
