import pickle, numpy as np, pandas as pd, math, json
from collections import Counter
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
np.random.seed(42)

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
N_COINS = len(tickers)

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5, start_idx=0):
    n, nt = c.shape; weights = np.zeros((n, nt)); prev_w = np.zeros(nt)
    for i in range(max(lb+1, start_idx+1), n):
        if (i - lb - 1) % rebal != 0:
            weights[i] = prev_w; continue
        r = c[i] / c[i-lb] - 1; ranks = np.argsort(r)
        w = np.zeros(nt)
        w[ranks[-top_k:]] = 1.0/top_k; w[ranks[:bot_k]] = -1.0/bot_k
        w -= w.mean(); weights[i] = w; prev_w = w.copy()
    return weights

def backtest_cs(close_mat, weights_arr, scale_factor=1.0, costs=0.0015):
    n = close_mat.shape[0]
    rets = close_mat[1:] / close_mat[:-1] - 1
    eq = 1.0; eqs = np.ones(n); trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(close_mat.shape[1]); pos_active = False
    for i in range(1, n):
        w = weights_arr[i].copy() * scale_factor
        if np.any(np.isnan(w)) or np.any(np.isinf(w)): w = np.zeros_like(w)
        turnover = np.sum(np.abs(w - prev_w))
        if turnover > 1e-10:
            if pos_active:
                trades += 1
                if eq > entry_eq: wins += 1
            pos_active = np.sum(np.abs(w)) > 1e-10
            entry_eq = eq; eq -= turnover * costs * eq
        port_ret = np.sum(w * rets[i-1]); eq *= 1 + port_ret
        eqs[i] = eq; prev_w = w.copy()
    if pos_active:
        trades += 1
        if eq > entry_eq: wins += 1
    rets_s = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1; ny = max(n/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets_s.mean()/rets_s.std()*math.sqrt(365) if len(rets_s)>0 and rets_s.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades, 1)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'trades':trades,'eqs':eqs,'returns':rets_s.values}

def find_scale(close_mat, weights, target_dd=0.199, max_scale=1.0):
    r = backtest_cs(close_mat, weights, 1.0)
    if r['dd'] <= target_dd: return 1.0
    lo, hi = 0.001, 1.0
    for _ in range(25):
        mid = (lo + hi) / 2
        if backtest_cs(close_mat, weights, mid)['dd'] > target_dd: hi = mid
        else: lo = mid
    return (lo + hi) / 2

