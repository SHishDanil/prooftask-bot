# ===== main.py =====
import os, uuid, stripe
from threading import Thread
from flask import Flask, request

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- CONFIG ----------
TELEGRAM_BOT_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
stripe.api_key         = os.environ["STRIPE_SECRET"]
STRIPE_WEBHOOK_SECRET  = os.environ["STRIPE_WEBHOOK_SECRET"]

# Память вместо БД для теста
TASKS = {}  # task_id -> {"pi_id": ..., "status": ...}

# ---------- FLASK (Stripe webhook) ----------
flask_app = Flask(__name__)

@flask_app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("Webhook signature error:", e)
        return "bad", 400

    etype = event["type"]
    obj   = event["data"]["object"]
    print("STRIPE:", etype, obj.get("id"))

    if etype == "payment_intent.amount_capturable_updated":
        _mark(obj["id"], "authorized")
    elif etype == "payment_intent.succeeded":
        _mark(obj["id"], "released")

    return "ok", 200

def _mark(pi_id: str, status: str):
    for t in TASKS.values():
        if t["pi_id"] == pi_id:
            t["status"] = status
            break

def run_flask():
    port = int(os.getenv("PORT", 5000))  # Render/Heroku кладут порт сюда
    flask_app.run(host="0.0.0.0", port=port)

# ---------- TELEGRAM ----------
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>\n"
        "/status <task_id>\n"
        "/release <task_id>\n"
    )

async def cmd_task(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if len(c.args) < 2:
        return await u.message.reply_text("Пример: /task 5 Лого")

    try:
        amount = int(c.args[0])
    except ValueError:
        return await u.message.reply_text("Сумма должна быть целым числом")

    title = " ".join(c.args[1:])
    task_id = uuid.uuid4().hex[:8]

    pi = stripe.PaymentIntent.create(
        amount=amount * 100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": task_id},
        description=title,
    )

    TASKS[task_id] = {
        "pi_id": pi.id,
        "amount": amount,
        "title": title,
        "status": "new",
    }

    await u.message.reply_text(
        f"✅ task_id `{task_id}` создан.\n"
        f"PaymentIntent: `{pi.id}` (manual hold).\n\n"
        "Оплати его руками в Stripe Dashboard (Test mode, 4242…)\n"
        "Когда появится authorized — пришли /release <task_id>.",
        parse_mode="Markdown",
    )

async def cmd_status(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        return await u.message.reply_text("Формат: /status <task_id>")
    t = TASKS.get(c.args[0])
    await u.message.reply_text(str(t) if t else "Не нашёл задачу")

async def cmd_release(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        return await u.message.reply_text("Формат: /release <task_id>")
    tid = c.args[0]
    t = TASKS.get(tid)
    if not t:
        return await u.message.reply_text("Не нашёл задачу")
    stripe.PaymentIntent.capture(t["pi_id"])
    await u.message.reply_text("✅ capture отправлен. Ждём вебхук succeeded.")

def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("task",    cmd_task))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("release", cmd_release))
    app.run_polling(drop_pending_updates=True)

# ---------- ENTRY ----------
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()  # поднимаем HTTP для Stripe
    run_bot()                                      # запускаем Telegram-бота
