# =================================================
# EMA TOUCH SCANNER BOT - MEXC PRO
# FINAL CLEAR OUTPUT VERSION
# =================================================

import ccxt
import pandas as pd
import asyncio
import os
import logging
import time

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
EMA_EXTRA = 250

TOLERANCE_PCT = 0.001  # 0.1%

# NORMAL FILTER
MIN_RANGE_PCT = 0.003
MIN_BODY_PCT = 0.0015

# STRICT FILTER
STRICT_RANGE_PCT = 0.006
STRICT_BODY_PCT = 0.003
STRICT_EMA_GAP = 0.002

TOP_N = 200
BATCH_SIZE = 50
TOTAL_BATCH = 4

DELAY_PER_SYMBOL = 0.5
DELAY_BETWEEN_BATCH = 10

# ================= EXCHANGE =================
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

MARKETS_LOADED = False

# ================= INIT MARKET =================
async def ensure_markets():
    global MARKETS_LOADED
    if not MARKETS_LOADED:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, exchange.load_markets)
        MARKETS_LOADED = True
        log.info("[INIT] Markets loaded")

# ================= SAFE FETCH =================
async def safe_fetch(symbol):
    loop = asyncio.get_running_loop()
    for i in range(3):
        try:
            return await loop.run_in_executor(
                None,
                lambda: exchange.fetch_ohlcv(symbol, TF, limit=FETCH_LIMIT)
            )
        except Exception as e:
            log.warning(f"[FETCH RETRY {i+1}] {symbol} | {e}")
            await asyncio.sleep(2)
    log.error(f"[FETCH FAILED] {symbol}")
    return None

# ================= EMA =================
def calc_ema(df):
    df["ema150"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["ema250"] = df["close"].ewm(span=EMA_EXTRA, adjust=False).mean()
    return df

# ================= TOP VOLUME =================
def get_top_volume_symbols(n):
    tickers = exchange.fetch_tickers()
    symbols = []
    for s, t in tickers.items():
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume"):
            symbols.append((s, t["quoteVolume"]))
    symbols.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in symbols[:n]]

# ================= SCAN CORE =================
async def scan_batch(symbols, batch_no, stats, strict=False):
    results = {"ema150": [], "ema200": [], "ema250": []}

    for idx, sym in enumerate(symbols, 1):
        base = sym.split("/")[0]
        log.info(f"[SCAN] Batch {batch_no}/{TOTAL_BATCH} | {base} ({idx}/{len(symbols)})")

        ohlcv = await safe_fetch(sym)
        if not ohlcv:
            continue

        df = pd.DataFrame(
            ohlcv,
            columns=["time","open","high","low","close","volume"]
        )
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df.set_index("time", inplace=True)

        if len(df) < EMA_EXTRA + 5:
            log.info(f"[SKIP] {base} | data kurang")
            continue

        df = calc_ema(df)
        c = df.iloc[-2]

        range_pct = (c.high - c.low) / c.close
        body_pct = abs(c.close - c.open) / c.close
        ema_gap = abs(c.ema150 - c.ema200) / c.close

        # ===== FILTER =====
        if strict:
            if range_pct < STRICT_RANGE_PCT:
                stats["filtered"] += 1
                log.info(f"[FILTER] {base} | range kecil (STRICT)")
                continue
            if body_pct < STRICT_BODY_PCT:
                stats["filtered"] += 1
                log.info(f"[FILTER] {base} | body kecil (STRICT)")
                continue
            if ema_gap < STRICT_EMA_GAP:
                stats["filtered"] += 1
                log.info(f"[FILTER] {base} | EMA tidak sejajar")
                continue
        else:
            if range_pct < MIN_RANGE_PCT or body_pct < MIN_BODY_PCT:
                stats["filtered"] += 1
                log.info(f"[FILTER] {base} | candle lemah")
                continue

        stats["scanned"] += 1

        trend = "Bullish 📈" if c.ema150 > c.ema200 else "Bearish 📉"
        stats["bullish" if "Bullish" in trend else "bearish"] += 1

        tol = c.close * TOLERANCE_PCT
        touched = False

        if c.low - tol <= c.ema150 <= c.high + tol:
            results["ema150"].append(f"{base} ({trend})")
            stats["ema150"] += 1
            touched = True

        if c.low - tol <= c.ema200 <= c.high + tol:
            results["ema200"].append(f"{base} ({trend})")
            stats["ema200"] += 1
            touched = True

        if c.low - tol <= c.ema250 <= c.high + tol:
            results["ema250"].append(f"{base} ({trend})")
            stats["ema250"] += 1
            touched = True

        log.info(f"[RESULT] {base} | {trend} | {'TOUCH' if touched else 'NO TOUCH'}")

        await asyncio.sleep(DELAY_PER_SYMBOL)

    return results

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *EMA TOUCH SCANNER BOT*\n\n"
        "Commands:\n"
        "• /scan → Normal mode\n"
        "• /scan_strict → Strict only\n"
        "• /status → Bot status",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text("⏳ Scan sedang berjalan")
    else:
        await update.message.reply_text("✅ Bot standby")

