# ===== main.py =====
import os
import uuid
import stripe
from threading import Thread
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIG: читаем из ENV ---
TELEGRAM_BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
stripe.api_key        = os.environ["STRIPE_SECRET"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

# in-memory «база» задач
TASKS = {}  # task_id -> {"pi_id":..., "status":..., "title":..., "amount":...}

# --- Flask: Stripe Webhook endpoint ---
flask_app = Flask(__name__)

@flask_app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("⚠️  Webhook signature error:", e)
        return "", 400

    etype = event["type"]
    obj   = event["data"]["object"]
    print("🔔 Stripe event:", etype, "for", obj.get("id"))

    if etype == "payment_intent.amount_capturable_updated":
        _mark(obj["id"], "authorized")
    elif etype == "payment_intent.succeeded":
        _mark(obj["id"], "released")

    return "", 200

def _mark(pi_id: str, status: str):
    for tid, t in TASKS.items():
        if t["pi_id"] == pi_id:
            t["status"] = status
            print(f"✔️  Task {tid} marked {status}")
            break

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# --- Telegram bot handlers ---
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>\n"
        "/status <task_id>\n"
        "/release <task_id>"
    )

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.effective_message.reply_text("Пример: /task 5 Лого")
    try:
        amount = int(ctx.args[0])
    except ValueError:
        return await update.effective_message.reply_text("Сумма должна быть целым числом")
    title = " ".join(ctx.args[1:])
    tid = uuid.uuid4().hex[:8]

    pi = stripe.PaymentIntent.create(
        amount=amount * 100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": tid},
        description=title,
    )

    TASKS[tid] = {
        "pi_id": pi.id,
        "amount": amount,
        "title": title,
        "status": "new",
    }

    await update.effective_message.reply_text(
        f"✅ Задача `{tid}` создана.\n"
        f"PaymentIntent: `{pi.id}`.\n\n"
        "— Оплати вручную в Dashboard (Test mode, 4242…)\n"
        "— Когда станет `authorized`, пришли `/release {tid}`",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.effective_message.reply_text("Формат: /status <task_id>")
    t = TASKS.get(ctx.args[0])
    await update.effective_message.reply_text(str(t) if t else "Не нашёл задачу")

async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.effective_message.reply_text("Формат: /release <task_id>")
    tid = ctx.args[0]
    t = TASKS.get(tid)
    if not t:
        return await update.effective_message.reply_text("Не нашёл задачу")
    stripe.PaymentIntent.capture(t["pi_id"])
    await update.effective_message.reply_text("✅ Capture отправлен, ждём вебхук succeeded")

def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("task",    cmd_task))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("release", cmd_release))
    app.run_polling(drop_pending_updates=True)

# --- ENTRY POINT ---
if __name__ == "__main__":
    # 1) запустить Flask в фоне
    Thread(target=run_flask, daemon=True).start()
    # 2) запустить Telegram‑бота
    run_bot()
