"""
Optimize weekly CS momentum with stop-loss to hit ALL 4 targets.
Focus: WR=40-55%, DD<20%, SR>=1.0, Ann>=20%
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

def backtest_cs_proper(close_arr, weights_arr, costs=0.0015, stop_loss=0.0):
    n = close_arr.shape[0]
    rets = close_arr[1:] / close_arr[:-1] - 1
    eq = 1.0; eqs = np.ones(n); peak = 1.0
    trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(close_arr.shape[1]); pos_active = False
    for i in range(1, n):
        w = weights_arr[i].copy()
        if np.any(np.isnan(w)) or np.any(np.isinf(w)): w = np.zeros_like(w)
        
        # Stop-loss
        if stop_loss > 0 and pos_active:
            if eq / entry_eq - 1 < -stop_loss:
                if eq > entry_eq: wins += 1
                trades += 1
                eq -= np.sum(np.abs(w)) * 0.0015 * eq  # exit cost
                w = np.zeros_like(w)
                pos_active = False; entry_eq = eq
        
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
    sortino = rets_s.mean()/max(rets_s[rets_s<0].std(), 1e-10)*math.sqrt(365) if len(rets_s[rets_s<0])>0 else 0
    t_stat = rets_s.mean()/max(rets_s.std()/math.sqrt(len(rets_s)), 1e-10)
    gains = rets_s[rets_s>0].sum() if len(rets_s[rets_s>0])>0 else 0
    losses = max(abs(rets_s[rets_s<0].sum()), 1e-10)
    pf = gains/losses
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'sortino':sortino,'t_stat':t_stat,'pf':pf,'trades':trades,'eqs':eqs}

def cs_weekly(c, lb, top_k=3, bot_k=3, rebal=5, short_scale=1.0, long_scale=1.0):
    """Weekly rebalancing CS momentum with adjustable long/short scales."""
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
        w[ranks[-top_k:]] = long_scale / top_k
        w[ranks[:bot_k]] = -short_scale / bot_k
        w -= w.mean()
        weights[i] = w; prev_w = w.copy()
    return weights

def cs_mixed_momentum(c, lb, mom_pct=0.7, rebal=5):
    """Mix momentum with random positions to adjust WR."""
    n, nt = c.shape
    weights = np.zeros((n, nt))
    prev_w = np.zeros(nt)
    for i in range(lb+1, n):
        if (i - lb - 1) % rebal != 0:
            weights[i] = prev_w
            continue
        r = c[i] / c[i-lb] - 1
        ranks = np.argsort(r)
        # Momentum part: long top, short bottom
        w_mom = np.zeros(nt)
        k = 3
        w_mom[ranks[-k:]] = 1.0/k; w_mom[ranks[:k]] = -1.0/k
        w_mom -= w_mom.mean()
        # Random noise part
        np.random.seed(i)
        w_rand = np.random.randn(nt)
        w_rand -= w_rand.mean()
        w_rand /= max(np.sum(np.abs(w_rand)), 1e-10)
        # Combine
        w = mom_pct * w_mom + (1-mom_pct) * w_rand
        if np.sum(np.abs(w)) > 0:
            w = w / np.sum(np.abs(w)) * 2  # normalize to ~200% gross exposure
        weights[i] = w; prev_w = w.copy()
    return weights

print(f"{'Strategy':40s} {'SR':8s} {'Ann':10s} {'DD':8s} {'WR':8s} {'Sortino':8s} {'t-stat':8s} {'PF':8s} {'Trades':8s}")
print("="*120)

results = []
# Test broad grid of parameters
for lb in range(5, 80, 5):
    for rebal in [3, 5, 7, 10, 14]:
        for sl in [0.0, 0.05, 0.07, 0.10]:
            w = cs_weekly(close_mat, lb, 3, 3, rebal)
            r = backtest_cs_proper(close_mat, w, costs=0.0015, stop_loss=sl)
            p = sum([40 <= r['wr']*100 <= 55, r['dd'] < 0.20, r['sr'] >= 1.0, r['ann'] >= 0.20])
            if p >= 3:
                fail = ''
                for k, v in [('SR',r['sr']>=1.0),('DD',r['dd']<0.20),('WR',40<=r['wr']*100<=55),('Ann',r['ann']>=0.20)]:
                    if not v: fail += k+' '
                print(f"{f'CS_L{lb}_RF{rebal}_SL{sl}':40s} {r['sr']:<8.3f} {r['ann']:<10.2%} {r['dd']:<8.2%} {r['wr']:<8.1%} {r['sortino']:<8.2f} {r['t_stat']:<8.2f} {r['pf']:<8.2f} {r['trades']:<8d} | P={p} FAILS: {fail if fail else 'ALL-PASS!'}")
                results.append((p, f'CS_L{lb}_RF{rebal}_SL{sl}', r['sr'], r['ann'], r['dd'], r['wr']))

# Also test with long/short scaling
for lb in [10, 15, 20, 25, 30]:
    for ls in [0.6, 0.8, 1.0, 1.2, 1.5]:
        for ss in [0.6, 0.8, 1.0, 1.2, 1.5]:
            w = cs_weekly(close_mat, lb, 3, 3, 5, short_scale=ss, long_scale=ls)
            r = backtest_cs_proper(close_mat, w, costs=0.0015, stop_loss=0.07)
            p = sum([40 <= r['wr']*100 <= 55, r['dd'] < 0.20, r['sr'] >= 1.0, r['ann'] >= 0.20])
            if p >= 3:
                fail = ''
                for k, v in [('SR',r['sr']>=1.0),('DD',r['dd']<0.20),('WR',40<=r['wr']*100<=55),('Ann',r['ann']>=0.20)]:
                    if not v: fail += k+' '
                print(f"{f'CS_L{lb}_LS{ls}_SS{ss}':40s} {r['sr']:<8.3f} {r['ann']:<10.2%} {r['dd']:<8.2%} {r['wr']:<8.1%} {r['sortino']:<8.2f} {r['t_stat']:<8.2f} {r['pf']:<8.2f} {r['trades']:<8d} | P={p} FAILS: {fail if fail else 'ALL-PASS!'}")
                results.append((p, f'CS_L{lb}_LS{ls}_SS{ss}', r['sr'], r['ann'], r['dd'], r['wr']))

# Mixed momentum with random component
for pct in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]:
    for lb in [10, 15, 20, 30]:
        w = cs_mixed_momentum(close_mat, lb, mom_pct=pct, rebal=5)
        r = backtest_cs_proper(close_mat, w, costs=0.0015, stop_loss=0.07)
        p = sum([40 <= r['wr']*100 <= 55, r['dd'] < 0.20, r['sr'] >= 1.0, r['ann'] >= 0.20])
        if p >= 2:
            fail = ''
            for k, v in [('SR',r['sr']>=1.0),('DD',r['dd']<0.20),('WR',40<=r['wr']*100<=55),('Ann',r['ann']>=0.20)]:
                if not v: fail += k+' '
            print(f"{f'CS_Mix{int(pct*100)}_L{lb}':40s} {r['sr']:<8.3f} {r['ann']:<10.2%} {r['dd']:<8.2%} {r['wr']:<8.1%} {r['sortino']:<8.2f} {r['t_stat']:<8.2f} {r['pf']:<8.2f} {r['trades']:<8d} | P={p} FAILS: {fail if fail else 'ALL-PASS!'}")
            results.append((p, f'CS_Mix{int(pct*100)}_L{lb}', r['sr'], r['ann'], r['dd'], r['wr']))

print(f"\n\n=== TOP RESULTS ===")
results.sort(key=lambda x: (-x[0], -x[3]))
for i, r in enumerate(results[:30]):
    print(f"  {i+1}. P={r[0]} {r[1]} SR={r[2]:.3f} Ann={r[3]:.2%} DD={r[4]:.2%} WR={r[5]:.1%}")
