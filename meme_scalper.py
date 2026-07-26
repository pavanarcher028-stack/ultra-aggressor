"""
MEME SCALPER — 1k INR to Lacs in Months
=========================================
High-frequency scalping on 1h DOGE/SOL/ADA/AVAX using DONCH + TSMOM signals.
Compounds aggressively. Run daily, get BUY/SELL/HOLD signals.
"""
import pickle, numpy as np, pandas as pd, math, json, os, warnings
warnings.filterwarnings('ignore')

# --- CONFIG ---
INITIAL_CAP = 1000     # INR
TARGET_CAP = 100000    # 1 Lac INR
RISK_PER_TRADE = 0.30  # 30% of capital per trade
STOP_LOSS = 0.04       # 4% stop
PROFIT_TIERS = [0.03, 0.06, 0.10, 0.18]
TRAIL_ACTIVATE = 0.05  # activate trailing at 5% profit
TRAIL_DIST = 0.025     # trail by 2.5%

# Best signals from backtest validation
STRATEGIES = {
    'DOGE-USD': ('donchian', {'p': 30}, 'ema', {'fast': 5, 'slow': 21}),
    'SOL-USD':  ('tsmom',    {'lb': 36, 'entry': 0.7}, 'ema', {'fast': 5, 'slow': 21}),
    'ADA-USD':  ('tsmom',    {'lb': 36, 'entry': 0.7}, None,  None),
    'AVAX-USD': ('tsmom',    {'lb': 36, 'entry': 0.7}, None,  None),
}

# --- LOAD DATA ---
def _flatten(d):
    if isinstance(d.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: d[c].values.ravel() for c in d.columns}, index=d.index)
    return d

def load_1h():
    with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample('1h').first(); h = d['High'].resample('1h').max()
        l = d['Low'].resample('1h').min(); c = d['Close'].resample('1h').last()
        v = d['Volume'].resample('1h').sum()
        dfs[t] = pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v}, index=o.index)
    common = sorted(set.intersection(*[set(df.index) for df in dfs.values()]))
    return {t: dfs[t].loc[common] for t in dfs}, common

def ema(s, p): return s.ewm(span=p).mean()

# --- SIGNALS ---
def gen_signal(df, kind, params):
    c = df['close'].values; n = len(c); sig = np.zeros(n)
    if kind == 'donchian':
        p = params.get('p', 30)
        h = df['high'].rolling(p).max().values
        l = df['low'].rolling(p).min().values
        for i in range(1, n):
            if c[i] > h[i-1]: sig[i] = 1.0
            elif c[i] < l[i-1]: sig[i] = -1.0
    elif kind == 'tsmom':
        lb = params.get('lb', 36); entry = params.get('entry', 0.7)
        for i in range(lb, n):
            y = np.log(c[i-lb:i]); x = np.arange(lb)
            xm, ym = x.mean(), y.mean()
            beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
            resid = y - (ym + beta*(x-xm))
            se = np.sqrt(np.sum(resid**2) / max(lb-2,1))
            se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
            ts = beta / se_b if se_b > 0 else 0
            sig[i] = 1.0 if ts > entry else (-1.0 if ts < -entry else 0)
    return sig

def gen_with_confirmation(df, prim_kind, prim_params, conf_kind, conf_params):
    psig = gen_signal(df, prim_kind, prim_params)
    if conf_kind is None: return psig
    csig = gen_signal(df, conf_kind, conf_params)
    return psig * csig  # both agree

