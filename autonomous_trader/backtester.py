"""
Backtesting Engine — Runs strategies against crypto market data
"""
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LINK-USD",
    "MATIC-USD", "UNI-USD", "LTC-USD", "ATOM-USD", "ETC-USD"
]


def load_crypto_data(tickers=None, start="2020-01-01", end="2025-07-21"):
    if tickers is None:
        tickers = CRYPTO_UNIVERSE
    data = {}
    try:
        df_all = yf.download(tickers, start=start, end=end, progress=False, group_by="ticker")
        for t in tickers:
            try:
                if isinstance(df_all.columns, pd.MultiIndex):
                    td = df_all[t].copy()
                else:
                    continue
                td.columns = [c.lower() for c in td.columns]
                td.dropna(subset=["close"], inplace=True)
                if len(td) >= 100:
                    data[t] = td
            except:
                continue
    except:
        pass
    for t in tickers:
        if t not in data:
            try:
                td = yf.download(t, start=start, end=end, progress=False)
                if not td.empty and len(td) >= 100:
                    if isinstance(td.columns, pd.MultiIndex):
                        td.columns = [col[0] for col in td.columns]
                    td.columns = [c.lower() for c in td.columns]
                    data[t] = td
            except:
                continue
    return data


def run_backtest(df, signal_func, initial_capital=10000, commission_pct=0.001,
                 slippage_pct=0.0005, borrow_cost_apr=0.05):
    """
    Position-based backtest: signal = fraction of capital to allocate.
    signal=1.0 = 100% long, signal=-0.5 = 50% short.
    FIXED: PnL = pos * ret * nav (was missing nav multiplication)
    """
    df = signal_func(df.copy())
    df["signal"] = df["signal"].fillna(0)

    nav = float(initial_capital)
    peak = nav
    max_dd_pct = 0.0
    equity_curve = [nav]
    dates_hist = []
    trade_log = []
    pnl_by_date = {}
    pos = 0.0

    for i in range(1, len(df)):
        dt = df.index[i]
        signal = float(df["signal"].iloc[i])
        price = float(df["close"].iloc[i])
        prev_price = float(df["close"].iloc[i-1])
        ret = (price / prev_price) - 1.0
        dates_hist.append(dt)

        day_pnl = 0.0
        if pos != 0:
            day_pnl = pos * ret * nav
            # Transaction costs on exit/flip
            if signal == 0 or np.sign(signal) != np.sign(pos):
                day_pnl -= abs(pos) * nav * (commission_pct + slippage_pct)
            if pos < 0:
                day_pnl -= abs(pos) * nav * borrow_cost_apr / 252

        # Entry cost for new position
        if signal != 0 and (pos == 0 or np.sign(signal) != np.sign(pos)):
            day_pnl -= abs(signal) * nav * (commission_pct + slippage_pct)

        nav += day_pnl
        nav = max(nav, 0.0)

        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak if peak > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd

        equity_curve.append(nav)
        pnl_by_date[dt] = day_pnl

        if pos != signal and signal != 0:
            trade_log.append({
                "date": dt, "action": "LONG" if signal > 0 else "SHORT",
                "size": signal, "price": price,
            })

        pos = signal

    if pos != 0 and len(df) > 1:
        ret2 = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-2])) - 1.0
        nav += pos * ret2 * nav
        nav -= abs(pos) * nav * (commission_pct + slippage_pct)
    equity_curve[-1] = nav

    # Metrics
    es = pd.Series(equity_curve, index=[df.index[0]] + dates_hist)
    rs = es.pct_change().dropna()

    total_return = (nav - initial_capital) / initial_capital
    n_days = len(rs)
    ann_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1 if n_days > 0 else 0.0

    avg_ret = rs.mean()
    std_ret = rs.std()
    sharpe = (avg_ret / max(std_ret, 1e-10)) * np.sqrt(252)

    neg_ret = rs[rs < 0]
    downside_std = neg_ret.std() if len(neg_ret) > 0 else 1e-10
    sortino = (avg_ret / max(downside_std, 1e-10)) * np.sqrt(252)

    calmar = (total_return * 100) / max(max_dd_pct * 100, 0.001)

    wins = (rs > 0).sum()
    total_days = len(rs)
    win_rate = wins / total_days if total_days > 0 else 0.0

    gross_profit = rs[rs > 0].sum()
    gross_loss = abs(rs[rs < 0].sum())
    profit_factor = gross_profit / max(gross_loss, 1e-10)

    monthly = {}
    for dt_idx, pnl in pnl_by_date.items():
        mk = dt_idx.strftime("%Y-%m")
        monthly.setdefault(mk, []).append(pnl)
    ms = pd.Series({k: sum(v) for k, v in monthly.items()})
    monthly_wr = (ms > 0).sum() / max(len(ms), 1)

    yearly = {}
    for idx_val in rs.index:
        yr = idx_val.year
        yearly.setdefault(yr, []).append(rs.loc[idx_val])
    yearly_returns = {yr: (np.prod(1 + np.array(rets)) - 1) * 100 for yr, rets in yearly.items()}

    return {
        "equity_curve": es, "daily_returns": rs,
        "monthly_returns": ms, "yearly_returns": yearly_returns,
        "trade_log": trade_log, "final_balance": nav,
        "total_return": total_return, "annualized_return": ann_return,
        "max_dd": max_dd_pct, "sharpe": sharpe, "sortino": sortino,
        "calmar": calmar, "win_rate": win_rate,
        "profit_factor": profit_factor, "monthly_win_rate": monthly_wr,
        "total_trades": len(trade_log),
        "positive_months": int((ms > 0).sum()), "total_months": len(ms),
        "avg_daily_return": avg_ret, "std_daily_return": std_ret,
        "best_day": rs.max() if len(rs) > 0 else 0,
        "worst_day": rs.min() if len(rs) > 0 else 0,
        "skew": rs.skew() if len(rs) > 2 else 0.0,
        "kurtosis": rs.kurtosis() if len(rs) > 2 else 0.0,
        "daily_var_95": np.percentile(rs, 5) if len(rs) > 0 else 0,
        "total_days": total_days, "peak_balance": es.max(),
    }
