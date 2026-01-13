# ==========================================================
# MONEY FLOW SCANNER v2
# Whale vs Retail Detection
# MEXC FUTURES | 400 COINS
# ==========================================================

import ccxt
import pandas as pd
import asyncio
import os
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

TOP_N = 400
BATCH = 40
DELAY = 0.4

SCALP_TF = "5m"
SWING_TF = "1h"

RS_MIN = 0.5
VOL_POWER_MIN = 1.5

exchange = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})

# ================= UTILS =================

async def safe_fetch(symbol, tf, limit=30):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: exchange.fetch_ohlcv(symbol, tf, limit=limit))
    except:
        return None

def calc_return(c):
    return (c["c"] - c["o"]) / c["o"] * 100

# ================= SYMBOLS =================

async def get_top_symbols():
    loop = asyncio.get_running_loop()
    tickers = await loop.run_in_executor(None, exchange.fetch_tickers)
    pairs = [(s, t["quoteVolume"]) for s,t in tickers.items() if s.endswith("/USDT:USDT") and t and t.get("quoteVolume")]
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [s for s,_ in pairs[:TOP_N]]

# ================= CORE =================

async def scan(update, context):

    await update.message.reply_text("💰 Money Flow Scan Started...")

    btc5 = await safe_fetch("BTC/USDT:USDT", SCALP_TF, 3)
    btc1h = await safe_fetch("BTC/USDT:USDT", SWING_TF, 3)

    btc5 = pd.DataFrame(btc5, columns=["t","o","h","l","c","v"]).iloc[-1]
    btc1h = pd.DataFrame(btc1h, columns=["t","o","h","l","c","v"]).iloc[-1]

    btc5_ret = calc_return(btc5)
    btc1h_ret = calc_return(btc1h)

    symbols = await get_top_symbols()

    whale = []
    retail = []
    distrib = []

    for sym in symbols:
        data = await safe_fetch(sym, SCALP_TF, 25)
        if not data: continue

        df = pd.DataFrame(data, columns=["t","o","h","l","c","v"])
        last = df.iloc[-1]

        alt_ret = calc_return(last)
        rs = alt_ret - btc5_ret

        vol_now = last.v
        vol_avg = df.v.mean()
        vol_power = vol_now / vol_avg if vol_avg > 0 else 0

        price_move = abs(last.c - last.o)
        efficiency = price_move / vol_now if vol_now > 0 else 0

        base = sym.split("/")[0]

        if rs > RS_MIN:
            if vol_power > VOL_POWER_MIN and efficiency > 0.0000005:
                whale.append((base, rs, alt_ret))
            else:
                retail.append((base, rs, alt_ret))

        if rs < -RS_MIN and vol_power > 1:
            distrib.append((base, rs, alt_ret))

        await asyncio.sleep(DELAY)

    whale = sorted(whale, key=lambda x: x[1], reverse=True)[:8]
    retail = sorted(retail, key=lambda x: x[1], reverse=True)[:8]
    distrib = sorted(distrib, key=lambda x: x[1])[:8]

    msg = (
        f"💰 MONEY FLOW v2\n"
        f"BTC 5m {btc5_ret:.2f}%\n\n"
        "🔥 WHALE ACCUMULATION\n"
    )

    for s,rs,ret in whale:
        msg += f"{s} | RS {rs:.2f}% | ALT {ret:.2f}%\n"

    msg += "\n🟢 RETAIL PUMP\n"
    for s,rs,ret in retail:
        msg += f"{s} | RS {rs:.2f}% | ALT {ret:.2f}%\n"

    msg += "\n🔴 DISTRIBUTION\n"
    for s,rs,ret in distrib:
        msg += f"{s} | RS {rs:.2f}% | ALT {ret:.2f}%\n"

    await update.message.reply_text(msg)

# ================= BOT =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/scan – Money Flow v2")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
