# ===== main.py =====
import os
import uuid
import stripe
from threading import Thread
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Читаем из переменных окружения ---
TELEGRAM_BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]    # из BotFather
stripe.api_key        = os.environ["STRIPE_SECRET"]         # sk_test_…
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"] # whsec_…

# Простая «in‑memory» база задач
TASKS = {}  # task_id → {"pi_id":…, "status":…}

# === Flask для Stripe вебхуков ===
app = Flask(__name__)

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        evt = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("❌ Webhook error:", e)
        return "", 400

    etype = evt["type"]
    obj = evt["data"]["object"]
    print("▶️ STRIPE EVENT:", etype, obj.get("id"))

    if etype == "payment_intent.amount_capturable_updated":
        _mark(obj["id"], "authorized")
    elif etype == "payment_intent.succeeded":
        _mark(obj["id"], "released")

    return "", 200

def _mark(pi_id, status):
    for tid, data in TASKS.items():
        if data["pi_id"] == pi_id:
            data["status"] = status
            print(f"✔️ Task {tid} → {status}")
            break

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# === Telegram‑бот ===
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>  — создать задачу и холд\n"
        "/status <task_id>       — проверить статус\n"
        "/release <task_id>      — захватить средства"
    )

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.message.reply_text("Использование: /task 5 Лого")
    try:
        amount = int(ctx.args[0])
    except:
        return await update.message.reply_text("Сумма — целое число, напр. 5")
    title = " ".join(ctx.args[1:])
    tid = uuid.uuid4().hex[:8]
    pi = stripe.PaymentIntent.create(
        amount=amount*100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": tid},
        description=title,
    )
    TASKS[tid] = {"pi_id": pi.id, "status": "new"}
    await update.message.reply_text(
        f"✅ Задача `{tid}` создана (ПИ {pi.id}).\n"
        "Оплатите в Dashboard (4242…), дождиcь статус `authorized`, потом /release <task_id>",
        parse_mode="Markdown",
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

def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("task",    cmd_task))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("release", cmd_release))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    run_bot()
