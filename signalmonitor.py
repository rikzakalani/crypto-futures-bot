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

TF_LTF = "5m"
TF_HTF_1 = "15m"
TF_HTF_2 = "1h"

FETCH_LIMIT = 300

EMA_FAST = 150
EMA_SLOW = 200
EMA_EXTRA = 250

TOLERANCE_PCT = 0.001  # 0.1%

# 🔥 ACTIVE MARKET FILTER (WINRATE FILTER)
MIN_RANGE_PCT = 0.003
MIN_BODY_PCT  = 0.0015

# 🔥 EMA SLOPE FILTER (ANTI FLAT)
MIN_EMA_SLOPE = 0.0002   # 0.02%

TOP_N = 200
BATCH_SIZE = 50
TOTAL_BATCH = 4

DELAY_BETWEEN_BATCH = 30
DELAY_PER_SYMBOL = 1

DEBUG = False  # 🔧 TRUE kalau mau lihat log detail

# ================= EXCHANGE =================
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

# ================= SAFE FETCH =================
async def safe_fetch(symbol, tf):
    loop = asyncio.get_running_loop()
    for i in range(3):
        try:
            return await loop.run_in_executor(
                None,
                lambda: exchange.fetch_ohlcv(symbol, tf, limit=FETCH_LIMIT)
            )
        except Exception as e:
            log.warning(f"Fetch {symbol} {tf} retry {i+1}: {e}")
            await asyncio.sleep(2)
    return None

# ================= EMA =================
def calc_ema(df):
    df["ema150"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["ema250"] = df["close"].ewm(span=EMA_EXTRA, adjust=False).mean()
    return df

# ================= TREND & SLOPE =================
def ema_slope_ok(series):
    slope = (series.iloc[-2] - series.iloc[-5]) / series.iloc[-5]
    return abs(slope) >= MIN_EMA_SLOPE

# ================= HTF BIAS =================
async def get_htf_bias(symbol):
    df15 = await safe_fetch(symbol, TF_HTF_1)
    df1h = await safe_fetch(symbol, TF_HTF_2)

    if not df15 or not df1h:
        return None

    df15 = pd.DataFrame(df15, columns=["t","o","h","l","c","v"])
    df1h = pd.DataFrame(df1h, columns=["t","o","h","l","c","v"])

    df15["ema200"] = df15["c"].ewm(span=200, adjust=False).mean()
    df1h["ema200"] = df1h["c"].ewm(span=200, adjust=False).mean()

    c15 = df15.iloc[-2]
    c1h = df1h.iloc[-2]

    if c15.c > c15.ema200 and c1h.c > c1h.ema200:
        return "Bullish"
    if c15.c < c15.ema200 and c1h.c < c1h.ema200:
        return "Bearish"

    return None

# ================= TOP VOLUME =================
def get_top_volume_symbols(n):
    tickers = exchange.fetch_tickers()
    symbols = [
        (s, t["quoteVolume"])
        for s, t in tickers.items()
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume")
    ]
    symbols.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in symbols[:n]]

# ================= SCAN CORE =================
async def scan_batch(symbols, batch_no, stats):
    ema150, ema200, ema250 = [], [], []

    for idx, sym in enumerate(symbols, 1):
        log.info(f"[Batch {batch_no}] {sym} ({idx}/{len(symbols)})")

        htf_bias = await get_htf_bias(sym)
        if not htf_bias:
            stats["filtered"] += 1
            continue

        ohlcv = await safe_fetch(sym, TF_LTF)
        if not ohlcv:
            continue

        df = pd.DataFrame(
            ohlcv,
            columns=["time","open","high","low","close","volume"]
        )
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        if len(df) < EMA_EXTRA + 5:
            continue

        df = calc_ema(df)
        c = df.iloc[-2]
        tol = c.close * TOLERANCE_PCT

        # ACTIVE CANDLE FILTER
        range_pct = (c.high - c.low) / c.close
        body_pct = abs(c.close - c.open) / c.close

        if range_pct < MIN_RANGE_PCT or body_pct < MIN_BODY_PCT:
            stats["filtered"] += 1
            continue

        # EMA SLOPE FILTER
        if not ema_slope_ok(df["ema200"]):
            stats["filtered"] += 1
            continue

        trend = "Bullish 📈" if c.ema150 > c.ema200 else "Bearish 📉"

        # 🚫 NO COUNTERTREND
        if htf_bias not in trend:
            stats["filtered"] += 1
            continue

        stats["scanned"] += 1
        stats["bullish" if "Bullish" in trend else "bearish"] += 1

        base = sym.split("/")[0]

        if c.low - tol <= c.ema150 <= c.high + tol:
            ema150.append(f"{base} ({trend})")
            stats["ema150"] += 1

        if c.low - tol <= c.ema200 <= c.high + tol:
            ema200.append(f"{base} ({trend})")
            stats["ema200"] += 1

        if c.low - tol <= c.ema250 <= c.high + tol:
            ema250.append(f"{base} ({trend})")
            stats["ema250"] += 1

        if DEBUG:
            log.info(f"{sym} PASS | {trend} | HTF {htf_bias}")

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return ema150, ema200, ema250

# ================= COMMANDS =================
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("⛔ Scan masih berjalan")
        return

    context.application.bot_data["scanning"] = True
    await ensure_markets()

    stats = {
        "scanned": 0,
        "ema150": 0,
        "ema200": 0,
        "ema250": 0,
        "bullish": 0,
        "bearish": 0,
        "filtered": 0,
    }

    try:
        await update.message.reply_text(
            "🔍 *EMA TOUCH SCAN FINAL*\n"
            "• TF Entry : 5m\n"
            "• HTF Bias : 15m + 1h\n"
            "• Trend Only (NO Countertrend)\n"
            "• High Winrate Mode\n\n"
            "⏳ Scanning...",
            parse_mode="Markdown"
        )

        symbols = get_top_volume_symbols(TOP_N)
        batches = [symbols[i:i+BATCH_SIZE] for i in range(0, TOP_N, BATCH_SIZE)]

        ema150_all, ema200_all, ema250_all = [], [], []

        for i, batch in enumerate(batches, 1):
            e150, e200, e250 = await scan_batch(batch, i, stats)
            ema150_all += e150
            ema200_all += e200
            ema250_all += e250
            if i < TOTAL_BATCH:
                await asyncio.sleep(DELAY_BETWEEN_BATCH)

        msg = (
            "🔍 *EMA TOUCH SCANNER – FINAL*\n\n"
            "━━━━━━━━━━━━━━\n"
            "📈 *EMA150*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema150_all))) if ema150_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📉 *EMA200*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema200_all))) if ema200_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "🟣 *EMA250*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema250_all))) if ema250_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📊 *STAT*\n"
            f"• Scanned  : {stats['scanned']}\n"
            f"• Filtered : {stats['filtered']}\n"
            f"• Bullish  : {stats['bullish']}\n"
            f"• Bearish  : {stats['bearish']}\n"
            f"\n🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )

        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        context.application.bot_data["scanning"] = False

# ================= INIT =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("scan", scan))
    log.info("EMA TOUCH SCANNER FINAL RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