# --- SCALPING BACKTEST (1h, compounding) ---
def scalping_backtest(cv, sig):
    n = len(cv); eq = INITIAL_CAP; peak = INITIAL_CAP
    eqs = np.ones(n) * INITIAL_CAP
    trades, wins = 0, 0
    in_pos = False; pos_dir = 0; entry_p = 0; peak_p = 0

    for i in range(1, n):
        s = sig[i]
        if np.isnan(s) or np.isinf(s): continue
        if not in_pos and abs(s) > 0.5:
            entry_p = cv[i]; peak_p = cv[i]
            pos_dir = 1 if s > 0 else -1
            in_pos = True; continue

        if in_pos:
            ret = (cv[i] / entry_p - 1) * pos_dir
            if ret > 0: peak_p = max(peak_p, cv[i])

            exited = False
            # Stop loss
            if ret < -STOP_LOSS:
                eq *= (1 + ret * RISK_PER_TRADE)
                trades += 1; wins += 1 if ret > 0 else 0; exited = True
            # Trailing stop
            elif ret > TRAIL_ACTIVATE:
                if (pos_dir > 0 and cv[i] < peak_p * (1 - TRAIL_DIST)) or \
                   (pos_dir < 0 and cv[i] > peak_p * (1 + TRAIL_DIST)):
                    eq *= (1 + ret * RISK_PER_TRADE)
                    trades += 1; wins += 1 if ret > 0 else 0; exited = True
            # Take profit
            if not exited:
                for tp in PROFIT_TIERS:
                    if ret >= tp:
                        eq *= (1 + tp * RISK_PER_TRADE / len(PROFIT_TIERS))
                        trades += 1; wins += 1; exited = True; break
            # Reversal
            if not exited and abs(s) > 0.5 and (s * pos_dir < 0):
                eq *= (1 + ret * RISK_PER_TRADE * 0.5)
                trades += 1; wins += 1 if ret > 0 else 0; exited = True

            if exited: in_pos = False; pos_dir = 0

        eqs[i] = eq; peak = max(peak, eq)

    rets = pd.Series(np.diff(np.log(np.maximum(eqs, 1)))).dropna()
    tr = eqs[-1] / INITIAL_CAP - 1
    ny = max(n / (365*24), 0.1)
    ann = (1+tr)**(1/ny)-1 if tr > -1 else -0.99
    sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*24)
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades,1)
    return {'eqs':eqs,'final_eq':float(eqs[-1]),'trades':trades,'wins':wins,
            'wr':wr,'sr':sr,'ann':ann,'dd':dd,'tr':tr}

# --- COMPOUNDING SIMULATOR ---
def simulate(wr, avg_win=0.04, avg_loss=0.03, trades_per_day=3, days=180):
    runs = 500
    eqs = np.ones((runs, days+1)) * INITIAL_CAP
    for r in range(runs):
        eq = INITIAL_CAP
        for d in range(days):
            for _ in range(trades_per_day):
                w = np.random.random() < wr
                ret = avg_win if w else -avg_loss
                eq *= (1 + ret * RISK_PER_TRADE)
            eqs[r, d+1] = eq
    return eqs

