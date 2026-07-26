import pickle, numpy as np, pandas as pd, math
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

tickers = sorted(raw.keys())
daily = {}
for t in tickers:
    d = _flatten(raw[t])
    o = d['Open'].resample('1D').first()
    c = d['Close'].resample('1D').last()
    daily[t] = pd.DataFrame({'c': c.values.ravel()}, index=o.index).dropna()
common = sorted(set(daily[tickers[0]].index).intersection(*[set(daily[t].index) for t in tickers[1:]]))
close_mat = np.zeros((len(common), len(tickers)))
for j, t in enumerate(tickers):
    close_mat[:, j] = daily[t].loc[common, 'c'].values

def backtest_cs_scaled(close_arr, weights_arr, scale_factor=1.0, costs=0.0015):
    n = close_arr.shape[0]
    rets = close_arr[1:] / close_arr[:-1] - 1
    eq = 1.0; eqs = np.ones(n); peak = 1.0
    trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(close_arr.shape[1]); pos_active = False
    for i in range(1, n):
        w = weights_arr[i].copy() * scale_factor
        if np.any(np.isnan(w)) or np.any(np.isinf(w)):
            w = np.zeros_like(w)
        turnover = np.sum(np.abs(w - prev_w))
        if turnover > 1e-10:
            if pos_active:
                trades += 1
                if eq > entry_eq:
                    wins += 1
            pos_active = np.sum(np.abs(w)) > 1e-10
            entry_eq = eq
            eq -= turnover * costs * eq
        port_ret = np.sum(w * rets[i-1])
        eq *= 1 + port_ret
        eqs[i] = eq
        peak = max(peak, eq)
        prev_w = w.copy()
    if pos_active:
        trades += 1
        if eq > entry_eq:
            wins += 1
    rets_s = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ny = max(n/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets_s.mean()/rets_s.std()*math.sqrt(365) if len(rets_s)>0 and rets_s.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades, 1)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'trades':trades}

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
        weights[i] = w
        prev_w = w.copy()
    return weights

# Find scale factor that gives DD = 20% via binary search
def find_scale(close_arr, weights, target_dd, max_scale=1.0):
    lo, hi = 0.001, max_scale
    for _ in range(20):
        mid = (lo + hi) / 2
        r = backtest_cs_scaled(close_arr, weights, scale_factor=mid)
        if r['dd'] > target_dd:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

# Test multiple strategies
for lb, rebal in [(30,3), (30,5), (55,3), (10,10)]:
    w = cs_weekly(close_mat, lb, 3, 3, rebal)
    r_nat = backtest_cs_scaled(close_mat, w, scale_factor=1.0)
    s = find_scale(close_mat, w, 0.20)
    rs = backtest_cs_scaled(close_mat, w, scale_factor=s)
    wr_ok = 40 <= rs['wr']*100 <= 55
    sr_ok = rs['sr'] >= 1.0
    dd_ok = rs['dd'] < 0.20
    ann_ok = rs['ann'] >= 0.20
    p = sum([wr_ok, dd_ok, sr_ok, ann_ok])
    print('L%d_RF%d: scale=%.4f NativeDD=%.2f%% ScaledDD=%.2f%% SR=%.3f WR=%.1f%% Ann=%.1f%% P=%d' % (
        lb, rebal, s, r_nat['dd']*100, rs['dd']*100, rs['sr'], rs['wr']*100, rs['ann']*100, p))
