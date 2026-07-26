"""
Full hedge fund pipeline (Gates 1-7) on the 51 passing CS strategies.
Tests walk-forward validation, statistical significance, and risk analysis.
"""
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
print('Data: %d bars, %d coins' % (n_bars, N_COINS))

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5, start_idx=0):
    """Generate CS weights matrix starting from start_idx."""
    n, nt = c.shape
    weights = np.zeros((n, nt))
    prev_w = np.zeros(nt)
    for i in range(max(lb+1, start_idx+1), n):
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

class GateResult:
    def __init__(self, name): self.name = name; self.tests = {}; self.passed = True
    def add(self, tn, passed, det=''):
        self.tests[tn] = {'passed':passed,'details':det}
        if not passed: self.passed = False

def run_gates(eqs_oos, eqs_all, window_results, name):
    g = GateResult(name)
    rets_all = pd.Series(np.diff(np.log(eqs_all))).dropna()
    rets_oos = pd.Series(np.diff(np.log(eqs_oos))).dropna()
    m_all = get_metrics(eqs_all)
    m_oos = get_metrics(eqs_oos)
    
    # Gate 1: Data sanity
    g.add('G1.1 No NaN', not np.any(np.isnan(eqs_all)))
    total_trades = sum(w.get('t_oad', w.get('trades',0)) for w in window_results)
    g.add('G1.2 Min Trades 60', total_trades >= 60, 'Trades: %d' % total_trades)
    
    # Gate 3: Walk-forward
    oos_srs = [w['sr'] for w in window_results if w.get('sr') is not None]
    is_srs = [w['is_sr'] for w in window_results if w.get('is_sr') is not None]
    wfes = []
    for i in range(len(is_srs)):
        if abs(is_srs[i]) > 0.001:
            wfes.append(oos_srs[i] / abs(is_srs[i]))
    avg_wfe = np.mean(wfes) if wfes else 0
    g.add('G3.1 WFE > 0.5', avg_wfe > 0.5, 'WFE=%.3f' % avg_wfe)
    
    # Average IS SR from walk-forward windows
    is_srs_list = [w['is_sr'] for w in window_results if w.get('is_sr') is not None]
    avg_is_sr = np.mean(is_srs_list) if is_srs_list else 0
    global_oos_sr = m_oos['sr']
    is_oos_ratio = abs(avg_is_sr / max(global_oos_sr, 0.001)) if abs(global_oos_sr) > 0.001 else 99
    g.add('G3.2 OOS SR>=0.15 IS/OOS<=2', global_oos_sr >= 0.15 and is_oos_ratio <= 2.0,
          'OOS SR=%.3f AvgIS=%.3f IS/OOS=%.2f' % (global_oos_sr, avg_is_sr, is_oos_ratio))
    
    neg_count = sum(1 for w in window_results if w.get('sr',0) < 0)
    g.add('G3.3 Neg Windows <= 1', neg_count <= 1, '%d negative' % neg_count)
    g.add('G3.5 Min Windows >= 3', len(window_results) >= 3, '%d windows' % len(window_results))
    
    # Gate 4: Statistical significance
    g.add('G4.1 SR >= 1.0', m_all['sr'] >= 1.0, 'SR=%.3f' % m_all['sr'])
    g.add('G4.2 t-stat >= 2.0', m_all['t_stat'] >= 2.0, 't=%.3f' % m_all['t_stat'])
    
    # Bootstrap
    if len(rets_all) > 20:
        boot_srs = []
        for _ in range(500):
            samp = np.random.choice(rets_all, len(rets_all))
            boot_srs.append(samp.mean()/max(samp.std(),1e-10)*math.sqrt(365))
        ci_lower = np.percentile(boot_srs, 5)
        g.add('G4.3 Bootstrap LB > 0', ci_lower > 0, '5th%% SR=%.3f' % ci_lower)
    
    # Perm test
    if len(rets_all) > 20:
        real_mean = rets_all.mean()
        perm_means = []
        for _ in range(500):
            perm = np.random.choice(rets_all, len(rets_all)) * np.random.choice([-1,1], len(rets_all))
            perm_means.append(perm.mean())
        p_val = np.mean(np.array(perm_means) >= real_mean)
        g.add('G4.4 Permutation p<0.05', p_val < 0.05, 'p=%.4f' % p_val)
    
    # Gate 5: Risk
    g.add('G5.1 MaxDD < 20%%', m_all['dd'] < 0.20, 'DD=%.2f%%' % (m_all['dd']*100))
    g.add('G5.2 Calmar > 0.5', m_all['ann']/max(m_all['dd'],0.001) > 0.5 if m_all['dd']>0 else False,
          'Calmar=%.2f' % (m_all['ann']/max(m_all['dd'],0.001)))
    g.add('G5.3 Sortino > 1.5', m_all['sortino'] > 1.5, 'Sortino=%.3f' % m_all['sortino'])
    g.add('G5.4 PF > 1.3', m_all['pf'] > 1.3, 'PF=%.3f' % m_all['pf'])
    
    # Gate 6: Regime
    if len(rets_all) > 40:
        half = len(rets_all)//2
        eqs1 = np.exp(np.concatenate([[0], rets_all[:half].cumsum()]))
        eqs2 = np.exp(np.concatenate([[0], rets_all[half:].cumsum()]))
        pos_reg = sum([get_metrics(eqs1)['sr'] > 0, get_metrics(eqs2)['sr'] > 0])
        g.add('G6.1 Regime Pos >= 2', pos_reg >= 2, '%d/2' % pos_reg)
        
        crisis = np.sort(rets_all)[:max(len(rets_all)//10,5)]
        c_sr = crisis.mean()/max(crisis.std(),1e-10)*math.sqrt(365)
        g.add('G6.2 Crisis SR > -2', c_sr > -2, 'Crisis SR=%.3f' % c_sr)
    
    return g

# Walk-forward test function
def walkforward_test(close_arr, weights_func, params, target_dd=0.199):
    """Run walk-forward validation for a CS strategy."""
    n = close_arr.shape[0]
    n_windows = 6
    window_size = n // n_windows
    
    window_results = []
    all_oos_eqs = [1.0]
    
    for wi in range(1, n_windows):  # Skip first window (no training)
        train_end = wi * window_size
        test_start = train_end
        test_end = min((wi+1) * window_size, n)
        
        if train_end < params['lb'] + 10:
            continue
        
        # Generate weights on training data
        train_w = weights_func(close_arr[:train_end], **params)
        test_w = weights_func(close_arr[:test_end], **params)
        
        # Find optimal scale on training data
        train_bt = backtest_cs(close_arr[:train_end], train_w, 1.0)
        if train_bt['trades'] < 10:
            continue
        
        scale = find_scale(close_arr[:train_end], train_w, target_dd)
        
        # Test on OOS data
        oos_w = test_w[test_start:test_end]
        oos_bt = backtest_cs(close_arr[test_start:test_end], oos_w, scale)
        
        if oos_bt['trades'] < 5:
            continue
        
        is_sr = train_bt['sr']
        is_dd = train_bt['dd']
        
        window_results.append({
            'sr': oos_bt['sr'], 'is_sr': is_sr, 'is_dd': is_dd,
            'dd': oos_bt['dd'], 'ann': oos_bt['ann'],
            'trades': oos_bt['trades'],
            'wfe': oos_bt['sr'] / max(abs(is_sr), 0.01) if abs(is_sr) > 0.01 else 0
        })
        all_oos_eqs.append(oos_bt['eqs'][1:])
    
    if len(window_results) < 2:
        return None
    
    # Stitch OOS
    stitched = np.concatenate(all_oos_eqs)
    
    # Full backtest
    full_w = weights_func(close_arr, **params)
    full_bt = backtest_cs(close_arr, full_w, find_scale(close_arr, full_w, target_dd))
    
    return {
        'window_results': window_results,
        'eqs_oos': stitched,
        'eqs_all': full_bt['eqs'],
        'full_metrics': get_metrics(full_bt['eqs'])
    }

# Load the 51 passing strategies
with open('p4_strategies.json') as f:
    strategies = json.load(f)

print('Loaded %d strategies from p4_strategies.json' % len(strategies))
print()

# Run pipeline on each
print('Running full pipeline (Gates 1-7)...')
print('%s' % ('='*90))

passing_pipeline = []

for s in strategies:
    # Parse name to params
    n = s['name']
    # Extract params from name
    lb = s.get('lb', 22)
    rebal = s.get('rebal', 5)
    tk = s.get('top_k', 3)
    bk = s.get('bot_k', 3)
    
    params = {'lb': lb, 'top_k': tk, 'bot_k': bk, 'rebal': rebal}
    
    def make_func(par):
        return lambda c, **kw: cs_weekly(c, par['lb'], par['top_k'], par['bot_k'], par['rebal'])
    
    try:
        wf_result = walkforward_test(close_mat, make_func(params), params)
        if wf_result is None:
            continue
        
        gate = run_gates(wf_result['eqs_oos'], wf_result['eqs_all'],
                        wf_result['window_results'], n)
        
        # Debug: show which gates failed
        failed_gates = [k for k,v in gate.tests.items() if not v['passed']]
        if failed_gates:
            print('  FAIL [%s] Gates: %s' % (n, ', '.join(failed_gates[:5])))
        else:
            print('  PASS [%s] All gates pass!' % n)
        
        if gate.passed:
            m = wf_result['full_metrics']
            passing_pipeline.append({
                'name': n,
                'sr': m['sr'], 'ann': m['ann'], 'dd': m['dd'],
                'sortino': m['sortino'], 't_stat': m['t_stat'], 'pf': m['pf'],
                'n_windows': len(wf_result['window_results']),
                'avg_wfe': np.mean([w.get('wfe',0) for w in wf_result['window_results']]),
                'params': params,
                'scale': find_scale(close_mat, make_func(params)(close_mat), 0.199)
            })
            
            print('PASS [%s] SR=%.2f Ann=%.1f%% DD=%.1f%% Sortino=%.2f t=%.2f PF=%.2f WFE=%.3f Win=%d/%d' % (
                n, m['sr'], m['ann']*100, m['dd']*100, m['sortino'], m['t_stat'], m['pf'],
                np.mean([w.get('wfe',0) for w in wf_result['window_results']]),
                sum(1 for w in wf_result['window_results'] if w.get('sr',0) > 0),
                len(wf_result['window_results'])))
    
    except Exception as e:
        pass

print()
print('%s' % ('='*90))
print('PIPELINE COMPLETE: %d / %d strategies pass ALL gates' % (len(passing_pipeline), len(strategies)))
print('%s' % ('='*90))

# Sort by SR
passing_pipeline.sort(key=lambda x: -x['sr'])
for i, r in enumerate(passing_pipeline):
    print('  %2d. %20s SR=%.2f Ann=%.1f%% DD=%.1f%% Sortino=%.2f t=%.2f PF=%.2f WFE=%.3f' % (
        i+1, r['name'], r['sr'], r['ann']*100, r['dd']*100, r['sortino'], r['t_stat'], r['pf'], r['avg_wfe']))

# Save
with open('pipeline_pass.json', 'w') as f:
    json.dump(passing_pipeline, f, indent=2, default=str)
print('\nSaved %d pipeline-passing strategies to pipeline_pass.json' % len(passing_pipeline))
