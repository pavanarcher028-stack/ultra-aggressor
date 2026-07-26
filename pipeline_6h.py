"""
Test pipeline on 6h data (4x more bars than daily = 2924 vs 731).
Cross-sectional momentum on 6h data.
"""
import pickle, numpy as np, pandas as pd, math, json
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
np.random.seed(42)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

tickers = sorted(raw.keys())

# Resample to 6h
daily = {}
for t in tickers:
    d = _flatten(raw[t])
    o = d['Open'].resample('6h').first(); c = d['Close'].resample('6h').last()
    daily[t] = pd.DataFrame({'c':c.values.ravel()}, index=o.index).dropna()
common = sorted(set(daily[tickers[0]].index).intersection(*[set(daily[t].index) for t in tickers[1:]]))
close_mat = np.zeros((len(common), len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values
dates = np.array(common)
n_bars = len(close_mat)
ny = n_bars / (365 * 4)  # 4 six-hour periods per day
print('6h Data: %d bars, %d coins, %.1f years (%s to %s)' % (n_bars, len(tickers), ny, str(dates[0])[:10], str(dates[-1])[:10]))

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5):
    n, nt = c.shape; weights = np.zeros((n, nt)); prev_w = np.zeros(nt)
    for i in range(lb+1, n):
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
    tr = eqs[-1] - 1
    ann = (1+tr)**(1/ny)-1
    sr = rets_s.mean()/rets_s.std()*math.sqrt(365) if len(rets_s)>0 and rets_s.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades, 1)
    sortino = rets_s.mean()/max(rets_s[rets_s<0].std(),1e-10)*math.sqrt(365) if len(rets_s[rets_s<0])>0 else 0
    t_stat = rets_s.mean()/max(rets_s.std()/math.sqrt(len(rets_s)), 1e-10)
    gains = rets_s[rets_s>0].sum() if len(rets_s[rets_s>0])>0 else 0
    losses = max(abs(rets_s[rets_s<0].sum()), 1e-10)
    pf = gains/losses
    calmar = ann/max(dd, 0.001)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'trades':trades,'sortino':sortino,'t_stat':t_stat,'pf':pf,'calmar':calmar,'eqs':eqs,'returns':rets_s.values}

def find_scale(close_arr, weights, target_dd=0.199):
    r = backtest_cs(close_arr, weights, 1.0)
    if r['dd'] <= target_dd: return 1.0
    lo, hi = 0.001, 1.0
    for _ in range(25):
        mid = (lo + hi) / 2
        if backtest_cs(close_arr, weights, mid)['dd'] > target_dd: hi = mid
        else: lo = mid
    return (lo + hi) / 2

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
        if train_end < params['lb'] + 10: continue
        
        train_w = cs_weekly(close_arr[:train_end], **params)
        train_bt = backtest_cs(close_arr[:train_end], train_w, 1.0)
        if train_bt['trades'] < 10: continue
        
        scale = find_scale(close_arr[:train_end], train_w, target_dd)
        
        test_w = cs_weekly(close_arr[:test_end], **params)
        oos_w = test_w[test_start:test_end]
        oos_bt = backtest_cs(close_arr[test_start:test_end], oos_w, scale)
        if oos_bt['trades'] < 5: continue
        
        window_results.append(oos_bt)
        window_results[-1]['is_sr'] = train_bt['sr']
        window_results[-1]['is_dd'] = train_bt['dd']
        window_results[-1]['scale'] = scale
        all_oos_eqs.append(oos_bt['eqs'][1:])
    
    if len(window_results) < 2:
        return None
    
    stitched = np.concatenate(all_oos_eqs)
    oos_metrics = get_metrics(stitched)
    
    full_w = cs_weekly(close_arr, **params)
    full_bt = backtest_cs(close_arr, full_w, find_scale(close_arr, full_w, target_dd))
    
    return {
        'window_results': window_results,
        'oos_metrics': oos_metrics,
        'full_metrics': get_metrics(full_bt['eqs'])
    }

def get_metrics(eqs):
    rets = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ann = (1+tr)**(1/ny)-1
    sr = rets.mean()/rets.std()*math.sqrt(365) if len(rets)>0 and rets.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    downside = rets[rets<0]
    sortino = rets.mean()/downside.std()*math.sqrt(365) if len(downside)>0 and downside.std()>0 else 0
    t_stat = rets.mean()/max(rets.std()/math.sqrt(len(rets)), 1e-10)
    gains = rets[rets>0].sum() if len(rets[rets>0])>0 else 0
    losses = max(abs(rets[rets<0].sum()), 1e-10)
    pf = gains/losses
    calmar = ann/max(dd, 0.001)
    return {'sr':sr,'ann':ann,'dd':dd,'sortino':sortino,'t_stat':t_stat,'pf':pf,'calmar':calmar}

