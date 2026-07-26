"""Direct test of walkforward_test for a few strategies."""
import pickle, numpy as np, pandas as pd, math, json
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
close_mat = np.zeros((len(common), len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values

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

def backtest_cs(close_arr, weights_arr, scale_factor=1.0, costs=0.0015):
    n = close_arr.shape[0]
    rets = close_arr[1:] / close_arr[:-1] - 1
    eq = 1.0; eqs = np.ones(n); trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(close_arr.shape[1]); pos_active = False
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

def find_scale(close_arr, weights, target_dd=0.199, max_scale=1.0):
    r = backtest_cs(close_arr, weights, 1.0)
    if r['dd'] <= target_dd: return 1.0
    lo, hi = 0.001, 1.0
    for _ in range(25):
        mid = (lo + hi) / 2
        if backtest_cs(close_arr, weights, mid)['dd'] > target_dd: hi = mid
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

def walkforward_test(close_arr, params, target_dd=0.199):
    n = close_arr.shape[0]
    n_windows = 6
    window_size = n // n_windows
    
    window_results = []
    all_oos_eqs = [np.array([1.0])]
    
    for wi in range(1, n_windows):
        train_end = wi * window_size
        test_start = train_end
        test_end = min((wi+1) * window_size, n)
        
        if train_end < params['lb'] + 10:
            continue
        
        train_w = cs_weekly(close_arr[:train_end], **params)
        test_w = cs_weekly(close_arr[:test_end], **params)
        
        train_bt = backtest_cs(close_arr[:train_end], train_w, 1.0)
        if train_bt['trades'] < 10: continue
        
        scale = find_scale(close_arr[:train_end], train_w, target_dd)
        
        oos_w = test_w[test_start:test_end]
        oos_bt = backtest_cs(close_arr[test_start:test_end], oos_w, scale)
        
        if oos_bt['trades'] < 5: continue
        
        window_results.append({
            'sr': oos_bt['sr'], 'is_sr': train_bt['sr'],
            'dd': oos_bt['dd'], 'ann': oos_bt['ann'], 'trades': oos_bt['trades'],
            'wfe': oos_bt['sr'] / max(abs(train_bt['sr']), 0.01) if abs(train_bt['sr']) > 0.01 else 0
        })
        all_oos_eqs.append(oos_bt['eqs'][1:])
    
    if len(window_results) < 2:
        return None, 'Only %d windows' % len(window_results)
    
    stitched = np.concatenate(all_oos_eqs)
    oos_metrics = get_metrics(stitched)
    
    full_w = cs_weekly(close_arr, **params)
    full_bt = backtest_cs(close_arr, full_w, find_scale(close_arr, full_w, target_dd))
    
    return {
        'window_results': window_results,
        'eqs_oos': stitched,
        'eqs_all': full_bt['eqs'],
        'oos_sr': oos_metrics['sr'],
        'full_sr': get_metrics(full_bt['eqs'])['sr']
    }, 'OK'

# Test top performing strategies
tests = [
    {'lb': 22, 'top_k': 3, 'bot_k': 3, 'rebal': 5},
    {'lb': 30, 'top_k': 3, 'bot_k': 3, 'rebal': 3},
    {'lb': 14, 'top_k': 3, 'bot_k': 3, 'rebal': 4},
    {'lb': 10, 'top_k': 4, 'bot_k': 4, 'rebal': 10},
    {'lb': 7, 'top_k': 3, 'bot_k': 3, 'rebal': 5},
    {'lb': 65, 'top_k': 3, 'bot_k': 3, 'rebal': 5},
]

for p in tests:
    result, msg = walkforward_test(close_mat, p)
    if result:
        wr = result['window_results']
        win = sum(1 for w in wr if w['sr'] > 0)
        avg_f = np.mean([w['wfe'] for w in wr])
        print('LB=%d RF=%d K=%d: OOS_SR=%.3f Full_SR=%.3f Win=%d/%d AvgWFE=%.3f' % (
            p['lb'], p['rebal'], p['top_k'],
            result['oos_sr'], result['full_sr'], win, len(wr), avg_f))
    else:
        print('LB=%d RF=%d K=%d: FAILED: %s' % (p['lb'], p['rebal'], p['top_k'], msg))