# ====================================================================
# MAIN
# ====================================================================
if __name__ == '__main__':
    print("=" * 72)
    print("  MEME SCALPER — 1k INR to Lacs in Months")
    print("  1h Scalping | DONCH + TSMOM + EMA Confirmation")
    print("=" * 72)

    data, idx = load_1h()
    print(f"\n  Data: {len(idx)} 1h bars ({len(idx)//24:.0f} days) for {len(data)} coins\n")

    # Phase 1: Backtest each coin
    print(f"  {'Coin':<10} {'Trades':>8} {'WR':>8} {'SR':>8} {'Ann%':>8} {'DD%':>8} {'Final(INR)':>12}")
    print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")

    results = []
    for ticker in ['DOGE-USD','SOL-USD','ADA-USD','AVAX-USD']:
        if ticker not in data: continue
        prim_kind, prim_params, conf_kind, conf_params = STRATEGIES[ticker]
        sig = gen_with_confirmation(data[ticker], prim_kind, prim_params, conf_kind, conf_params)
        r = scalping_backtest(data[ticker]['close'].values, sig)
        if r and r['trades'] > 0:
            print(f"  {ticker:<10} {r['trades']:>8d} {r['wr']*100:>7.1f}% "
                  f"{r['sr']:>8.2f} {r['ann']*100:>7.1f}% {r['dd']*100:>7.1f}% "
                  f"Rs{r['final_eq']:>9.0f}")
            results.append((ticker, r))

    results.sort(key=lambda x: x[1]['sr'], reverse=True)
    if not results:
        print("\n  No valid results. Check data."); exit()

    best_ticker, best = results[0]
    print(f"\n  >> BEST: {best_ticker} — WR={best['wr']*100:.1f}% SR={best['sr']:.2f}")

    # Phase 2: Compounding simulation
    print(f"\n{'='*72}")
    print(f"  COMPOUNDING SIMULATION: Rs{INITIAL_CAP} -> Rs{TARGET_CAP}")
    print(f"  Based on {best_ticker} ({best['trades']} hist trades, WR={best['wr']*100:.1f}%)")
    print(f"{'='*72}")

    eqs = simulate(best['wr'], avg_win=0.04, avg_loss=0.03, days=180)
    med = np.median(eqs, axis=0)
    p75 = np.percentile(eqs, 75, axis=0)
    p25 = np.percentile(eqs, 25, axis=0)

    hit_target = np.sum(eqs[:,-1] >= TARGET_CAP) / eqs.shape[0] * 100
    avg_days = 0; count = 0
    for r in range(eqs.shape[0]):
        for d in range(eqs.shape[1]):
            if eqs[r, d] >= TARGET_CAP:
                avg_days += d; count += 1; break
    avg_days = avg_days / max(count, 1)

    print(f"\n  500 simulations, 180 trading days (~9 months):")
    print(f"    Hit Rs{TARGET_CAP:,}: {hit_target:.0f}% of runs")
    print(f"    Avg time to target: {avg_days:.0f} days ({avg_days/22:.1f} months)")
    print(f"    Final: Median=Rs{med[-1]:,.0f}, P25=Rs{p25[-1]:,.0f}, P75=Rs{p75[-1]:,.0f}")
    print(f"    Required daily ROI to hit target: {(TARGET_CAP/INITIAL_CAP)**(1/180)-1:.4f} ({((TARGET_CAP/INITIAL_CAP)**(1/180)-1)*100:.2f}%/day)")

    # Phase 3: Live signals
    print(f"\n{'='*72}")
    print(f"  LIVE SIGNALS (LAST 5 BARS)")
    print(f"{'='*72}")

    for ticker in ['DOGE-USD','SOL-USD','ADA-USD','AVAX-USD']:
        if ticker not in data: continue
        prim_kind, prim_params, conf_kind, conf_params = STRATEGIES[ticker]
        sig = gen_with_confirmation(data[ticker], prim_kind, prim_params, conf_kind, conf_params)
        last5 = sig[-5:]; price = data[ticker]['close'].values[-1]
        sig_str = ''.join(['B' if s > 0.5 else ('S' if s < -0.5 else '.') for s in last5])
        action = 'BUY' if last5[-1] > 0.5 else ('SELL' if last5[-1] < -0.5 else 'HOLD')
        print(f"  {ticker:<10} ${price:<8.2f}  {sig_str}  -> {action}")

    # Phase 4: Save
    np.savetxt('scalper_equity_median.csv', med, delimiter=',')
    out = {'best_ticker': best_ticker, 'wr': best['wr'], 'sr': best['sr'],
           'hit_target_pct': hit_target, 'avg_days_to_target': avg_days}
    with open('scalper_results.json', 'w') as f: json.dump(out, f, indent=2)
    print(f"\n  Saved: scalper_results.json, scalper_equity_median.csv")

    # Phase 5: Loop-ready output
    print(f"\n{'='*72}")
    print(f"  TRADE PLAN — Compounding Loop Ready")
    print(f"{'='*72}")
    print(f"""
  HOW TO USE:
    1. Check signals daily (above)
    2. For each BUY signal: enter with {RISK_PER_TRADE*100:.0f}% of capital, stop at -{STOP_LOSS*100:.0f}%
    3. Take profit at {PROFIT_TIERS[0]*100:.0f}%/{PROFIT_TIERS[1]*100:.0f}%/{PROFIT_TIERS[2]*100:.0f}%/{PROFIT_TIERS[3]*100:.0f}%
    4. Compound ALL profits back into next trade
    5. Run this script daily to get updated signals

  EXPECTED:
    - Win rate: {best['wr']*100:.0f}%+ on {best_ticker}
    - Trades per day: 2-4
    - Rs{INITIAL_CAP} -> Rs{TARGET_CAP:,} in {avg_days:.0f} days avg
    """)
