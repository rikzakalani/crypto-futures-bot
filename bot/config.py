import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET = os.getenv("TARGET")

if not BOT_TOKEN or not TARGET:
    raise RuntimeError("BOT_TOKEN atau TARGET belum diset")

# === GLOBAL ===
LIMIT = 200
SEND_DELAY = 5   # aman untuk VPS kecil

# === SCANNER ===
TOP_N = 5
MIN_MOVE_PCT = 3

TF_MAP = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400
}

# === SIGNAL ===
TF_SIGNAL = "15m"
SIGNAL_COOLDOWN = 900
