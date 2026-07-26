"""
Max EMA grid: all combos on 10 coins, find all strategies passing all 4 targets.
"""
import sys, os, pickle, time, json, math
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
print(f"Data: {len(tickers)} tickers, {len(next(iter(data_6h.values())))} bars each")

def run_bt(df, sig_fn, comm=0.001, slip=0.0005, borrow=0.05):
    sig=sig_fn(df)["signal"].values;c=df["close"].values;n=len(sig)
    eq=1.0;eqs=np.ones(n);trades=0;wins=0;pos=0.0;entry_eq=0.0;peak=1.0
    for i in range(1,n):
        s=sig[i];turn=abs(s-pos)
        if turn>0:
            if abs(pos)>0:
                trades+=1
                if eq>entry_eq:wins+=1
            eq-=turn*(comm+slip)*eq
            if abs(s)>0:entry_eq=eq
        pos=s;ret=c[i]/c[i-1]-1
        if pos>0:eq*=1+ret*abs(pos)
        elif pos<0:eq*=1-ret*abs(pos)-borrow/(252*4)*abs(pos)
        eqs[i]=eq;peak=max(peak,eq)
    rets=pd.Series(eqs).pct_change().dropna()
    tr=eqs[-1]-1;ny=n/(252*4)
    ann=(1+tr)**(1/max(ny,0.1))-1
    sr=rets.mean()/rets.std()*math.sqrt(252*4) if len(rets)>0 and rets.std()>0 else 0
    dd=(1-eqs/np.maximum.accumulate(eqs)).max()
    return {"wr":wins/max(trades,1)*100,"dd":dd*100,"sharpe":sr,"ann":ann*100,"total":tr*100,"trades":trades}

# EMA strategy
def ema_fn(fast,slow,mp):
    def gen(df):
        df=df.copy();c=df["close"]
        ema_f=c.ewm(span=fast).mean();ema_s=c.ewm(span=slow).mean()
        df["signal"]=pd.Series(np.where(ema_f>ema_s,mp,-mp),index=df.index)
        return df
    return gen

# Full grid
fasts = [3,4,5,6,8,10,12,14,16,18,20,24,30,36,42,48]
slows = [12,16,20,24,30,36,40,48,60,72,80,96,120,144,160,192,200]
max_poss = [0.3,0.5,0.8,1.0,1.2,1.5,1.8,2.0,2.5,3.0]

configs = []
for fast in fasts:
    for slow in slows:
        if slow<=fast or slow-fast<4: continue
        for mp in max_poss:
            configs.append((fast,slow,mp))

print(f"Total EMA configs: {len(configs)}")
print(f"Total backtests: {len(configs)} x {len(tickers)} = {len(configs)*len(tickers)}")

results=[];t0=time.time();all4=set()

for idx,(fast,slow,mp) in enumerate(configs):
    fn=ema_fn(fast,slow,mp)
    for ticker in tickers:
        try:
            r=run_bt(data_6h[ticker],fn)
            passes = sum([40<=r["wr"]<=55, r["dd"]<=20, r["sharpe"]>=1.0, r["ann"]>=20])
            r.update({"strategy":"ema_cross","ticker":ticker,"fast":fast,"slow":slow,"max_pos":mp,"passes":passes})
            results.append(r)
            if passes==4:
                key=(ticker,fast,slow,mp)
                if key not in all4:
                    all4.add(key)
                    print(f"  ALL4: {ticker:8s} fast={fast:2d} slow={slow:3d} mp={mp:.1f} WR={r['wr']:.1f}% DD={r['dd']:.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}% Trades={r['trades']}", flush=True)
        except:pass
    if (idx+1)%50==0:
        p4=sum(1 for r in results if r["passes"]==4)
        print(f"  {idx+1}/{len(configs)} configs -> {len(results)} res, {p4} pass ALL4 [{time.time()-t0:.0f}s]", flush=True)

elapsed=time.time()-t0
p4_all=[r for r in results if r["passes"]==4]
print(f"\n=== DONE ({elapsed:.0f}s) ===", flush=True)
print(f"Total ALL4: {len(p4_all)}", flush=True)

# Show unique (ticker,fast,slow,mp) combos
seen=set()
unique_all4=[]
for r in p4_all:
    k=(r["ticker"],r["fast"],r["slow"],r["max_pos"])
    if k not in seen:
        seen.add(k)
        unique_all4.append(r)
        print(f"  {r['ticker']:8s} fast={r['fast']:2d} slow={r['slow']:3d} mp={r['max_pos']:.1f} WR={r['wr']:.1f}% DD={r['dd']:.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}% Trades={r['trades']}", flush=True)

print(f"\nUnique ALL4 combos: {len(unique_all4)}", flush=True)

# Stats per ticker
from collections import Counter
tc=Counter(r["ticker"] for r in p4_all)
print(f"\nPer ticker:", flush=True)
for t,c in tc.most_common():
    print(f"  {t}: {c}", flush=True)
