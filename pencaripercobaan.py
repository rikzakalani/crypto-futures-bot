# =================================================
# EMA TOUCH SCANNER BOT - MEXC PRO (FIX FINAL)
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
)
log = logging.getLogger("EMA-SCANNER")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET = int(os.getenv("TARGET", "0"))

TF = "5m"
FETCH_LIMIT = 300

EMA_FAST = 150
EMA_SLOW = 200
TOLERANCE_PCT = 0.001  # ✅ 0.1% (ideal scalping)

TOP_N = 100
BATCH_SIZE = 50
DELAY_BETWEEN_BATCH = 30
DELAY_PER_SYMBOL = 1

# ================= EXCHANGE ===============
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

MARKETS_LOADED = False

async def ensure_markets():
    global MARKETS_LOADED
    if not MARKETS_LOADED:
        await asyncio.get_running_loop().run_in_executor(
            None, exchange.load_markets
        )
        MARKETS_LOADED = True

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
def calc_ema(df):
    df["ema150"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df

# ================= TOP VOLUME =============
def get_top_volume_symbols(n):
    try:
        tickers = exchange.fetch_tickers()
    except Exception as e:
        log.error(f"fetch_tickers error: {e}")
        return []

    symbols = []
    for s, t in tickers.items():
        if (
            s.endswith("/USDT:USDT")
            and t
            and t.get("quoteVolume")
        ):
            symbols.append((s, t["quoteVolume"]))

    symbols.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in symbols[:n]]

# ================= SCAN CORE ==============
async def scan_batch(symbols, batch_no):
    ema150, ema200 = [], []

    for idx, sym in enumerate(symbols, 1):
        log.info(f"[Batch {batch_no}] {sym} ({idx}/{len(symbols)})")

        ohlcv = await safe_fetch(sym)
        if not ohlcv:
            continue

        df = pd.DataFrame(
            ohlcv,
            columns=["time","open","high","low","close","volume"]
        )
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        if len(df) < EMA_SLOW + 2:
            continue

        df = calc_ema(df)
        c = df.iloc[-2]  # closed candle
        tol = c.close * TOLERANCE_PCT
        base = sym.split("/")[0]

        if c.low - tol <= c.ema150 <= c.high + tol:
            ema150.append(base)

        if c.low - tol <= c.ema200 <= c.high + tol:
            ema200.append(base)

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return ema150, ema200

# ================= COMMANDS ===============
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("⛔ Scan masih berjalan...")
        return

    context.application.bot_data["scanning"] = True
    await ensure_markets()

    try:
        await update.message.reply_text("🔍 Scan TOP 100 dimulai...")

        symbols = get_top_volume_symbols(TOP_N)
        batch1 = symbols[:BATCH_SIZE]
        batch2 = symbols[BATCH_SIZE:]

        ema150_1, ema200_1 = await scan_batch(batch1, 1)
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

    finally:
        context.application.bot_data["scanning"] = False

# ================= INIT ===================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("scan", scan))
    log.info("EMA TOUCH SCANNER RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
