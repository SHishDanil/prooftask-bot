# --- Stripe webhook + Flask ---
import os
import stripe
from flask import Flask, request
from threading import Thread

stripe.api_key = os.environ["STRIPE_SECRET"]
ENDPOINT_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

flask_app = Flask(__name__)

@flask_app.post("/webhook/stripe")
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, ENDPOINT_SECRET)
    except ValueError:
        # Неверное тело
        return "Bad payload", 400
    except stripe.error.SignatureVerificationError:
        # Подпись не совпала
        return "Bad signature", 400

    etype = event["type"]
    obj = event["data"]["object"]

    # Минимальная логика (для отладки)
    print("STRIPE EVENT:", etype, obj.get("id"))

    # TODO: тут обновляй статус задачи в БД:
    # if etype == "payment_intent.amount_capturable_updated": status = "authorized"
    # if etype == "payment_intent.succeeded": status = "released"

    return "ok", 200

def run_flask():
    # Render отдаёт порт в переменной PORT
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
