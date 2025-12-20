# =================================================
# EMA TOUCH SIGNAL BOT - MEXC ACCURATE FINAL
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
import logging

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
log = logging.getLogger("MEXC-EMA")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET = int(os.getenv("TARGET", "0"))

if not BOT_TOKEN or TARGET == 0:
    log.error("BOT_TOKEN / TARGET belum diset")
    exit(1)

TF = "5m"
FETCH_LIMIT = 300
PLOT_CANDLE = 120
SEND_DELAY = 2
SIGNAL_COOLDOWN = 300

EMA_FAST = 150
EMA_SLOW = 200
EMA_SMOOTH = 9        # 🔥 MEXC STYLE

# ================= STATE ==================
MONITOR_ON = False
WATCHLIST = [
    "BTC/USDT:USDT",
    "LINK/USDT:USDT",
    "PIPPIN/USDT:USDT",
    "ZEC/USDT:USDT",
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
    log.info("Market loaded")
except Exception as e:
    log.error(f"Load market failed: {e}")
    exit(1)

def symbol_available(symbol):
    return symbol in exchange.markets and exchange.markets[symbol].get("swap")

# ================= SAFE FETCH ==============
async def safe_fetch(symbol):
    for i in range(3):
        try:
            return exchange.fetch_ohlcv(symbol, TF, limit=FETCH_LIMIT)
        except Exception as e:
            log.warning(f"Fetch {symbol} retry {i+1}: {e}")
            await asyncio.sleep(2)
    return None

# ================= MEXC EMA =================
def mexc_ema(series, length, smooth=9):
    ema = series.ewm(span=length, adjust=False).mean()
    return ema.rolling(smooth).mean()

def calc_ema(df):
    df["ema150"] = mexc_ema(df["close"], EMA_FAST, EMA_SMOOTH)
    df["ema200"] = mexc_ema(df["close"], EMA_SLOW, EMA_SMOOTH)
    return df

# ================= TOUCH LOGIC =============
def ema_touch(df):
    c = df.iloc[-2]  # CLOSED candle only

    tolerance = c.close * 0.0003  # 0.03%

    if abs(c.low - c.ema150) <= tolerance or abs(c.high - c.ema150) <= tolerance:
        return "EMA150"

    if abs(c.low - c.ema200) <= tolerance or abs(c.high - c.ema200) <= tolerance:
        return "EMA200"

    return None

# ================= SEND SIGNAL =============
async def send_signal(app, symbol, ema_type, df):
    key = f"{symbol}_{ema_type}"
    now = datetime.now(timezone.utc).timestamp()

    if now - LAST_SIGNAL.get(key, 0) < SIGNAL_COOLDOWN:
        return

    LAST_SIGNAL[key] = now
    log.info(f"SIGNAL {symbol} {ema_type}")

    fname = symbol.replace("/", "").replace(":", "") + ".png"
    plot_df = df.iloc[-PLOT_CANDLE-1:-1]

    mpf.plot(
        plot_df,
        type="candle",
        style="charles",
        volume=True,
        addplot=[
            mpf.make_addplot(plot_df["ema150"], color="orange", width=1),
            mpf.make_addplot(plot_df["ema200"], color="red", width=1),
        ],
        title=f"{symbol} | {ema_type} TOUCH | TF 5m",
        savefig=dict(fname=fname, dpi=130)
    )

    caption = (
        f"🚨 *EMA TOUCH SIGNAL*\n"
        f"{symbol}\n"
        f"{ema_type} (MEXC)\n"
        f"TF 5m\n"
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )

    try:
        with open(fname, "rb") as img:
            await app.bot.send_photo(
                chat_id=TARGET,
                photo=img,
                caption=caption,
                parse_mode="Markdown"
            )
    except Exception as e:
        log.error(f"Telegram error: {e}")
    finally:
        if os.path.exists(fname):
            os.remove(fname)

# ================= LOOP ====================
async def monitor_loop(app):
    log.info("Monitor loop started")
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

                if len(df) < EMA_SLOW + EMA_SMOOTH + 2:
                    continue

                df = calc_ema(df)
                signal = ema_touch(df)

                if signal:
                    await send_signal(app, sym, signal, df)
                else:
                    log.info(f"NO SIGNAL {sym}")

                await asyncio.sleep(SEND_DELAY)

            except Exception as e:
                log.error(f"Monitor error {sym}: {e}")

# ================= COMMANDS ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("CMD /start")
    await update.message.reply_text(
        "🤖 EMA TOUCH BOT (MEXC)\n\n"
        "/on /off\n"
        "/addcoin btc\n"
        "/delcoin btc\n"
        "/listcoin\n"
        "/status"
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

    log.info("EMA TOUCH BOT MEXC FINAL RUNNING")
    app.run_polling(stop_signals=None)

if __name__ == "__main__":
    main()
