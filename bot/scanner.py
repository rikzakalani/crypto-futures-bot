import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")

import asyncio, os
from datetime import datetime
from config import *
from exchange import exchange, SYMBOLS
from utils import calc_support_resistance

AUTO_SCAN = False
AUTO_TF = "15m"
AUTO_INTERVAL = TF_MAP[AUTO_TF]

def get_top_movers():
    tickers = exchange.fetch_tickers(SYMBOLS)
    data = []

    for sym, t in tickers.items():
        pct = t.get("percentage")
        if pct is None or abs(pct) < MIN_MOVE_PCT:
            continue

        data.append({
            "symbol": sym,
            "change": pct,
            "volume": t.get("quoteVolume") or 0
        })

    df = pd.DataFrame(data)
    if df.empty:
        return df

    df = df.sort_values("volume", ascending=False).head(30)
    return df.sort_values("change", ascending=False).head(TOP_N)

async def send_chart(app, symbol, change, tf):
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=LIMIT)
    df = pd.DataFrame(
        ohlcv,
        columns=["time","open","high","low","close","volume"]
    )
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df.set_index("time", inplace=True)

    supports, resistances = calc_support_resistance(df)

    apds = []
    for s in supports:
        apds.append(mpf.make_addplot([s]*len(df), linestyle="--"))
    for r in resistances:
        apds.append(mpf.make_addplot([r]*len(df), linestyle="--"))

    label = "GAINER 🚀" if change > 0 else "LOSER 🔻"
    fname = symbol.replace("/", "").replace(":", "") + f"_{tf}.png"

    mpf.plot(
        df,
        type="candle",
        style="charles",
        volume=True,
        figsize=(10, 6),
        addplot=apds,
        title=f"{symbol} | {tf.upper()} | {label} {change:+.2f}%",
        savefig=dict(fname=fname, dpi=160, bbox_inches="tight")
    )

    caption = (
        f"📊 {symbol}\n"
        f"TF: {tf.upper()}\n"
        f"{label} {change:+.2f}%\n"
        f"Support: {supports}\n"
        f"Resistance: {resistances}\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    with open(fname, "rb") as img:
        await app.bot.send_photo(chat_id=TARGET, photo=img, caption=caption)

    os.remove(fname)

async def scanner_loop(app):
    global AUTO_SCAN
    await asyncio.sleep(5)
    while True:
        if AUTO_SCAN:
            coins = get_top_movers()
            for _, r in coins.iterrows():
                await send_chart(app, r.symbol, r.change, AUTO_TF)
                await asyncio.sleep(SEND_DELAY)
            await asyncio.sleep(AUTO_INTERVAL)
        else:
            await asyncio.sleep(2)
