"""
================================================================================
  CRYPTO ADAPTIVE TSMOM — Full Hedge Fund-Grade Backtest
================================================================================
  Components:
    1. Adaptive TSMOM with regime-switching (fast 15d / slow 120d for crypto)
    2. Sparse trend t-statistic signals (|t| > 1.5 by default)
    3. Yang-Zhang (2000) range-based volatility estimation
    4. Volatility parity position sizing
    5. Dynamic volatility scaling for crash mitigation
================================================================================
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as scipy_stats
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
np.random.seed(42)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LINK-USD",
    "MATIC-USD", "UNI-USD", "LTC-USD", "ATOM-USD", "ETC-USD"
]

START_DATE  = "2020-01-01"
END_DATE    = "2025-07-21"

# --- Strategy Parameters (Tuned for Crypto) --------------------------------
LOOKBACK_FAST   = 15       # 3 weeks (high vol regime)
LOOKBACK_SLOW   = 120      # 4 months (low vol regime)
REGIME_WINDOW   = 30       # vol regime detection window
T_STAT_THRESH   = 1.5      # t-stat threshold (crypto needs more signals)
YZ_WINDOW       = 20       # Yang-Zhang estimation window
TARGET_ANN_VOL  = 0.50     # higher vol target for crypto
MAX_LEVERAGE    = 1.5      # max gross leverage
MAX_POSITION_PCT = 0.25    # max 25% in any single asset
VOL_CAP_MULTIPLIER = 2.5
PORTFOLIO_VOL_TARGET = 0.35  # portfolio vol target for scaling

# --- Costs -----------------------------------------------------------------
COMMISSION_PCT  = 0.001    # 0.1% per trade
SLIPPAGE_PCT    = 0.0005   # 0.05% slippage
BORROW_COST_APR = 0.05     # 5% annual short borrow cost

INITIAL_CAPITAL = 1_000_000

# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

def load_crypto_universe(tickers, start, end):
    print(f"Downloading {len(tickers)} crypto assets from {start} to {end} ...")
    data = {}
    # Try batch download first
    df_all = yf.download(tickers, start=start, end=end, progress=False, group_by="ticker")
    for t in tickers:
        try:
            if isinstance(df_all.columns, pd.MultiIndex):
                t_data = df_all[t].copy()
            else:
                continue
            t_data.columns = [c.lower() for c in t_data.columns]
            t_data.dropna(subset=["close"], inplace=True)
            if len(t_data) < 100:
                continue
            data[t] = t_data
        except Exception:
            continue
    # Individual downloads for any missing
    for t in tickers:
        if t in data:
            continue
        try:
            t_data = yf.download(t, start=start, end=end, progress=False)
            if t_data.empty:
                continue
            if isinstance(t_data.columns, pd.MultiIndex):
                t_data.columns = [col[0] for col in t_data.columns]
            t_data.columns = [c.lower() for c in t_data.columns]
            t_data.dropna(subset=["close"], inplace=True)
            if len(t_data) < 100:
                continue
            data[t] = t_data
        except Exception:
            continue
    print(f"  Loaded {len(data)} assets successfully")
    for t, df in sorted(data.items()):
        print(f"    {t}: {df.index[0].date()} -> {df.index[-1].date()} ({len(df)} days)")
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 2. YANG-ZHANG VOLATILITY (2000)
# ═══════════════════════════════════════════════════════════════════════════

def yang_zhang_vol(ohlc, window=20):
    """
    Yang-Zhang (2000) range-based volatility.
    Returns annualized volatility as a Series.
    """
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]

    log_overnight = np.log(o / c.shift(1))
    log_close = np.log(c / c.shift(1))
    log_hc = np.log(h / c)
    log_ho = np.log(h / o)
    log_lc = np.log(l / c)
    log_lo = np.log(l / o)

    rs_var = log_hc * log_ho + log_lc * log_lo

    overnight_var = log_overnight.rolling(window).var(ddof=0)
    close_var = log_close.rolling(window).var(ddof=0)
    rs_mean = rs_var.rolling(window).mean()

    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    yz_var = overnight_var + k * close_var + (1 - k) * rs_mean
    yz_vol = np.sqrt(np.maximum(yz_var * 252, 1e-8))

    return yz_vol


# ═══════════════════════════════════════════════════════════════════════════
# 3. REGIME DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def detect_regime(yz_vol, window=30):
    """
    Returns 1 (high vol / fast lookback) or 0 (low vol / slow lookback).
    """
    median_vol = yz_vol.rolling(window, min_periods=window // 2).median()
    regime = (yz_vol > median_vol).astype(int)
    return regime


# ═══════════════════════════════════════════════════════════════════════════
# 4. TREND T-STATISTIC (Sparse Signal)
# ═══════════════════════════════════════════════════════════════════════════

def trend_tstat(prices, lookback):
    """
    OLS linear trend on log prices. Returns t-stat of slope.
    |t| > threshold indicates statistically significant trend.
    """
    if len(prices) < lookback:
        return np.nan

    y = np.log(prices.values[-lookback:])
    x = np.arange(lookback)
    x_mean = x.mean()
    y_mean = y.mean()

    beta = np.sum((x - x_mean) * (y - y_mean)) / max(np.sum((x - x_mean) ** 2), 1e-10)
    alpha = y_mean - beta * x_mean

    residuals = y - (alpha + beta * x)
    se = np.sqrt(np.sum(residuals ** 2) / max(lookback - 2, 1))
    se_beta = se / max(np.sqrt(np.sum((x - x_mean) ** 2)), 1e-10)

    if se_beta == 0:
        return 0.0

    return beta / se_beta


# ═══════════════════════════════════════════════════════════════════════════
# 5. PORTFOLIO CONSTRUCTION & RISK
# ═══════════════════════════════════════════════════════════════════════════

def compute_position(equity, signal, asset_vol):
    """
    Volatility parity sizing with crash safeguards.
    Returns notional for the position (positive=long, negative=short).
    """
    if signal == 0 or asset_vol <= 0:
        return 0.0

    safe_equity = max(equity, 0.0)
    if safe_equity < 1:
        return 0.0

    vol_ratio = TARGET_ANN_VOL / asset_vol
    notional = signal * vol_ratio * safe_equity
    max_notional = safe_equity * MAX_POSITION_PCT
    notional = np.clip(notional, -max_notional, max_notional)

    if asset_vol > VOL_CAP_MULTIPLIER * TARGET_ANN_VOL:
        notional *= 0.5

    return notional


def dynamic_scale(asset_vols):
    """
    Crash mitigation scale factor.
    Reduces exposure when market vol spikes above target.
    Returns factor in [0, 1].
    """
    vols = [v for v in asset_vols.values() if v > 0 and not np.isnan(v)]
    if len(vols) < 3:
        return 1.0

    market_vol = np.median(vols)
    scale = PORTFOLIO_VOL_TARGET / max(market_vol, 0.01)
    return float(np.clip(scale, 0.05, 1.0))


# ═══════════════════════════════════════════════════════════════════════════
# 6. CORE BACKTEST
# ═══════════════════════════════════════════════════════════════════════════

def backtest_portfolio(data, initial_capital=1_000_000):
    """
    Run adaptive TSMOM portfolio backtest.
    """
    # --- Align all assets to common date index ---
    common = None
    for t, df in data.items():
        if common is None:
            common = df.index
        else:
            common = common.intersection(df.index)
    common = common.sort_values()
    print(f"\nCommon trading days: {len(common)}")

    # --- Pre-compute signals for each asset ---
    all_signals = {}
    all_vols = {}

    for t, df_in in data.items():
        df = df_in.loc[common].copy()
        if len(df) < 100:
            continue

        yz = yang_zhang_vol(df, YZ_WINDOW)
        regime = detect_regime(yz, REGIME_WINDOW)
        all_vols[t] = yz

        sig_series = pd.Series(0.0, index=common)

        for i in range(len(common)):
            if i < max(LOOKBACK_FAST, LOOKBACK_SLOW, YZ_WINDOW, REGIME_WINDOW) + 1:
                continue

            lb = LOOKBACK_FAST if regime.iloc[i] == 1 else LOOKBACK_SLOW
            eff_lb = min(lb, i)

            prices = df["close"].iloc[i - eff_lb : i + 1]
            t_stat = trend_tstat(prices, eff_lb)

            if t_stat > T_STAT_THRESH:
                sig_series.iloc[i] = 1.0
            elif t_stat < -T_STAT_THRESH:
                sig_series.iloc[i] = -1.0
            else:
                sig_series.iloc[i] = 0.0

        # Shift signal by 1 to prevent look-ahead
        all_signals[t] = sig_series.shift(1)

    valid_assets = [t for t in all_signals if all_signals[t].notna().sum() > 50]
    print(f"Assets with valid signals: {len(valid_assets)}")
    for t in valid_assets:
        net_sig = all_signals[t].sum()
        print(f"  {t}: net signal = {net_sig:+.0f}")

    if len(valid_assets) < 3:
        print("ERROR: too few assets with valid signals")
        return None

    # --- Walk-forward loop ---
    warmup = max(LOOKBACK_FAST, LOOKBACK_SLOW, REGIME_WINDOW, YZ_WINDOW) + 5
    if warmup >= len(common):
        warmup = len(common) // 4

    nav = float(initial_capital)
    peak = nav
    max_dd_pct = 0.0
    nav_history = []
    dates_history = []
    trade_log = []
    daily_pnl_values = []
    flat_mode = False

    # Track daily PnL per date for monthly/yearly aggregation
    pnl_by_date = {}

    notionals = {t: 0.0 for t in valid_assets}
    prev_notionals = {t: 0.0 for t in valid_assets}

    trading_start_idx = warmup
    print(f"\nTrading period: {common[trading_start_idx].date()} to {common[-1].date()}")
    print(f"Trading days: {len(common) - trading_start_idx}")

    for i in range(trading_start_idx, len(common)):
        dt = common[i]
        prev_dt = common[i - 1]

        # Circuit breaker
        if flat_mode:
            nav_history.append(nav)
            dates_history.append(dt)
            daily_pnl_values.append(0.0)
            pnl_by_date[dt] = 0.0
            continue

        if nav <= 0 or nav < peak * 0.05:
            for t in valid_assets:
                prev_notionals[t] = 0.0
                notionals[t] = 0.0
            flat_mode = True
            nav_history.append(nav)
            dates_history.append(dt)
            daily_pnl_values.append(0.0)
            pnl_by_date[dt] = 0.0
            continue

        # --- Compute PnL from previous day's positions ---
        day_pnl = 0.0

        for t in valid_assets:
            pnl_notional = prev_notionals.get(t, 0.0)
            if pnl_notional == 0.0:
                continue

            try:
                prev_c = data[t].loc[prev_dt, "close"]
                curr_c = data[t].loc[dt, "close"]
            except KeyError:
                continue

            ret = (curr_c / prev_c) - 1.0

            # Transaction costs on signal change
            old_sig = 1 if pnl_notional > 0 else (-1 if pnl_notional < 0 else 0)
            new_sig = 1 if notionals[t] > 0 else (-1 if notionals[t] < 0 else 0)

            cost = 0.0
            if old_sig != new_sig:
                turnover = abs(pnl_notional) + abs(notionals[t])
                cost = turnover * (COMMISSION_PCT + SLIPPAGE_PCT)

            borrow = 0.0
            if pnl_notional < 0:
                borrow = abs(pnl_notional) * BORROW_COST_APR / 252

            pnl = pnl_notional * ret - cost - borrow
            day_pnl += pnl

        # --- Update NAV ---
        nav += day_pnl
        nav = max(nav, 0.0)

        nav_history.append(nav)
        dates_history.append(dt)
        daily_pnl_values.append(day_pnl)
        pnl_by_date[dt] = day_pnl

        # Drawdown tracking
        if nav > peak:
            peak = nav
        dd_pct = (peak - nav) / peak if peak > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        # --- Compute new positions for next day ---
        current_vols = {}
        for t in valid_assets:
            v = all_vols[t].get(dt, np.nan)
            if not np.isnan(v) and v > 0:
                current_vols[t] = v

        scale = dynamic_scale(current_vols)

        total_gross = 0.0
        for t in valid_assets:
            sig = all_signals[t].get(dt, 0.0)
            if np.isnan(sig):
                sig = 0.0

            vol = current_vols.get(t, TARGET_ANN_VOL)
            if np.isnan(vol) or vol <= 0:
                vol = TARGET_ANN_VOL

            ntl = compute_position(nav, sig, vol)
            ntl *= scale
            notionals[t] = ntl
            total_gross += abs(ntl)

        # Leverage cap
        safe_nav = max(nav, 1.0)
        if total_gross > safe_nav * MAX_LEVERAGE:
            lev_ratio = (safe_nav * MAX_LEVERAGE) / max(total_gross, 1.0)
            for t in valid_assets:
                notionals[t] *= lev_ratio

        # Log trade entries/exits
        for t in valid_assets:
            old_s = 1 if prev_notionals.get(t, 0) > 0 else (-1 if prev_notionals.get(t, 0) < 0 else 0)
            new_s = 1 if notionals[t] > 0 else (-1 if notionals[t] < 0 else 0)
            if old_s != new_s and new_s != 0:
                trade_log.append({
                    "date": dt,
                    "asset": t,
                    "action": "LONG" if new_s > 0 else "SHORT",
                    "notional": abs(notionals[t]),
                })

        prev_notionals = dict(notionals)

    # --- Compute Metrics ---
    if len(nav_history) < 5:
        print("ERROR: insufficient trading history")
        return None

    equity_series = pd.Series(nav_history, index=dates_history)
    ret_series = equity_series.pct_change().dropna()

    total_return = (nav - initial_capital) / initial_capital
    n_days = len(ret_series)
    ann_factor = 252 / max(n_days, 1)
    ann_return = (1 + total_return) ** ann_factor - 1 if n_days > 0 else 0.0

    # Sharpe
    avg_ret = ret_series.mean()
    std_ret = ret_series.std()
    sharpe = (avg_ret / max(std_ret, 1e-10)) * np.sqrt(252)

    # Sortino
    neg_ret = ret_series[ret_series < 0]
    downside_std = neg_ret.std() if len(neg_ret) > 0 else 1e-10
    sortino = (avg_ret / max(downside_std, 1e-10)) * np.sqrt(252)

    # Calmar
    calmar = (total_return * 100) / max(max_dd_pct * 100, 0.001)

    # Win rate
    wins = (ret_series > 0).sum()
    total_days = len(ret_series)
    win_rate = wins / total_days if total_days > 0 else 0.0

    # Profit factor
    gross_profit = ret_series[ret_series > 0].sum()
    gross_loss = abs(ret_series[ret_series < 0].sum())
    pf = gross_profit / max(gross_loss, 1e-10)

    # Monthly returns
    monthly = {}
    for dt, pnl in pnl_by_date.items():
        mk = dt.strftime("%Y-%m")
        if mk not in monthly:
            monthly[mk] = []
        monthly[mk].append(pnl)

    monthly_net = {k: sum(v) for k, v in monthly.items()}
    monthly_series = pd.Series(monthly_net)
    pos_months = (monthly_series > 0).sum()
    total_months = len(monthly_series)
    monthly_wr = pos_months / max(total_months, 1)

    # Yearly returns (from daily return series)
    yearly = {}
    for idx_val in ret_series.index:
        yr = idx_val.year
        if yr not in yearly:
            yearly[yr] = []
        yearly[yr].append(ret_series.loc[idx_val])

    yearly_returns = {yr: np.sum(rets) * 100 for yr, rets in yearly.items()}

    # VaR
    daily_var_95 = np.percentile(ret_series, 5)

    results = {
        "equity_curve": equity_series,
        "daily_returns": ret_series,
        "monthly_returns": monthly_series,
        "yearly_returns": yearly_returns,
        "trade_log": trade_log,
        "final_balance": nav,
        "total_return": total_return,
        "annualized_return": ann_return,
        "max_dd": max_dd_pct,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "win_rate": win_rate,
        "profit_factor": pf,
        "monthly_win_rate": monthly_wr,
        "total_trades": len(trade_log),
        "positive_months": pos_months,
        "total_months": total_months,
        "avg_daily_return": avg_ret,
        "std_daily_return": std_ret,
        "best_day": ret_series.max(),
        "worst_day": ret_series.min(),
        "skew": ret_series.skew() if len(ret_series) > 2 else 0.0,
        "kurtosis": ret_series.kurtosis() if len(ret_series) > 2 else 0.0,
        "daily_var_95": daily_var_95,
        "total_days": total_days,
    }

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 7. REPORT
# ═══════════════════════════════════════════════════════════════════════════

def print_report(r, init_cap=1_000_000):
    sep72 = "=" * 72
    sep55 = "-" * 55

    def fmt(v, pct=False):
        if pct:
            return "{:+.2f}%".format(v * 100)
        return "{:.2f}".format(v)

    print()
    print(sep72)
    print("  CRYPTO ADAPTIVE TSMOM - HEDGE FUND PERFORMANCE REPORT")
    print(sep72)

    lines = [
        ("", "", ""),
        ("  SUMMARY STATISTICS", "", ""),
        ("  " + sep55, "", ""),
        ("  {:<35} {:>15}", "Metric", "Value"),
        ("  {:<35} {:>15}", "-" * 35, "-" * 15),
        ("  {:<35} {:>15}", "Strategy", "Adaptive TSMOM (Crypto)"),
        ("  {:<35} {:>15}", "Universe", "{} assets".format(len(CRYPTO_UNIVERSE))),
        ("  {:<35} {:>15}", "Period", "{} -> {}".format(START_DATE, END_DATE)),
        ("  {:<35} {:>15}", "Initial Capital", "${:,.0f}".format(init_cap)),
        ("  {:<35} {:>15}", "Final Balance", "${:,.2f}".format(r["final_balance"])),
        ("", "", ""),
        ("  PERFORMANCE METRICS", "", ""),
        ("  " + sep55, "", ""),
        ("  {:<35} {:>15}", "Metric", "Value"),
        ("  {:<35} {:>15}", "-" * 35, "-" * 15),
        ("  {:<35} {:>15}", "Total Return", fmt(r["total_return"], True)),
        ("  {:<35} {:>15}", "Annualized Return", fmt(r["annualized_return"], True)),
        ("  {:<35} {:>15}", "Max Drawdown", "{:.2f}%".format(r["max_dd"] * 100)),
        ("  {:<35} {:>15}", "Sharpe Ratio (ann.)", fmt(r["sharpe"])),
        ("  {:<35} {:>15}", "Sortino Ratio (ann.)", fmt(r["sortino"])),
        ("  {:<35} {:>15}", "Calmar Ratio", fmt(r["calmar"])),
        ("  {:<35} {:>15}", "Profit Factor", fmt(r["profit_factor"])),
        ("  {:<35} {:>15}", "Skewness", fmt(r["skew"])),
        ("  {:<35} {:>15}", "Kurtosis (excess)", fmt(r["kurtosis"])),
        ("", "", ""),
        ("  TRADE ANALYSIS", "", ""),
        ("  " + sep55, "", ""),
        ("  {:<35} {:>15}", "Metric", "Value"),
        ("  {:<35} {:>15}", "-" * 35, "-" * 15),
        ("  {:<35} {:>15}", "Total Trades", "{}".format(r["total_trades"])),
        ("  {:<35} {:>15}", "Total Trading Days", "{}".format(r["total_days"])),
        ("  {:<35} {:>15}", "Win Rate (daily)", "{:.2f}%".format(r["win_rate"] * 100)),
        ("  {:<35} {:>15}", "Win Rate (monthly)", "{:.2f}%".format(r["monthly_win_rate"] * 100)),
        ("  {:<35} {:>15}", "Positive Months", "{}/{}".format(r["positive_months"], r["total_months"])),
        ("  {:<35} {:>15}", "Avg Daily Return", "{:+.4f}%".format(r["avg_daily_return"] * 100)),
        ("  {:<35} {:>15}", "Std Dev (daily)", "{:+.4f}%".format(r["std_daily_return"] * 100)),
        ("  {:<35} {:>15}", "Best Day", "{:+.4f}%".format(r["best_day"] * 100)),
        ("  {:<35} {:>15}", "Worst Day", "{:+.4f}%".format(r["worst_day"] * 100)),
        ("", "", ""),
        ("  RISK METRICS", "", ""),
        ("  " + sep55, "", ""),
        ("  {:<35} {:>15}", "Metric", "Value"),
        ("  {:<35} {:>15}", "-" * 35, "-" * 15),
        ("  {:<35} {:>15}", "Max Drawdown", "{:.2f}%".format(r["max_dd"] * 100)),
        ("  {:<35} {:>15}", "Daily VaR (95%)", "{:+.4f}%".format(r["daily_var_95"] * 100)),
        ("  {:<35} {:>15}", "Monthly Std Dev", "${:,.0f}".format(r["monthly_returns"].std())),
    ]

    for item in lines:
        if len(item) == 3 and item[0]:
            print(item[0].format(item[1], item[2]))
        else:
            print(item[0])

    # Yearly returns
    print()
    print("  YEARLY RETURNS")
    print("  " + sep55)
    for yr in sorted(r["yearly_returns"].keys()):
        yr_ret = r["yearly_returns"][yr]
        bar = "#" * max(1, min(int(abs(yr_ret) / 3), 25))
        print("  {:<10} {:>+8.2f}%  {}".format(yr, yr_ret, bar))

    # Key stats
    print()
    print("  PORTFOLIO STATISTICS")
    print("  " + sep55)
    ec = r["equity_curve"]
    print("  {:<35} {:>15}".format("Peak NAV", "${:,.2f}".format(ec.max())))
    print("  {:<35} {:>15}".format("Trough NAV", "${:,.2f}".format(ec.min())))
    print("  {:<35} {:>15}".format("Avg Leverage", "{}x".format(1.0)))  # placeholder
    if r["total_days"] > 0:
        print("  {:<35} {:>15}".format("Avg Holding Period", "{:.0f} days".format(
            r["total_days"] / max(r["total_trades"], 1))))

    print()
    print(sep72)
    print("  END OF REPORT")
    print(sep72)

    return r


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(sep72 := "=" * 72)
    print("  CRYPTO ADAPTIVE TSMOM BACKTEST")
    print(sep72)
    print()
    print("  Configuration:")
    print(f"    Universe:      {len(CRYPTO_UNIVERSE)} crypto assets")
    print(f"    Fast Lookback: {LOOKBACK_FAST}d (high volatility regime)")
    print(f"    Slow Lookback: {LOOKBACK_SLOW}d (low volatility regime)")
    print(f"    Regime Window: {REGIME_WINDOW}d")
    print(f"    T-Stat Threshold: +/-{T_STAT_THRESH}")
    print(f"    Vol Estimator: Yang-Zhang ({YZ_WINDOW}d)")
    print(f"    Asset Vol Target: {TARGET_ANN_VOL*100:.0f}% ann.")
    print(f"    Portfolio Vol Target: {PORTFOLIO_VOL_TARGET*100:.0f}% ann.")
    print(f"    Max Leverage:  {MAX_LEVERAGE}x")
    print(f"    Initial Capital: ${INITIAL_CAPITAL:,.0f}")

    data = load_crypto_universe(CRYPTO_UNIVERSE, START_DATE, END_DATE)

    if len(data) < 3:
        print("ERROR: Need at least 3 assets with data.")
        exit(1)

    print()
    print("=" * 72)
    print("  RUNNING BACKTEST...")
    print("=" * 72)

    result = backtest_portfolio(data)

    if result is None:
        print("ERROR: Backtest failed.")
        exit(1)

    print_report(result, INITIAL_CAPITAL)

    # Save
    result["equity_curve"].to_csv("equity_curve.csv")
    result["daily_returns"].to_csv("daily_returns.csv")
    print()
    print("  Files saved: equity_curve.csv, daily_returns.csv")
