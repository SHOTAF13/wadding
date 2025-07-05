#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RSVP Bot for WhatsApp – Green-API + Google Sheets
------------------------------------------------
* run:      python rsvp_bot.py runserver      # webhook + send endpoint (Render)
* manual:   python rsvp_bot.py send           # שליחת סבב ידנית מהמחשב
"""
import os
import re
import time
import sys
from datetime import datetime

import requests
from flask import Flask, request, jsonify

# ספריות לגוגל שיטס
from google.oauth2.service_account import Credentials
import gspread

# ───────── CONFIG ─────────
GREEN_ID    = os.getenv("GREEN_ID")
GREEN_TOKEN = os.getenv("GREEN_TOKEN")
DEFAULT_MSG = os.getenv(
    "DEFAULT_MSG",
    "היי {name}! 🎉\nנשמח לראותך בחתונתנו ב-19.2.2025 בסיטרוס אירועים, אבן יהודה.\nקבלת פנים: 19:30 | חופה: 20:30\n\nנודה לאישור הגעה בהודעה חוזרת: כן / לא / אולי\n\nנתראה בשמחות! 🎉"
)

# Google Sheets config
SHEET_NAME     = os.getenv("SHEET_NAME", "wedding_rsvp")
JSON_KEY_PATH  = os.getenv("GOOGLE_CREDENTIALS_PATH", "service_account.json")
GSCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]
credentials = Credentials.from_service_account_file(JSON_KEY_PATH, scopes=GSCOPE)
gc = gspread.authorize(credentials)
sheet = gc.open(SHEET_NAME).sheet1

API_URL = f"https://api.green-api.com/waInstance{GREEN_ID}"
HEADERS = {"Content-Type": "application/json"}

YES_WORDS   = {"כן", "מגיע", "אהיה", "בא", "באה", "yes", "y"}
NO_WORDS    = {"לא", "לא מגיע", "לא אהיה", "no", "n"}
MAYBE_WORDS = {"אולי", "maybe", "נראה", "נראה לי"}

# ───────── HELPERS ─────────
def load_df():
    import pandas as pd
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def save_df(df):
    # מנקה את הגיליון ומעדכן אותו מחדש בכל הנתונים
    sheet.clear()
    sheet.update([df.columns.values.tolist()] + df.values.tolist())

def il_to_chatid(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    if not digits.startswith("972"):
        digits = "972" + digits
    if not digits.endswith("@c.us"):
        digits += "@c.us"
    return digits

def classify(text: str) -> str:
    t = text.strip().lower()
    for w in YES_WORDS:
        if w in t:
            return "YES"
    for w in NO_WORDS:
        if w in t:
            return "NO"
    for w in MAYBE_WORDS:
        if w in t:
            return "MAYBE"
    return "UNKNOWN"

def send_text(chat_id: str, message: str):
    payload = {"chatId": chat_id, "message": message}
    r = requests.post(f"{API_URL}/sendMessage/{GREEN_TOKEN}", headers=HEADERS, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()

def build_message(row):
    return DEFAULT_MSG.format(name=row["שם מלא"])

# ───────── SENDING ROUND ─────────
def send_round():
    df = load_df()
    # וידוא עמודות
    for col in ["Status", "LastSent", "AnsweredAt"]:
        if col not in df.columns:
            df[col] = ""

    today = datetime.now().date().isoformat()
    pending = df[df["Status"].isin(["", "MAYBE", "UNKNOWN"])]

    print(f"Total guests: {len(df)} • pending: {len(pending)}")
    for idx, row in pending.iterrows():
        chat_id = il_to_chatid(str(row["טלפון"]))
        msg = build_message(row)
        try:
            send_text(chat_id, msg)
            df.at[idx, "LastSent"] = today
            print(f"✓ sent to {row['שם מלא']} ({chat_id})")
            time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ failed {chat_id}: {e}", file=sys.stderr)

    save_df(df)
    print("✔️ round finished")

# ───────── WEBHOOK SERVER ─────────
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if not data or "body" not in data:
        print("⚠️ Webhook missing 'body'")
        return jsonify({"status": "ignored"}), 200
    try:
        body = data["body"]
        if body.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"status": "ignored"})

        sender = body["senderData"]["chatId"]
        text   = body["messageData"]["textMessageData"]["textMessage"]
        decision = classify(text)

        df = load_df()
        mask = df["טלפון"].apply(il_to_chatid) == sender
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

# ───────── ENTRY POINT ─────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        send_round()
    else:
        port = int(os.getenv("PORT", 10000))
        app.run(host="0.0.0.0", port=port)
