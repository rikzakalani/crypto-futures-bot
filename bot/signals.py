import pandas as pd
import asyncio, time
from telegram import Update
from telegram.ext import ContextTypes

from config import *
from exchange import exchange, symbol_available

WATCHLIST = ["BTC/USDT:USDT", "ETH/USDT:USDT"]

MONITOR_ON = False
MONITOR_MODE = "ALL"
MONITOR_SYMBOL = None
LAST_SIGNAL_TIME = {}

def calc_indicators(df):
    df["ema9"] = df.close.ewm(span=9).mean()
    df["ema26"] = df.close.ewm(span=26).mean()
    df["ema50"] = df.close.ewm(span=50).mean()
    df["ema200"] = df.close.ewm(span=200).mean()
    return df

def check_signal(df):
    last = df.iloc[-1]
    if last.ema9 > last.ema26 > last.ema50 > last.ema200:
        return "BUY"
    if last.ema9 < last.ema26 < last.ema50 < last.ema200:
        return "SELL"
    return None

# ===== COMMANDS =====
async def signalmonitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_ON, MONITOR_MODE, MONITOR_SYMBOL

    if not context.args:
        await update.message.reply_text("Gunakan: /signalmonitor on|off|btc")
        return

    arg = context.args[0].lower()

    if arg == "on":
        MONITOR_ON = True
        MONITOR_MODE = "ALL"
        MONITOR_SYMBOL = None
        await update.message.reply_text("🟢 Signal monitor aktif (ALL)")
        return

    if arg == "off":
        MONITOR_ON = False
        await update.message.reply_text("🔴 Signal monitor dihentikan")
        return

    symbol = f"{arg.upper()}/USDT:USDT"
    if not symbol_available(symbol):
        await update.message.reply_text("⛔ Symbol tidak tersedia")
        return

    MONITOR_ON = True
    MONITOR_MODE = "SINGLE"
    MONITOR_SYMBOL = symbol

    await update.message.reply_text(f"🟢 Signal monitor aktif\n{symbol}")

async def listcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 WATCHLIST:\n" + "\n".join(WATCHLIST))

async def addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    symbol = f"{context.args[0].upper()}/USDT:USDT"
    if symbol not in WATCHLIST:
        WATCHLIST.append(symbol)
    await update.message.reply_text(f"✅ Ditambahkan: {symbol}")

async def delcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    symbol = f"{context.args[0].upper()}/USDT:USDT"
    if symbol in WATCHLIST:
        WATCHLIST.remove(symbol)
    await update.message.reply_text(f"🗑️ Dihapus: {symbol}")

async def monitor_loop(app):
    await asyncio.sleep(5)
    while True:
        if MONITOR_ON:
            symbols = WATCHLIST if MONITOR_MODE == "ALL" else [MONITOR_SYMBOL]
            for sym in symbols:
                df = pd.DataFrame(
                    exchange.fetch_ohlcv(sym, TF_SIGNAL, limit=LIMIT),
                    columns=["time","open","high","low","close","volume"]
                )
                df["time"] = pd.to_datetime(df["time"], unit="ms")
                df.set_index("time", inplace=True)

                df = calc_indicators(df)
                signal = check_signal(df)

                if signal:
                    now = time.time()
                    if now - LAST_SIGNAL_TIME.get(sym, 0) > SIGNAL_COOLDOWN:
                        LAST_SIGNAL_TIME[sym] = now
                        await app.bot.send_message(
                            chat_id=TARGET,
                            text=f"🚨 {signal} SIGNAL\n{sym}\nTF: 15M"
                        )
                await asyncio.sleep(2)
        await asyncio.sleep(5)
