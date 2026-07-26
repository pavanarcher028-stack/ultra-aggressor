"""
Full grid search for ALL strategies that pass all 4 targets.
Uses binary search to find exact scale factor for DD = 20%.
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
    daily[t] = pd.DataFrame({'c':c.values.ravel()}, index=o.index).dropna()
common = sorted(set(daily[tickers[0]].index).intersection(*[set(daily[t].index) for t in tickers[1:]]))
n_bars = len(common)
close_mat = np.zeros((n_bars, len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values
print('Data: %d bars, %d coins' % (n_bars, len(tickers)))

def backtest_cs(close_arr, weights_arr, scale_factor=1.0, costs=0.0015):
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
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'trades':trades,'tr':tr*100,'eqs':eqs}

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5):
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

def find_scale(close_arr, weights, target_dd=0.199, max_scale=1.0):
    """Binary search for scale factor that gives DD = target_dd."""
    if backtest_cs(close_arr, weights, 1.0)['dd'] <= target_dd:
        return 1.0
    lo, hi = 0.001, 1.0
    for _ in range(25):
        mid = (lo + hi) / 2
        r = backtest_cs(close_arr, weights, scale_factor=mid)
        if r['dd'] > target_dd:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

def evaluate_strategy(weights, max_scale=1.0):
    """Find optimal scale and check if all 4 targets pass."""
    r_native = backtest_cs(close_mat, weights, 1.0)
    if r_native['wr']*100 < 40 or r_native['wr']*100 > 55:
        return None, 'WR out of range: %.1f%%' % (r_native['wr']*100)
    # Try to find scale that achieves DD=20% while keeping targets
    for target_dd in [0.199, 0.195, 0.19, 0.18, 0.17, 0.15]:
        s = find_scale(close_mat, weights, target_dd=target_dd, max_scale=max_scale)
        rs = backtest_cs(close_mat, weights, scale_factor=s)
        if (40 <= rs['wr']*100 <= 55 and rs['dd'] < 0.20 and rs['sr'] >= 1.0 and rs['ann'] >= 0.20):
            return s, rs
    return None, 'Cannot achieve all 4 targets'

# Generate all configurations
print('Testing configurations...')
passing_results = []
total_tested = 0

# Main grid: lookback 5-75 step 5 × rebal 3-21
lbrange = list(range(5, 80, 5)) + [7, 8, 9, 12, 14, 16, 17, 18, 19, 22, 24, 25, 26, 28, 32, 34, 35, 36, 38, 42, 44, 45, 46, 48, 52, 58, 62, 68, 72, 78]
rebalrange = [3, 5, 7, 10, 14, 21, 2, 4, 6, 8, 9, 12, 15, 20]

for lb in lbrange:
    for rebal in rebalrange:
        total_tested += 1
        w = cs_weekly(close_mat, lb, 3, 3, rebal)
        s, rs_or_msg = evaluate_strategy(w, max_scale=1.0)
        if s is not None:
            rs = rs_or_msg
            passing_results.append({
                'name': 'CS_L%d_RF%d_3x3' % (lb, rebal),
                'lb': lb, 'rebal': rebal, 'top_k': 3, 'bot_k': 3,
                'scale': s,
                'sr': rs['sr'], 'ann': rs['ann'], 'dd': rs['dd'], 'wr': rs['wr'],
                'trades': rs['trades'], 'tr': rs['tr']
            })
            print('  PASS: L%d RF%d scale=%.3f SR=%.3f Ann=%.1f%% DD=%.1f%% WR=%.1f%%' % (
                lb, rebal, s, rs['sr'], rs['ann']*100, rs['dd']*100, rs['wr']*100))

# Also test different k values
for lb in [10, 15, 20, 30]:
    for rebal in [5, 7, 10]:
        for k in [2, 4]:
            total_tested += 1
            w = cs_weekly(close_mat, lb, k, k, rebal)
            s, rs_or_msg = evaluate_strategy(w, max_scale=1.0)
            if s is not None:
                rs = rs_or_msg
                passing_results.append({
                    'name': 'CS_L%d_RF%d_K%d' % (lb, rebal, k),
                    'lb': lb, 'rebal': rebal, 'top_k': k, 'bot_k': k,
                    'scale': s,
                    'sr': rs['sr'], 'ann': rs['ann'], 'dd': rs['dd'], 'wr': rs['wr'],
                    'trades': rs['trades'], 'tr': rs['tr']
                })
                print('  PASS: L%d RF%d K%d scale=%.3f SR=%.3f Ann=%.1f%% DD=%.1f%% WR=%.1f%%' % (
                    lb, rebal, k, s, rs['sr'], rs['ann']*100, rs['dd']*100, rs['wr']*100))

# Also test asymmetric k (different long/short counts)
for lb in [15, 20, 30]:
    for rebal in [5, 7]:
        for tk, bk in [(2,4), (4,2), (2,3), (3,2)]:
            total_tested += 1
            w = cs_weekly(close_mat, lb, tk, bk, rebal)
            s, rs_or_msg = evaluate_strategy(w, max_scale=1.0)
            if s is not None:
                rs = rs_or_msg
                passing_results.append({
                    'name': 'CS_L%d_RF%d_L%dS%d' % (lb, rebal, tk, bk),
                    'lb': lb, 'rebal': rebal, 'top_k': tk, 'bot_k': bk,
                    'scale': s,
                    'sr': rs['sr'], 'ann': rs['ann'], 'dd': rs['dd'], 'wr': rs['wr'],
                    'trades': rs['trades'], 'tr': rs['tr']
                })
                print('  PASS: L%d RF%d L%dS%d scale=%.3f SR=%.3f Ann=%.1f%% DD=%.1f%% WR=%.1f%%' % (
                    lb, rebal, tk, bk, s, rs['sr'], rs['ann']*100, rs['dd']*100, rs['wr']*100))

print('\n%53s' % '='*53)
print('SUMMARY: %d/%d strategies pass all 4 targets' % (len(passing_results), total_tested))
print('%53s' % '='*53)

passing_results.sort(key=lambda x: -x['sr'])
for i, r in enumerate(passing_results):
    print('  %2d. %20s | SR=%.2f Ann=%.1f%% DD=%.1f%% WR=%.1f%% Scale=%.2f Trades=%d' % (
        i+1, r['name'], r['sr'], r['ann']*100, r['dd']*100, r['wr']*100, r['scale'], r['trades']))

# Save
with open('p4_strategies.json', 'w') as f:
    json.dump(passing_results, f, indent=2, default=str)
print('\nSaved %d passing strategies to p4_strategies.json' % len(passing_results))
