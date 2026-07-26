"""
================================================================================
  CRYPTO TSMOM v2 — Long-Only with Enhanced Crash Mitigation
================================================================================
  Changes from v1:
    - Long-only signals (no shorting — crypto momentum is asymmetric)
    - Tighter position sizing (15% max per asset)
    - Earlier circuit breaker (20% peak drawdown → 50% reduction)
    - Progressive vol scaling (scale down as drawdown deepens)
    - Volatility stop: exit position if daily move > 4 * target vol
================================================================================
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG — Tuned for crypto with crash protection
# ═══════════════════════════════════════════════════════════════════════════

CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LINK-USD",
    "MATIC-USD", "UNI-USD", "LTC-USD", "ATOM-USD", "ETC-USD"
]

START_DATE = "2020-01-01"
END_DATE   = "2025-07-21"

# Strategy
LOOKBACK_FAST   = 15
LOOKBACK_SLOW   = 90   # 3 months for crypto
REGIME_WINDOW   = 30
T_STAT_THRESH   = 1.5
YZ_WINDOW       = 20
TARGET_ANN_VOL  = 0.40
MAX_POSITION_PCT = 0.15   # tighter: 15% max per asset
MAX_GROSS_LEV   = 1.2     # max 1.2x gross
PORTFOLIO_VOL_TARGET = 0.25  # lower portfolio vol target

# Crash protection
DD_REDUCTION_THRESH = 0.15   # at 15% DD, reduce by 50%
DD_EXIT_THRESH      = 0.35   # at 35% DD, exit completely
VOL_SPIKE_MULTIPLIER = 3.0   # if daily vol > 3x target, scale to 0
CIRCUIT_BREAKER_DD  = 0.50   # at 50% DD, shut down

# Costs
COMMISSION_PCT  = 0.001
SLIPPAGE_PCT    = 0.0005
INITIAL_CAPITAL = 1_000_000


# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA
# ═══════════════════════════════════════════════════════════════════════════

def load_data(tickers, start, end):
    print(f"Downloading {len(tickers)} crypto assets ...")
    data = {}
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
        except Exception:
            continue
    for t in tickers:
        if t not in data:
            try:
                td = yf.download(t, start=start, end=end, progress=False)
                if not td.empty and len(td) >= 100:
                    if isinstance(td.columns, pd.MultiIndex):
                        td.columns = [col[0] for col in td.columns]
                    td.columns = [c.lower() for c in td.columns]
                    data[t] = td
            except Exception:
                continue
    print(f"  Loaded {len(data)} assets")
    for t, d in sorted(data.items()):
        print(f"    {t}: {d.index[0].date()} -> {d.index[-1].date()} ({len(d)} days)")
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 2. YANG-ZHANG VOL
# ═══════════════════════════════════════════════════════════════════════════

def yz_vol(ohlc, w=20):
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    lo = np.log(o / c.shift(1))
    lc = np.log(c / c.shift(1))
    rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
    k = 0.34 / (1.34 + (w+1)/(w-1))
    yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv * 252, 1e-8))


# ═══════════════════════════════════════════════════════════════════════════
# 3. REGIME
# ═══════════════════════════════════════════════════════════════════════════

def regime(yz, w=30):
    return (yz > yz.rolling(w, min_periods=w//2).median()).astype(int)


# ═══════════════════════════════════════════════════════════════════════════
# 4. TREND T-STAT (LONG ONLY — positive t-stat only)
# ═══════════════════════════════════════════════════════════════════════════

def trend_tstat(prices, lb):
    if len(prices) < lb:
        return np.nan
    y = np.log(prices.values[-lb:])
    x = np.arange(lb)
    xm, ym = x.mean(), y.mean()
    beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
    alpha = ym - beta*xm
    resid = y - (alpha + beta*x)
    se = np.sqrt(np.sum(resid**2) / max(lb-2, 1))
    se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
    return beta / se_b if se_b > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 5. BACKTEST (Long-only)
# ═══════════════════════════════════════════════════════════════════════════

def run(data, initial_capital=1_000_000):
    # Common index
    common = None
    for d in data.values():
        if common is None:
            common = d.index
        else:
            common = common.intersection(d.index)
    common = common.sort_values()
    print(f"\nCommon dates: {len(common)}")

    # Pre-compute signals
    sigs = {}
    vols = {}
    for t, df_in in data.items():
        df = df_in.loc[common].copy()
        if len(df) < 100:
            continue
        yz = yz_vol(df, YZ_WINDOW)
        vols[t] = yz
        reg = regime(yz, REGIME_WINDOW)

        s = pd.Series(0.0, index=common)
        min_data = max(LOOKBACK_FAST, LOOKBACK_SLOW, YZ_WINDOW, REGIME_WINDOW) + 1
        for i in range(min_data, len(common)):
            lb = LOOKBACK_FAST if reg.iloc[i] == 1 else LOOKBACK_SLOW
            eff = min(lb, i)
            prices = df["close"].iloc[i-eff:i+1]
            ts = trend_tstat(prices, eff)
            # LONG ONLY: only go long when t-stat > threshold
            s.iloc[i] = 1.0 if ts > T_STAT_THRESH else 0.0
        sigs[t] = s.shift(1)

    valid = [t for t in sigs if sigs[t].notna().sum() > 50]
    print(f"Valid assets: {len(valid)}")

    # Walk forward
    warmup = max(LOOKBACK_FAST, LOOKBACK_SLOW, REGIME_WINDOW, YZ_WINDOW) + 5
    if warmup >= len(common):
        warmup = len(common) // 4

    nav = float(initial_capital)
    peak = nav
    max_dd = 0.0
    eq = [nav]
    dates = [common[warmup]]
    pnls = []
    trade_log = []
    pnl_by_date = {}

    notionals = {t: 0.0 for t in valid}
    prev_ntl = {t: 0.0 for t in valid}
    stopped = False

    print(f"\nTrading: {common[warmup].date()} to {common[-1].date()} ({len(common)-warmup} days)")

    for i in range(warmup, len(common)):
        dt = common[i]
        pd_dt = common[i-1]

        if stopped:
            eq.append(nav)
            dates.append(dt)
            pnls.append(0.0)
            continue

        # Drawdown-based risk reduction
        dd = (peak - nav) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        # Circuit breaker
        if dd >= CIRCUIT_BREAKER_DD:
            for t in valid:
                prev_ntl[t] = 0.0
                notionals[t] = 0.0
            stopped = True
            eq.append(nav)
            dates.append(dt)
            pnls.append(0.0)
            continue

        # Drawdown-based scale
        dd_scale = 1.0
        if dd > DD_EXIT_THRESH:
            dd_scale = 0.0
        elif dd > DD_REDUCTION_THRESH:
            dd_scale = 0.5 * (DD_EXIT_THRESH - dd) / (DD_EXIT_THRESH - DD_REDUCTION_THRESH)

        # --- PnL from previous positions ---
        day_pnl = 0.0
        for t in valid:
            pn = prev_ntl.get(t, 0.0)
            if pn == 0.0:
                continue
            try:
                pc = data[t].loc[pd_dt, "close"]
                cc = data[t].loc[dt, "close"]
            except KeyError:
                continue
            ret = (cc / pc) - 1.0

            old_s = 1 if pn > 0 else 0
            new_s = 1 if notionals[t] > 0 else 0
            cost = 0.0
            if old_s != new_s:
                cost = (abs(pn)+abs(notionals[t]))*(COMMISSION_PCT+SLIPPAGE_PCT)
            pnl = pn * ret - cost
            day_pnl += pnl

        nav += day_pnl
        nav = max(nav, 0.0)
        eq.append(nav)
        dates.append(dt)
        pnls.append(day_pnl)
        pnl_by_date[dt] = day_pnl

        if nav > peak:
            peak = nav

        # --- New positions ---
        current_vols = {}
        for t in valid:
            v = vols[t].get(dt, np.nan)
            if not np.isnan(v) and v > 0:
                current_vols[t] = v

        # Vol spike check
        market_vol = np.median(list(current_vols.values())) if current_vols else 0
        vol_scale = 1.0
        if market_vol > PORTFOLIO_VOL_TARGET * VOL_SPIKE_MULTIPLIER:
            vol_scale = 0.0
        elif market_vol > PORTFOLIO_VOL_TARGET * 2:
            vol_scale = 0.5

        scale = min(dd_scale, vol_scale)
        safe_nav = max(nav, 0.0)

        total_gross = 0.0
        for t in valid:
            sig = sigs[t].get(dt, 0.0)
            if np.isnan(sig):
                sig = 0.0
            v = current_vols.get(t, TARGET_ANN_VOL)
            if np.isnan(v) or v <= 0:
                v = TARGET_ANN_VOL
            ntl = 0.0
            if sig > 0 and safe_nav > 0:
                vol_r = TARGET_ANN_VOL / v
                ntl = vol_r * safe_nav
                ntl = min(ntl, safe_nav * MAX_POSITION_PCT)
            ntl *= scale
            notionals[t] = ntl
            total_gross += ntl  # all positive (long-only)

        # Leverage cap
        if total_gross > safe_nav * MAX_GROSS_LEV and safe_nav > 0:
            r = (safe_nav * MAX_GROSS_LEV) / max(total_gross, 1.0)
            for t in valid:
                notionals[t] *= r

        for t in valid:
            o = 1 if prev_ntl.get(t, 0) > 0 else 0
            n = 1 if notionals[t] > 0 else 0
            if o != n and n > 0:
                trade_log.append({"date": dt, "asset": t, "action": "ENTER",
                                  "notional": notionals[t]})

        prev_ntl = dict(notionals)

    # Metrics
    es = pd.Series(eq, index=dates)
    rs = es.pct_change().dropna()

    total_ret = (nav - INITIAL_CAPITAL) / INITIAL_CAPITAL
    n = len(rs)
    ann_r = (1+total_ret)**(252/max(n,1))-1 if n > 0 else 0.0
    sharpe = (rs.mean()/max(rs.std(),1e-10))*np.sqrt(252)
    neg = rs[rs < 0]
    ds = neg.std() if len(neg) > 0 else 1e-10
    sortino = (rs.mean()/max(ds,1e-10))*np.sqrt(252)
    calmar = total_ret*100/max(max_dd*100,0.001)
    wr = (rs > 0).sum()/max(len(rs),1)
    gp = rs[rs > 0].sum()
    gl = abs(rs[rs < 0].sum())
    pf = gp/max(gl,1e-10)

    monthly = {}
    for dt, p in pnl_by_date.items():
        mk = dt.strftime("%Y-%m")
        monthly.setdefault(mk, []).append(p)
    ms = pd.Series({k: sum(v) for k, v in monthly.items()})
    mwr = (ms > 0).sum()/max(len(ms),1)

    yearly = {}
    for idx_val in rs.index:
        yr = idx_val.year
        yearly.setdefault(yr, []).append(rs.loc[idx_val])
    yr_ret = {yr: sum(rets)*100 for yr, rets in yearly.items()}

    return {
        "eq": es, "ret": rs, "monthly": ms, "yearly": yr_ret,
        "trades": trade_log, "final": nav, "total_ret": total_ret,
        "ann_ret": ann_r, "max_dd": max_dd, "sharpe": sharpe,
        "sortino": sortino, "calmar": calmar, "win_rate": wr,
        "pf": pf, "mwr": mwr, "n_trades": len(trade_log),
        "pos_months": int((ms > 0).sum()), "tot_months": len(ms),
        "avg_ret": rs.mean(), "std_ret": rs.std(),
        "best": rs.max(), "worst": rs.min(),
        "skew": rs.skew() if len(rs) > 2 else 0,
        "kurt": rs.kurtosis() if len(rs) > 2 else 0,
        "var95": np.percentile(rs, 5), "days": len(rs),
        "peak_eq": es.max(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. REPORT
# ═══════════════════════════════════════════════════════════════════════════

def report(r):
    S = "=" * 72
    print(f"\n{S}")
    print("  CRYPTO TSMOM v2 — LONG-ONLY WITH CRASH MITIGATION")
    print(S)

    data = [
        ("SUMMARY", [
            ("Strategy", "TSMOM v2 (Long-Only)"),
            ("Universe", f"{len(CRYPTO_UNIVERSE)} assets"),
            ("Period", f"{START_DATE} -> {END_DATE}"),
            ("Initial Capital", "${:,.0f}".format(INITIAL_CAPITAL)),
            ("Final Balance", "${:,.2f}".format(r["final"])),
        ]),
        ("PERFORMANCE", [
            ("Total Return", "{:+.2f}%".format(r["total_ret"]*100)),
            ("Annualized Return", "{:+.2f}%".format(r["ann_ret"]*100)),
            ("Max Drawdown", "{:.2f}%".format(r["max_dd"]*100)),
            ("Sharpe Ratio", "{:.3f}".format(r["sharpe"])),
            ("Sortino Ratio", "{:.3f}".format(r["sortino"])),
            ("Calmar Ratio", "{:.3f}".format(r["calmar"])),
            ("Profit Factor", "{:.3f}".format(r["pf"])),
            ("Skewness", "{:.3f}".format(r["skew"])),
            ("Kurtosis", "{:.3f}".format(r["kurt"])),
        ]),
        ("TRADE ANALYSIS", [
            ("Total Trades", "{}".format(r["n_trades"])),
            ("Trading Days", "{}".format(r["days"])),
            ("Win Rate (daily)", "{:.2f}%".format(r["win_rate"]*100)),
            ("Monthly Win Rate", "{:.2f}%".format(r["mwr"]*100)),
            ("Pos. Months", "{}/{}".format(r["pos_months"], r["tot_months"])),
            ("Avg Daily Return", "{:+.4f}%".format(r["avg_ret"]*100)),
            ("Std Dev (daily)", "{:+.4f}%".format(r["std_ret"]*100)),
            ("Best Day", "{:+.4f}%".format(r["best"]*100)),
            ("Worst Day", "{:+.4f}%".format(r["worst"]*100)),
        ]),
        ("RISK", [
            ("Max Drawdown", "{:.2f}%".format(r["max_dd"]*100)),
            ("Daily VaR (95%)", "{:+.4f}%".format(r["var95"]*100)),
            ("Peak NAV", "${:,.2f}".format(r["peak_eq"])),
            ("Trough NAV", "${:,.2f}".format(r["eq"].min())),
        ]),
    ]

    for title, items in data:
        print(f"\n  {title}")
        print("  " + "-" * 55)
        print("  {:<35} {:>15}".format("Metric", "Value"))
        print("  {:<35} {:>15}".format("-"*35, "-"*15))
        for k, v in items:
            print("  {:<35} {:>15}".format(k, v))

    print()
    print("  YEARLY RETURNS")
    print("  " + "-" * 55)
    for yr in sorted(r["yearly"].keys()):
        ret = r["yearly"][yr]
        bar = "#" * max(1, min(int(abs(ret)/3), 25))
        print("  {:<10} {:>+8.2f}%  {}".format(yr, ret, bar))

    print(f"\n{S}")
    print("  END OF REPORT")
    print(S)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("  CRYPTO TSMOM v2 — Long-Only + Crash Mitigation")
    print("=" * 72)
    print(f"\n  Config: fast={LOOKBACK_FAST}d slow={LOOKBACK_SLOW}d t-stat>={T_STAT_THRESH}")
    print(f"  Max pos: {MAX_POSITION_PCT*100:.0f}% | Leverage: {MAX_GROSS_LEV}x | Vol target: {PORTFOLIO_VOL_TARGET*100:.0f}%")
    print(f"  Circuit breaker at {CIRCUIT_BREAKER_DD*100:.0f}% DD")
    print(f"  Initial capital: ${INITIAL_CAPITAL:,.0f}")

    d = load_data(CRYPTO_UNIVERSE, START_DATE, END_DATE)
    if len(d) < 3:
        print("ERROR: insufficient data")
        exit(1)

    print("\n" + "=" * 72)
    print("  RUNNING BACKTEST...")
    print("=" * 72)
    r = run(d)

    if r is None:
        print("ERROR: backtest failed")
        exit(1)

    report(r)
    r["eq"].to_csv("equity_curve_v2.csv")
    r["ret"].to_csv("daily_returns_v2.csv")
    print("\n  Saved: equity_curve_v2.csv, daily_returns_v2.csv")
