# =================================================
# EMA TOUCH SCANNER BOT - MEXC PRO FIX FINAL
# Mode     : MANUAL SCANNER
# TF       : 5m
# Volume   : TOP 100 (Batch 50 + Delay)
# =================================================

import ccxt
import pandas as pd
import asyncio
import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from datetime import datetime, timezone

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scanner.log", encoding="utf-8")
    ]
)
log = logging.getLogger("EMA-SCANNER")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET = int(os.getenv("TARGET", "0"))

if not BOT_TOKEN or TARGET == 0:
    log.error("BOT_TOKEN / TARGET belum diset")
    exit(1)

TF = "5m"
FETCH_LIMIT = 300

EMA_FAST = 150
EMA_SLOW = 200
EMA_SMOOTH = 9
TOLERANCE_PCT = 0.0003

TOP_N = 100
BATCH_SIZE = 50
DELAY_BETWEEN_BATCH = 30   # detik
DELAY_PER_SYMBOL = 1       # detik

# ================= EXCHANGE ===============
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})
exchange.load_markets()

# ================= SAFE FETCH =============
async def safe_fetch(symbol):
    loop = asyncio.get_running_loop()
    for i in range(3):
        try:
            return await loop.run_in_executor(
                None,
                lambda: exchange.fetch_ohlcv(symbol, TF, limit=FETCH_LIMIT)
            )
        except Exception as e:
            log.warning(f"Fetch {symbol} retry {i+1}: {e}")
            await asyncio.sleep(2)
    return None

# ================= EMA ====================
def mexc_ema(series, length, smooth):
    ema = series.ewm(span=length, adjust=False).mean()
    return ema.rolling(smooth).mean()

def calc_ema(df):
    df["ema150"] = mexc_ema(df["close"], EMA_FAST, EMA_SMOOTH)
    df["ema200"] = mexc_ema(df["close"], EMA_SLOW, EMA_SMOOTH)
    return df

# ================= TOP VOLUME =============
def get_top_volume_symbols(n):
    tickers = exchange.fetch_tickers()
    sorted_symbols = sorted(
        tickers.items(),
        key=lambda x: x[1]["quoteVolume"] or 0,
        reverse=True
    )
    return [
        s for s, _ in sorted_symbols
        if s.endswith("/USDT:USDT")
        and exchange.markets[s].get("swap")
    ][:n]

# ================= SCAN CORE ==============
async def scan_batch(symbols, batch_no):
    ema150, ema200 = [], []

    for idx, sym in enumerate(symbols, 1):
        log.info(f"[Batch {batch_no}] Scanning {sym} ({idx}/{len(symbols)})")

        ohlcv = await safe_fetch(sym)
        if not ohlcv:
            continue

        df = pd.DataFrame(
            ohlcv,
            columns=["time","open","high","low","close","volume"]
        )
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        if len(df) < EMA_SLOW + EMA_SMOOTH + 2:
            continue

        df = calc_ema(df)
        c = df.iloc[-2]  # CLOSED candle

        tol = c.close * TOLERANCE_PCT
        base = sym.split("/")[0]

        if abs(c.low - c.ema150) <= tol or abs(c.high - c.ema150) <= tol:
            ema150.append(base)

        if abs(c.low - c.ema200) <= tol or abs(c.high - c.ema200) <= tol:
            ema200.append(base)

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return ema150, ema200

# ================= COMMANDS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 EMA TOUCH SCANNER (MEXC)\n\n"
        "/scan   → Scan TOP 100 (batch 50)\n"
        "/status → Bot status"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 Bot aktif\n"
        "Mode: Scanner\n"
        "TF: 5m\n"
        "EMA: 150 / 200\n"
        "Top Volume: 100 (batch 50)"
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Scan TOP 100 Volume dimulai...")

    symbols = get_top_volume_symbols(TOP_N)

    batch1 = symbols[:BATCH_SIZE]
    batch2 = symbols[BATCH_SIZE:TOP_N]

    ema150_1, ema200_1 = await scan_batch(batch1, 1)

    await update.message.reply_text("⏳ Batch 1 selesai, lanjut Batch 2...")
    await asyncio.sleep(DELAY_BETWEEN_BATCH)

    ema150_2, ema200_2 = await scan_batch(batch2, 2)

    ema150 = sorted(set(ema150_1 + ema150_2))
    ema200 = sorted(set(ema200_1 + ema200_2))

    msg = (
        "🔍 *EMA TOUCH SCANNER – TOP 100*\n"
        f"TF: {TF}\n\n"
        "✅ *EMA150 TOUCH:*\n"
        + ("\n".join(ema150) if ema150 else "- None") +
        "\n\n✅ *EMA200 TOUCH:*\n"
        + ("\n".join(ema200) if ema200 else "- None") +
        f"\n\n⏱ {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= INIT ===================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan))

    log.info("EMA TOUCH SCANNER TOP100 RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
