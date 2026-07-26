import pickle, numpy as np, pandas as pd, sys
sys.path.insert(0, '.')
from meme_coin_hedge_fund import generate_meme_signals, BASE, backtest_meme

with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
    return data

def build_aligned(freq='4h'):
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample(freq).first()
        h = d['High'].resample(freq).max()
        l = d['Low'].resample(freq).min()
        c = d['Close'].resample(freq).last()
        v = d['Volume'].resample(freq).sum()
        dfs[t] = pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v}, index=o.index)
    common = sorted(set.intersection(*[set(df.index) for df in dfs.values()]))
    return {t: dfs[t].loc[common].dropna() for t in dfs}, common

data, idx = build_aligned('4h')
print(f"Data built: {len(idx)} bars for {list(data.keys())}")

btc = data['BTC-USD']
doge = data['DOGE-USD']
print(f"DOGE shape: {doge.shape}")
print(f"BTC shape: {btc.shape}")
print(f"DOGE close: {doge['close'].values[:5]}")

sig = generate_meme_signals(doge, btc, BASE)
print(f"Signal: shape={sig.shape}, min={sig.min():.4f}, max={sig.max():.4f}")
print(f"Non-zero sigs: {np.sum(abs(sig)>0.01)}/{len(sig)}")

cv = doge['close'].values
v = doge['volume'].values
r = backtest_meme(cv, v, sig, BASE)
print(f"Backtest result: {r}")
