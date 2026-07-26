"""
MEME SWINGER — 1k INR to Lacs: Catch Big Pumps, Compound Fast
==============================================================
Strategy: Swing trade meme coins on 4h, catch 30-100% moves, tight stops.
- Low win rate (30-40%) but massive risk-reward (1:5 to 1:20)
- Full capital per trade (aggressive compounding)
- Exit only on stop-loss or trailing stop (let winners ride)

Target: 1k INR -> 1 Lac+ in 3-6 months by catching 3-5 big pumps
"""
import pickle, numpy as np, pandas as pd, math, json, os, warnings
warnings.filterwarnings('ignore')

INITIAL_CAP = 1000
TARGET_CAP = 100000
CAPITAL_PER_TRADE = 1.0   # 100% of capital per trade (all-in on conviction)
STOP_LOSS = 0.08           # 8% stop loss
TRAIL_ACTIVATE = 0.15      # start trailing at 15% profit
TRAIL_DIST = 0.08          # trail by 8%

# Best 4h strategies from backtest validation
STRATEGIES = {
    'DOGE-USD': ('donchian', {'p': 30}),
    'SOL-USD':  ('ema',      {'fast': 5, 'slow': 21}),
    'ADA-USD':  ('tsmom',    {'lb': 36, 'entry': 0.7}),
    'AVAX-USD': ('tsmom',    {'lb': 36, 'entry': 0.7}),
}

def _flatten(d):
    if isinstance(d.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: d[c].values.ravel() for c in d.columns}, index=d.index)
    return d

def load_4h():
    with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample('4h').first(); h = d['High'].resample('4h').max()
        l = d['Low'].resample('4h').min(); c = d['Close'].resample('4h').last()
        v = d['Volume'].resample('4h').sum()
        dfs[t] = pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v}, index=o.index)
    common = sorted(set.intersection(*[set(df.index) for df in dfs.values()]))
    return {t: dfs[t].loc[common] for t in dfs}, common

def ema(s, p): return s.ewm(span=p).mean()

def gen_signal(df, kind, params):
    c = df['close'].values; n = len(c); sig = np.zeros(n)
    if kind == 'donchian':
        p = params.get('p', 30)
        h = df['high'].rolling(p).max().values
        l = df['low'].rolling(p).min().values
        for i in range(1, n):
            sig[i] = 1.0 if c[i] > h[i-1] else (-1.0 if c[i] < l[i-1] else sig[i-1])
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
            sig[i] = 1.0 if ts > entry else (-1.0 if ts < -entry else sig[i-1])
    elif kind == 'ema':
        f = ema(df['close'], params.get('fast',5)).values
        s = ema(df['close'], params.get('slow',21)).values
        sig = np.where(f > s, 1.0, -1.0)
    return sig

# --- SWING BACKTEST (let winners ride, tight stops) ---
def swing_backtest(cv, sig):
    n = len(cv); eq = INITIAL_CAP; peak_eq = INITIAL_CAP
    eqs = np.ones(n) * INITIAL_CAP
    trades, wins = 0, 0
    in_pos = False; pos_dir = 0; entry_p = 0; peak_p = 0
    max_win = 0; max_loss = 0; trade_rets = []

    for i in range(1, n):
        s = sig[i]
        if np.isnan(s) or np.isinf(s): s = 0.0

        # Entry
        if not in_pos and abs(s) > 0.5:
            entry_p = cv[i]; peak_p = cv[i]
            pos_dir = 1 if s > 0 else -1
            in_pos = True; continue

        # Management
        if in_pos:
            ret = (cv[i] / entry_p - 1) * pos_dir
            if ret > 0: peak_p = max(peak_p, cv[i])

            exited = False
            # Stop loss
            if ret < -STOP_LOSS: exited = True
            # Trailing stop (activates at 15%+ profit)
            if ret > TRAIL_ACTIVATE:
                if (pos_dir > 0 and cv[i] < peak_p * (1 - TRAIL_DIST)) or \
                   (pos_dir < 0 and cv[i] > peak_p * (1 + TRAIL_DIST)):
                    exited = True

            if exited:
                eq *= (1 + ret)
                trade_rets.append(ret)
                max_win = max(max_win, ret)
                max_loss = min(max_loss, ret)
                trades += 1; wins += 1 if ret > 0 else 0
                in_pos = False; pos_dir = 0

        eqs[i] = eq; peak_eq = max(peak_eq, eq)

    rets = pd.Series(np.diff(np.log(np.maximum(eqs, 1)))).dropna()
    tr = eqs[-1] / INITIAL_CAP - 1
    ny = max(n / (365*6), 0.1)  # 4h bars
    ann = (1+tr)**(1/ny)-1 if tr > -1 else -0.99
    sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*6)
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades,1)

    avg_win = np.mean([r for r in trade_rets if r > 0]) if any(r > 0 for r in trade_rets) else 0
    avg_loss = abs(np.mean([r for r in trade_rets if r < 0])) if any(r < 0 for r in trade_rets) else 0
    rr = avg_win / max(avg_loss, 0.001)

    return {'eqs':eqs,'final_eq':float(eqs[-1]),'trades':trades,'wins':wins,
            'wr':wr,'sr':sr,'ann':ann,'dd':dd,'tr':tr,
            'avg_win':avg_win,'avg_loss':avg_loss,'rr':rr,'max_win':max_win,'max_loss':max_loss}

