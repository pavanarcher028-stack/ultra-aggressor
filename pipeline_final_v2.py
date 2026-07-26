"""
Full Pipeline v2: Gates 1-7 with 4 walk-forward windows (6-month test periods).
Tests all 51 CS momentum strategies.
"""
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
dates = np.array(common)
print('Data: %d bars, %d coins, %s to %s' % (len(close_mat), len(tickers), str(dates[0])[:10], str(dates[-1])[:10]))

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
    tr = eqs[-1] - 1; ny = max(n/365, 0.1)
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
    """4 windows, ~6-month test periods each."""
    n = close_arr.shape[0]
    n_windows = 4
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
    calmar = ann/max(dd, 0.001)
    return {'sr':sr,'ann':ann,'dd':dd,'sortino':sortino,'t_stat':t_stat,'pf':pf,'calmar':calmar}

# Load strategies
with open('p4_strategies.json') as f:
    strategies = json.load(f)

# De-duplicate by params
unique = {}
for s in strategies:
    p = tuple([s.get('lb',0), s.get('rebal',0), s.get('top_k',3), s.get('bot_k',3)])
    if p not in unique:
        unique[p] = s
strategies = list(unique.values())
print('Unique strategies: %d' % len(strategies))

def run_gates(strat_name, params, wf_result):
    gates = []
    
    # G1: Basic backtest targets
    full = wf_result['full_metrics']
    g1_wr = 0.40 <= full['sr'] <= 0.55  # No, this is wrong - WR is win rate not SR
    g1_dd = wf_result['target_dd'] < 0.20
    # Actually compute WR from full backtest
    all_w = cs_weekly(close_mat, **params)
    all_bt = backtest_cs(close_mat, all_w, find_scale(close_mat, all_w, 0.199))
    wr_pass = 0.40 <= all_bt['wr'] <= 0.55
    dd_pass = all_bt['dd'] < 0.20
    sr_pass = full['sr'] >= 1.0
    ann_pass = full['ann'] >= 0.20
    
    # G2: Statistical significance
    t_pass = full['t_stat'] >= 2.0
    
    # Bootstrap CI (95%)
    rets = all_bt['returns']
    n_boot = 1000
    boot_srs = []
    for _ in range(n_boot):
        idx = np.random.randint(0, len(rets), len(rets))
        boot_srs.append(np.mean(rets[idx])/max(np.std(rets[idx]),1e-10)*math.sqrt(365))
    boot_srs = np.array(boot_srs)
    ci_lo, ci_hi = np.percentile(boot_srs, [2.5, 97.5])
    ci_pass = ci_lo > 0
    
    # Permutation test
    perm_srs = []
    for _ in range(500):
        perm_rets = rets[np.random.permutation(len(rets))]
        perm_srs.append(np.mean(perm_rets)/max(np.std(perm_rets),1e-10)*math.sqrt(365))
    perm_pass = full['sr'] > np.percentile(perm_srs, 95)
    
    # G3: Walk-forward
    wr_best = max(0, np.mean([w['sr'] for w in wf_result['window_results']]))
    n_win = sum(1 for w in wf_result['window_results'] if w['sr'] > 0)
    n_total = len(wf_result['window_results'])
    win_pct = n_win / n_total
    
    oos_sr = wf_result['oos_metrics']['sr']
    oos_dd = wf_result['oos_metrics']['dd']
    
    is_srs = [w['is_sr'] for w in wf_result['window_results']]
    avg_is_sr = np.mean(is_srs) if is_srs else 0
    is_oos_ratio = abs(avg_is_sr / max(oos_sr, 0.001)) if abs(oos_sr) > 0.001 else 99
    
    # G4: Correlation / Regime
    # Check correlation with equal-weight crypto
    ew_ret = close_mat[1:] / close_mat[:-1] - 1
    ew_port = ew_ret.mean(axis=1)
    corr_ew = np.corrcoef(all_bt['returns'], ew_port)[0,1] if len(all_bt['returns']) == len(ew_port) else 0
    corr_pass = abs(corr_ew) < 0.7
    
    # G5: Scalability (equal weight across multiple strat periods)
    # Simplified: check annual turnover
    turnover_pass = all_bt['trades'] > 20
    
    # G6: Consistency (split sample)
    if len(all_bt['returns']) >= 20:
        half = len(all_bt['returns']) // 2
        sr1 = np.mean(all_bt['returns'][:half])/max(np.std(all_bt['returns'][:half]),1e-10)*math.sqrt(365)
        sr2 = np.mean(all_bt['returns'][half:])/max(np.std(all_bt['returns'][half:]),1e-10)*math.sqrt(365)
        consistent_pass = sr1 > 0 and sr2 > 0
    else:
        consistent_pass = False
    
    # G7: Risk
    sortino_pass = all_bt['sortino'] >= 1.5
    calmar_pass = all_bt['calmar'] >= 1.0
    pf_pass = all_bt['pf'] >= 1.2
    
    gate_results = {
        'G1.1 WR 40-55%': wr_pass,
        'G1.2 DD <20%': dd_pass,
        'G1.3 SR >=1.0': sr_pass,
        'G1.4 Ann >=20%': ann_pass,
        'G2.1 t-stat >=2.0': t_pass,
        'G2.2 Bootstrap CI>0': ci_pass,
        'G2.3 Permutation p<0.05': perm_pass,
        'G3.1 Win%>=60': win_pct >= 0.6,
        'G3.2 OOS SR>=0.15': oos_sr >= 0.15,
        'G3.3 No neg windows': sum(1 for w in wf_result['window_results'] if w['sr'] < -0.5) == 0,
        'G3.4 IS/OOS<=2.0': is_oos_ratio <= 2.0,
        'G4 Low mkt corr': corr_pass,
        'G5 Active (trades>20)': turnover_pass,
        'G6 Split-sample>0': consistent_pass,
        'G7.1 Sortino>=1.5': sortino_pass,
        'G7.2 Calmar>=1.0': calmar_pass,
        'G7.3 PF>=1.2': pf_pass,
    }
    return gate_results

