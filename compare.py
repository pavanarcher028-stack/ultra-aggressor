import numpy as np
import pandas as pd
import yfinance as yf

def backtest(ticker, start, end, use_filter):
    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df[["Open", "Close"]].dropna().copy()
    df.columns = ["open", "close"]
    df["prev_close"] = df["close"].shift(1)
    df["ret"] = (df["open"] - df["close"]) / df["open"]
    if use_filter:
        cond = df["open"] > df["prev_close"]
    else:
        cond = pd.Series(True, index=df.index)
    trades = df.loc[cond & df["ret"].notna(), "ret"]
    if len(trades) == 0:
        return None
    bal = 100_000
    peak = bal
    max_dd = 0
    rets = []
    for r in trades:
        bal *= (1 + r)
        rets.append(r)
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak
        if dd > max_dd:
            max_dd = dd
    wins = sum(1 for r in rets if r > 0)
    s = pd.Series(rets)
    sr = (s.mean() / s.std()) * np.sqrt(252) if s.std() > 0 else 0
    roi = (bal - 100000) / 100000 * 100
    return {"ticker": ticker, "filter": use_filter, "roi": roi,
            "win_rate": wins / len(rets) * 100, "max_dd": max_dd * 100,
            "sharpe": sr, "trades": len(rets)}

start = "2015-01-01"
end = "2025-07-21"
tickers = ["^BSESN", "^NSEI", "^GSPC", "^FCHI", "SPY", "^N225"]

print(f"{'Ticker':<10} {'Filter':>8} {'ROI%':>10} {'Win%':>8} {'MaxDD%':>8} {'Sharpe':>8} {'Trades':>8}")
print("-" * 60)
for t in tickers:
    for f in [True, False]:
        r = backtest(t, start, end, f)
        if r:
            print(f"{r['ticker']:<10} {str(r['filter']):>8} {r['roi']:>+9.2f}% {r['win_rate']:>7.1f}% {r['max_dd']:>7.2f}% {r['sharpe']:>8.2f} {r['trades']:>8}")
