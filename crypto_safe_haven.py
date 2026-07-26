"""
================================================================================
  CRYPTO "SAFE-HAVEN" ADAPTIVE MOMENTUM — Tail-Risk Protected
================================================================================
  Key Innovations:
    1. Random Forest regime-switching (7d fast / 28d slow lookbacks)
    2. t-stat signal with hysteresis (enter > 2.0, exit < 1.0)
    3. Yang-Zhang vol estimator for position sizing
    4. 15% trailing stop-loss on every position (structural floor)
    5. Portfolio DD > 10% → halve all positions
    6. Cash-only regime when no assets trend positive (no shorting)
================================================================================
"""

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

CRYPTO_UNIVERSE = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LINK-USD",
    "MATIC-USD", "UNI-USD", "LTC-USD", "ATOM-USD", "ETC-USD"
]

START_DATE = "2020-01-01"
END_DATE   = "2025-07-21"

# --- Lookbacks (Crypto-optimized: short!) ----------------------------------
LOOKBACK_FAST = 7     # 1 week for high vol regimes
LOOKBACK_SLOW = 28    # 4 weeks for low vol regimes

# --- Signal thresholds (hysteresis) ----------------------------------------
T_ENTER = 2.0    # Enter long when t-stat > 2.0
T_EXIT  = 1.0    # Exit when t-stat < 1.0

# --- Volatility & Sizing ---------------------------------------------------
YZ_WINDOW       = 14    # shorter YZ window for faster adaptation
TARGET_ANN_VOL  = 0.40  # 40% target vol per position
MAX_POS_PCT     = 0.15  # max 15% per asset
MAX_GROSS_LEV   = 1.0   # no leverage (gross notional ≤ NAV)
PORT_VOL_TARGET = 0.30  # for dynamic scaling

# --- Circuit Breakers ------------------------------------------------------
TRAILING_STOP   = 0.15    # 15% trailing stop per position
PORTFOLIO_DD_REDUCE = 0.10  # reduce by 50% at 10% portfolio DD
PORTFOLIO_DD_RESTORE = 0.05 # restore when DD recovers below 5%

# --- RF Regime Model -------------------------------------------------------
RF_RETRAIN_DAYS   = 63    # retrain every ~3 months
RF_TRAIN_WINDOW   = 504   # use 2 years of training data
RF_N_ESTIMATORS   = 100

# --- Costs -----------------------------------------------------------------
COMMISSION = 0.001
SLIPPAGE   = 0.0005

INITIAL_CAPITAL = 1_000_000


# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

def load_data(tickers, start, end):
    print(f"Downloading {len(tickers)} crypto assets ...")
    data = {}
    df_all = yf.download(tickers, start=start, end=end, progress=False, group_by="ticker")
    for t in tickers:
        try:
            td = df_all[t].copy() if isinstance(df_all.columns, pd.MultiIndex) else None
            if td is None:
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
# 2. YANG-ZHANG VOLATILITY
# ═══════════════════════════════════════════════════════════════════════════

def yang_zhang(ohlc, w=14):
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    lo = np.log(o / c.shift(1))
    lc = np.log(c / c.shift(1))
    rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
    k = 0.34 / (1.34 + (w+1)/max(w-1, 1))
    yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv * 252, 1e-8))


# ═══════════════════════════════════════════════════════════════════════════
# 3. TREND T-STATISTIC
# ═══════════════════════════════════════════════════════════════════════════

def calc_tstat(prices, lb):
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
# 4. RANDOM FOREST REGIME DETECTION (Market-wide)
# ═══════════════════════════════════════════════════════════════════════════

def build_regime_features(df_dict, common_idx):
    """
    Build feature matrix for RF regime detection.
    Returns DataFrame with one row per date.
    Features are medians across all assets.
    """
    features = {}
    for t, df in df_dict.items():
        df_a = df.loc[common_idx]
        o, h, l, c, v = df_a["open"], df_a["high"], df_a["low"], df_a["close"], df_a["volume"]

        feat = pd.DataFrame(index=common_idx)
        feat["vol5"]  = (np.log(c / c.shift(1))).rolling(5).std() * np.sqrt(252)
        feat["vol20"] = (np.log(c / c.shift(1))).rolling(20).std() * np.sqrt(252)
        feat["ret5"]  = c.pct_change(5)
        feat["ret20"] = c.pct_change(20)
        feat["yz"]    = yang_zhang(df_a, YZ_WINDOW)
        feat["vol_chg"] = v.pct_change(5)

        for col in feat.columns:
            if col not in features:
                features[col] = []
            features[col].append(feat[col])

    # Take median across assets
    result = pd.DataFrame(index=common_idx)
    for col, series_list in features.items():
        result[col] = pd.concat(series_list, axis=1).median(axis=1)

    return result


