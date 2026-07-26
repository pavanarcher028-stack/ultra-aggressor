import pickle, numpy as np, pandas as pd
from meme_coin_hedge_fund import compute_features, generate_signal

with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values.ravel() for c in data.columns}, index=data.index)
    return data

def build_data(freq='4h'):
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample(freq).first(); h = d['High'].resample(freq).max()
        l = d['Low'].resample(freq).min(); c = d['Close'].resample(freq).last()
        v = d['Volume'].resample(freq).sum()
        dfs[t] = pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v}, index=o.index)
    common = sorted(set.intersection(*[set(df.index) for df in dfs.values()]))
    return {t: dfs[t].loc[common] for t in dfs}, common

data, idx = build_data('4h')

# Check DOGE
cv = data['DOGE-USD']['close'].values
v = data['DOGE-USD']['volume'].values
btc_cv = data['BTC-USD']['close'].values

f = compute_features(cv, v, btc_cv)

print("=== Proxy Signal Stats (DOGE) ===")
for k in ['accum','viral','whale','kol','liq']:
    arr = f[k]
    print(f"{k:8s}: mean={np.mean(arr):.4f} std={np.std(arr):.4f} max={np.max(arr):.4f} nonzero={np.mean(arr>0.01):.2%}")

print(f"\nema_f > ema_s: {np.mean(f['ema_f'] > f['ema_s']):.2%}")
print(f"vol range: {np.min(f['vol']):.4f} to {np.max(f['vol']):.4f}")

# Test signal
test_p = {'wv':0.35,'wa':0.25,'wk':0.15,'wt':0.25,'vt':0.40,'mp':0.50,
          'et':0.30,'di':0.50,'ta':3.0,'tt':[0.5,1.0,2.0,4.0],'cb':30,'mdk':0.30}
sig = generate_signal(f, test_p)
print(f"\nSignal stats:")
print(f"  Non-zero: {np.mean(np.abs(sig)>0.01):.2%}")
print(f"  Mean when active: {np.mean(sig[np.abs(sig)>0.01]):.4f}")
print(f"  Range: {np.min(sig):.4f} to {np.max(sig):.4f}")

# Check entry scores at each bar
entry_scores = np.zeros(len(cv))
tech = (f['ema_f'] > f['ema_s']).astype(float)
entry_scores = (test_p['wv']*f['viral'] + test_p['wa']*f['accum'] +
                test_p['wk']*f['kol'] + test_p['wt']*tech)
print(f"\nEntry scores:")
print(f"  Mean: {np.mean(entry_scores):.4f}")
print(f"  Max: {np.max(entry_scores):.4f}")
print(f"  >0.30: {np.mean(entry_scores>0.30):.2%}")
print(f"  >0.20: {np.mean(entry_scores>0.20):.2%}")
print(f"  >0.10: {np.mean(entry_scores>0.10):.2%}")

# Check what limits each component
print(f"\n=== Component breakdown at max entry ===")
idx_max = np.argmax(entry_scores)
print(f"At bar {idx_max}:")
print(f"  accum={f['accum'][idx_max]:.4f}")
print(f"  viral={f['viral'][idx_max]:.4f}")
print(f"  kol={f['kol'][idx_max]:.4f}")
print(f"  tech={tech[idx_max]:.1f}")
print(f"  entry={entry_scores[idx_max]:.4f}")
print(f"  price={cv[idx_max]:.2f}, vol={v[idx_max]:.0f}")

# Also check a few random high-volume periods
print(f"\n=== Top 5 entry score bars ===")
top5 = np.argsort(entry_scores)[-5:][::-1]
for i in top5:
    print(f"  [{i}] entry={entry_scores[i]:.4f} accum={f['accum'][i]:.4f} viral={f['viral'][i]:.4f} kol={f['kol'][i]:.4f} tech={tech[i]:.1f}")
