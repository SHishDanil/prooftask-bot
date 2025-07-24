# bot.py
import os
import uuid
import stripe
from threading import Thread

from flask import Flask, request

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =======================
# 0. ENV / CONFIG
# =======================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
STRIPE_SECRET = os.getenv("STRIPE_SECRET")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
if not STRIPE_SECRET:
    raise RuntimeError("STRIPE_SECRET is not set")
if not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set")

stripe.api_key = STRIPE_SECRET

# Память вместо БД для теста
TASKS: dict[str, dict] = {}

# =======================
# 1. FLASK (Stripe webhook)
# =======================
flask_app = Flask(__name__)

@flask_app.post("/webhook/stripe")
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return "Bad payload", 400
    except stripe.error.SignatureVerificationError:
        return "Bad signature", 400

    etype = event["type"]
    obj = event["data"]["object"]

    print(">>> STRIPE EVENT:", etype, obj.get("id"))

    # Обновим статусы «в памяти»
    if etype == "payment_intent.amount_capturable_updated":
        pi_id = obj["id"]
        # ищем задачу по pi_id
        for t in TASKS.values():
            if t.get("pi_id") == pi_id:
                t["status"] = "authorized"
                break

    if etype == "payment_intent.succeeded":
        pi_id = obj["id"]
        for t in TASKS.values():
            if t.get("pi_id") == pi_id:
                t["status"] = "released"
                break

    return "ok", 200

def run_flask():
    # Render/Heroku задают PORT через env
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# =======================
# 2. TELEGRAM BOT
# =======================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я жив. Команды:\n"
        "/task <сумма> <описание> — создать задачу и PaymentIntent (manual hold)\n"
