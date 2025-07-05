#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RSVP Bot for WhatsApp – Green-API
---------------------------------
* run:      python rsvp_bot.py runserver      # webhook + send endpoint (Render)
* manual:   python rsvp_bot.py send           # שליחת סבב ידנית מהמחשב
"""
import os, re, json, time, sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from flask import Flask, request, jsonify

# ─────────── CONFIG ───────────
GREEN_ID   = os.getenv("GREEN_ID")
GREEN_TOKEN= os.getenv("GREEN_TOKEN")
EXCEL_PATH = Path(os.getenv("EXCEL_PATH", "heb_rsvp.xlsx"))
DEFAULT_MSG= os.getenv("DEFAULT_MSG", "היי {name}! 🎉\nנשמח לראותך ב-12.09.25.\nרשום/י כן, לא, או אולי.")

API_URL    = f"https://api.green-api.com/waInstance{GREEN_ID}"
HEADERS    = {"Content-Type": "application/json"}

YES_WORDS   = {"כן", "מגיע", "אהיה", "בא", "באה", "yes", "y"}
NO_WORDS    = {"לא", "לא מגיע", "לא אהיה", "no", "n"}
MAYBE_WORDS = {"אולי", "maybe", "נראה", "נראה לי"}

# ─────────── HELPERS ───────────
def load_df() -> pd.DataFrame:
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"{EXCEL_PATH} not found")
    return pd.read_excel(EXCEL_PATH)

def save_df(df: pd.DataFrame):
    df.to_excel(EXCEL_PATH, index=False)

def il_to_chatid(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    if not digits.endswith("@c.us"):
        digits += "@c.us"
    return digits

def classify(text: str) -> str:
    t = text.strip().lower()
    for word in YES_WORDS:
        if word in t:
            return "YES"
    for word in NO_WORDS:
        if word in t:
            return "NO"
    for word in MAYBE_WORDS:
        if word in t:
            return "MAYBE"
    return "UNKNOWN"

def send_text(chat_id: str, message: str):
    url = f"{API_URL}/sendMessage/{GREEN_TOKEN}"
    payload = {"chatId": chat_id, "message": message}
    r = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()

def build_message(row, template=DEFAULT_MSG) -> str:
    return template.format(name=row["שם מלא"])

# ─────────── SENDING ROUND ───────────
def send_round():
    df = load_df()

    # ensure columns exist
    for col in ["Status", "LastSent", "AnsweredAt"]:
        if col not in df.columns:
            df[col] = ""

    today = datetime.now().date().isoformat()
    pending = df[df["Status"].isin(["", "MAYBE", "UNKNOWN"])]

    print(f"Total guests: {len(df)}  •  pending: {len(pending)}")
    for _, row in pending.iterrows():
        chat_id = il_to_chatid(str(row["מספר טלפון"]))
        msg     = build_message(row)
        try:
            send_text(chat_id, msg)
            df.loc[row.name, "LastSent"] = today
            print(f"✓ sent to {row['שם מלא']} ({chat_id})")
            time.sleep(0.2)  # נחמד ל-WhatsApp
        except Exception as e:
            print(f"⚠️  failed {chat_id}: {e}", file=sys.stderr)

    save_df(df)
    print("✔️  round finished")

# ─────────── WEBHOOK SERVER ───────────
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    try:
        body = data["body"]
        if body["typeWebhook"] != "incomingMessageReceived":
            return jsonify({"status": "ignored"})

        sender = body["senderData"]["chatId"]      # '9725XXXX@c.us'
        text   = body["messageData"]["textMessageData"]["textMessage"]
        decision = classify(text)

        df = load_df()
        mask = df["מספר טלפון"].apply(il_to_chatid) == sender
        if mask.any():
            idx = df[mask].index[0]
            df.at[idx, "Status"] = decision
            df.at[idx, "AnsweredAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_df(df)
            print(f"{sender} → {decision}")
        else:
            print(f"Unknown sender {sender}")

    except Exception as exc:
        print(f"Webhook error: {exc}", file=sys.stderr)
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"})

@app.route("/send_round", methods=["GET"])
def trigger_send():
    send_round()
    return jsonify({"status": "round_sent"})

# ─────────── ENTRY POINT ───────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        send_round()
    else:
        port = int(os.getenv("PORT", 10000))
        app.run(host="0.0.0.0", port=port)