# Test a few strategies on 6h data
tests = [
    {'lb': 14, 'top_k': 3, 'bot_k': 3, 'rebal': 4},
    {'lb': 22, 'top_k': 3, 'bot_k': 3, 'rebal': 5},
    {'lb': 10, 'top_k': 4, 'bot_k': 4, 'rebal': 10},
    {'lb': 25, 'top_k': 3, 'bot_k': 3, 'rebal': 4},
    {'lb': 12, 'top_k': 3, 'bot_k': 3, 'rebal': 9},
]

print('\n=== WALK-FORWARD ON 6h DATA (6 windows) ===')
print()
for p in tests:
    wf = walkforward_test(close_mat, p, 0.199)
    if wf:
        wrs = [round(w['sr'], 3) for w in wf['window_results']]
        is_srs = [round(w['is_sr'], 3) for w in wf['window_results']]
        n_pos = sum(1 for w in wf['window_results'] if w['sr'] > 0)
        # Check IS/OOS
        oos_sr = round(wf['oos_metrics']['sr'], 3)
        avg_is = round(np.mean(is_srs), 3)
        ratio = round(abs(avg_is / max(oos_sr, 0.001)), 2) if abs(oos_sr) > 0.001 else 99
        print('  L%d_RF%d_K%d: OOS_SR=%.3f AvgIS=%.3f IS/OOS=%.2f Win=%d/%d' % (
            p['lb'], p['rebal'], p['top_k'], oos_sr, avg_is, ratio, n_pos, len(wrs)))
        print('    Full SR=%.2f Ann=%.1f%% DD=%.1f%% Sortino=%.2f' % (
            wf['full_metrics']['sr'], wf['full_metrics']['ann']*100,
            wf['full_metrics']['dd']*100, wf['full_metrics']['sortino']))
        print('    Test SRs: %s' % str(wrs))
        print('    IS SRs:   %s' % str(is_srs))
    else:
        print('  L%d_RF%d_K%d: FAILED (WF)' % (p['lb'], p['rebal'], p['top_k']))

# Quick scan: test daily-passing strategies on 6h data
print('\n=== TEST DAILY STRATEGIES ON 6h DATA ===')
with open('p4_strategies.json') as f:
    daily_strats = json.load(f)
# De-duplicate
unique = {}
for s in daily_strats:
    p = tuple([s.get('lb',0), s.get('rebal',0), s.get('top_k',3), s.get('bot_k',3)])
    if p not in unique: unique[p] = s
daily_strats = list(unique.values())
print('Testing %d unique strategies...' % len(daily_strats))

passing_6h = []
for s in daily_strats:
    p = {'lb': s['lb'], 'top_k': s['top_k'], 'bot_k': s['bot_k'], 'rebal': s['rebal']}
    label = 'L%d_RF%d_K%d' % (p['lb'], p['rebal'], p['top_k'])
    
    wf = walkforward_test(close_mat, p, 0.199)
    if wf is None: continue
    
    wrs = [round(w['sr'], 3) for w in wf['window_results']]
    is_srs = [round(w['is_sr'], 3) for w in wf['window_results']]
    n_pos = sum(1 for w in wf['window_results'] if w['sr'] > 0)
    oos_sr = round(wf['oos_metrics']['sr'], 3)
    avg_is = round(np.mean(is_srs), 3) if is_srs else 0
    ratio = round(abs(avg_is / max(oos_sr, 0.001)), 2) if abs(oos_sr) > 0.001 else 99
    
    # Check which gates pass
    full_sr = wf['full_metrics']['sr']
    full_ann = wf['full_metrics']['ann']
    full_dd = wf['full_metrics']['dd']
    full_sortino = wf['full_metrics']['sortino']
    full_t = wf['full_metrics']['t_stat']
    full_pf = wf['full_metrics']['pf']
    n_windows = len(wrs)
    
    g_pass = sum([full_sr >= 1.0, full_ann >= 0.20, full_dd < 0.20,
                  full_sortino >= 1.5, full_pf >= 1.2, full_t >= 2.0,
                  oos_sr >= 0.15, ratio <= 2.0, n_pos >= n_windows * 0.6,
                  all(w > -0.5 for w in wrs)])  # no severely negative windows
    
    print('  %s: OOS_SR=%.3f AvgIS=%.3f IS/OOS=%.2f Win=%d/%d Gates=%d/10' % (
        label, oos_sr, avg_is, ratio, n_pos, n_windows, g_pass))
    
    if g_pass >= 8:
        passing_6h.append(label)

print('\n6h High-pass (>=8/10 gates): %d' % len(passing_6h))
for s in passing_6h:
    print('  %s' % s)
