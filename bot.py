# ===== main.py =====
import os, stripe, uuid
from threading import Thread
from flask import Flask, request

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- CONFIG ----------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
stripe.api_key        = os.environ["STRIPE_SECRET"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

# ---------- IN-MEMORY TASKS ----------
TASKS = {}           # task_id -> dict

# ---------- FLASK ----------
flask_app = Flask(__name__)

@flask_app.route("/webhook/stripe", methods=["POST"])   # <-- маршрут, который дергает Stripe
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("Signature error:", e)
        return "bad", 400

    ty  = event["type"]
    obj = event["data"]["object"]
    print("STRIPE:", ty, obj["id"])

    # минимальная логика
    if ty == "payment_intent.amount_capturable_updated":
        _mark(obj["id"], "authorized")
    elif ty == "payment_intent.succeeded":
        _mark(obj["id"], "released")
    return "ok", 200

def _mark(pi_id, new_status):
    for t in TASKS.values():
        if t["pi_id"] == pi_id:
            t["status"] = new_status
            break

def run_flask():
    port = int(os.getenv("PORT", 5000))     # Render / Railway / Heroku кладут порт сюда
    flask_app.run(host="0.0.0.0", port=port)

# ---------- TELEGRAM ----------
async def start_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание>\n"
        "/status <task_id>\n"
        "/release <task_id>"
    )

async def task_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if len(c.args) < 2:
        return await u.message.reply_text("Пример: /task 5 Лого")

    amount = int(c.args[0])
    title  = " ".join(c.args[1:])
    tid    = uuid.uuid4().hex[:8]

    pi = stripe.PaymentIntent.create(
        amount=amount*100,
        currency="usd",
        capture_method="manual",
        payment_method_types=["card"],
        metadata={"task_id": tid},
        description=title,
    )
    TASKS[tid] = {"pi_id": pi.id, "amount": amount, "title": title, "status": "new"}
    await u.message.reply_text(
        f"Создано task_id `{tid}`. \n"
        f"PaymentIntent `{pi.id}` (manual). \n"
        "Оплатите его в Dashboard картой 4242…\n"
        "После `authorized` пришлите /release <task_id>",
        parse_mode="Markdown",
    )

async def status_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args: return
    t = TASKS.get(c.args[0])
    await u.message.reply_text(str(t) if t else "нет такой задачи")

async def release_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args: return
    tid = c.args[0]
    t = TASKS.get(tid)
    if not t: return await u.message.reply_text("нет задачи")
    stripe.PaymentIntent.capture(t["pi_id"])
    await u.message.reply_text("capture вызван — ждём succeeded")

def run_bot():
    bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", start_cmd))
    bot.add_handler(CommandHandler("task", task_cmd))
    bot.add_handler(CommandHandler("status", status_cmd))
    bot.add_handler(CommandHandler("release", release_cmd))
    bot.run_polling(drop_pending_updates=True)

# ---------- ENTRY ----------
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()   # веб-сервер для Stripe
    run_bot()                                      # Telegram-бот
