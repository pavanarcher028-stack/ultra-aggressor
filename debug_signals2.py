import pickle, numpy as np, pandas as pd
from meme_coin_hedge_fund import compute_features, generate_signal, MEME, data

# Use DOGE
ticker = 'DOGE-USD'
cv = data[ticker]['close'].values
v = data[ticker]['volume'].values
btc_cv = data['BTC-USD']['close'].values

f = compute_features(cv, v, btc_cv)

p = {'wv':0.35,'wa':0.25,'wk':0.15,'wt':0.25,'vt':0.60,'mp':0.60,
     'et':0.10,'di':0.50,'ta':4.0,'tt':[0.5,1.0,2.0,4.0],'cb':20,'mdk':0.35}

n = len(cv); sig = np.zeros(n)
entry_hits = 0; first_entry = -1

for i in range(100, n):
    if f['whale'][i] > 0.5 or f['liq'][i] < 0.05:
        sig[i] = 0.0; continue
    tech = 1.0 if f['ema_f'][i] > f['ema_s'][i] else -0.5
    entry = (p['wv']*f['viral'][i] + p['wa']*f['accum'][i] +
             p['wk']*f['kol'][i] + p['wt']*tech)
    vol_scale = min(1.0, p['vt']/max(f['vol'][i], 0.01))
    max_pos = p['mp'] * vol_scale
    
    if abs(sig[i-1]) > 0.01:
        sig[i] = sig[i-1] * (1.2 if entry > 0.25 else 0.95 if entry < 0.05 else 1.0)
        sig[i] = min(sig[i], max_pos)
        if i < 200:  # debug first 100 bars
            print(f"  IN-POS bar {i}: entry={entry:.3f} sig={sig[i]:.4f} max_pos={max_pos:.4f} tech={tech}")
    elif entry > p['et'] and tech > 0:
        sig[i] = max_pos * p['di']
        if first_entry < 0: first_entry = i
        entry_hits += 1
        if entry_hits <= 5 or i < 200:
            print(f"  ENTRY bar {i}: entry={entry:.3f} sig={sig[i]:.4f} max_pos={max_pos:.4f} tech={tech} viral={f['viral'][i]:.3f} accum={f['accum'][i]:.3f} kol={f['kol'][i]:.3f}")
    elif entry > p['et'] * 1.3:
        sig[i] = max_pos * p['di'] * 0.6
        if entry_hits < 5:
            print(f"  ENTRY2 bar {i}: entry={entry:.3f} sig={sig[i]:.4f}")

print(f"\nFirst entry at bar: {first_entry}")
print(f"Total entry hits: {entry_hits}")
print(f"Non-zero signal: {np.mean(np.abs(sig) > 0.01):.2%}")

# Also check what's happening with early bars
print(f"\n=== Bar 100-120 analysis ===")
for i in range(100, 120):
    tech = 1.0 if f['ema_f'][i] > f['ema_s'][i] else -0.5
    entry = (p['wv']*f['viral'][i] + p['wa']*f['accum'][i] +
             p['wk']*f['kol'][i] + p['wt']*tech)
    cond1 = entry > p['et']
    cond2 = tech > 0
    blocked = f['whale'][i] > 0.5 or f['liq'][i] < 0.05
    print(f"  bar {i}: entry={entry:.4f} et={p['et']:.2f} entry>et={cond1} tech>0={cond2} blocked={blocked} liq={f['liq'][i]:.4f} whale={f['whale'][i]:.4f} viral={f['viral'][i]:.4f} accum={f['accum'][i]:.4f} kol={f['kol'][i]:.4f}")
