# ==========================================================
# MONEY FLOW SCANNER v3 – SMART MONEY EDITION
# Whale Accumulation vs Retail vs Distribution
# MEXC FUTURES
# ==========================================================

import ccxt, pandas as pd, asyncio, os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

TOP_N = 400
BATCH_SIZE = 25
DELAY = 0.25

TF = "5m"
RS_MIN = 0.6
VOL_SPIKE = 1.8
EFF_MIN = 0.25

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

# ================= UTILS =================

async def fetch(symbol, tf, limit=30):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: exchange.fetch_ohlcv(symbol, tf, limit=limit)
        )
    except:
        return None

def ret(c): 
    return (c.c - c.o) / c.o * 100

def efficiency(c):
    return abs(c.c - c.o) / (c.h - c.l + 1e-8)

# ================= SYMBOLS =================

async def get_symbols():
    loop = asyncio.get_running_loop()
    tickers = await loop.run_in_executor(None, exchange.fetch_tickers)
    pairs = [
        s for s,t in tickers.items()
        if s.endswith("/USDT:USDT") and t and t.get("quoteVolume")
    ]
    return pairs[:TOP_N]

# ================= CORE =================

async def scan(update, context):

    await update.message.reply_text("💰 Money Flow v3 Scanning...")

    btc = await fetch("BTC/USDT:USDT", TF, 20)
    btc = pd.DataFrame(btc, columns=["t","o","h","l","c","v"])
    btc_ret = ret(btc.iloc[-1])
    btc_trend = btc.c.iloc[-1] > btc.c.mean()

    symbols = await get_symbols()

    whale, retail, distrib = [], [], []

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]

        tasks = [fetch(sym, TF, 30) for sym in batch]
        results = await asyncio.gather(*tasks)

        for sym, data in zip(batch, results):
            if not data: continue

            df = pd.DataFrame(data, columns=["t","o","h","l","c","v"])
            last = df.iloc[-1]

            rs = ret(last) - btc_ret
            vol_power = last.v / df.v.mean()
            eff = efficiency(last)

            base = sym.split("/")[0]

            # 🐳 Whale Accumulation
            if rs > RS_MIN and vol_power > VOL_SPIKE and eff < EFF_MIN:
                whale.append((base, rs))

            # 🟢 Retail Pump
            elif rs > RS_MIN and eff > EFF_MIN:
                retail.append((base, rs))

            # 🔴 Distribution
            elif rs < -RS_MIN and vol_power > VOL_SPIKE:
                distrib.append((base, rs))

        await asyncio.sleep(DELAY)

    whale = sorted(whale, key=lambda x: x[1], reverse=True)[:8]
    retail = sorted(retail, key=lambda x: x[1], reverse=True)[:8]
    distrib = sorted(distrib, key=lambda x: x[1])[:8]

    msg = f"""
💰 MONEY FLOW v3
BTC 5m: {btc_ret:.2f}% | Trend: {"UP" if btc_trend else "DOWN"}

🐳 WHALE ACCUMULATION
""" + "\n".join(f"{s} | RS {r:.2f}%" for s,r in whale)

    msg += "\n\n🟢 RETAIL PUMP\n"
    msg += "\n".join(f"{s} | RS {r:.2f}%" for s,r in retail)

    msg += "\n\n🔴 DISTRIBUTION\n"
    msg += "\n".join(f"{s} | RS {r:.2f}%" for s,r in distrib)

    await update.message.reply_text(msg)

# ================= BOT =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/scan – Money Flow v3")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
