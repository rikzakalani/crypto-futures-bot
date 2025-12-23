# =================================================
# EMA TOUCH SCANNER BOT - MEXC PRO (UX FRIENDLY)
# Mode     : MANUAL SCANNER
# TF       : 5m
# Volume   : TOP 200 (4 Batch)
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

EMA_FAST = 150
EMA_SLOW = 200
EMA_EXTRA = 250   # ✅ EMA250

TOLERANCE_PCT = 0.001  # 0.1%

# 🔥 FILTER KOIN YANG BERGERAK
MIN_RANGE_PCT = 0.003   # 0.3% candle range
MIN_BODY_PCT  = 0.0015  # 0.15% candle body

TOP_N = 200
BATCH_SIZE = 50
TOTAL_BATCH = 4

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
    df["ema250"] = df["close"].ewm(span=EMA_EXTRA, adjust=False).mean()
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
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume"):
            symbols.append((s, t["quoteVolume"]))

    symbols.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in symbols[:n]]

# ================= SCAN CORE ==============
async def scan_batch(symbols, batch_no, stats):
    ema150, ema200, ema250 = [], [], []

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

        if len(df) < EMA_EXTRA + 2:
            continue

        df = calc_ema(df)
        c = df.iloc[-2]
        tol = c.close * TOLERANCE_PCT

        # 🔥 FILTER KOIN YANG BERGERAK
        range_pct = (c.high - c.low) / c.close
        body_pct = abs(c.close - c.open) / c.close

        if range_pct < MIN_RANGE_PCT or body_pct < MIN_BODY_PCT:
            stats["filtered"] += 1
            continue

        trend = "Bullish 📈" if c.ema150 > c.ema200 else "Bearish 📉"
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

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return ema150, ema200, ema250

# ================= COMMANDS UX =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Selamat datang di EMA Touch Scanner Bot*\n\n"
        "📌 Fitur:\n"
        "• Scan Futures MEXC\n"
        "• TF 5 Menit\n"
        "• EMA150 / EMA200 / EMA250 Touch\n"
        "• Filter koin aktif\n"
        "• TOP 200 Volume\n\n"
        "📊 Cocok untuk Scalping & Pullback\n\n"
        "Ketik /help untuk panduan"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📘 *PANDUAN BOT*\n\n"
        "🔹 /scan → Mulai scan EMA Touch\n"
        "🔹 /status → Status bot\n\n"
        "📈 TREND:\n"
        "Bullish → EMA150 > EMA200\n"
        "Bearish → EMA150 < EMA200\n\n"
        "⚠️ Gunakan money management"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("🔄 Status: Scan sedang berjalan")
    else:
        await update.message.reply_text("✅ Status: Bot standby")

# ================= SCAN COMMAND =================
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("⛔ Scan masih berjalan, mohon tunggu...")
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
            "🔍 *EMA TOUCH SCAN DIMULAI*\n\n"
            "• Exchange : MEXC Futures\n"
            "• TF       : 5m\n"
            "• EMA      : 150 / 200 / 250\n"
            "• Volume   : TOP 200\n\n"
            "⏳ Mohon tunggu...",
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
            "🔍 *EMA TOUCH SCANNER – TOP 200*\n"
            f"⏱ TF : {TF}\n\n"
            "━━━━━━━━━━━━━━\n"
            "📈 *EMA150 TOUCH*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema150_all))) if ema150_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📉 *EMA200 TOUCH*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema200_all))) if ema200_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "🟣 *EMA250 TOUCH*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(ema250_all))) if ema250_all else "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📊 *STATISTIK SCAN*\n"
            "━━━━━━━━━━━━━━\n"
            f"• Total Scanned : {stats['scanned']}\n"
            f"• EMA150 Touch : {stats['ema150']}\n"
            f"• EMA200 Touch : {stats['ema200']}\n"
            f"• EMA250 Touch : {stats['ema250']}\n"
            f"• Filtered     : {stats['filtered']}\n"
            f"• Bullish      : {stats['bullish']}\n"
            f"• Bearish      : {stats['bearish']}\n"
            f"\n🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )

        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        context.application.bot_data["scanning"] = False

# ================= INIT ===================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan))

    log.info("EMA TOUCH SCANNER BOT RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
