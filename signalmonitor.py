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
EMA_EXTRA = 250
EMA_SMOOTH = 9

# ================= STATE ==================
MONITOR_ON = False
WATCHLIST = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "LINK/USDT:USDT"
]

LAST_SIGNAL = {}
TOUCH_MEMORY = {}

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
    for i in range(3):
        try:
            return exchange.fetch_ohlcv(symbol, TF, limit=FETCH_LIMIT)
        except Exception as e:
            log.warning(f"Fetch {symbol} retry {i+1}: {e}")
            await asyncio.sleep(2)
    return None

# ================= EMA =====================
def mexc_ema(series, length, smooth=9):
    ema = series.ewm(span=length, adjust=False).mean()
    return ema.rolling(smooth).mean()

def calc_ema(df):
    df["ema150"] = mexc_ema(df["close"], EMA_FAST, EMA_SMOOTH)
    df["ema200"] = mexc_ema(df["close"], EMA_SLOW, EMA_SMOOTH)
    df["ema250"] = mexc_ema(df["close"], EMA_EXTRA, EMA_SMOOTH)
    return df

# ================= TOUCH ===================
def ema_touch(df):
    c = df.iloc[-2]
    tol = c.close * 0.0003

    for ema in ["ema150", "ema200", "ema250"]:
        if abs(c.low - c[ema]) <= tol or abs(c.high - c[ema]) <= tol:
            return ema.upper()
    return None

# ================= POST TOUCH ANALYSIS =====
def evaluate_post_touch(df, memory):
    try:
        idx = df.index.get_loc(memory["index"])
    except KeyError:
        return None

    if idx + 3 >= len(df):
        return None

    base = memory["price"]
    ema_col = memory["ema"].lower()
    retouch = False

    for i in range(1, 4):
        c = df.iloc[idx + i]
        tol = c.close * 0.0003
        if abs(c.low - c[ema_col]) <= tol or abs(c.high - c[ema_col]) <= tol:
            retouch = True

    last_close = df.iloc[idx + 3].close

    if retouch:
        return "RETOUCH"
    if last_close > base:
        return "UP"
    if last_close < base:
        return "DOWN"
    return "FLAT"

# ================= SEND SIGNAL =============
async def send_signal(app, symbol, text, df):
    key = f"{symbol}_{text}"
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
            mpf.make_addplot(plot_df["ema150"], color="orange"),
            mpf.make_addplot(plot_df["ema200"], color="red"),
            mpf.make_addplot(plot_df["ema250"], color="purple"),
        ],
        title=f"{symbol} | {text}",
        savefig=dict(fname=fname, dpi=130)
    )

    caption = (
        f"🚨 *EMA TOUCH SIGNAL*\n"
        f"{symbol}\n"
        f"{text}\n"
        f"TF 5m\n"
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )

    with open(fname, "rb") as img:
        await app.bot.send_photo(
            chat_id=TARGET,
            photo=img,
            caption=caption,
            parse_mode="Markdown"
        )

    os.remove(fname)

# ================= LOOP ====================
async def monitor_loop(app):
    log.info("Monitor loop started")
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

            if len(df) < EMA_EXTRA + EMA_SMOOTH + 5:
                continue

            df = calc_ema(df)

            # DEBUG SCAN (lihat bot bergerak)
            log.info(f"SCAN {sym} | candle {df.index[-2]}")

            touch = ema_touch(df)

            if touch and sym not in TOUCH_MEMORY:
                TOUCH_MEMORY[sym] = {
                    "ema": touch,
                    "index": df.index[-2],
                    "price": df.iloc[-2].close
                }
                await send_signal(app, sym, f"{touch} TOUCH", df)

            if sym in TOUCH_MEMORY:
                result = evaluate_post_touch(df, TOUCH_MEMORY[sym])
                if result:
                    await send_signal(
                        app,
                        sym,
                        f'{TOUCH_MEMORY[sym]["ema"]} → {result}',
                        df
                    )
                    del TOUCH_MEMORY[sym]

            await asyncio.sleep(SEND_DELAY)

# ================= COMMANDS ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❗ Gunakan: /addcoin btc")
        return

    sym = f"{context.args[0].upper()}/USDT:USDT"

    if not symbol_available(sym):
        await update.message.reply_text("❌ Symbol tidak tersedia")
        return

    if sym in WATCHLIST:
        await update.message.reply_text("⚠️ Symbol sudah ada")
        return

    WATCHLIST.append(sym)
    await update.message.reply_text(f"✅ {sym} added")

async def delcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Gunakan: /delcoin btc")
        return

    sym = f"{context.args[0].upper()}/USDT:USDT"

    if sym not in WATCHLIST:
        await update.message.reply_text("⚠️ Symbol tidak ada")
        return

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
    app.create_task(monitor_loop(app))

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
