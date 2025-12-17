import pandas as pd
import mplfinance as mpf
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
        if pct and abs(pct) >= MIN_MOVE_PCT:
            data.append({
                "symbol": sym,
                "change": pct,
                "volume": t.get("quoteVolume") or 0
            })

    df = pd.DataFrame(data)
    if df.empty:
        return df

    return (
        df.sort_values("volume", ascending=False)
          .head(30)
          .sort_values("change", ascending=False)
          .head(TOP_N)
    )

async def send_chart(app, symbol, change, tf):
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=LIMIT)
    df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df.set_index("time", inplace=True)

    supports, resistances = calc_support_resistance(df)
    apds = []

    for s in supports:
        apds.append(mpf.make_addplot([s]*len(df), linestyle="--"))
    for r in resistances:
        apds.append(mpf.make_addplot([r]*len(df), linestyle="--"))

    fname = f"{symbol.replace('/','').replace(':','')}_{tf}.png"

    mpf.plot(
        df,
        type="candle",
        volume=True,
        addplot=apds,
        figsize=(8, 5),
        savefig=dict(fname=fname, dpi=120)
    )

    caption = (
        f"📊 {symbol}\n"
        f"TF: {tf.upper()}\n"
        f"Change: {change:+.2f}%\n"
        f"{datetime.now():%Y-%m-%d %H:%M}"
    )

    with open(fname, "rb") as img:
        await app.bot.send_photo(chat_id=TARGET, photo=img, caption=caption)

    os.remove(fname)

async def scanner_loop(app):
    await asyncio.sleep(5)
    while True:
        if AUTO_SCAN:
            for _, r in get_top_movers().iterrows():
                await send_chart(app, r.symbol, r.change, AUTO_TF)
                await asyncio.sleep(SEND_DELAY)
            await asyncio.sleep(AUTO_INTERVAL)
        else:
            await asyncio.sleep(2)
