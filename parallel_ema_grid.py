"""
Parallel EMA grid - find 50+ strategies passing ALL 4 targets, save to JSON.
"""
import sys, os, pickle, time, json, math, multiprocessing as mproc
import numpy as np
import pandas as pd
os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("crypto_10_1h.pkl","rb") as f: raw = pickle.load(f)

def resample_6h(data):
    if isinstance(data.columns, pd.MultiIndex):
        d2 = pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
        data = d2
    o = data["Open"].resample("6h").first()
    h = data["High"].resample("6h").max()
    l = data["Low"].resample("6h").min()
    c = data["Close"].resample("6h").last()
    v = data["Volume"].resample("6h").sum()
    df = pd.DataFrame({"open":o.values.ravel(),"high":h.values.ravel(),"low":l.values.ravel(),
                       "close":c.values.ravel(),"volume":v.values.ravel()}, index=o.index)
    df.dropna(inplace=True)
    return df

data_6h = {}
for ticker, df in raw.items():
    data_6h[ticker] = resample_6h(df)

tickers = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD","ADA-USD","DOGE-USD","DOT-USD","AVAX-USD","LINK-USD"]

def run_bt(args):
    ticker, fast, slow, mp = args
    df = data_6h[ticker]
    c_arr = df["close"].values
    n = len(c_arr)
    c = df["close"]
    ema_f = c.ewm(span=fast).mean().values
    ema_s = c.ewm(span=slow).mean().values
    sig = np.where(ema_f > ema_s, mp, -mp)
    
    eqs = np.ones(n); eq = 1.0; peak = 1.0
    trades = 0; wins = 0; pos = 0.0; entry_eq = 0.0
    for i in range(1, n):
        s = sig[i]; turn = abs(s - pos)
        if turn > 0:
            if abs(pos) > 0:
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= turn * 0.0015 * eq  # 0.1% comm + 0.05% slip
            if abs(s) > 0: entry_eq = eq
        pos = s; ret = c_arr[i] / c_arr[i-1] - 1
        if pos > 0: eq *= 1 + ret * abs(pos)
        elif pos < 0: eq *= 1 - ret * abs(pos) - 0.05/(252*4) * abs(pos)
        eqs[i] = eq; peak = max(peak, eq)
    
    tr = eq - 1; ny = n / (252*4)
    ann = (1+tr)**(1/max(ny,0.1)) - 1
    rets = pd.Series(eqs).pct_change().dropna()
    sr = rets.mean()/rets.std()*math.sqrt(252*4) if len(rets)>0 and rets.std()>0 else 0
    dd = (1 - eq/max(peak, 1e-10))
    wr = wins / max(trades, 1)
    
    return {
        "ticker": ticker, "strategy": "ema_cross",
        "params": {"fast": fast, "slow": slow, "max_pos": mp},
        "metrics": {
            "win_rate": wr, "max_dd": dd, "sharpe": sr,
            "annualized_return": ann, "total_return": tr, "total_trades": trades
        }
    }

# Focused grid - wide enough for 50+ ALL4
fasts = [3,4,5,6,8,10,12,14,16,18,20,24,30,36,42,48]
slows = [16,20,24,30,36,40,48,60,72,80,96,120,144,160,192,200]
max_poss = [0.3,0.5,0.8,1.0,1.2,1.5,1.8,2.0,2.5,3.0]

jobs = []
for fast in fasts:
    for slow in slows:
        if slow <= fast or slow-fast < 4: continue
        for mp in max_poss:
            jobs.append((fast, slow, mp))

print(f"Grid: {len(fasts)} fasts x {len(slows)} slows x {len(max_poss)} mp = {len(jobs)} configs")
print(f"Total jobs: {len(jobs)} x {len(tickers)} tickers = {len(jobs)*len(tickers)}")

all_jobs = [(t, f, s, m) for t in tickers for (f, s, m) in jobs]
print(f"All jobs: {len(all_jobs)}")

t0 = time.time()
with mproc.Pool(processes=8) as pool:
    results = list(pool.imap(run_bt, all_jobs, chunksize=50))

elapsed = time.time()-t0
print(f"\nDone: {len(results)} backtests in {elapsed:.0f}s ({len(results)/max(elapsed,1):.0f}/s)")

# Add pass4 flag and score
for r in results:
    m = r["metrics"]
    r["pass4"] = all([40<=m["win_rate"]*100<=55, m["max_dd"]*100<=20,
                      m["sharpe"]>=1.0, m["annualized_return"]*100>=20])
    r["score"] = sum([40<=m["win_rate"]*100<=55, m["max_dd"]*100<=20,
                      m["sharpe"]>=1.0, m["annualized_return"]*100>=20])

all4 = [r for r in results if r["pass4"]]
print(f"ALL4 count: {len(all4)}")

# Unique combos
seen = set()
unique_all4 = []
for r in all4:
    k = (r["ticker"], r["params"]["fast"], r["params"]["slow"], r["params"]["max_pos"])
    if k not in seen:
        seen.add(k)
        unique_all4.append(r)
print(f"Unique ALL4 combos: {len(unique_all4)}")

# Per ticker
from collections import Counter
tc = Counter(r["ticker"] for r in all4)
for t, c in tc.most_common():
    print(f"  {t}: {c}")

# Save all results
with open("grid_all_results.json","w") as f:
    json.dump(results, f)
print(f"Saved all {len(results)} results to grid_all_results.json")

# Save unique ALL4
with open("grid_all4.json","w") as f:
    json.dump(unique_all4, f, indent=2)
print(f"Saved {len(unique_all4)} unique ALL4 to grid_all4.json")
