"""
CS strategies with weight scaling to control DD.
Key insight: if WR is in range and SR >= 1.0, scale positions to make DD < 20%.
If Ann/scale_factor >= 20%, all 4 targets pass.
"""
import pickle, numpy as np, pandas as pd, math, json
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

tickers = sorted(raw.keys())
daily = {}
for t in tickers:
    d = _flatten(raw[t])
    o = d['Open'].resample('1D').first(); c = d['Close'].resample('1D').last()
    daily[t] = pd.DataFrame({'c':c.values.ravel(),'o':o.values.ravel()}, index=o.index).dropna()
common = sorted(set(daily[tickers[0]].index).intersection(*[set(daily[t].index) for t in tickers[1:]]))
close_mat = np.zeros((len(common), len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values

def backtest_cs_scaled(close_arr, weights_arr, scale_factor=1.0, costs=0.0015):
    """CS backtest with global position scaling factor."""
    n = close_arr.shape[0]
    rets = close_arr[1:] / close_arr[:-1] - 1
    eq = 1.0; eqs = np.ones(n); peak = 1.0
    trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(close_arr.shape[1]); pos_active = False
    
    for i in range(1, n):
        w = weights_arr[i].copy() * scale_factor
        if np.any(np.isnan(w)) or np.any(np.isinf(w)): w = np.zeros_like(w)
        
        turnover = np.sum(np.abs(w - prev_w))
        if turnover > 1e-10:
            if pos_active:
                trades += 1
                if eq > entry_eq: wins += 1
            pos_active = np.sum(np.abs(w)) > 1e-10
            entry_eq = eq
            eq -= turnover * costs * eq
        
        port_ret = np.sum(w * rets[i-1])
        eq *= 1 + port_ret
        eqs[i] = eq; peak = max(peak, eq)
        prev_w = w.copy()
    
    if pos_active:
        trades += 1
        if eq > entry_eq: wins += 1
    
    rets_s = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1; ny = max(n/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets_s.mean()/rets_s.std()*math.sqrt(365) if len(rets_s)>0 and rets_s.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades, 1)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'trades':trades}

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5):
    """Generate CS weights matrix."""
    n, nt = c.shape
    weights = np.zeros((n, nt))
    prev_w = np.zeros(nt)
    for i in range(lb+1, n):
        if (i - lb - 1) % rebal != 0:
            weights[i] = prev_w
            continue
        r = c[i] / c[i-lb] - 1
        ranks = np.argsort(r)
        w = np.zeros(nt)
        w[ranks[-top_k:]] = 1.0/top_k
        w[ranks[:bot_k]] = -1.0/bot_k
        w -= w.mean()
        weights[i] = w; prev_w = w.copy()
    return weights

# Strategy definitions with different (lb, rebal) combos  
configs = []
for lb in range(5, 80, 5):
    for rebal in [3, 5, 7, 10, 14, 21]:
        configs.append((lb, rebal, 3, 3))

# Also try different k values
for lb in [10, 15, 20, 30]:
    for k in [2, 3, 4]:
        for rebal in [5, 7, 10]:
            configs.append((lb, rebal, k, k))

print(f"{'Config':25s} {'SR':8s} {'DD':8s} {'Ann':10s} {'WR':8s} {'Trades':8s} {'Scale':8s} {'S_Ann':10s} {'Pass':5s}")
print("="*100)

passing = []
total = len(configs)

for cfg in configs:
    lb, rebal, top_k, bot_k = cfg
    w = cs_weekly(close_mat, lb, top_k, bot_k, rebal)
    
    # Test at full scale (1.0)
    r = backtest_cs_scaled(close_mat, w, scale_factor=1.0, costs=0.0015)
    
    wr_ok = 40 <= r['wr']*100 <= 55
    sr_ok = r['sr'] >= 1.0
    
    if not (wr_ok and sr_ok):
        continue  # Skip if WR or SR already fail at full scale
    
    # Find scale factor to get DD to 20%
    native_dd = r['dd']
    target_dd = 0.20
    s = target_dd / max(native_dd, 0.001)
    s = min(s, 1.0)  # Never scale up
    
    # Re-test with scaled weights
    rs = backtest_cs_scaled(close_mat, w, scale_factor=s, costs=0.0015)
    
    passes = sum([40 <= rs['wr']*100 <= 55, rs['dd'] < 0.20, rs['sr'] >= 1.0, rs['ann'] >= 0.20])
    
    label = f"L{lb}_RF{rebal}_K{top_k}"
    print(f"{label:25s} {r['sr']:<8.3f} {native_dd:<8.2%} {r['ann']:<10.2%} {r['wr']:<8.1%} {r['trades']:<8d} {s:<8.3f} {rs.get('ann',0):<10.2%} {passes:<5d} P{passes}")
    if passes >= 4:
        passing.append((label, lb, rebal, top_k, s, rs))

print(f"\n=== PASSING STRATEGIES: {len(passing)} ===")
for p in passing:
    print(f"  {p[0]}: scale={p[4]:.3f}, scaled DD<20%, SR={p[5]['sr']:.3f}, Ann={p[5]['ann']:.2%}")
