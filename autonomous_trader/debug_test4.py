"""Find the backtester bug."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from backtester import load_crypto_data

data = load_crypto_data(["BTC-USD"])
df = data["BTC-USD"].copy()

# Test: constant signal
df["signal"] = 0.10
print(f"Signal type: {type(df['signal'])}")
print(f"Signal first 5: {df['signal'].values[:5]}")

# Manually backtest
nav = 10000.0
pos = 0.0
for i in range(1, min(10, len(df))):
    signal = float(df["signal"].iloc[i])
    price = float(df["close"].iloc[i])
    prev_price = float(df["close"].iloc[i-1])
    ret = (price / prev_price) - 1.0
    print(f"i={i}: pos={pos:.4f}, signal={signal:.4f}, price={price:.2f}, prev={prev_price:.2f}, ret={ret*100:.4f}%")
    if pos != 0:
        day_pnl = pos * ret
        print(f"  day_pnl = {pos} * {ret} = {day_pnl}")
        nav += day_pnl
    pos = signal
    print(f"  nav = {nav:.2f}, pos = {pos}")
