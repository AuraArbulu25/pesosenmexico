import os
import re

import requests
from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]          # any secret word you choose
WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]      # access token from Meta
PHONE_NUMBER_ID = os.environ["PHONE_NUMBER_ID"]    # test number's ID from Meta

GRAPH_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
RATE_URL = "https://api.frankfurter.app/latest?from=MXN&to=EUR"

SPANISH_HINTS = ("cuanto", "cuánto", "cuesta", "vale", "hola", "precio", "cuántos", "cuantos", "mil ")


def get_rate():
    r = requests.get(RATE_URL, timeout=10)
    r.raise_for_status()
    return r.json()["rates"]["EUR"]


def extract_amounts(text):
    """Find numbers like 350, 1,500, 99.50, 2k, 1.5k, '2 mil'."""
    amounts = []
    pattern = r"(\d[\d,]*\.?\d*)\s*(k|mil)?\b"
    for num, suffix in re.findall(pattern, text.lower()):
        try:
            value = float(num.replace(",", ""))
        except ValueError:
            continue
        if suffix:
            value *= 1000
        amounts.append(value)
    return amounts


def is_spanish(text):
    t = text.lower()
    return any(h in t for h in SPANISH_HINTS)


def build_reply(text):
    amounts = extract_amounts(text)
    spanish = is_spanish(text)
    if not amounts:
        return ("Escríbeme un precio en pesos, por ejemplo: 350"
                if spanish else
                "Send me a price in pesos, for example: 350")
    rate = get_rate()
    lines = [f"{a:,.2f} MXN ≈ €{a * rate:,.2f}" for a in amounts]
    footer = f"(1 MXN = €{rate:.4f})"
    return "\n".join(lines + [footer])


def send_message(to, body):
    requests.post(
        GRAPH_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        timeout=10,
    )


PRIVACY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy - Peso Bot</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.6;color:#222}</style>
</head><body>
<h1>Privacy Policy</h1>
<p>Last updated: October 2026</p>
<p>Peso Bot is a small personal WhatsApp bot that converts prices from Mexican pesos (MXN) to euros (EUR).</p>
<h2>What data is used</h2>
<p>When you send a message to the bot, it reads the text of that message (for example a price) and your WhatsApp phone number, only to send the reply back to you.</p>
<h2>What is stored</h2>
<p>Nothing. The bot does not store messages, phone numbers or any personal data in a database. Messages are processed in memory and discarded.</p>
<h2>Third parties</h2>
<p>Messages travel through the WhatsApp Business Platform (Meta). Hosting is provided by Vercel. Exchange rates come from the public Frankfurter API; no personal data is sent to it.</p>
<h2>Who can use it</h2>
<p>The bot is private and limited to a few approved test users. It is not offered to the public.</p>
<h2>Contact</h2>
<p>Questions or requests to delete data: aura.arbulu@iflry.org</p>
</body></html>"""


@app.get("/privacy")
def privacy():
    return PRIVACY_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


PATHS = ["/", "/webhook", "/api/index", "/api/index/webhook"]


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def handle(path):
    if request.method == "GET":
        if request.args.get("hub.mode") == "subscribe":
            if request.args.get("hub.verify_token") == VERIFY_TOKEN:
                return request.args.get("hub.challenge", ""), 200
            return "Forbidden", 403
        return "Peso bot running", 200

    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    reply = build_reply(msg["text"]["body"])
                    send_message(msg["from"], reply)
    except Exception as e:  # keep returning 200 so Meta doesn't retry
        print("error:", e)
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
