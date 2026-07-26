"""
Max-aggression approach: long-biased momentum with no stops.
Crypto 2024-2025 is a bull market - simple long capture should work.
"""
import sys, os, pickle, time, json, math, random
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

tickers = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD"]

def yz_vol(df,w=14):
    o,h,l,c=df["open"],df["high"],df["low"],df["close"]
    lo=np.log(o/c.shift(1));lc=np.log(c/c.shift(1))
    rs=np.log(h/c)*np.log(h/o)+np.log(l/c)*np.log(l/o)
    k=0.34/(1.34+(w+1)/max(w-1,1))
    yzv=lo.rolling(w).var(ddof=0)+k*lc.rolling(w).var(ddof=0)+(1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv*(252*4),1e-8))

def tstat(prices,lb):
    if len(prices)<lb+2:return 0.0
    y=np.log(prices.values[-lb:]);x=np.arange(lb)
    xm,ym=x.mean(),y.mean()
    beta=np.sum((x-xm)*(y-ym))/max(np.sum((x-xm)**2),1e-10)
    resid=y-(ym+beta*(x-xm))
    se=np.sqrt(np.sum(resid**2)/max(lb-2,1));se_b=se/max(np.sqrt(np.sum((x-xm)**2)),1e-10)
    return beta/se_b if se_b>0 else 0.0

# Strategy 1: Long-only momentum (capture bull market)
def make_long_only(lb=48, entry_t=0.3, exit_t=-0.1, vol_target=0.50, max_pos=1.0):
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        sig=pd.Series(0.0,index=df.index);in_pos=False
        for i in range(100,len(df)):
            lb_=min(lb,i)
            ts=tstat(c.iloc[i-lb_:i+1],lb_)
            if in_pos and ts<exit_t:
                sig.iloc[i]=0.0;in_pos=False
            elif not in_pos and ts>entry_t:
                sig.iloc[i]=1.0;in_pos=True
            elif in_pos:
                sig.iloc[i]=1.0
            else:
                sig.iloc[i]=0.0
        pos=sig.shift(1).fillna(0)
        # No vol scaling - just fixed position
        df["signal"]=pos*max_pos
        return df
    return gen

# Strategy 2: Aggressive momentum (both directions, no stop, high pos)
def make_aggressive_mom(lb=48, entry_t=0.5, exit_t=0.1, vol_target=0.40, max_pos=2.0):
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        sig=pd.Series(0.0,index=df.index);in_pos=False
        for i in range(100,len(df)):
            lb_=min(lb,i)
            ts=tstat(c.iloc[i-lb_:i+1],lb_)
            if in_pos and abs(ts)<exit_t:
                sig.iloc[i]=0.0;in_pos=False
            elif not in_pos and abs(ts)>entry_t:
                sig.iloc[i]=1.0 if ts>0 else -1.0;in_pos=True
            elif in_pos:
                sig.iloc[i]=sig.iloc[i-1]
            else:
                sig.iloc[i]=0.0
        pos=sig.shift(1).fillna(0)
        scale=(vol_target/yz.clip(lower=0.01)).clip(upper=3.0).fillna(1.0)
        df["signal"]=(pos*scale*max_pos).clip(-max_pos*3.0,max_pos*3.0)
        return df
    return gen

# Strategy 3: Pure EMA crossover (simple, proven)
def make_ema_cross(fast=12, slow=48, vol_target=0.30, max_pos=1.5):
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        ema_f=c.ewm(span=fast).mean();ema_s=c.ewm(span=slow).mean()
        sig=np.where(ema_f>ema_s,1.0,-1.0)
        df["signal"]=pd.Series(sig,index=df.index)*max_pos
        return df
    return gen

def run_bt(df, sig_fn, comm=0.001, slip=0.0005, borrow=0.05):
    df2=sig_fn(df);sig=df2["signal"].values;c=df["close"].values;n=len(sig)
    eq=1.0;peak=1.0;eqs=np.ones(n);trades=0;wins=0;pos=0.0;peq=1.0
    for i in range(1,n):
        s=sig[i];turn=abs(s-pos)
        if turn>0:
            eq-=turn*(comm+slip)*eq
            if pos!=0:
                trades+=1
                if eq>peq:wins+=1
        pos=s
        ret=c[i]/c[i-1]-1
        if pos>0:eq*=1+ret*abs(pos)
        elif pos<0:eq*=1-ret*abs(pos)-borrow/(252*4)*abs(pos)
        eqs[i]=eq;peak=max(peak,eq);peq=eq
    rets=pd.Series(eqs).pct_change().dropna()
    tr=eqs[-1]-1;ny=n/(252*4)
    ann=(1+tr)**(1/max(ny,0.1))-1
    sr=rets.mean()/rets.std()*math.sqrt(252*4) if len(rets)>0 and rets.std()>0 else 0
    dd=(1-eqs/np.maximum.accumulate(eqs)).max()
    wr=wins/max(trades,1)
    return {"total_return":tr,"annualized_return":ann,"sharpe":sr,"max_dd":dd,"win_rate":wr,"total_trades":trades}

