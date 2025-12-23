# =================================================
# EMA TOUCH SCANNER BOT - MEXC PRO (FIXED & CLEAN)
# Mode     : MANUAL SCANNER
# TF       : 5m
# Volume   : TOP 200
# =================================================

import ccxt
import pandas as pd
import asyncio
import os
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime, timezone

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("EMA-SCANNER")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")

TF = "5m"
FETCH_LIMIT = 300

EMA_FAST  = 150
EMA_MID   = 200
EMA_SLOW  = 250

TOLERANCE_PCT = 0.0005  # buffer kecil (0.05%)

MIN_RANGE_PCT = 0.003
MIN_BODY_PCT  = 0.0015

TOP_N = 200
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
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, exchange.load_markets)
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
            log.warning(f"{symbol} retry {i+1}: {e}")
            await asyncio.sleep(2)
    return None

# ================= EMA ====================
def calc_ema(df):
    df["ema150"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=EMA_MID, adjust=False).mean()
    df["ema250"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df

# ================= TOP VOLUME =============
def get_top_volume_symbols(n):
    tickers = exchange.fetch_tickers()
    symbols = [
        (s, t["quoteVolume"])
        for s, t in tickers.items()
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume")
    ]
    symbols.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in symbols[:n]]

# ================= SCAN CORE ==============
async def scan_batch(symbols, batch_no, stats):
    result = {
        "ema150": {"bull": [], "bear": []},
        "ema200": {"bull": [], "bear": []},
        "ema250": {"bull": [], "bear": []},
    }

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
        c = df.iloc[-2]

        # ===== Candle Filter =====
        range_pct = (c.high - c.low) / c.close
        body_pct  = abs(c.close - c.open) / c.close

        if range_pct < MIN_RANGE_PCT or body_pct < MIN_BODY_PCT:
            stats["filtered"] += 1
            continue

        # ===== EMA ALIGNMENT =====
        bullish = c.ema150 > c.ema200 > c.ema250
        bearish = c.ema150 < c.ema200 < c.ema250

        if not bullish and not bearish:
            continue

        stats["scanned"] += 1
        trend = "bull" if bullish else "bear"
        stats["bullish" if bullish else "bearish"] += 1

        tol = c.close * TOLERANCE_PCT
        base = sym.split("/")[0]

        def touched(ema):
            return c.low - tol <= ema <= c.high + tol

        if touched(c.ema150):
            result["ema150"][trend].append(base)
            stats["ema150"] += 1

        if touched(c.ema200):
            result["ema200"][trend].append(base)
            stats["ema200"] += 1

        if touched(c.ema250):
            result["ema250"][trend].append(base)
            stats["ema250"] += 1

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return result

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *EMA Touch Scanner Bot*\n\n"
        "• MEXC Futures\n"
        "• TF 5m\n"
        "• EMA150 / 200 / 250\n"
        "• EMA Harus Sejajar\n\n"
        "Gunakan /scan",
        parse_mode="Markdown"
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("⛔ Scan sedang berjalan")
        return

    context.application.bot_data["scanning"] = True
    await ensure_markets()

    stats = dict.fromkeys(
        ["scanned","ema150","ema200","ema250","bullish","bearish","filtered"], 0
    )

    try:
        await update.message.reply_text("🔍 *Scan Dimulai...*", parse_mode="Markdown")

        symbols = get_top_volume_symbols(TOP_N)
        batches = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]

        final = {
            "ema150": {"bull": set(), "bear": set()},
            "ema200": {"bull": set(), "bear": set()},
            "ema250": {"bull": set(), "bear": set()},
        }

        for i, batch in enumerate(batches, 1):
            res = await scan_batch(batch, i, stats)
            for ema in final:
                for t in final[ema]:
                    final[ema][t].update(res[ema][t])
            await asyncio.sleep(DELAY_BETWEEN_BATCH)

        def block(title, data):
            return f"*{title}*\n" + ("\n".join(sorted(data)) if data else "- None")

        msg = (
            "🔍 *EMA TOUCH RESULT*\n\n"
            f"📈 *BULLISH*\n"
            f"{block('EMA150', final['ema150']['bull'])}\n\n"
            f"{block('EMA200', final['ema200']['bull'])}\n\n"
            f"{block('EMA250', final['ema250']['bull'])}\n\n"
            f"📉 *BEARISH*\n"
            f"{block('EMA150', final['ema150']['bear'])}\n\n"
            f"{block('EMA200', final['ema200']['bear'])}\n\n"
            f"{block('EMA250', final['ema250']['bear'])}\n\n"
            "━━━━━━━━━━━━━━\n"
            f"Scanned : {stats['scanned']}\n"
            f"Filtered: {stats['filtered']}\n"
            f"Bullish : {stats['bullish']}\n"
            f"Bearish : {stats['bearish']}\n\n"
            f"🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )

        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        context.application.bot_data["scanning"] = False

# ================= INIT ===================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    log.info("EMA TOUCH SCANNER BOT RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
