import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

def backtest_intraday_short(ticker, start, end, filter_open_higher=True):
    print(f"\n{'=' * 65}")
    print(f"  INTRADAY SHORT-AND-BUY STRATEGY: {ticker}")
    print(f"  Period: {start} to {end}")
    print(f"  Filter: Open > Prev Close = {filter_open_higher}")
    print(f"{'=' * 65}")

    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty:
        print(f"  No data for {ticker}")
        return None

    # Flatten MultiIndex columns if needed
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df = df[["Open", "Close"]].dropna().copy()
    df.columns = ["open", "close"]
    df["prev_close"] = df["close"].shift(1)

    print(f"  Downloaded {len(df)} trading days")

    # Daily return from shorting at open and covering at close
    # Short at Open: profit = (Open - Close) / Open
    df["daily_return"] = (df["open"] - df["close"]) / df["open"]

    # Filter: only trade if open > previous close
    if filter_open_higher:
        df["trade"] = df["open"] > df["prev_close"]
    else:
        df["trade"] = True

    # Trading logic
    balance = 100_000
    peak = balance
    max_dd = 0
    equity_curve = [balance]
    trade_returns = []
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        if not row["trade"] or pd.isna(row["daily_return"]):
            equity_curve.append(equity_curve[-1])
            continue

        ret = row["daily_return"]
        trade_returns.append(ret)
        balance *= (1 + ret)

        trades.append({
            "date": df.index[i],
            "open": row["open"],
            "close": row["close"],
            "return": ret
        })

        equity = balance
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    final_balance = balance
    total_return = (final_balance - 100_000) / 100_000

    # Metrics
    wins = sum(1 for t in trade_returns if t > 0)
    total_trades = len(trade_returns)
    win_rate = wins / total_trades if total_trades > 0 else 0

    daily_returns = pd.Series(trade_returns)
    avg_ret = daily_returns.mean()
    std_ret = daily_returns.std()
    sr = (avg_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0

    print(f"\n  {'=' * 55}")
    print(f"  BACKTEST RESULTS")
    print(f"  {'=' * 55}")
    print(f"  Initial Balance:    $100,000.00")
    print(f"  Final Balance:      ${final_balance:,.2f}")
    print(f"  ROI:                {total_return * 100:+.2f}%")
    print(f"  Win Rate:           {win_rate * 100:.1f}%  ({wins}/{total_trades} days)")
    print(f"  Max Drawdown:       {max_dd * 100:.2f}%")
    print(f"  Sharpe Ratio:       {sr:.2f}")
    print(f"  Total Trades:       {total_trades}")
    print(f"  Avg Daily Return:   {avg_ret * 100:+.4f}%")
    print(f"  Best Day:           {daily_returns.max() * 100:+.4f}%")
    print(f"  Worst Day:          {daily_returns.min() * 100:+.4f}%")
    print(f"  Std Dev (daily):    {std_ret * 100:.4f}%")
    print(f"  {'=' * 55}")

    return {
        "ticker": ticker,
        "filter": filter_open_higher,
        "final_balance": final_balance,
        "roi": total_return * 100,
        "win_rate": win_rate * 100,
        "max_dd": max_dd * 100,
        "sharpe": sr,
        "total_trades": total_trades,
        "avg_return": avg_ret * 100,
        "best_day": daily_returns.max() * 100,
        "worst_day": daily_returns.min() * 100,
        "std_daily": std_ret * 100
    }


# ===== MAIN =====
print("=" * 65)
print("  INTRADAY SHORT-AND-BUY STRATEGY BACKTEST")
print("  Short at Open, Cover at Close (same day)")
print("=" * 65)

tickers = ["^BSESN", "^FCHI", "^GSPC", "^NSEI", "SPY", "^N225"]
start = "2005-01-01"
end = "2025-12-31"
# Using a shorter date range that definitely works with yfinance
start2 = "2015-01-01"
end2 = "2025-07-21"

results = []
for t in tickers:
    try:
        r = backtest_intraday_short(t, start2, end2, filter_open_higher=True)
        if r:
            results.append(r)
    except Exception as e:
        print(f"  Error with {t}: {e}")

# Summary table
if results:
    print(f"\n{'=' * 65}")
    print(f"  SUMMARY: ALL MARKETS")
    print(f"{'=' * 65}")
    print(f"  {'Ticker':<12} {'ROI%':>10} {'WinRate%':>10} {'MaxDD%':>10} {'Sharpe':>8} {'Trades':>8}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")
    for r in results:
        print(f"  {r['ticker']:<12} {r['roi']:>+9.2f}% {r['win_rate']:>9.1f}% {r['max_dd']:>9.2f}% {r['sharpe']:>8.2f} {r['total_trades']:>8}")
    print(f"  {'=' * 55}")

print(f"\n  Strategy: Short at Open, Cover at Close (same day)")
print(f"  No overnight holding — no carry costs")
print(f"  Filter: Only trade when Open > Previous Close")
print(f"  {'=' * 65}")
