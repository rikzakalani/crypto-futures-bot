# =================================================
# EMA TOUCH SIGNAL BOT - FINAL FIX & STABLE
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
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ISI_TOKEN_KAMU"
TARGET = os.getenv("TARGET") or "CHAT_ID_KAMU"

TF = "5m"
FETCH_LIMIT = 260        # ambil panjang
PLOT_CANDLE = 120        # yang diplot
SEND_DELAY = 2
SIGNAL_COOLDOWN = 300    # 5 menit

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
exchange.load_markets()

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
    last = df.iloc[-1]

    low = last.low
    high = last.high

    if low <= last.ema150 <= high:
        return "EMA150"

    if low <= last.ema200 <= high:
        return "EMA200"

    return None

# ================= SEND SIGNAL =============
async def send_signal(app, symbol, ema_type, df):
    now = datetime.now(timezone.utc).timestamp()
    if now - LAST_SIGNAL.get(symbol, 0) < SIGNAL_COOLDOWN:
        return

    LAST_SIGNAL[symbol] = now

    fname = symbol.replace("/", "").replace(":", "") + ".png"

    plot_df = df.tail(PLOT_CANDLE)

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
        f"🚨 *BUY SIGNAL*\n"
        f"📊 {symbol}\n"
        f"📌 {ema_type} TOUCH CANDLE\n"
        f"⏱ TF: 5m\n"
        f"🕒 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )

    print(f"[SIGNAL] {symbol} {ema_type}")

    try:
        with open(fname, "rb") as img:
            await app.bot.send_photo(
                chat_id=TARGET,
                photo=img,
                caption=caption,
                parse_mode="Markdown"
            )
    finally:
        if os.path.exists(fname):
            os.remove(fname)

# ================= LOOP ====================
async def monitor_loop(app):
    print("[MONITOR] LOOP STARTED")
    while True:
        if not MONITOR_ON:
            await asyncio.sleep(5)
            continue

        for sym in WATCHLIST:
            ohlcv = await safe_fetch(sym)
            if not ohlcv:
                continue

            df = pd.DataFrame(
                ohlcv,
                columns=["time","open","high","low","close","volume"]
            )
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
            df.set_index("time", inplace=True)

            df = calc_ema(df)

            if len(df) < EMA_SLOW:
                continue

            signal = ema_touch(df)
            if signal:
                await send_signal(app, sym, signal, df)

            await asyncio.sleep(SEND_DELAY)

# ================= COMMANDS ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *EMA TOUCH BOT*\n\n"
        "/on  - start monitor\n"
        "/off - stop monitor\n"
        "/addcoin btc\n"
        "/delcoin btc\n"
        "/listcoin\n"
        "/status",
        parse_mode="Markdown"
    )

async def on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_ON
    MONITOR_ON = True
    print("[MONITOR] ON")
    await update.message.reply_text("🟢 Monitor ON")

async def off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_ON
    MONITOR_ON = False
    print("[MONITOR] OFF")
    await update.message.reply_text("🔴 Monitor OFF")

async def addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    sym = f"{context.args[0].upper()}/USDT:USDT"
    if symbol_available(sym) and sym not in WATCHLIST:
        WATCHLIST.append(sym)
        print(f"[ADD] {sym}")
        await update.message.reply_text(f"✅ {sym} added")

async def delcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    sym = f"{context.args[0].upper()}/USDT:USDT"
    if sym in WATCHLIST:
        WATCHLIST.remove(sym)
        print(f"[DEL] {sym}")
        await update.message.reply_text(f"🗑️ {sym} removed")

async def listcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n".join(WATCHLIST))

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 STATUS\n"
        f"Monitor: {MONITOR_ON}\n"
        f"TF: 5m\n"
        f"Coins: {len(WATCHLIST)}"
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

    print("✅ EMA TOUCH BOT RUNNING (TF 5m)")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
