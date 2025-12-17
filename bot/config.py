import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET = os.getenv("TARGET")

# === SCANNER CONFIG ===
TOP_N = 10
SEND_DELAY = 3
LIMIT = 200
MIN_MOVE_PCT = 3

TF_MAP = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400
}

# === SIGNAL CONFIG ===
SIGNAL_TF = "15m"
SIGNAL_INTERVAL = 900
SIGNAL_COOLDOWN = 900

if not BOT_TOKEN or not TARGET:
    raise ValueError("BOT_TOKEN atau TARGET belum diset")
