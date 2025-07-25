#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from threading import Thread

import stripe
from flask import Flask, request, jsonify

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ═══════════════════════════════
#  Настройка ключей из окружения
# ═══════════════════════════════
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
# секрет вебхука Stripe (см. Dashboard → Webhooks)
endpoint_secret = os.environ.get("STRIPE_ENDPOINT_SECRET")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ═══════════════════════════════
#  Flask‑сервер для Stripe вебхуков
# ═══════════════════════════════
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as e:
        print("❌ Webhook parse error:", e)
        return jsonify(success=False), 400

    if endpoint_secret:
        sig_header = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except stripe.error.SignatureVerificationError as e:
            print("❌ Signature verification failed:", e)
            return jsonify(success=False), 400

    # Обрабатываем события
    etype = event["type"]
    data = event["data"]["object"]
    if etype == "payment_intent.succeeded":
        print(f"🔔 PaymentIntent succeeded: {data['id']} amount={data['amount']}")
        # тут можно связать с вашим TASKS и слать уведомления в телеграм
    elif etype == "payment_method.attached":
        print(f"🔔 PaymentMethod attached: {data['id']}")
    else:
        print("🔔 Unhandled event:", etype)

    return jsonify(success=True)


# ═══════════════════════════════
#  Логика телеграм‑бота
# ═══════════════════════════════
TASKS = {}  # простой in‑memory словарь: {task_id: {"pi_id": ..., "status": ...}}

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/task <usd> <описание> — создать задачу и холд\n"
        "/status <task_id> — проверить статус платежа\n"
        "/release <task_id> — захватить средства"
    )

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        return await update.message.reply_text(
            "Использование: /task <usd> <описание>"
        )
    try:
        amount_usd = float(ctx.args[0])
    except ValueError:
        return await update.message.reply_text("Первый аргумент должен быть числом (USD).")
    description = " ".join(ctx.args[1:])

    # создаём PaymentIntent с ручным захватом
    pi = stripe.PaymentIntent.create(
        amount=int(amount_usd * 100),
        currency="usd",
        payment_method_types=["card"],
        capture_method="manual",
        description=description,
    )
    task_id = str(len(TASKS) + 1)
    TASKS[task_id] = {"pi_id": pi.id, "status": "new"}

    await update.message.reply_text(
        f"✅ Задача {task