# ================= RUN SCAN =================
async def run_scan(update, context, strict=False):
    if context.application.bot_data.get("scanning"):
        await update.message.reply_text(
            "⛔ Scan masih berjalan\nMohon tunggu sampai selesai ⏳"
        )
        return

    context.application.bot_data["scanning"] = True
    await ensure_markets()

    mode = "STRICT ONLY" if strict else "NORMAL"
    start_time = time.time()

    await update.message.reply_text(
        f"🔍 *SCAN DIMULAI*\n\n"
        f"Mode : {mode}\n"
        f"TF   : {TF}\n"
        f"Pair : TOP {TOP_N}\n"
        f"Estimasi : ±8–12 menit\n\n"
        "⏳ Bot sedang bekerja...",
        parse_mode="Markdown"
    )

    log.info(f"[SCAN START] Mode={mode}")

    stats = {
        "scanned": 0,
        "filtered": 0,
        "ema150": 0,
        "ema200": 0,
        "ema250": 0,
        "bullish": 0,
        "bearish": 0,
    }

    symbols = get_top_volume_symbols(TOP_N)
    batches = [symbols[i:i+BATCH_SIZE] for i in range(0, TOP_N, BATCH_SIZE)]

    all_results = {"ema150": [], "ema200": [], "ema250": []}

    try:
        for i, batch in enumerate(batches, 1):
            batch_result = await scan_batch(batch, i, stats, strict)

            for k in all_results:
                all_results[k] += batch_result[k]

            await update.message.reply_text(
                f"🔄 Progress Scan\nBatch {i}/{TOTAL_BATCH} selesai"
            )

            log.info(f"[BATCH DONE] {i}/{TOTAL_BATCH}")
            await asyncio.sleep(DELAY_BETWEEN_BATCH)

        elapsed = int(time.time() - start_time)

        if not any(all_results.values()):
            await update.message.reply_text(
                "🚫 *TIDAK ADA SIGNAL*\n\n"
                f"Mode : {mode}\n"
                "Market tidak memenuhi kriteria ketat.\n"
                "Tidak entry = good risk management ✅",
                parse_mode="Markdown"
            )
            return

        msg = (
            f"🔍 *HASIL SCAN ({mode})*\n\n"
            "━━━━━━━━━━━━━━\n"
            "📈 *EMA150*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(all_results["ema150"]))) or "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📉 *EMA200*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(all_results["ema200"]))) or "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "🟣 *EMA250*\n"
            "━━━━━━━━━━━━━━\n"
            + ("\n".join(sorted(set(all_results["ema250"]))) or "- None") +
            "\n\n━━━━━━━━━━━━━━\n"
            "📊 *STAT*\n"
            "━━━━━━━━━━━━━━\n"
            f"Scanned  : {stats['scanned']}\n"
            f"Filtered : {stats['filtered']}\n"
            f"Bullish  : {stats['bullish']}\n"
            f"Bearish  : {stats['bearish']}\n"
            f"Time     : {elapsed//60}m {elapsed%60}s\n\n"
            f"🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )

        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        context.application.bot_data["scanning"] = False
        log.info("[SCAN FINISHED]")

# ================= COMMAND BINDING =================
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_scan(update, context, strict=False)

async def scan_strict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_scan(update, context, strict=True)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("scan_strict", scan_strict))

    log.info("EMA TOUCH SCANNER BOT RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