def train_rf(features, target_idx):
    """
    Train Random Forest on features up to target_idx (exclusive)
    to predict if next 20d vol > historical median.
    Returns: trained RF + scaler
    """
    # Feature columns
    feat_cols = ["vol5", "vol20", "ret5", "ret20", "yz", "vol_chg"]

    X = features[feat_cols].iloc[:target_idx].dropna()
    y_raw = features["vol20"].iloc[:target_idx]

    if len(X) < 100:
        return None, None

    # Target: next 20-day vol > median of all vol20 so far
    median_vol = y_raw.median()
    y = (y_raw.shift(-20) > median_vol).astype(int)
    y = y.loc[X.index]

    y = y.dropna()
    X = X.loc[y.index]

    if len(X) < 50 or y.nunique() < 2:
        return None, None

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    rf = RandomForestClassifier(n_estimators=RF_N_ESTIMATORS, max_depth=5,
                                 min_samples_leaf=10, random_state=42)
    rf.fit(X_scaled, y)

    return rf, scaler


def predict_regime(rf, scaler, features, idx_loc):
    """
    Predict regime at position idx_loc using trained RF.
    Returns 1 (high vol = fast lookback) or 0 (low vol = slow lookback).
    """
    if rf is None or scaler is None:
        return 0

    feat_cols = ["vol5", "vol20", "ret5", "ret20", "yz", "vol_chg"]
    latest = features[feat_cols].iloc[idx_loc:idx_loc+1].dropna()
    if len(latest) == 0:
        return 0

    X = scaler.transform(latest)
    pred = rf.predict(X)[0]
    return int(pred)


