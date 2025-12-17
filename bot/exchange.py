import ccxt

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

markets = exchange.load_markets()

SYMBOLS = [
    s for s in markets
    if s.endswith(":USDT") and markets[s].get("swap")
]

def symbol_available(symbol: str) -> bool:
    return symbol in markets and markets[symbol].get("swap")
