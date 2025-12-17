import pandas as pd

def calc_support_resistance(df, window=20):
    supports, resistances = [], []

    for i in range(window, len(df) - window):
        if df.low.iloc[i] == df.low.iloc[i-window:i+window].min():
            supports.append(float(df.low.iloc[i]))
        if df.high.iloc[i] == df.high.iloc[i-window:i+window].max():
            resistances.append(float(df.high.iloc[i]))

    return supports[-2:], resistances[-2:]
