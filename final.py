# ==========================================================
# SCANNER v12.1 — MARKET SENSE MULTI-TF SCANNER
# Binance Futures | FILTER ONLY (NOT SIGNAL)
# ==========================================================

import ccxt
import asyncio
import os
import pandas as pd
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===================== CONFIG =====================
BOT_TOKEN = "8037827696:AAHodY7-aQNg9l6v21zISnxFxazxK5I0TL8"

TFS = ["5m", "15m", "1h"]
LOOKBACK = 120
MAX_PAIRS = 300
SCAN_DELAY = 0.12

# ===================== EXCHANGE =====================
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"}
})

markets = exchange.load_markets()
PAIRS = [
    s for s, m in markets.items()
    if m.get("contract")
    and m.get("quote") == "USDT"
    and m.get("active")
][:MAX_PAIRS]

ccxt_lock = asyncio.Lock()

# ===================== MARKET MEMORY =====================
market_memory = {}

# ===================== DATA =====================
async def fetch_ohlcv(symbol, tf):
    try:
        async with ccxt_lock:
            return await asyncio.to_thread(
                exchange.fetch_ohlcv, symbol, tf, limit=LOOKBACK
            )
    except:
        return None

# ===================== SWING (ATR BASED) =====================
def build_swings(df, atr_mult=1.2):
    atr = (df["h"] - df["l"]).rolling(14).mean()
    swings = []
    last_price = df["c"].iloc[0]
    direction = None

    for i in range(14, len(df)):
        threshold = atr.iloc[i] * atr_mult
        price = df["c"].iloc[i]

        if direction is None:
            if abs(price - last_price) > threshold:
                direction = "UP" if price > last_price else "DOWN"
                last_price = price
        else:
            if direction == "UP" and price < last_price - threshold:
                swings.append({"type": "HIGH", "price": last_price})
                direction = "DOWN"
                last_price = price
            elif direction == "DOWN" and price > last_price + threshold:
                swings.append({"type": "LOW", "price": last_price})
                direction = "UP"
                last_price = price

    return swings[-6:]

# ===================== STRUCTURE =====================
def classify_structure(swings):
    if len(swings) < 4:
        return "RANGE"

    highs = [s["price"] for s in swings if s["type"] == "HIGH"]
    lows = [s["price"] for s in swings if s["type"] == "LOW"]

    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "UPTREND"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "DOWNTREND"

    return "RANGE"

# ===================== ENERGY =====================
def calc_energy(df):
    atr = (df["h"] - df["l"]).rolling(14).mean().iloc[-1]
    rng = df["h"].iloc[-20:].max() - df["l"].iloc[-20:].min()
    if atr == 0 or np.isnan(atr):
        return 0
    return round(min(rng / (atr * 3), 1), 2)

# ===================== STATE =====================
def resolve_state(energy, structure):
    if energy < 0.25:
        return "DORMANT"
    if energy < 0.45:
        return "IGNITION"
    if energy >= 0.45 and structure != "RANGE":
        return "EXPANSION"
    if energy >= 0.6 and structure == "RANGE":
        return "DISTRIBUTION"
    return "DECAY"

# ===================== DIRECTION =====================
def resolve_direction(structure, last_swing):
    if structure == "UPTREND" and last_swing == "HIGH":
        return "BULL"
    if structure == "DOWNTREND" and last_swing == "LOW":
        return "BEAR"
    return "COUNTER"

# ===================== PHASE =====================
def resolve_phase(energy):
    if energy < 0.55:
        return "EARLY"
    if energy < 0.75:
        return "MID"
    return "LATE"

# ===================== ANALYZE TF =====================
async def analyze_tf(symbol, tf):
    raw = await fetch_ohlcv(symbol, tf)
    if not raw:
        return None

    df = pd.DataFrame(raw, columns=["t","o","h","l","c","v"])
    swings = build_swings(df)
    if not swings:
        return None

    structure = classify_structure(swings)
    energy = calc_energy(df)
    state = resolve_state(energy, structure)

    last_swing = swings[-1]["type"]
    direction = resolve_direction(structure, last_swing)
    phase = resolve_phase(energy) if state == "EXPANSION" else None

    return {
        "tf": tf,
        "state": state,
        "structure": structure,
        "direction": direction,
        "phase": phase,
        "energy": energy
    }

