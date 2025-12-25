import ccxt
import pandas as pd
import time
import os
import asyncio
import logging
import math

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")

TIMEFRAMES = ["5m", "15m", "1h", "1d"]
FETCH_LIMIT = 50

TOP_N = 400
BATCH_COUNT = 6
SLEEP_PER_SYMBOL = 0.12
DELAY_BETWEEN_BATCH = 5  # seconds

# Stochastic settings
STO_K = 5
STO_D = 3
STO_SMOOTH = 3

OVERBOUGHT = 83
OVERSOLD = 10

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("STOCH-OB-OS-BOT")

# ================= EXCHANGE =================
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

MARKETS_LOADED = False

# ================= INIT =================
async def ensure_markets():
    global MARKETS_LOADED
    if not MARKETS_LOADED:
        log.info("Loading markets...")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, exchange.load_markets)
        MARKETS_LOADED = True
        log.info("Markets loaded")

# ================= INDICATOR =================
def calc_stochastic(df, k_period=5, d_period=3, smooth=3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()

    df["%K_raw"] = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%K"] = df["%K_raw"].rolling(smooth).mean()
    df["%D"] = df["%K"].rolling(d_period).mean()

    return df

def stochastic_overbought(df):
    if len(df) < 20:
        return False

    k2 = df["%K"].iloc[-2]  # last closed candle
    d2 = df["%D"].iloc[-2]
    k3 = df["%K"].iloc[-3]

    if pd.isna(k2) or pd.isna(d2) or pd.isna(k3):
        return False

    return (
        k2 > OVERBOUGHT and
        d2 > OVERBOUGHT and
        k2 < k3  # momentum mulai melemah
    )

def stochastic_oversold(df):
    if len(df) < 20:
        return False

    k2 = df["%K"].iloc[-2]
    d2 = df["%D"].iloc[-2]
    k3 = df["%K"].iloc[-3]

    if pd.isna(k2) or pd.isna(d2) or pd.isna(k3):
        return False

    return (
        k2 < OVERSOLD and
        d2 < OVERSOLD and
        k2 > k3  # momentum mulai menguat
    )

# ================= FETCH =================
def get_top_symbols(n):
    log.info("Fetching tickers...")
    tickers = exchange.fetch_tickers()
    pairs = []

    for s, t in tickers.items():
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume"):
            pairs.append((s, t["quoteVolume"]))

    pairs.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in pairs[:n]]

    log.info(f"Selected TOP {len(symbols)} symbols")
    return symbols

def fetch_df(symbol, tf):
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=FETCH_LIMIT)
    return pd.DataFrame(
        ohlcv,
        columns=["time", "open", "high", "low", "close", "volume"]
    )

# ================= SCANNER =================
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_markets()

    start_time = time.time()

    await update.message.reply_text(
        "🔍 *STOCHASTIC SCANNER*\n"
        "KDJ (5,3,3)\n"
        "🔴 OB > 83 | 🟢 OS < 10\n\n"
        "📦 TOP 400 coins · Multi TF\n"
        "⏳ Please wait...",
        parse_mode="Markdown"
    )

    symbols = get_top_symbols(TOP_N)
    batch_size = math.ceil(len(symbols) / BATCH_COUNT)
    batches = [
        symbols[i:i + batch_size]
        for i in range(0, len(symbols), batch_size)
    ]

    results = {
        "overbought": {tf: [] for tf in TIMEFRAMES},
        "oversold":   {tf: [] for tf in TIMEFRAMES}
    }

    for bi, batch in enumerate(batches, 1):
        log.info(f"===== BATCH {bi}/{len(batches)} START =====")

        for sym in batch:
            base = sym.split("/")[0]

            for tf in TIMEFRAMES:
                try:
                    df = fetch_df(sym, tf)
                    df = calc_stochastic(df, STO_K, STO_D, STO_SMOOTH)

                    if stochastic_overbought(df):
                        results["overbought"][tf].append(base)
                        log.info(f"🔴 OB {base} @ {tf}")

                    if stochastic_oversold(df):
                        results["oversold"][tf].append(base)
                        log.info(f"🟢 OS {base} @ {tf}")

                except Exception as e:
                    log.warning(f"Error {base} {tf}: {e}")

            await asyncio.sleep(SLEEP_PER_SYMBOL)

        await update.message.reply_text(f"✅ Batch {bi}/{len(batches)} selesai")

        if bi < len(batches):
            await asyncio.sleep(DELAY_BETWEEN_BATCH)

    elapsed = int(time.time() - start_time)

    # ================= OUTPUT =================
    msg = "📊 *STOCHASTIC SCANNER RESULT*\n"
    msg += "KDJ (5,3,3)\n\n"

    found = False

    for tf in TIMEFRAMES:
        ob = results["overbought"][tf]
        os_ = results["oversold"][tf]

        if not ob and not os_:
            continue

        found = True
        msg += f"⏱ *TF {tf}*\n"

        if ob:
            msg += "🔴 Overbought:\n"
            msg += ", ".join(ob[:20]) + "\n"

        if os_:
            msg += "🟢 Oversold:\n"
            msg += ", ".join(os_[:20]) + "\n"

        msg += "\n"

    if not found:
        await update.message.reply_text("❌ Tidak ada signal OB / OS ditemukan")
        return

    msg += (
        "Note:\n"
        "- Overbought → potensi pullback / rejection\n"
        "- Oversold → potensi pullback / bounce\n"
        f"⏱ Scan time: {elapsed//60}m {elapsed%60}s"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= MAIN =================
def main():
    log.info("Starting STOCHASTIC OB / OS Scanner Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("scan", scan))
    log.info("Bot is running. Use /scan in Telegram")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
