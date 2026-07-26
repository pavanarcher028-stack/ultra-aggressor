"""Direct backtester test with simple signals."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from backtester import load_crypto_data, run_backtest

data = load_crypto_data(["BTC-USD"])

# Simple test: always long 10% of capital
def simple_buy_hold(df):
    df = df.copy()
    df["signal"] = 0.10
    return df

result = run_backtest(data["BTC-USD"].copy(), simple_buy_hold)
print(f"Simple 10% long BTC:")
print(f"  Return: {result['total_return']*100:.2f}%")
print(f"  Sharpe: {result['sharpe']:.3f}")
print(f"  DD: {result['max_dd']*100:.2f}%")
print(f"  WR: {result['win_rate']*100:.1f}%")
print(f"  Final: ${result['final_balance']:.2f}")
print(f"  Days: {result['total_days']}")
print(f"  Daily mean: {result['avg_daily_return']*100:.6f}%")
print(f"  Daily std: {result['std_daily_return']*100:.4f}%")

# Now test: alternating +20%/-20% each day
def alternating(df):
    df = df.copy()
    df["signal"] = [0.2 if i % 2 == 0 else -0.2 for i in range(len(df))]
    return df

result2 = run_backtest(data["BTC-USD"].copy(), alternating)
print(f"\nAlternating ±20%:")
print(f"  Return: {result2['total_return']*100:.2f}%")
print(f"  Sharpe: {result2['sharpe']:.2f}")
print(f"  Final: ${result2['final_balance']:.2f}")