# ===================== AGGREGATOR =====================
def aggregate_market(tf_data):
    htf = tf_data.get("1h")
    mtf = tf_data.get("15m")
    ltf = tf_data.get("5m")

    # ===== REGIME (HTF) =====
    if htf and htf["state"] == "EXPANSION" and htf["structure"] != "RANGE":
        regime = "TRENDING"
    elif htf and htf["state"] in ["DORMANT", "RANGE"]:
        regime = "BALANCED"
    elif htf and htf["state"] == "DISTRIBUTION":
        regime = "DISTRIBUTING"
    else:
        regime = "UNKNOWN"

    # ===== FLOW (HTF vs MTF) =====
    if htf and mtf:
        if htf["structure"] == mtf["structure"]:
            flow = "ALIGNED"
        elif mtf["state"] == "EXPANSION":
            flow = "EARLY SHIFT"
        else:
            flow = "COUNTER"
    else:
        flow = "INSUFFICIENT DATA"

    # ===== PRESSURE (LTF OPTIONAL) =====
    if ltf:
        if ltf["state"] == "EXPANSION":
            pressure = "ACTIVE"
        elif ltf["state"] == "IGNITION":
            pressure = "BUILDING"
        else:
            pressure = "QUIET"
    else:
        pressure = "UNKNOWN"

    # ===== ENVIRONMENT =====
    if regime == "TRENDING" and flow == "ALIGNED":
        env = "TREND CONTINUATION"
        risk = "NORMAL"
    elif regime == "BALANCED" and pressure in ["ACTIVE", "BUILDING"]:
        env = "EARLY BREAKOUT"
        risk = "FAKEOUT RISK"
    elif htf and htf.get("phase") == "LATE":
        env = "EXHAUSTION ZONE"
        risk = "HIGH"
    elif flow == "COUNTER":
        env = "COUNTER TREND"
        risk = "HIGH"
    else:
        env = "NO EDGE"
        risk = "RANDOM"

    return {
        "regime": regime,
        "flow": flow,
        "pressure": pressure,
        "environment": env,
        "risk": risk
    }

# ===================== ANALYZE SYMBOL =====================
async def analyze(symbol):
    tf_results = {}

    for tf in TFS:
        r = await analyze_tf(symbol, tf)
        if r:
            tf_results[tf] = r

    # minimal: salah satu TF EXPANSION
    if not any(v["state"] == "EXPANSION" for v in tf_results.values()):
        return None

    sense = aggregate_market(tf_results)

    return {
        "symbol": symbol.replace("/", ""),
        "tfs": tf_results,
        "sense": sense
    }

# ===================== FORMAT =====================
def format_msg(r):
    tf_lines = []
    for tf, d in r["tfs"].items():
        tf_lines.append(
            f"{tf}: {d['state']} • {d['structure']} • {d['direction']}"
        )

    msg = f"""📊 {r['symbol']}
Market Sense : {r['sense']['environment']}
Regime       : {r['sense']['regime']}
Flow         : {r['sense']['flow']}
Pressure     : {r['sense']['pressure']}
Risk         : {r['sense']['risk']}

TF Snapshot:
- """ + "\n- ".join(tf_lines) + """

Action       : WAIT MANUAL SETUP
"""
    return msg

# ===================== TELEGRAM =====================
async def scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Scanning market sense...")
    results = []

    for s in PAIRS:
        r = await analyze(s)
        if r:
            results.append(r)
        await asyncio.sleep(SCAN_DELAY)

    if not results:
        await update.message.reply_text("📭 No valid market sense")
        return

    for r in results[:10]:
        await update.message.reply_text(format_msg(r))

# ===================== RUN =====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("scan", scan))
    print("SCANNER v12.1 MARKET SENSE MULTI-TF RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
