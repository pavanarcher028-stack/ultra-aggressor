import numpy as np, pandas as pd, math
from meme_coin_hedge_fund import data, gen_signal_single, backtest_base, proxy_signals, backtest_meme

doge = data['DOGE-USD']
sig = gen_signal_single(doge, 'ema', fast=5, slow=50)
cv = doge['close'].values

# Vanilla backtest (no meme overlay, daily freq assumption)
r = backtest_base(cv, sig, scale=0.3, stop_loss=0.05)
if r:
    print(f"Vanilla (daily freq): SR={r['sr']:.3f} Ann={r['ann']:.2%} DD={r['dd']:.2%} Trades={r['trades']}")

# Fix: compute SR for 4h frequency
rets = pd.Series(np.diff(np.log(r['eqs']))).dropna()
tr = r['eqs'][-1]-1
ny = max(len(r['eqs'])/(365*6), 0.1)  # 6 periods per day (4h)
ann = (1+tr)**(1/ny)-1
sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*6)
print(f"  Fixed freq: SR={sr:.3f} Ann={ann:.2%}")

# Check proxy signals
prox = proxy_signals(doge)
print(f"\nvol_decay: mean={np.mean(prox['vol_decay']):.3f} p10={np.percentile(prox['vol_decay'],10):.3f} p50={np.percentile(prox['vol_decay'],50):.3f}")
print(f"whale: mean={np.mean(prox['whale']):.4f}")
print(f"liq: mean={np.mean(prox['liq']):.3f} p10={np.percentile(prox['liq'],10):.3f}")

# Test with meme overlay (fixed)
rp = {'ta': 15.0, 'tt': [1.0, 2.0, 3.0, 5.0], 'cb': 20, 'mdk': 0.50}
r2 = backtest_meme(cv, doge['volume'].values, sig, prox, rp)
if r2:
    print(f"\nMeme overlay: SR={r2['sr']:.3f} Ann={r2['ann']:.2%} DD={r2['dd']:.2%} Trades={r2['trades']}")

# What fraction of time is volume decay < 0.15?
print(f"\nVolume decay < 0.15: {np.mean(prox['vol_decay'] < 0.15):.1%}")
print(f"Volume decay < 0.30: {np.mean(prox['vol_decay'] < 0.30):.1%}")
