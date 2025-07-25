#!/usr/bin/env python3
import os
import uuid
import stripe
from threading import Thread
from flask import Flask, request, abort
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# === Конфиг: читаем из переменных окружения ===
TELEGRAM_TOKEN         = os.environ["TELEGRAM_BOT_TOKEN"]
stripe.api_key         = os.environ["STRIPE_SECRET"]
STRIPE_WEBHOOK_SECRET  = os.environ["STRIPE_WEBHOOK_SECRET"]

# Простая in‑memory «БД» задач
TASKS = {}  # task_id → {"pi_id":..., "status":...}

# === Flask для Stripe webhook ===
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        print("Webhook signature failed:", e)
        return abort(400)

    etype = event["type"]
    obj   = event["data"]["object"]
    print("▶️ STRIPE EVENT", etype, obj.get("id"))

    # Отмечаем статус в памяти
    if etype == "payment_intent.amount_capturable_updated":
        for t in TASKS.values():
            if t["pi_id"] == obj["id"]:
                t["status"] = "authorized"
    elif etype == "payment_intent.succeeded":
        for t in TASKS.values():
            if t["pi_id"] == obj["id"]:
                t["status"] = "released"

    return ("", 200)

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# === Telegram‑бот ===
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>  — создать задачу (будет холд)\n"
        "/status <task_id>       — проверить статус\n"
        "/release <task_id>      — захватить средства"
    )

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.message.reply_text("Использование: /task 5 Лого")
    try:
        amount = int(ctx.args[0])
    except ValueError:
        return await update.message.reply_text("Сумма должна быть целым числом")
    desc = " ".join(ctx.args[1:])
    task_id = uuid.uuid4().hex[:8]

    pi = stripe.PaymentIntent.create(
        amount=amount * 100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": task_id},
        description=desc,
    )

    TASKS[task_id] = {"pi_id": pi.id, "status": "new"}
    await update.message.reply_text(
        f"✅ Задача `{task_id}` создана. PI `{pi.id}` (manual hold).\n"
        "Оплатите в Dashboard (Test mode, карта 4242…), дождитесь `authorized`, затем пришлите:\n"
        f"/release {task_id}",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /status <task_id>")
    t = TASKS.get(ctx.args[0])
    await update.message.reply_text(str(t or "Задача не найдена"))

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Использование: /release <task_id>")
    t = TASKS.get(ctx.args[0])
    if not t:
        return await update.message.reply_text("Задача не найдена")
    stripe.PaymentIntent.capture(t["pi_id"])
    await update.message.reply_text("✅ Capture отправлен. Ждём succeeded")

def run_bot():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("task",    cmd_task))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("release", cmd_release))
    app.run_polling(drop_pending_updates=True)

# === Entry point ===
if __name__ == "__main__":
    # 1) Запускаем Flask для Stripe в фоне
    Thread(target=run_flask, daemon=True).start()
    # 2) Запускаем Telegram‑бота
    run_bot()
