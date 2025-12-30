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

TOP_N = 250
BATCH_COUNT = 5
SLEEP_PER_SYMBOL = 0.1
DELAY_BETWEEN_BATCH = 4

# Stochastic
STO_K = 5
STO_D = 3
STO_SMOOTH = 3
OVERBOUGHT = 83
OVERSOLD = 10

# Auto scan
AUTO_INTERVAL = 10 * 60  # 10 menit
AUTO_SCAN = False
AUTO_TASK = None
CHAT_ID = None

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("STOCH-SCANNER")

# ================= EXCHANGE =================
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

MARKETS_LOADED = False

# ================= ASYNC CCXT =================
async def run_ccxt(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

# ================= INIT =================
async def ensure_markets():
    global MARKETS_LOADED
    if not MARKETS_LOADED:
        log.info("Loading markets...")
        await run_ccxt(exchange.load_markets)
        MARKETS_LOADED = True
        log.info("Markets loaded")

# ================= INDICATOR =================
def calc_stochastic(df):
    low_min = df["low"].rolling(STO_K).min()
    high_max = df["high"].rolling(STO_K).max()
    rng = (high_max - low_min).replace(0, pd.NA)

    df["%K"] = 100 * (df["close"] - low_min) / rng
    df["%K"] = df["%K"].rolling(STO_SMOOTH).mean()
    df["%D"] = df["%K"].rolling(STO_D).mean()
    return df

def is_overbought(df):
    k2, d2, k3 = df["%K"].iloc[-2], df["%D"].iloc[-2], df["%K"].iloc[-3]
    return k2 > OVERBOUGHT and d2 > OVERBOUGHT and k2 < k3

def is_oversold(df):
    k2, d2, k3 = df["%K"].iloc[-2], df["%D"].iloc[-2], df["%K"].iloc[-3]
    return k2 < OVERSOLD and d2 < OVERSOLD and k2 > k3

# ================= DATA =================
async def get_top_symbols(n):
    log.info("Fetching tickers...")
    tickers = await run_ccxt(exchange.fetch_tickers)

    pairs = [
        (s, t["quoteVolume"])
        for s, t in tickers.items()
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume")
    ]

    pairs.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in pairs[:n]]

    log.info(f"TOP {len(symbols)} symbols selected")
    return symbols

async def fetch_df(symbol, tf):
    ohlcv = await run_ccxt(exchange.fetch_ohlcv, symbol, tf, None, FETCH_LIMIT)
    return pd.DataFrame(
        ohlcv, columns=["time", "open", "high", "low", "close", "volume"]
    )

# ================= SCAN CORE =================
async def run_scan(app, chat_id):
    await ensure_markets()
    start = time.time()

    status = await app.bot.send_message(
        chat_id,
        "🔍 *STOCHASTIC SCANNER*\n\n"
        "⏳ Initializing...",
        parse_mode="Markdown"
    )

    symbols = await get_top_symbols(TOP_N)
    batch_size = math.ceil(len(symbols) / BATCH_COUNT)
    batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]

    results = {tf: {"OB": set(), "OS": set()} for tf in TIMEFRAMES}

    for i, batch in enumerate(batches, 1):
        log.info(f"BATCH {i}/{len(batches)}")

        for sym in batch:
            base = sym.split("/")[0]

            for tf in TIMEFRAMES:
                try:
                    df = await fetch_df(sym, tf)
                    df = calc_stochastic(df)

                    if is_overbought(df):
                        results[tf]["OB"].add(base)
                        log.info(f"🔴 OB {base} {tf}")

                    if is_oversold(df):
                        results[tf]["OS"].add(base)
                        log.info(f"🟢 OS {base} {tf}")

                except Exception as e:
                    log.warning(f"{base} {tf} error: {e}")

            await asyncio.sleep(SLEEP_PER_SYMBOL)

        progress = int((i / len(batches)) * 100)
        await status.edit_text(
            f"🔍 *STOCHASTIC SCANNER*\n\n"
            f"📦 TOP {TOP_N}\n"
            f"⏱ TF: {', '.join(TIMEFRAMES)}\n\n"
            f"Progress: {progress}%",
            parse_mode="Markdown"
        )

        if i < len(batches):
            await asyncio.sleep(DELAY_BETWEEN_BATCH)

    elapsed = int(time.time() - start)

    # ================= OUTPUT =================
    msg = "📊 *SCAN RESULT*\n\n"
    found = False

    for tf in TIMEFRAMES:
        ob = list(results[tf]["OB"])
        os_ = list(results[tf]["OS"])

        if not ob and not os_:
            continue

        found = True
        msg += f"⏱ *{tf}*\n"

        if ob:
            msg += "🔴 OB: " + ", ".join(ob[:20]) + "\n"
        if os_:
            msg += "🟢 OS: " + ", ".join(os_[:20]) + "\n"

        msg += "\n"

    if not found:
        msg += "❌ Tidak ada signal ditemukan\n\n"

    msg += f"⏱ Scan time: {elapsed//60}m {elapsed%60}s"

    await app.bot.send_message(chat_id, msg, parse_mode="Markdown")

# ================= COMMANDS =================
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await run_scan(context.application, CHAT_ID)

async def auto_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_SCAN, AUTO_TASK, CHAT_ID

    CHAT_ID = update.effective_chat.id

    if AUTO_SCAN:
        await update.message.reply_text("⚠️ Auto scan sudah aktif")
        return

    AUTO_SCAN = True

    async def loop():
        while AUTO_SCAN:
            log.info("AUTO SCAN RUN")
            await run_scan(context.application, CHAT_ID)
            await asyncio.sleep(AUTO_INTERVAL)

    AUTO_TASK = asyncio.create_task(loop())
    await update.message.reply_text("✅ Auto scan ON (setiap 10 menit)")

async def auto_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_SCAN, AUTO_TASK

    AUTO_SCAN = False
    if AUTO_TASK:
        AUTO_TASK.cancel()
        AUTO_TASK = None

    await update.message.reply_text("⛔ Auto scan OFF")

# ================= MAIN =================
def main():
    log.info("Starting STOCHASTIC SCANNER BOT")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("auto_on", auto_on))
    app.add_handler(CommandHandler("auto_off", auto_off))

    log.info("Bot ready. Commands: /scan /auto_on /auto_off")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