# --- COMPOUNDING SIMULATOR (swing style) ---
def simulate_swing(wr, avg_win_pct, avg_loss_pct, trades_per_month=4, months=12):
    """Monte Carlo: each trade is a 'swing' with full capital at risk."""
    runs = 2000
    eqs = np.ones((runs, months+1)) * INITIAL_CAP
    for r in range(runs):
        eq = INITIAL_CAP
        for m in range(months):
            for _ in range(trades_per_month):
                w = np.random.random() < wr
                ret = avg_win_pct if w else -avg_loss_pct
                eq *= (1 + ret)
                if eq <= 0: eq = 0.1; break
            eqs[r, m+1] = eq
    return eqs

if __name__ == '__main__':
    print("=" * 72)
    print("  MEME SWINGER — 1k INR to Lacs in Months")
    print("  4h Swing Trading | Catch Big Pumps | Full Capital Compounding")
    print("=" * 72)

    data, idx = load_4h()
    print(f"\n  Data: {len(idx)} 4h bars ({len(idx)//6:.0f} days) for {len(data)} coins\n")

    # Phase 1: Backtest each coin with swing parameters
    print(f"  {'Coin':<10} {'Trades':>8} {'WR':>8} {'SR':>8} {'Ann%':>10} {'DD%':>8} {'R:R':>8} {'Final(INR)':>12}")
    print(f"  {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*12}")

    results = []
    for ticker in ['DOGE-USD','SOL-USD','ADA-USD','AVAX-USD']:
        if ticker not in data: continue
        kind, params = STRATEGIES[ticker]
        sig = gen_signal(data[ticker], kind, params)
        r = swing_backtest(data[ticker]['close'].values, sig)
        if r and r['trades'] > 0:
            print(f"  {ticker:<10} {r['trades']:>8d} {r['wr']*100:>7.1f}% "
                  f"{r['sr']:>8.2f} {r['ann']*100:>9.1f}% {r['dd']*100:>7.1f}% "
                  f"{r['rr']:>7.1f}x  Rs{r['final_eq']:>9.0f}")
            results.append((ticker, r))

    if not results:
        print("\n  No valid results. Check data."); exit()

    results.sort(key=lambda x: x[1]['final_eq'], reverse=True)
    best_ticker, best = results[0]

    print(f"\n  >> BEST: {best_ticker} — Rs{best['final_eq']:,.0f} final, WR={best['wr']*100:.1f}%, "
          f"RR={best['rr']:.1f}x, MaxWin={best['max_win']*100:.0f}%")

    if best['trades'] > 0:
        print(f"    Avg Win: {best['avg_win']*100:.1f}% | Avg Loss: {best['avg_loss']*100:.1f}% | "
              f"Best Trade: +{best['max_win']*100:.0f}%")

    # Phase 2: Compounding projection
    print(f"\n{'='*72}")
    print(f"  COMPOUNDING SIMULATION: Rs{INITIAL_CAP:,} -> Rs{TARGET_CAP:,}")
    print(f"  Based on {best_ticker} swing backtest")
    print(f"{'='*72}")

    months_max = 24
    eqs_all = simulate_swing(best['wr'], best['avg_win'], best['avg_loss'],
                              trades_per_month=4, months=months_max)

    med = np.median(eqs_all, axis=0)
    p75 = np.percentile(eqs_all, 75, axis=0)
    p25 = np.percentile(eqs_all, 25, axis=0)

    hit_pct = np.sum(eqs_all[:,-1] >= TARGET_CAP) / eqs_all.shape[0] * 100
    hit_6mo = np.sum(eqs_all[:, 6] >= TARGET_CAP) / eqs_all.shape[0] * 100
    hit_12mo = np.sum(eqs_all[:, 12] >= TARGET_CAP) / eqs_all.shape[0] * 100

    # Days to target (avg)
    avg_months = 0; count = 0
    for r in range(eqs_all.shape[0]):
        for m in range(eqs_all.shape[1]):
            if eqs_all[r, m] >= TARGET_CAP:
                avg_months += m; count += 1; break
    avg_months = avg_months / max(count, 1)

    print(f"\n  2000 simulations, 4 trades/month, {months_max} months max:")
    print(f"    Hit Rs{TARGET_CAP:,}: {hit_pct:.0f}% of all runs")
    print(f"    Hit within 6 months: {hit_6mo:.0f}%")
    print(f"    Hit within 12 months: {hit_12mo:.0f}%")
    print(f"    Avg time to target: {avg_months:.1f} months")
    print(f"    Final equity: Median=Rs{med[-1]:,.0f}, P75=Rs{p75[-1]:,.0f}, P25=Rs{p25[-1]:,.0f}")

    # Scenario: best path
    best_path = eqs_all[np.argmax(eqs_all[:,-1])]
    best_months = next(m for m in range(len(best_path)) if best_path[m] >= TARGET_CAP)
    print(f"    Best run hit Rs{TARGET_CAP:,} in {best_months} months")
    worst_path = eqs_all[np.argmin(eqs_all[:,-1])]
    print(f"    Worst run final: Rs{worst_path[-1]:,.0f}")

    # Phase 3: Current signals
    print(f"\n{'='*72}")
    print(f"  LIVE SIGNALS (last 6 bars)")
    print(f"{'='*72}")
    print(f"  {'Coin':<10} {'Price':>10} {'Signal':>20} {'Action':>10}")
    print(f"  {'-'*10} {'-'*10} {'-'*20} {'-'*10}")

    for ticker in ['DOGE-USD','SOL-USD','ADA-USD','AVAX-USD']:
        if ticker not in data: continue
        kind, params = STRATEGIES[ticker]
        sig = gen_signal(data[ticker], kind, params)
        last6 = sig[-6:]; price = data[ticker]['close'].values[-1]
        sig_str = ''.join(['B' if s > 0.5 else ('S' if s < -0.5 else '_') for s in last6])
        action = 'BUY' if last6[-1] > 0.5 else ('SELL' if last6[-1] < -0.5 else 'WAIT')
        print(f"  {ticker:<10} ${price:<8.2f}  {sig_str:>20}  {action:>8}")

    # Phase 4: Save
    np.savetxt('swinger_equity_median.csv', med, delimiter=',')
    out = {'best_ticker': best_ticker, 'best_final_eq': best['final_eq'],
           'wr': best['wr'], 'rr': best['rr'],
           'hit_pct': hit_pct, 'hit_6mo_pct': hit_6mo, 'hit_12mo_pct': hit_12mo,
           'avg_months_to_target': avg_months}
    with open('swinger_results.json', 'w') as f: json.dump(out, f, indent=2)
    print(f"\n  Saved: swinger_results.json, swinger_equity_median.csv")

    # Phase 5: Action plan
    wins_needed = max(1, int(np.log(TARGET_CAP/INITIAL_CAP)/np.log(1+best['avg_win'])))
    print(f"\n{'='*72}")
    print(f"  ACTION PLAN: Rs{INITIAL_CAP:,} -> Rs{TARGET_CAP:,}")
    print(f"{'='*72}")
    print(f"""
  PHASE 1 - Build (Rs1,000 -> Rs10,000)
    Trade: {best_ticker} ({kind})
    Entry: On signal (BUY above Donchian/EMA or TSMOM > 0.7)
    Stop:  -{STOP_LOSS*100:.0f}% hard stop
    Exit:  Trailing at {TRAIL_DIST*100:.0f}% (activate at {TRAIL_ACTIVATE*100:.0f}% profit)
    Target: Let it ride - aim for 30-100% winners
    Compounding: 100% of capital per trade

  PHASE 2 - Scale (Rs10,000 -> Rs50,000)
    Add:  2nd coin with confirmed signal
    Risk: Same rules, split capital 50/50

  PHASE 3 - Accelerate (Rs50,000 -> Rs1,00,000+)
    Add:  All 4 coins
    Risk: 25% per coin, compound aggressively

  KEY STATS:
    Win Rate: {best['wr']*100:.0f}% | Avg Win: {best['avg_win']*100:.0f}% | Avg Loss: {best['avg_loss']*100:.0f}%
    Reward:Risk: {best['rr']:.1f}x | Best Trade: +{best['max_win']*100:.0f}%
    Need ~{wins_needed} winning trades to 100x (with full compounding)

  COMPOUNDING SIMULATION:
    Hit Rs{TARGET_CAP:,} within 12 months: {hit_12mo:.0f}% probability
    Average time to target: {avg_months:.1f} months
    """)