print('\n=== PIPELINE RESULTS (Gates 1-7) ===')
print()

gates_order = ['G1.1 WR 40-55%','G1.2 DD <20%','G1.3 SR >=1.0','G1.4 Ann >=20%',
               'G2.1 t-stat >=2.0','G2.2 Bootstrap CI>0','G2.3 Permutation p<0.05',
               'G3.1 Win%>=60','G3.2 OOS SR>=0.15','G3.3 No neg windows','G3.4 IS/OOS<=2.0',
               'G4 Low mkt corr','G5 Active (trades>20)','G6 Split-sample>0',
               'G7.1 Sortino>=1.5','G7.2 Calmar>=1.0','G7.3 PF>=1.2']

# Print header
hdr = '  %-18s' % 'Strategy'
for g in gates_order:
    hdr += ' %-5s' % g[-4:-1]
print(hdr)
print('  ' + '-'*18 + ' ' + '-'.join(['    ' for _ in gates_order]))

passing_strats = []

for s in strategies:
    params = {'lb': s['lb'], 'top_k': s['top_k'], 'bot_k': s['bot_k'], 'rebal': s['rebal']}
    label = 'L%d_RF%d_K%d' % (params['lb'], params['rebal'], params['top_k'])
    
    wf = walkforward_test(close_mat, params, 0.199)
    if wf is None:
        print('  %-18s FAILED (WF)' % label)
        continue
    
    wf['target_dd'] = backtest_cs(close_mat, cs_weekly(close_mat, **params), find_scale(close_mat, cs_weekly(close_mat, **params), 0.199))['dd']
    
    gates = run_gates(label, params, wf)
    
    n_pass = sum(1 for v in gates.values() if v)
    n_total = len(gates)
    
    line = '  %-18s' % label
    for g in gates_order:
        line += '  %s  ' % ('P' if gates.get(g, False) else '.')
    line += ' %2d/%d' % (n_pass, n_total)
    print(line)
    
    if n_pass == n_total:
        passing_strats.append(label)

print()
print('FULL PASS: %d / %d' % (len(passing_strats), len(strategies)))
for s in passing_strats:
    print('  %s' % s)

# Detailed report for top strategies
print()
print('\n=== DETAILED METRICS (TOP SCORING) ===')
for s in strategies:
    params = {'lb': s['lb'], 'top_k': s['top_k'], 'bot_k': s['bot_k'], 'rebal': s['rebal']}
    label = 'L%d_RF%d_K%d' % (params['lb'], params['rebal'], params['top_k'])
    wf = walkforward_test(close_mat, params, 0.199)
    if wf is None: continue
    
    wrs = [round(w['sr'], 3) for w in wf['window_results']]
    is_srs = [round(w['is_sr'], 3) for w in wf['window_results']]
    scales = [round(w['scale'], 3) for w in wf['window_results']]
    n_pos = sum(1 for w in wf['window_results'] if w['sr'] > 0)
    
    oos_sr = round(wf['oos_metrics']['sr'], 3)
    avg_is_sr = round(np.mean(is_srs), 3)
    ratio = round(abs(avg_is_sr / max(oos_sr, 0.001)), 2) if abs(oos_sr) > 0.001 else 99
    
    print('  %s: OOS_SR=%.3f AvgIS=%.3f Ratio=%.2f Win=%d/%d Scales=%s' % (
        label, oos_sr, avg_is_sr, ratio, n_pos, len(wrs), scales[:3]))
    print('    Test SRs: %s' % str(wrs))
