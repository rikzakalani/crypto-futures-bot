# =================================================
# EMA TOUCH SIGNAL BOT - FINAL HARDENED
# Exchange : MEXC Futures (SWAP)
# TF       : 5m
# =================================================

import ccxt
import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Application
)

from datetime import datetime, timezone
import asyncio
import os

# ================= CONFIG =================
BOT_TOKEN = os.getenv("8037827696:AAHodY7-aQNg9l6v21zISnxFxazxK5I0TL8") or "8037827696:AAHodY7-aQNg9l6v21zISnxFxazxK5I0TL8"
TARGET = int(os.getenv("8037827696") or 8037827696)  # 🔥 HARUS INT

TF = "5m"
FETCH_LIMIT = 260
PLOT_CANDLE = 120
SEND_DELAY = 2
SIGNAL_COOLDOWN = 300  # per EMA

EMA_FAST = 150
EMA_SLOW = 200

# ================= STATE ==================
MONITOR_ON = False
WATCHLIST = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT"
]

LAST_SIGNAL = {}
MONITOR_TASK = None

# ================= EXCHANGE ===============
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

try:
    exchange.load_markets()
except Exception as e:
    print("[FATAL] Load markets failed:", e)
    exit(1)

def symbol_available(symbol):
    return symbol in exchange.markets and exchange.markets[symbol].get("swap")

# ================= SAFE FETCH ==============
async def safe_fetch(symbol):
    for _ in range(3):
        try:
            return exchange.fetch_ohlcv(symbol, TF, limit=FETCH_LIMIT)
        except Exception as e:
            print(f"[FETCH ERROR] {symbol}: {e}")
            await asyncio.sleep(2)
    return None

# ================= INDICATOR ===============
def calc_ema(df):
    df["ema150"] = df["close"].ewm(span=EMA_FAST).mean()
    df["ema200"] = df["close"].ewm(span=EMA_SLOW).mean()
    return df

# ================= TOUCH LOGIC =============
def ema_touch(df):
    last = df.iloc[-2]  # 🔥 candle CLOSED

    if last.low <= last.ema150 <= last.high:
        return "EMA150"

    if last.low <= last.ema200 <= last.high:
        return "EMA200"

    return None

# ================= SEND SIGNAL =============
async def send_signal(app, symbol, ema_type, df):
    key = f"{symbol}_{ema_type}"
    now = datetime.now(timezone.utc).timestamp()

    if now - LAST_SIGNAL.get(key, 0) < SIGNAL_COOLDOWN:
        return

    LAST_SIGNAL[key] = now

    fname = symbol.replace("/", "").replace(":", "") + ".png"
    plot_df = df.iloc[-PLOT_CANDLE-1:-1]

    mpf.plot(
        plot_df,
        type="candle",
        style="charles",
        volume=True,
        addplot=[
            mpf.make_addplot(plot_df["ema150"]),
            mpf.make_addplot(plot_df["ema200"]),
        ],
        savefig=dict(fname=fname, dpi=130)
    )

    caption = (
        f"🚨 *EMA TOUCH SIGNAL*\n"
        f"📊 {symbol}\n"
        f"📌 {ema_type} TOUCH (CLOSED)\n"
        f"⏱ TF: 5m\n"
        f"🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )

    try:
        with open(fname, "rb") as img:
            await app.bot.send_photo(
                chat_id=TARGET,
                photo=img,
                caption=caption,
                parse_mode="Markdown"
            )
        print(f"[SIGNAL] {symbol} {ema_type}")
    except Exception as e:
        print("[TELEGRAM ERROR]", e)
    finally:
        if os.path.exists(fname):
            os.remove(fname)

# ================= LOOP ====================
async def monitor_loop(app):
    print("[MONITOR] LOOP STARTED")
    while True:
        if not MONITOR_ON or not WATCHLIST:
            await asyncio.sleep(5)
            continue

        for sym in WATCHLIST:
            try:
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
                signal = ema_touch(df)

                if signal:
                    await send_signal(app, sym, signal, df)

                await asyncio.sleep(SEND_DELAY)

            except Exception as e:
                print(f"[MONITOR ERROR] {sym}: {e}")

# ================= COMMANDS ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *EMA TOUCH BOT*\n\n"
        "/on /off\n"
        "/addcoin btc\n"
        "/delcoin btc\n"
        "/listcoin\n"
        "/status",
        parse_mode="Markdown"
    )

async def on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_ON
    MONITOR_ON = True
    await update.message.reply_text("🟢 Monitor ON")

async def off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_ON
    MONITOR_ON = False
    await update.message.reply_text("🔴 Monitor OFF")

async def addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    sym = f"{context.args[0].upper()}/USDT:USDT"
    if symbol_available(sym) and sym not in WATCHLIST:
        WATCHLIST.append(sym)
        await update.message.reply_text(f"✅ {sym} added")

async def delcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    sym = f"{context.args[0].upper()}/USDT:USDT"
    if sym in WATCHLIST:
        WATCHLIST.remove(sym)
        await update.message.reply_text(f"🗑️ {sym} removed")

async def listcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n".join(WATCHLIST))

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Monitor: {MONITOR_ON}\nCoins: {len(WATCHLIST)}"
    )

# ================= INIT ====================
async def post_init(app: Application):
    global MONITOR_TASK
    if not MONITOR_TASK:
        MONITOR_TASK = app.create_task(monitor_loop(app))

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on_cmd))
    app.add_handler(CommandHandler("off", off_cmd))
    app.add_handler(CommandHandler("addcoin", addcoin))
    app.add_handler(CommandHandler("delcoin", delcoin))
    app.add_handler(CommandHandler("listcoin", listcoin))
    app.add_handler(CommandHandler("status", status))

    print("✅ EMA TOUCH BOT RUNNING (HARDENED)")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
