"""
================================================================================
  CRYPTO TSMOM v3 — Optimized Parameters (Medium lookback, lower t-stat)
================================================================================
  - Single 60-day lookback (no regime switching for simplicity)
  - T-stat threshold: 1.0 (more frequent signals)
  - Both long & short with improved sizing
  - Progressive position sizing based on |t-stat| strength
================================================================================
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

START_DATE = "2020-01-01"
END_DATE   = "2025-07-21"

LOOKBACK      = 63    # 3 months
T_STAT_MIN    = 0.5   # minimum |t| for any position
T_STAT_FULL   = 2.0   # |t| for full-sized position
YZ_WINDOW     = 20
TARGET_VOL    = 0.40
MAX_POS       = 0.20  # 20% per asset
MAX_LEV       = 1.5
PORT_VOL_TARGET = 0.30
COMMISSION    = 0.001
SLIPPAGE      = 0.0005
INIT_CAP      = 1_000_000


def load(tickers, start, end):
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


def yz_vol(ohlc, w=20):
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    lo = np.log(o / c.shift(1))
    lc = np.log(c / c.shift(1))
    rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
    k = 0.34 / (1.34 + (w+1)/(w-1))
    yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv * 252, 1e-8))


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


def position_strength(t_stat):
    """Convert t-stat to position strength [0, 1]."""
    abs_t = abs(t_stat)
    if abs_t <= T_STAT_MIN:
        return 0.0
    if abs_t >= T_STAT_FULL:
        return 1.0
    return (abs_t - T_STAT_MIN) / (T_STAT_FULL - T_STAT_MIN)


def run(data):
    common = None
    for d in data.values():
        if common is None:
            common = d.index
        else:
            common = common.intersection(d.index)
    common = common.sort_values()
    print(f"Common dates: {len(common)}")

    sigs = {}
    vols = {}
    for t, df_in in data.items():
        df = df_in.loc[common].copy()
        if len(df) < 100:
            continue
        vols[t] = yz_vol(df, YZ_WINDOW)
        s = pd.Series(0.0, index=common)
        for i in range(LOOKBACK+5, len(common)):
            prices = df["close"].iloc[i-LOOKBACK:i+1]
            ts = trend_tstat(prices, LOOKBACK)
            strength = position_strength(ts)
            s.iloc[i] = np.sign(ts) * strength if strength > 0 else 0.0
        sigs[t] = s.shift(1)

    valid = [t for t in sigs if sigs[t].notna().sum() > 50]
    print(f"Valid: {len(valid)}")

    warmup = LOOKBACK + YZ_WINDOW + 5
    if warmup >= len(common):
        warmup = len(common) // 4

    nav = float(INIT_CAP)
    peak = nav
    max_dd = 0.0
    eq = [nav]
    dates = [common[warmup]]
    pnls = []
    pnl_by_date = {}
    tlog = []
    ntl = {t: 0.0 for t in valid}
    prev = {t: 0.0 for t in valid}

    print(f"Trading: {common[warmup].date()} to {common[-1].date()} ({len(common)-warmup} days)")

    for i in range(warmup, len(common)):
        dt = common[i]
        pd_dt = common[i-1]

        # PnL from prev positions
        day_pnl = 0.0
        for t in valid:
            pn = prev.get(t, 0.0)
            if pn == 0.0:
                continue
            try:
                pc = data[t].loc[pd_dt, "close"]
                cc = data[t].loc[dt, "close"]
            except:
                continue
            ret = (cc / pc) - 1.0
            old_s = np.sign(pn)
            new_s = np.sign(ntl[t]) if ntl[t] != 0 else 0
            cost = 0.0
            if old_s != new_s:
                cost = (abs(pn)+abs(ntl[t]))*(COMMISSION+SLIPPAGE)
            borrow = 0.0
            if pn < 0:
                borrow = abs(pn) * 0.05 / 252
            day_pnl += pn * ret - cost - borrow

        nav += day_pnl
        nav = max(nav, 0.0)
        eq.append(nav)
        dates.append(dt)
        pnls.append(day_pnl)
        pnl_by_date[dt] = day_pnl

        if nav > peak:
            peak = nav
        dd = (peak-nav)/peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

        # Dynamic scale from market vol
        cur_vols = {}
        for t in valid:
            v = vols[t].get(dt, np.nan)
            if not np.isnan(v) and v > 0:
                cur_vols[t] = v
        mkt_vol = np.median(list(cur_vols.values())) if cur_vols else PORT_VOL_TARGET
        scale = PORT_VOL_TARGET / max(mkt_vol, 0.01)
        scale = np.clip(scale, 0.1, 1.0)

        safe = max(nav, 0.0)
        total_gross = 0.0
        for t in valid:
            sig = sigs[t].get(dt, 0.0)
            if np.isnan(sig):
                sig = 0.0
            v = cur_vols.get(t, TARGET_VOL)
            if np.isnan(v) or v <= 0:
                v = TARGET_VOL
            n = 0.0
            if abs(sig) > 0 and safe > 0:
                vol_r = TARGET_VOL / v
                n = sig * vol_r * safe
                # Cap position
                max_n = safe * MAX_POS
                n = np.clip(n, -max_n, max_n)
            n *= scale
            ntl[t] = n
            total_gross += abs(n)

        if total_gross > safe * MAX_LEV and safe > 0:
            r = (safe * MAX_LEV) / max(total_gross, 1.0)
            for t in valid:
                ntl[t] *= r

        for t in valid:
            o = np.sign(prev.get(t, 0))
            n = np.sign(ntl[t])
            if o != n and n != 0:
                tlog.append({"date": dt, "asset": t, "action": "LONG" if n>0 else "SHORT"})

        prev = dict(ntl)

    # Metrics
    es = pd.Series(eq, index=dates)
    rs = es.pct_change().dropna()
    tr = (nav - INIT_CAP) / INIT_CAP
    n = len(rs)
    ann = (1+tr)**(252/max(n,1))-1 if n > 0 else 0.0
    sr = (rs.mean()/max(rs.std(),1e-10))*np.sqrt(252)
    neg_r = rs[rs < 0]
    ds = neg_r.std() if len(neg_r) > 0 else 1e-10
    sort = (rs.mean()/max(ds,1e-10))*np.sqrt(252)
    cal = tr*100/max(max_dd*100, 0.001)
    wr = (rs > 0).sum()/max(n,1)
    gp = rs[rs > 0].sum()
    gl = abs(rs[rs < 0].sum())
    pf = gp/max(gl, 1e-10)

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
    yr_r = {yr: sum(rets)*100 for yr, rets in yearly.items()}

    return {
        "eq": es, "ret": rs, "monthly": ms, "yearly": yr_r,
        "trades": tlog, "final": nav, "total_ret": tr,
        "ann_ret": ann, "max_dd": max_dd, "sharpe": sr,
        "sortino": sort, "calmar": cal, "win_rate": wr,
        "pf": pf, "mwr": mwr, "n_trades": len(tlog),
        "pos_months": int((ms > 0).sum()), "tot_months": len(ms),
        "avg_ret": rs.mean(), "std_ret": rs.std(),
        "best": rs.max(), "worst": rs.min(),
        "skew": rs.skew() if len(rs) > 2 else 0,
        "kurt": rs.kurtosis() if len(rs) > 2 else 0,
        "var95": np.percentile(rs, 5), "days": n,
        "peak_eq": es.max(),
    }


def report(r):
    S = "=" * 72
    print(f"\n{S}")
    print("  CRYPTO TSMOM v3 — Medium Lookback, Progressive Sizing")
    print(S)

    sections = [
        ("SUMMARY", [
            ("Strategy", "TSMOM v3 (Long+Short, Progressive)"),
            ("Universe", f"{len(CRYPTO_UNIVERSE)} assets"),
            ("Period", f"{START_DATE} -> {END_DATE}"),
            ("Initial Capital", "${:,.0f}".format(INIT_CAP)),
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
            ("Excess Kurtosis", "{:.3f}".format(r["kurt"])),
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

    for title, items in sections:
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


if __name__ == "__main__":
    print("=" * 72)
    print("  CRYPTO TSMOM v3")
    print("=" * 72)
    print(f"\n  Lookback: {LOOKBACK}d | T-stat range: {T_STAT_MIN}-{T_STAT_FULL}")
    print(f"  Max pos: {MAX_POS*100:.0f}% | Leverage: {MAX_LEV}x")
    print(f"  Initial: ${INIT_CAP:,.0f}")

    d = load(CRYPTO_UNIVERSE, START_DATE, END_DATE)
    if len(d) < 3:
        print("FAILED: insufficient data"); exit(1)

    print("\n" + "=" * 72)
    print("  RUNNING BACKTEST...")
    print("=" * 72)
    r = run(d)
    if r is None:
        print("FAILED"); exit(1)

    report(r)
    r["eq"].to_csv("equity_curve_v3.csv")
    r["ret"].to_csv("daily_returns_v3.csv")
    print("\n  Saved: equity_curve_v3.csv, daily_returns_v3.csv")