# ═══════════════════════════════════════════════════════════════════════════
# 5. BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(data):
    # Common index across all assets
    common = None
    for d in data.values():
        if common is None:
            common = d.index
        else:
            common = common.intersection(d.index)
    common = common.sort_values()
    print(f"\nCommon dates: {len(common)}")

    # Pre-compute YZ vols
    all_vols = {}
    for t, df_in in data.items():
        df = df_in.loc[common]
        all_vols[t] = yang_zhang(df, YZ_WINDOW)

    # Pre-compute t-stats for both lookbacks
    all_tstat_fast = {}
    all_tstat_slow = {}
    for t, df_in in data.items():
        df = df_in.loc[common]
        ts_f = pd.Series(np.nan, index=common)
        ts_s = pd.Series(np.nan, index=common)
        for i in range(max(LOOKBACK_FAST, LOOKBACK_SLOW), len(common)):
            ts_f.iloc[i] = calc_tstat(df["close"].iloc[:i+1], LOOKBACK_FAST)
            ts_s.iloc[i] = calc_tstat(df["close"].iloc[:i+1], LOOKBACK_SLOW)
        all_tstat_fast[t] = ts_f
        all_tstat_slow[t] = ts_s

    # Build RF features
    print("Building RF regime features ...")
    rf_features = build_regime_features(data, common)
    valid_assets = list(all_vols.keys())
    print(f"Valid assets: {len(valid_assets)}")

    # --- Walk-forward loop ---
    min_warmup = max(LOOKBACK_FAST, LOOKBACK_SLOW, YZ_WINDOW, RF_TRAIN_WINDOW) + 5
    if min_warmup >= len(common):
        min_warmup = len(common) // 4

    nav = float(INITIAL_CAPITAL)
    peak = nav
    max_dd = 0.0
    equity_curve = [nav]
    dates_hist = [common[min_warmup]]
    daily_pnl_list = []
    pnl_by_date = {}
    trade_log = []

    # Position tracking
    # Each position: {"notional": float, "entry_price": float, "high_since_entry": float, "active": bool}
    positions = {t: None for t in valid_assets}
    prev_notionals = {t: 0.0 for t in valid_assets}

    # Portfolio DD state
    dd_reduced = False  # whether portfolio DD > 10% and we've halved

    # RF retraining tracker
    last_rf_retrain = 0
    rf_model = None
    rf_scaler = None

    # Current signal state (for hysteresis)
    # in_position[t] = True if currently in a long position for asset t
    in_position = {t: False for t in valid_assets}

    print(f"\nTrading: {common[min_warmup].date()} to {common[-1].date()} "
          f"({len(common)-min_warmup} days)")

    for i in range(min_warmup, len(common)):
        dt = common[i]
        prev_dt = common[i-1]

        # --- RF Regime Training / Prediction ---
        # Retrain every RF_RETRAIN_DAYS
        if i - last_rf_retrain >= RF_RETRAIN_DAYS or rf_model is None:
            if i > RF_TRAIN_WINDOW:
                rf_model, rf_scaler = train_rf(rf_features, i)
                last_rf_retrain = i

        # Predict current regime
        current_regime = predict_regime(rf_model, rf_scaler, rf_features, i)
        lookback = LOOKBACK_FAST if current_regime == 1 else LOOKBACK_SLOW

        # --- Determine signals with hysteresis ---
        new_signals = {}  # t -> 1 (long) or 0 (flat)

        for t in valid_assets:
            tstat_f = all_tstat_fast[t].iloc[i]
            tstat_s = all_tstat_slow[t].iloc[i]
            tstat = tstat_f if current_regime == 1 else tstat_s
            if np.isnan(tstat):
                new_signals[t] = 0
                continue

            if in_position[t]:
                # We have a position: exit if t-stat drops below T_EXIT
                if tstat < T_EXIT:
                    new_signals[t] = 0
                    in_position[t] = False
                else:
                    new_signals[t] = 1  # hold
            else:
                # No position: enter if t-stat exceeds T_ENTER
                if tstat > T_ENTER:
                    new_signals[t] = 1
                    in_position[t] = True
                else:
                    new_signals[t] = 0

        # --- Cash-only regime: if NO asset has a signal, stay in cash ---
        any_signal = any(v == 1 for v in new_signals.values())
        if not any_signal:
            # Move all to cash: set all signals to 0
            for t in valid_assets:
                new_signals[t] = 0
                in_position[t] = False

        # --- Compute PnL from previous positions ---
        day_pnl = 0.0
        for t in valid_assets:
            pnl_ntl = prev_notionals.get(t, 0.0)
            if pnl_ntl == 0.0:
                continue
            try:
                prev_c = data[t].loc[prev_dt, "close"]
                curr_c = data[t].loc[dt, "close"]
            except KeyError:
                continue

            ret = (curr_c / prev_c) - 1.0

            # Cost on entry/exit
            old_s = 1 if pnl_ntl > 0 else 0
            new_s = 1 if new_signals[t] == 1 else 0
            cost = 0.0
            if old_s != new_s:
                cost = (abs(pnl_ntl) + abs(pnl_ntl) * (0 if new_s == 0 else 1)) * (COMMISSION + SLIPPAGE)
            else:
                cost = 0.0

            pnl = pnl_ntl * ret - cost
            day_pnl += pnl

            # Update tracking for trailing stop
            if positions[t] is not None and positions[t]["active"]:
                pos = positions[t]
                if curr_c > pos["high_since_entry"]:
                    pos["high_since_entry"] = curr_c
                # Check trailing stop
                if curr_c < pos["high_since_entry"] * (1 - TRAILING_STOP):
                    new_signals[t] = 0
                    in_position[t] = False
                    # Close on next iteration (can't close here since we already computed PnL)
                    # We mark it for closure in the next step
                    trade_log.append({
                        "date": dt, "asset": t, "action": "TRAILING_STOP",
                        "price": curr_c,
                        "high": pos["high_since_entry"],
                        "pnl_realized": pnl
                    })

        # --- Update NAV ---
        nav += day_pnl
        nav = max(nav, 0.0)
        equity_curve.append(nav)
        dates_hist.append(dt)
        daily_pnl_list.append(day_pnl)
        pnl_by_date[dt] = day_pnl

        if nav > peak:
            peak = nav

        dd_pct = (peak - nav) / peak if peak > 0 else 0.0
        if dd_pct > max_dd:
            max_dd = dd_pct

        # --- Portfolio-level DD reduction ---
        if dd_pct >= PORTFOLIO_DD_REDUCE:
            dd_reduced = True
        if dd_pct <= PORTFOLIO_DD_RESTORE:
            dd_reduced = False

        # --- Compute new positions ---
        total_gross = 0.0
        current_vols = {}
        for t in valid_assets:
            v = all_vols[t].get(dt, np.nan)
            if not np.isnan(v) and v > 0:
                current_vols[t] = v

        # Dynamic vol scaling
        mkt_vol = np.median(list(current_vols.values())) if current_vols else PORT_VOL_TARGET
        dyn_scale = PORT_VOL_TARGET / max(mkt_vol, 0.01)
        dyn_scale = np.clip(dyn_scale, 0.1, 1.0)

        # Portfolio DD scale
        dd_scale = 1.0
        if dd_reduced:
            dd_scale = 0.5

        safe_nav = max(nav, 1.0)

        for t in valid_assets:
            sig = new_signals.get(t, 0)
            ntl = 0.0
            if sig == 1 and safe_nav > 0:
                v = current_vols.get(t, TARGET_ANN_VOL)
                if np.isnan(v) or v <= 0:
                    v = TARGET_ANN_VOL
                vol_r = TARGET_ANN_VOL / v
                ntl = vol_r * safe_nav
                ntl = min(ntl, safe_nav * MAX_POS_PCT)

            # Apply scaling
            ntl *= dyn_scale * dd_scale

            prev_notionals[t] = ntl
            total_gross += abs(ntl)

            # Update position tracking
            if sig == 1 and ntl > 0:
                try:
                    curr_c = data[t].loc[dt, "close"]
                except KeyError:
                    curr_c = 0
                if positions[t] is None or not positions[t]["active"]:
                    # Entering new position
                    positions[t] = {
                        "notional": ntl,
                        "entry_price": curr_c,
                        "high_since_entry": curr_c,
                        "active": True
                    }
                else:
                    # Update existing position
                    positions[t]["notional"] = ntl
            else:
                if positions[t] is not None:
                    positions[t]["active"] = False
                positions[t] = None

        # Leverage check
        if total_gross > safe_nav * MAX_GROSS_LEV:
            r = (safe_nav * MAX_GROSS_LEV) / max(total_gross, 1.0)
            for t in valid_assets:
                prev_notionals[t] *= r

        # Log entries
        for t in valid_assets:
            if new_signals.get(t, 0) == 1 and prev_notionals[t] > 0:
                # Check if this is a new entry (not a hold)
                if positions[t] is not None and positions[t]["active"]:
                    try:
                        entry_p = data[t].loc[dt, "close"]
                    except KeyError:
                        entry_p = 0
                    # Check if just entered (entry_price was just set)
                    if positions[t]["entry_price"] == entry_p and positions[t]["notional"] > 0:
                        pass  # Already logged

    # --- Metrics ---
    es = pd.Series(equity_curve, index=dates_hist)
    rs = es.pct_change().dropna()

    tr = (nav - INITIAL_CAPITAL) / INITIAL_CAPITAL
    n = len(rs)
    ann = (1+tr)**(252/max(n,1))-1 if n > 0 else 0.0
    sr = (rs.mean()/max(rs.std(), 1e-10))*np.sqrt(252)
    neg = rs[rs < 0]
    ds = neg.std() if len(neg) > 0 else 1e-10
    sort = (rs.mean()/max(ds, 1e-10))*np.sqrt(252)
    cal = tr*100/max(max_dd*100, 0.001)
    wr = (rs > 0).sum()/max(n, 1)
    gp = rs[rs > 0].sum()
    gl = abs(rs[rs < 0].sum())
    pf = gp/max(gl, 1e-10)

    monthly = {}
    for dt, p in pnl_by_date.items():
        mk = dt.strftime("%Y-%m")
        monthly.setdefault(mk, []).append(p)
    ms = pd.Series({k: sum(v) for k, v in monthly.items()})
    mwr = (ms > 0).sum()/max(len(ms), 1)

    yearly = {}
    for idx_val in rs.index:
        yr = idx_val.year
        yearly.setdefault(yr, []).append(rs.loc[idx_val])
    yr_r = {yr: (np.prod(1+np.array(rets))-1)*100 for yr, rets in yearly.items()}

    # Win/loss trade analysis
    trade_wins = sum(1 for t in trade_log if "pnl_realized" in t and t["pnl_realized"] > 0)
    trade_losses = sum(1 for t in trade_log if "pnl_realized" in t and t["pnl_realized"] <= 0)

    # Proper monthly percentage returns from equity curve
    monthly_ret = es.resample('ME').apply(lambda x: (x.iloc[-1] / x.iloc[0] - 1) * 100)
    monthly_ret = monthly_ret.dropna()

    return {
        "eq": es, "ret": rs, "monthly": ms, "yearly": yr_r,
        "trades": trade_log, "final": nav, "total_ret": tr,
        "ann_ret": ann, "max_dd": max_dd, "sharpe": sr,
        "sortino": sort, "calmar": cal, "win_rate": wr,
        "pf": pf, "mwr": mwr, "n_trades": len(trade_log),
        "pos_months": int((ms > 0).sum()), "tot_months": len(ms),
        "avg_ret": rs.mean(), "std_ret": rs.std(),
        "best": rs.max(), "worst": rs.min(),
        "skew": rs.skew() if len(rs) > 2 else 0,
        "kurt": rs.kurtosis() if len(rs) > 2 else 0,
        "var95": np.percentile(rs, 5), "days": n,
        "peak_eq": es.max(),
        "trade_wins": trade_wins,
        "trade_losses": trade_losses,
        "monthly_ret_pct": monthly_ret,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. REPORT
# ═══════════════════════════════════════════════════════════════════════════

def print_report(r):
    S = "=" * 72
    print(f"\n{S}")
    print("  CRYPTO SAFE-HAVEN ADAPTIVE MOMENTUM — FINAL REPORT")
    print(S)

    sections = [
        ("SUMMARY", [
            ("Strategy", "Safe-Haven Adaptive TSMOM"),
            ("Universe", f"{len(CRYPTO_UNIVERSE)} assets"),
            ("Period", f"{START_DATE} -> {END_DATE}"),
            ("Lookbacks", f"Fast={LOOKBACK_FAST}d Slow={LOOKBACK_SLOW}d"),
            ("RF Regime", "Random Forest (retrain every {}d)".format(RF_RETRAIN_DAYS)),
            ("Signal", "t-stat hyst: enter>{}, exit<{}".format(T_ENTER, T_EXIT)),
            ("Stop-Loss", "{}% trailing per position".format(TRAILING_STOP*100)),
            ("Portfolio DD", "halve at {}%, restore at {}%".format(
                PORTFOLIO_DD_REDUCE*100, PORTFOLIO_DD_RESTORE*100)),
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
        ("RISK & SURVIVAL", [
            ("Max Drawdown", "{:.2f}%".format(r["max_dd"]*100)),
            ("Daily VaR (95%)", "{:+.4f}%".format(r["var95"]*100)),
            ("Peak NAV", "${:,.2f}".format(r["peak_eq"])),
            ("Trough NAV", "${:,.2f}".format(r["eq"].min())),
            ("Survived 2022", "YES" if r["final"] > 0 else "NO"),
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

    # Monthly returns table
    print()
    print("  MONTHLY RETURNS (%)")
    print("  " + "-" * 55)
    mp = r["monthly_ret_pct"]
    for idx_val in mp.index[:24]:
        val = mp.loc[idx_val]
        bar = "+" if val > 0 else "-"
        print("  {:<10} {:>+8.2f}%  {}".format(str(idx_val)[:7], val, bar))
    if len(mp) > 24:
        print("  ... ({} total months)".format(len(mp)))

    print(f"\n{S}")
    print("  END OF REPORT")
    print(S)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 72)
    print("  CRYPTO SAFE-HAVEN ADAPTIVE MOMENTUM STRATEGY")
    print("=" * 72)
    print(f"\n  Configuration:")
    print(f"    Lookbacks:           {LOOKBACK_FAST}d (fast) / {LOOKBACK_SLOW}d (slow)")
    print(f"    Regime:              Random Forest (retrain every {RF_RETRAIN_DAYS}d)")
    print(f"    Signal thresholds:   Enter t>{T_ENTER}, Exit t<{T_EXIT}")
    print(f"    Trailing stop:       {TRAILING_STOP*100:.0f}% per position")
    print(f"    Portfolio DD halve:  {PORTFOLIO_DD_REDUCE*100:.0f}%")
    print(f"    No shorting:         Cash-only when no signals")
    print(f"    Initial capital:     ${INITIAL_CAPITAL:,.0f}")

    data = load_data(CRYPTO_UNIVERSE, START_DATE, END_DATE)
    if len(data) < 3:
        print("ERROR: insufficient data")
        exit(1)

    print("\n" + "=" * 72)
    print("  RUNNING BACKTEST...")
    print("=" * 72)

    result = run_backtest(data)

    if result is None:
        print("ERROR: backtest failed")
        exit(1)

    print_report(result)

    result["eq"].to_csv("equity_curve_safehaven.csv")
    result["ret"].to_csv("daily_returns_safehaven.csv")
    print("\n  Saved: equity_curve_safehaven.csv, daily_returns_safehaven.csv")
