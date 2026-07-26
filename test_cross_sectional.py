"""Test cross-sectional strategies - these should be market neutral and more robust."""
import pickle, numpy as np, pandas as pd, math
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

# Build daily matrix
tickers = sorted(raw.keys())
daily = {}
for t in tickers:
    d = _flatten(raw[t])
    o = d['Open'].resample('1D').first(); c = d['Close'].resample('1D').last()
    daily[t] = pd.DataFrame({'c':c.values.ravel(),'o':o.values.ravel()}, index=o.index).dropna()

# Align dates
common = set(daily[tickers[0]].index)
for t in tickers[1:]:
    common &= set(daily[t].index)
common = sorted(common)

close_mat = np.zeros((len(common), len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values

def backtest_cs(close_mat, weights_mat, costs=0.0015):
    """Cross-sectional backtest with walk-forward compatible structure."""
    n_bars = close_mat.shape[0]
    rets = close_mat[1:] / close_mat[:-1] - 1
    eq = 1.0; eqs = np.ones(n_bars); peak = 1.0
    trades = 0; wins = 0; entry_eq = 1.0
    prev_w = np.zeros(close_mat.shape[1])
    
    for i in range(1, n_bars):
        w = weights_mat[i]
        if np.any(np.isnan(w)) or np.any(np.isinf(w)):
            w = np.zeros_like(w)
        # Rebalancing cost
        turnover = np.sum(np.abs(w - prev_w))
        if turnover > 0:
            if np.any(np.abs(prev_w) > 1e-10):
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= turnover * costs * eq
            entry_eq = eq
        # P&L
        port_ret = np.sum(w * rets[i-1])
        eq *= 1 + port_ret
        eqs[i] = eq; peak = max(peak, eq)
        prev_w = w.copy()
    
    rets_s = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ny = max(n_bars/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets_s.mean()/rets_s.std()*math.sqrt(365) if len(rets_s)>0 and rets_s.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades, 1)
    sortino = rets_s.mean()/rets_s[rets_s<0].std()*math.sqrt(365) if len(rets_s[rets_s<0])>0 and rets_s[rets_s<0].std()>0 else 0
    t_stat = rets_s.mean()/max(rets_s.std()/math.sqrt(len(rets_s)), 1e-10)
    gains = rets_s[rets_s>0].sum() if len(rets_s[rets_s>0])>0 else 0
    losses = abs(rets_s[rets_s<0].sum()) if len(rets_s[rets_s<0])>0 else 1e-10
    pf = gains/max(losses, 1e-10)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'sortino':sortino,'t_stat':t_stat,'pf':pf,'trades':trades,'eqs':eqs,'rets':rets_s}

def cs_momentum(close_mat, lb, top_k=3, bot_k=3):
    """Cross-sectional momentum with market neutral weighting."""
    n, nt = close_mat.shape
    weights = np.zeros((n, nt))
    for i in range(lb+1, n):
        r = close_mat[i] / close_mat[i-lb] - 1
        ranks = np.argsort(r)
        w = np.zeros(nt)
        w[ranks[-top_k:]] = 1.0/top_k
        w[ranks[:bot_k]] = -1.0/bot_k
        w -= w.mean()  # market neutral
        weights[i] = w
    return weights

def cs_momentum_vol_scaled(close_mat, lb, top_k=3, bot_k=3, vol_lookback=20):
    """Cross-sectional momentum with volatility scaling."""
    n, nt = close_mat.shape
    weights = np.zeros((n, nt))
    rets = close_mat[1:] / close_mat[:-1] - 1
    for i in range(lb+1, n):
        r = close_mat[i] / close_mat[i-lb] - 1
        ranks = np.argsort(r)
        w = np.zeros(nt)
        w[ranks[-top_k:]] = 1.0/top_k
        w[ranks[:bot_k]] = -1.0/bot_k
        # Vol scaling
        if i > vol_lookback:
            vols = np.array([np.std(rets[max(0,i-vol_lookback):i, j]) for j in range(nt)])
            mean_vol = np.mean(vols)
            vol_scale = mean_vol / np.maximum(vols, 1e-10)
            w = w * vol_scale
        w -= w.mean()
        weights[i] = w
    return weights

def cs_dual_momentum(close_mat, fast_lb, slow_lb, top_k=2):
    """Dual momentum: need both fast and slow momentum to be positive to go long."""
    n, nt = close_mat.shape
    weights = np.zeros((n, nt))
    for i in range(max(fast_lb, slow_lb)+1, n):
        r_fast = close_mat[i] / close_mat[i-fast_lb] - 1
        r_slow = close_mat[i] / close_mat[i-slow_lb] - 1
        # Only long coins with positive fast AND slow momentum
        scores = np.where((r_fast > 0) & (r_slow > 0), r_fast + r_slow, -np.inf)
        # Short coins with negative fast AND slow momentum
        short_scores = np.where((r_fast < 0) & (r_slow < 0), -(r_fast + r_slow), -np.inf)
        w = np.zeros(nt)
        top = np.argsort(-scores)[:top_k]
        bot = np.argsort(-short_scores)[:top_k]
        if np.any(scores[top] > -np.inf):
            w[top] = 1.0/sum(scores[top] > -np.inf)
        if np.any(short_scores[bot] > -np.inf):
            w[bot] -= 1.0/sum(short_scores[bot] > -np.inf)
        if np.sum(np.abs(w)) > 0:
            w -= w.mean()
        weights[i] = w
    return weights

def cs_mean_reversion(close_mat, lb, top_k=3, bot_k=3):
    """Mean reversion: short winners, long losers."""
    w = cs_momentum(close_mat, lb, top_k, bot_k)
    return -w

def cs_pairs(close_mat, lb=20):
    """Simple pair trading: find most correlated pair, trade divergence."""
    n, nt = close_mat.shape
    rets = close_mat[1:] / close_mat[:-1] - 1
    weights = np.zeros((n, nt))
    for i in range(lb*2, n):
        # Find most correlated pair in lookback
        corr_mat = np.corrcoef(rets[i-lb:i].T)
        np.fill_diagonal(corr_mat, -1)
        max_corr_idx = np.unravel_index(np.argmax(corr_mat), corr_mat.shape)
        # Spread
        p1, p2 = max_corr_idx
        spread = np.log(close_mat[:i+1, p1] / close_mat[:i+1, p2])
        z = (spread[-1] - np.mean(spread[-lb:])) / max(np.std(spread[-lb:]), 1e-10)
        if z > 1.5:
            weights[i, p1] = -0.5  # short overperformer
            weights[i, p2] = 0.5   # long underperformer
        elif z < -1.5:
            weights[i, p1] = 0.5   # long underperformer
            weights[i, p2] = -0.5  # short overperformer
        weights[i] -= weights[i].mean()
    return weights

print(f"{'Strategy':30s} {'SR':8s} {'Ann':8s} {'DD':8s} {'Sortino':8s} {'t-stat':8s} {'PF':8s} {'Trades':8s} {'WR':8s}")
print("="*100)

# Test all CS strategies
for name, func, params in [
    ('CS_Mom_10', cs_momentum, {'lb':10,'top_k':3,'bot_k':3}),
    ('CS_Mom_20', cs_momentum, {'lb':20,'top_k':3,'bot_k':3}),
    ('CS_Mom_40', cs_momentum, {'lb':40,'top_k':3,'bot_k':3}),
    ('CS_Mom_60', cs_momentum, {'lb':60,'top_k':3,'bot_k':3}),
    ('CS_Mom_80', cs_momentum, {'lb':80,'top_k':3,'bot_k':3}),
    ('CS_Mom_120', cs_momentum, {'lb':120,'top_k':3,'bot_k':3}),
    ('CS_Rev_10', cs_mean_reversion, {'lb':10,'top_k':3,'bot_k':3}),
    ('CS_Rev_20', cs_mean_reversion, {'lb':20,'top_k':3,'bot_k':3}),
    ('CS_Rev_40', cs_mean_reversion, {'lb':40,'top_k':3,'bot_k':3}),
    ('CS_MomVol_20', cs_momentum_vol_scaled, {'lb':20,'top_k':3,'bot_k':3,'vol_lookback':20}),
    ('CS_MomVol_40', cs_momentum_vol_scaled, {'lb':40,'top_k':3,'bot_k':3,'vol_lookback':20}),
    ('CS_Dual_20_60', cs_dual_momentum, {'fast_lb':20,'slow_lb':60,'top_k':2}),
    ('CS_Dual_10_40', cs_dual_momentum, {'fast_lb':10,'slow_lb':40,'top_k':2}),
    ('CS_Dual_20_80', cs_dual_momentum, {'fast_lb':20,'slow_lb':80,'top_k':2}),
    ('CS_Pairs_20', cs_pairs, {'lb':20}),
]:
    w = func(close_mat, **params)
    r = backtest_cs(close_mat, w)
    p = sum([40 <= r['wr']*100 <= 55, r['dd'] < 0.20, r['sr'] >= 1.0, r['ann'] >= 0.20])
    fail = ''
    if r['sr'] < 1.0: fail += 'SR '
    if r['dd'] >= 0.20: fail += 'DD '
    if r['t_stat'] < 2.0: fail += 't '
    if r['sortino'] < 1.5: fail += 'Sort '
    if r['pf'] < 1.3: fail += 'PF '
    if r['trades'] < 60: fail += 'Tr '
    print(f"{name:30s} {r['sr']:<8.3f} {r['ann']:<8.2%} {r['dd']:<8.2%} {r['sortino']:<8.2f} {r['t_stat']:<8.2f} {r['pf']:<8.2f} {r['trades']:<8d} {r['wr']:<8.1%} | P={p} FAILS: {fail if fail else 'NONE'}")