def get_metrics(eqs):
    rets = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1; ny = max(len(eqs)/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets.mean()/rets.std()*math.sqrt(365) if len(rets)>0 and rets.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    downside = rets[rets<0]
    sortino = rets.mean()/downside.std()*math.sqrt(365) if len(downside)>0 and downside.std()>0 else 0
    t_stat = rets.mean()/max(rets.std()/math.sqrt(len(rets)), 1e-10)
    gains = rets[rets>0].sum() if len(rets[rets>0])>0 else 0
    losses = max(abs(rets[rets<0].sum()), 1e-10)
    pf = gains/losses
    return {'sr':sr,'ann':ann,'dd':dd,'sortino':sortino,'t_stat':t_stat,'pf':pf}

# Test just ONE strategy through walk-forward and check all gates
params = {'lb': 22, 'top_k': 3, 'bot_k': 3, 'rebal': 5}
n = close_mat.shape[0]
n_windows = 6
window_size = n // n_windows

print('Walk-forward test for L22_RF5_3x3:')
print('%s' % ('='*60))

window_results = []
all_oos_eqs = [np.array([1.0])]

for wi in range(1, n_windows):
    train_end = wi * window_size
    test_start = train_end
    test_end = min((wi+1) * window_size, n)
    
    if train_end < params['lb'] + 10:
        continue
    
    train_w = cs_weekly(close_mat[:train_end], **params)
    test_w = cs_weekly(close_mat[:test_end], **params)
    
    train_bt = backtest_cs(close_mat[:train_end], train_w, 1.0)
    if train_bt['trades'] < 10: continue
    
    scale = find_scale(close_mat[:train_end], train_w, 0.199)
    print('  Window %d: train_bars=%d-%d, test_bars=%d-%d, train_trades=%d, scale=%.3f' % (
        wi, 0, train_end, test_start, test_end, train_bt['trades'], scale))
    print('    IS: SR=%.3f Ann=%.1f%% DD=%.1f%% WR=%.1f%%' % (
        train_bt['sr'], train_bt['ann']*100, train_bt['dd']*100, train_bt['wr']*100))
    
    oos_w = test_w[test_start:test_end]
    oos_bt = backtest_cs(close_mat[test_start:test_end], oos_w, scale)
    
    if oos_bt['trades'] < 5: continue
    
    print('    OOS: SR=%.3f Ann=%.1f%% DD=%.1f%% WR=%.1f%% Trades=%d' % (
        oos_bt['sr'], oos_bt['ann']*100, oos_bt['dd']*100, oos_bt['wr']*100, oos_bt['trades']))
    
    window_results.append({
        'sr': oos_bt['sr'], 'is_sr': train_bt['sr'], 'is_dd': train_bt['dd'],
        'dd': oos_bt['dd'], 'ann': oos_bt['ann'], 'trades': oos_bt['trades'],
        'wfe': oos_bt['sr'] / max(abs(train_bt['sr']), 0.01) if abs(train_bt['sr']) > 0.01 else 0
    })
    all_oos_eqs.append(oos_bt['eqs'][1:])

print()
stitched = np.concatenate(all_oos_eqs)
full_w = cs_weekly(close_mat, **params)
full_bt = backtest_cs(close_mat, full_w, find_scale(close_mat, full_w, 0.199))
full_m = get_metrics(full_bt['eqs'])

print('Stitched OOS: SR=%.3f Ann=%.1f%% DD=%.1f%%' % (get_metrics(stitched)['sr'],
    get_metrics(stitched)['ann']*100, get_metrics(stitched)['dd']*100))
print('Full test: SR=%.3f Ann=%.1f%% DD=%.1f%% Sortino=%.2f t=%.2f PF=%.2f' % (
    full_m['sr'], full_m['ann']*100, full_m['dd']*100, full_m['sortino'], full_m['t_stat'], full_m['pf']))

print()
print('Gate checks:')
print('  G3.1 WFE > 0.5: avg=%.3f' % (np.mean([w.get('wfe',0) for w in window_results]) if window_results else 0))
print('  G3.2 OOS SR>=0.2: %.3f' % get_metrics(stitched)['sr'])
print('  G3.3 Neg Windows: %d' % sum(1 for w in window_results if w.get('sr',0) < 0))
print('  G4.1 SR >= 1.0: %.3f' % full_m['sr'])
print('  G4.2 t-stat >= 2.0: %.2f' % full_m['t_stat'])
print('  G4.3 Bootstrap LB > 0: ', end='')
ret = pd.Series(np.diff(np.log(full_bt['eqs']))).dropna()
if len(ret) > 20:
    boot = []
    for _ in range(500):
        s = np.random.choice(ret, len(ret))
        boot.append(s.mean()/max(s.std(),1e-10)*math.sqrt(365))
    print('%.3f' % np.percentile(boot, 5))
print('  G5.1 DD < 20%%: %.2f%%' % (full_m['dd']*100))
print('  G5.2 Calmar > 0.5: %.2f' % (full_m['ann']/max(full_m['dd'],0.001)))
print('  G5.3 Sortino > 1.5: %.2f' % full_m['sortino'])
print('  G5.4 PF > 1.3: %.2f' % full_m['pf'])
print('  G6.1 Regime: ', end='')
if len(ret) > 40:
    h = len(ret)//2
    s1 = get_metrics(np.exp(np.concatenate([[0], ret[:h].cumsum()])))['sr'] > 0
    s2 = get_metrics(np.exp(np.concatenate([[0], ret[h:].cumsum()])))['sr'] > 0
    print('%s,%s' % (s1, s2))
