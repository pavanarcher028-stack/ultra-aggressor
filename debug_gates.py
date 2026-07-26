"""Debug which gates pass/fail for each strategy."""
import pickle, numpy as np, pandas as pd, math
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def ema(s,p): return s.ewm(span=p).mean()
def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

tickers = ['BTC-USD','ETH-USD','SOL-USD','XRP-USD','ADA-USD']
data = {}
for t in tickers:
    d = _flatten(raw[t])
    o = d['Open'].resample('1D').first()
    c = d['Close'].resample('1D').last()
    data[t] = pd.DataFrame({'c':c.values.ravel()}, index=o.index).dropna()

def backtest(close_arr, sig_arr, scale=0.3, stop_loss=0.05):
    n = len(sig_arr)
    eq = 1.0; eqs = np.ones(n); trades = 0; wins = 0; pos = 0.0; entry_eq = 1.0; peak = 1.0
    for i in range(1, n):
        s = sig_arr[i-1] if i > 0 else 0.0
        if np.isnan(s) or np.isinf(s): s = 0.0
        s = max(min(s * scale, 1.0), -1.0)
        if stop_loss > 0 and abs(pos) > 0:
            if abs(eq / entry_eq - 1) >= stop_loss:
                if eq > entry_eq: wins += 1
                trades += 1; pos = 0.0; s = 0.0; entry_eq = eq
        turn = abs(s - pos)
        if turn > 0:
            if abs(pos) > 0:
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= turn * 0.0015 * eq
            if abs(s) > 0: entry_eq = eq
        pos = s; ret = close_arr[i] / close_arr[i-1] - 1
        if pos > 0: eq *= 1 + ret * abs(pos)
        elif pos < 0: eq *= 1 - ret * abs(pos) - 0.05 / 365 * abs(pos)
        eqs[i] = eq; peak = max(peak, eq)
    rets = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1; ny = max(n/365, 0.1)
    ann = (1+tr)**(1/ny)-1
    sr = rets.mean()/rets.std()*math.sqrt(365) if len(rets)>0 and rets.std()>0 else 0
    dd = (1-eqs/np.maximum.accumulate(eqs)).max()
    wr = wins/max(trades,1)
    sortino = rets.mean()/rets[rets<0].std()*math.sqrt(365) if len(rets[rets<0])>0 and rets[rets<0].std()>0 else 0
    t_stat = rets.mean()/max(rets.std()/math.sqrt(len(rets)), 1e-10)
    gains = rets[rets>0].sum() if len(rets[rets>0])>0 else 0
    losses = abs(rets[rets<0].sum()) if len(rets[rets<0])>0 else 1e-10
    pf = gains/max(losses, 1e-10)
    return {'sr':sr,'ann':ann,'dd':dd,'wr':wr,'sortino':sortino,'t_stat':t_stat,'pf':pf,'trades':trades,'rets':rets,'eqs':eqs}

print(f"{'Strategy':15s} {'Coin':8s} {'SR':8s} {'Ann':8s} {'DD':8s} {'WR':8s} {'t-stat':8s} {'Sortino':8s} {'PF':8s} {'Trades':8s} {'P4':4s}")
print("="*90)

# Test each strategy type at optimal scale
for name, kind, p, scale, sl in [
    ('EMA_5_50','ema',{'fast':5,'slow':50}, 0.3, 0.05),
    ('EMA_3_100','ema',{'fast':3,'slow':100}, 0.3, 0.05),
    ('EMA_10_50','ema',{'fast':10,'slow':50}, 0.3, 0.05),
    ('ZMR_20_1.5','zmr',{'p':20,'entry':1.5}, 0.3, 0.05),
    ('ZMR_10_1.5','zmr',{'p':10,'entry':1.5}, 0.25, 0.04),
    ('ZMR_40_1.5','zmr',{'p':40,'entry':1.5}, 0.35, 0.07),
    ('RSI50_14','rsi',{'p':14,'th':50}, 0.3, 0.05),
    ('HMA_8_40','hma',{'f':8,'s':40}, 0.3, 0.05),
    ('RSI7','rsi',{'p':7,'th':50}, 0.3, 0.04),
    ('RSI21','rsi',{'p':21,'th':50}, 0.3, 0.06),
]:
    for ticker in tickers:
        df = data[ticker]; c = df['c']; cv = c.values; n = len(cv)
        sig = np.zeros(n)
        
        if kind == 'ema':
            f = ema(c, p['fast']).values; s_ = ema(c, p['slow']).values
            sig = np.where(f > s_, 1.0, -1.0)
        elif kind == 'zmr':
            p_ = p['p']; entry = p['entry']
            m = c.rolling(p_).mean().values; std = c.rolling(p_).std().replace(0,1e-10).values
            z = (cv - m) / std
            for i in range(1, n):
                if z[i-1] <= -entry: sig[i] = 1.0
                elif z[i-1] >= entry: sig[i] = -1.0
                else: sig[i] = sig[i-1]
        elif kind == 'rsi':
            d = c.diff(); g = d.clip(0); l_ = -d.clip(upper=0)
            ag = g.ewm(span=p['p']).mean(); al = l_.ewm(span=p['p']).mean().replace(0,1e-10)
            rs = 100 - 100/(1+ag/al)
            sig = np.where(rs.values > 50, 1.0, -1.0)
        elif kind == 'hma':
            def hma(s,p_): return s.ewm(span=p_).mean()
            f = hma(c, p['f']).values; s_ = hma(c, p['s']).values
            sig = np.where(f > s_, 1.0, -1.0)
        
        r = backtest(cv, sig, scale=scale, stop_loss=sl)
        
        p4 = sum([40 <= r['wr']*100 <= 55, r['dd'] < 0.20, r['sr'] >= 1.0, r['ann'] >= 0.20])
        
        # Gate checks
        g1_min_trades = r['trades'] >= 60
        g3_wfe = True  # placeholder (need walk-forward for this)
        g4_sr = r['sr'] >= 1.0
        g4_tstat = r['t_stat'] >= 2.0
        g4_sortino = r['sortino'] > 1.5
        g4_pf = r['pf'] > 1.3
        g5_dd = r['dd'] < 0.20
        g5_calmar = r['ann'] / max(r['dd'], 0.001) > 0.5 if r['dd'] > 0 else False
        
        gate_str = ''
        if not g4_sr: gate_str += 'SR '
        if not g5_dd: gate_str += 'DD '
        if not g4_tstat: gate_str += 't '
        if not g4_sortino: gate_str += 'Sort '
        if not g4_pf: gate_str += 'PF '
        if not g1_min_trades: gate_str += 'Tr '
        
        print(f"{name:15s} {ticker:8s} {r['sr']:<8.3f} {r['ann']:<8.2%} {r['dd']:<8.2%} {r['wr']:<8.1%} {r['t_stat']:<8.2f} {r['sortino']:<8.2f} {r['pf']:<8.2f} {r['trades']:<8d} {p4:<4d} | FAILS: {gate_str if gate_str else 'NONE'}")
