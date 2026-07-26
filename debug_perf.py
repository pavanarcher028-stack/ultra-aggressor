import pickle, numpy as np, pandas as pd, math
from meme_coin_hedge_fund import compute_features, generate_signal, data

ticker = 'DOGE-USD'
cv = data[ticker]['close'].values
v = data[ticker]['volume'].values
btc_cv = data['BTC-USD']['close'].values

f = compute_features(cv, v, btc_cv)

p = {'wv':0.35,'wa':0.25,'wk':0.15,'wt':0.25,'vt':1.5,'mp':0.80,
     'et':0.10,'di':0.50,'ta':5.0,'tt':[0.5,1.0,2.0,4.0],'cb':20,'mdk':0.40}

sig = generate_signal(f, p)

# Simple return contribution analysis
n = len(cv); eq = 1.0; pos = 0.0
eqs = np.ones(n); trades = 0; wins = 0
for i in range(1, n):
    s = sig[i]
    turn = abs(s-pos)
    if turn > 0 and abs(pos) > 0:
        trades += 1
        if eq > 1.0: wins += 1
    pos = s
    ret = cv[i]/cv[i-1] - 1 if cv[i-1] > 0 else 0
    if abs(pos) > 0.01:
        eq *= 1 + ret * pos
    eqs[i] = eq

ann_ret = (eq**(1/max(n/(365*24),0.1)) - 1)
print(f"Simple backtest: Final eq={eq:.4f}, Ann ret={ann_ret:.2%}, Trades={trades}, Win={wins}/{trades}")

# Compare: buy-and-hold
bh = cv[-1]/cv[0]
bh_ann = (bh**(1/max(n/(365*24),0.1)) - 1)
print(f"Buy & Hold: {bh:.2%}, Ann={bh_ann:.2%}")

# Check signal vs. price direction correlation
price_dir = np.sign(np.diff(np.log(cv), prepend=0))
sig_dir = np.sign(sig)
corr = np.corrcoef(price_dir[100:], sig_dir[100:])[0,1] if n > 100 else 0
print(f"Signal-price direction correlation: {corr:.3f}")

# Check if signal is better than random
rand_sig = np.random.choice([0, 0.2], size=n, p=[0.5, 0.5])
pos2 = 0.0; eq2 = 1.0
for i in range(1, n):
    s2 = rand_sig[i]
    pos2 = s2
    ret = cv[i]/cv[i-1] - 1
    if abs(pos2) > 0.01:
        eq2 *= 1 + ret * pos2
ann2 = (eq2**(1/max(n/(365*24),0.1)) - 1)
print(f"Random (50% in): Ann={ann2:.2%}")

# Analyze when signal is active vs market conditions
in_market = sig > 0.01
out_market = sig <= 0.01
in_returns = np.diff(np.log(cv))[1:][in_market[:-1]]  # returns when IN
out_returns = np.diff(np.log(cv))[1:][out_market[:-1]]  # returns when OUT
print(f"\nIn market: {np.mean(in_market):.1%} of time")
print(f"  Mean return when in: {np.mean(in_returns)*100:.4f}% per 4h")
print(f"  Mean return when out: {np.mean(out_returns)*100:.4f}% per 4h")
print(f"  Sum return when in: {np.sum(in_returns)*100:.2f}%")
print(f"  Sum return when out: {np.sum(out_returns)*100:.2f}%")