# Build param grids - focused on high return
configs = []
for lb in [24, 48, 80, 120, 160]:
    for et in [0.2, 0.3, 0.5]:
        for mp in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            configs.append(("long_only", dict(lb=lb, entry_t=et, exit_t=-0.1, vol_target=0.5, max_pos=mp)))

for lb in [24, 48, 80, 120]:
    for et in [0.3, 0.5, 0.8]:
        for vt in [0.30, 0.50, 0.70]:
            for mp in [1.0, 1.5, 2.0, 2.5, 3.0]:
                configs.append(("agg_mom", dict(lb=lb, entry_t=et, exit_t=0.1, vol_target=vt, max_pos=mp)))

for fast in [6, 12, 24, 48]:
    for slow in [24, 48, 96, 192]:
        for mp in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            configs.append(("ema_cross", dict(fast=fast, slow=slow, vol_target=0.3, max_pos=mp)))

random.seed(42); random.shuffle(configs)
configs = configs[:200]  # Limit to 200 for speed
print(f"Running {len(configs)} configs x {len(tickers)} tickers = {len(configs)*len(tickers)} tests")

results = []; t0=time.time()

for idx,(name,params) in enumerate(configs):
    if name=="long_only": fn=make_long_only(**params)
    elif name=="agg_mom": fn=make_aggressive_mom(**params)
    else: fn=make_ema_cross(**params)
    for ticker in tickers:
        try:
            r=run_bt(data_6h[ticker], fn)
            results.append({"strategy":name,"ticker":ticker,"params":params,
                "wr":r["win_rate"]*100,"dd":r["max_dd"]*100,"sharpe":r["sharpe"],
                "ann":r["annualized_return"]*100,"total":r["total_return"]*100,"trades":r["total_trades"]})
        except: pass
    if (idx+1)%20==0:
        passed=sum(1 for r in results if r["sharpe"]>=0.7 and r["ann"]>=15 and r["dd"]<=20)
        print(f"  {idx+1}/{len(configs)} -> {len(results)} res, {passed} pass Ann>=15+Sharpe>=0.7+DD<=20 [{time.time()-t0:.0f}s]", flush=True)

# Score
def score(r):
    s=0
    if 40<=r["wr"]<=55:s+=1
    if r["dd"]<=20:s+=1
    if r["sharpe"]>=0.7:s+=1
    if r["sharpe"]>=1.0:s+=3
    if r["ann"]>=15:s+=1
    if r["ann"]>=20:s+=2
    if r["ann"]>=25:s+=3
    return s
for r in results: r["score"]=score(r)
results.sort(key=lambda x:x["score"],reverse=True)

print(f"\nTop 30 of {len(results)}:")
for i,r in enumerate(results[:30]):
    print(f"  {i+1:>2}. {r['strategy']:12s} {r['ticker']:8s} WR={r['wr']:5.1f}% DD={r['dd']:5.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:5.1f}% Tot={r['total']:7.1f}% Tr={r['trades']:4d} S={r['score']}")

targets=[("WR 40-55%",lambda r:40<=r["wr"]<=55),("DD<20%",lambda r:r["dd"]<=20),
         ("Sharpe>=1.0",lambda r:r["sharpe"]>=1.0),("Ann>=20%",lambda r:r["ann"]>=20)]
for (l,_),c in [(l,sum(1 for r in results if ch(r))) for l,ch in targets]:
    print(f"  {l}: {c}/{len(results)} ({c/max(len(results),1)*100:.1f}%)")

# Best combos
for i,r in enumerate(results):
    p=sum(1 for _,ch in targets if ch(r))
    if p>=3:
        print(f"\n*** {i+1}: {r['strategy']:12s} {r['ticker']:8s} passes {p}/4! WR={r['wr']:.1f}% DD={r['dd']:.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}% Tot={r['total']:.1f}%")

save=[{"strategy":r["strategy"],"ticker":r["ticker"],
    "params":{str(k):v for k,v in r["params"].items()},
    "metrics":{"win_rate":r["wr"]/100,"max_dd":r["dd"]/100,"sharpe":r["sharpe"],
               "annualized_return":r["ann"]/100,"total_return":r["total"]/100,"total_trades":r["trades"]},
    "score":r["score"]} for r in results]
with open("bull_results.json","w") as f: json.dump(save,f,indent=2)
print(f"\nSaved {len(save)} to bull_results.json")
