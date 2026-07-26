"""
Focused: use proven params from test_fixed.py (high Sharpe, high Ann)
with 6h data + risk-managed scaling to push to targets.
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

print(f"Data: {len(data_6h)} tickers, {len(next(iter(data_6h.values())))} bars each")
tickers = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD"]

# ===== YANG-ZHANG VOL =====
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

# ===== STRATEGY: PROVEN PARAMS FROM test_fixed.py, ADAPTED FOR 6h =====
# Proven params that gave best results:
#   Sharpe 0.92: lb_f=12, lb_s=40, max_pos=1.0, vol_target=0.50, entry=0.60, exit=0.20, stop=0.20
#   Ann 21%:     lb_f=12, lb_s=60, max_pos=1.8, vol_target=0.80, entry=0.60, exit=1.00, stop=0.15
#
# For 6h data, adjust lookbacks: 12 daily bars = ~48 6h bars, 40 daily = ~160 6h
# But crypto momentum works at shorter horizons (1-4 weeks), so for 6h:
#   Short: 8-48 bars (2-12 days), Long: 20-160 bars (5-40 days)

def make_proven_tsmom(lb_f=24, lb_s=80, entry_t=0.6, exit_t=0.3, 
                       vol_target=0.50, max_pos=1.0, stop_pct=0.20):
    """Original working strategy, adapted for 6h bars"""
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        med=yz.rolling(30,min_periods=15).median()
        reg=(yz>med*1.2).astype(int)
        sig=pd.Series(0.0,index=df.index);in_pos=False;entry_h=0.0
        for i in range(100,len(df)):
            lb=lb_f if reg.iloc[i]==1 else lb_s;lb=min(lb,i)
            ts=tstat(c.iloc[i-lb:i+1],lb)
            if in_pos:
                entry_h=max(entry_h,c.iloc[i])
                if (entry_h-c.iloc[i])/entry_h>stop_pct:
                    sig.iloc[i]=0.0;in_pos=False
                else:
                    sig.iloc[i]=1.0 if sig.iloc[i-1]>0 else -1.0
            elif ts>entry_t:
                sig.iloc[i]=1.0;in_pos=True;entry_h=c.iloc[i]
            elif ts<-entry_t:
                sig.iloc[i]=-1.0;in_pos=True;entry_h=c.iloc[i]
            elif abs(ts)<exit_t:
                sig.iloc[i]=0.0
            else:
                sig.iloc[i]=sig.iloc[i-1]
        pos=sig.shift(1).fillna(0)
        mult=(vol_target/yz.clip(lower=0.01)).clip(upper=3.0).fillna(1.0)
        df["signal"]=(pos*mult*max_pos).clip(-max_pos*3.0,max_pos*3.0)
        return df
    return gen

def make_risk_managed(lb_f=12, lb_s=60, entry_t=0.6, exit_t=0.2,
                      vol_target=0.60, max_pos=0.80, stop_pct=0.15):
    """No trailing stop, just vol-scaled momentum with drawdown cap"""
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        med=yz.rolling(30,min_periods=15).median()
        reg=(yz>med*1.3).astype(int)
        sig=pd.Series(0.0,index=df.index);in_pos=False
        peak=1.0;eq=1.0
        for i in range(100,len(df)):
            lb=lb_f if reg.iloc[i]==1 else lb_s;lb=min(lb,i)
            ts=tstat(c.iloc[i-lb:i+1],lb)
            if in_pos:
                # Exit on trend reversal
                if (ts>0 and sig.iloc[i-1]<0) or (ts<0 and sig.iloc[i-1]>0):
                    sig.iloc[i]=0.0;in_pos=False
                elif abs(ts)<exit_t:
                    sig.iloc[i]=0.0;in_pos=False
                else:
                    sig.iloc[i]=sig.iloc[i-1]
            elif ts>entry_t:
                sig.iloc[i]=1.0;in_pos=True
            elif ts<-entry_t:
                sig.iloc[i]=-1.0;in_pos=True
            else:
                sig.iloc[i]=0.0
        pos=sig.shift(1).fillna(0)
        # Vol scaling: target vol / realized vol
        rv=yz.rolling(40,min_periods=10).mean().fillna(yz.median())
        scale=(vol_target/rv.clip(lower=0.01)).clip(upper=4.0).fillna(1.0)
        df["signal"]=(pos*scale*max_pos).clip(-max_pos*4.0,max_pos*4.0)
        return df
    return gen

def make_high_conviction(lb=48, entry_t=1.2, exit_t=0.3,
                          vol_target=0.40, max_pos=0.60, stop_pct=0.12):
    """Higher conviction: fewer trades, tighter stops, better risk-adjusted"""
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        sig=pd.Series(0.0,index=df.index);in_pos=False;entry_h=0.0
        for i in range(100,len(df)):
            lb_=min(lb,i)
            ts=tstat(c.iloc[i-lb_:i+1],lb_)
            if in_pos:
                entry_h=max(entry_h,c.iloc[i])
                if (entry_h-c.iloc[i])/entry_h>stop_pct:
                    sig.iloc[i]=0.0;in_pos=False
                elif abs(ts)<exit_t:
                    sig.iloc[i]=0.0;in_pos=False
                else:
                    sig.iloc[i]=sig.iloc[i-1]
            elif ts>entry_t:
                sig.iloc[i]=1.0;in_pos=True;entry_h=c.iloc[i]
            elif ts<-entry_t:
                sig.iloc[i]=-1.0;in_pos=True;entry_h=c.iloc[i]
            else:
                sig.iloc[i]=0.0
        pos=sig.shift(1).fillna(0)
        mult=(vol_target/yz.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
        df["signal"]=(pos*mult*max_pos).clip(-max_pos*2.0,max_pos*2.0)
        return df
    return gen

def make_aggressive(lb_f=8, lb_s=40, entry_t=0.4, exit_t=0.1,
                    vol_target=0.80, max_pos=1.5, stop_pct=0.25):
    """Aggressive: low entry threshold, high max_pos, wide stop — max returns"""
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        med=yz.rolling(20,min_periods=10).median()
        reg=(yz>med*1.5).astype(int)
        sig=pd.Series(0.0,index=df.index);in_pos=False;entry_h=0.0
        for i in range(80,len(df)):
            lb=lb_f if reg.iloc[i]==1 else lb_s;lb=min(lb,i)
            ts=tstat(c.iloc[i-lb:i+1],lb)
            if in_pos:
                entry_h=max(entry_h,c.iloc[i])
                if (entry_h-c.iloc[i])/entry_h>stop_pct:
                    sig.iloc[i]=0.0;in_pos=False
                else:
                    sig.iloc[i]=sig.iloc[i-1]
            elif abs(ts)>entry_t:
                sig.iloc[i]=1.0 if ts>0 else -1.0
                in_pos=True;entry_h=c.iloc[i]
            else:
                sig.iloc[i]=0.0
        pos=sig.shift(1).fillna(0)
        mult=(vol_target/yz.clip(lower=0.01)).clip(upper=5.0).fillna(1.0)
        df["signal"]=(pos*mult*max_pos).clip(-max_pos*5.0,max_pos*5.0)
        return df
    return gen

# ===== BACKTESTER =====
def run_bt(df, sig_fn, comm=0.001, slip=0.0005, borrow=0.05):
    df2=sig_fn(df);sig=df2["signal"].values;c=df["close"].values;n=len(sig)
    eq=1.0;peak=1.0;eqs=np.ones(n);trades=0;wins=0;pos=0.0
    for i in range(1,n):
        s=sig[i];turn=abs(s-pos)
        if turn>0:eq-=turn*(comm+slip)*eq
        if s!=0 and pos!=0 and turn==0:
            trades+=1
            if eq>peak*0.99:wins+=1
        pos=s
        ret=c[i]/c[i-1]-1
        if pos>0:eq*=1+ret*abs(pos)
        elif pos<0:eq*=1-ret*abs(pos)-borrow/(252*4)*abs(pos)
        eqs[i]=eq;peak=max(peak,eq)
    rets=pd.Series(eqs).pct_change().dropna()
    tr=eqs[-1]-1;ny=n/(252*4)
    ann=(1+tr)**(1/max(ny,0.1))-1
    sr=rets.mean()/rets.std()*math.sqrt(252*4) if len(rets)>0 and rets.std()>0 else 0
    dd=(1-eqs/np.maximum.accumulate(eqs)).max()
    wr=wins/max(trades,1)
    return {"total_return":tr,"annualized_return":ann,"sharpe":sr,"max_dd":dd,"win_rate":wr,"total_trades":trades}

# ===== PARAM GRIDS =====
strategies = [
    ("tsmom_proven", make_proven_tsmom, [
        dict(lb_f=lb_f,lb_s=lb_s,entry_t=et,exit_t=0.3,vol_target=vt,max_pos=mp,stop_pct=sp)
        for lb_f in [12,24,48] for lb_s in [40,80,120,160]
        for et in [0.4,0.6,0.8] for vt in [0.30,0.50,0.70,1.00]
        for mp in [0.5,0.8,1.0,1.5,2.0] for sp in [0.12,0.15,0.20,0.25,0.30]
    ]),
    ("risk_managed", make_risk_managed, [
        dict(lb_f=lb_f,lb_s=lb_s,entry_t=et,exit_t=0.2,vol_target=vt,max_pos=mp,stop_pct=sp)
        for lb_f in [8,12,24] for lb_s in [40,60,80,120]
        for et in [0.4,0.6,0.8] for vt in [0.40,0.60,0.80,1.20]
        for mp in [0.5,0.8,1.0,1.5,2.0] for sp in [0.10,0.15,0.20,0.25]
    ]),
    ("high_conviction", make_high_conviction, [
        dict(lb=lb,et=et,exit_t=0.3,vol_target=vt,max_pos=mp,stop_pct=sp)
        for lb in [24,48,80,120] for et in [0.8,1.0,1.2,1.5]
        for vt in [0.30,0.40,0.60,0.80] for mp in [0.3,0.5,0.8,1.0,1.5]
        for sp in [0.08,0.12,0.15,0.20]
    ]),
    ("aggressive", make_aggressive, [
        dict(lb_f=lb_f,lb_s=lb_s,et=et,exit_t=0.1,vol_target=vt,max_pos=mp,stop_pct=sp)
        for lb_f in [6,8,12,18] for lb_s in [30,40,60,80]
        for et in [0.3,0.4,0.5] for vt in [0.60,0.80,1.00,1.50]
        for mp in [1.0,1.5,2.0,2.5] for sp in [0.15,0.20,0.25,0.30]
    ]),
]

print("Config counts:")
for name, _, configs in strategies:
    print(f"  {name}: {len(configs)}")

# Stratify pick 60 per type
random.seed(42)
for i in range(len(strategies)):
    name, maker, configs = strategies[i]
    if len(configs) > 60:
        configs.sort(key=lambda p: (p["vol_target"], p["max_pos"]))
        step = len(configs)/60
        strategies[i] = (name, maker, [configs[int(j*step)] for j in range(60)])
    print(f"  {name}: {len(strategies[i][2])} (after reduction)")

# ===== RUN =====
all_results = []
t0 = time.time()
total = sum(len(c) for _,_,c in strategies)
done = 0

print(f"\nRunning {total} configs x {len(tickers)} tickers = {total*len(tickers)} backtests...")

for name, maker_fn, configs in strategies:
    for params in configs:
        sig_fn = maker_fn(**params)
        for ticker in tickers:
            try:
                r = run_bt(data_6h[ticker], sig_fn)
                all_results.append({
                    "strategy": name, "ticker": ticker, "params": params,
                    "wr": r["win_rate"]*100, "dd": r["max_dd"]*100,
                    "sharpe": r["sharpe"], "ann": r["annualized_return"]*100,
                    "total": r["total_return"]*100, "trades": r["total_trades"]
                })
            except: pass
        done += 1
        if done % 10 == 0:
            elapsed = time.time()-t0
            passed = sum(1 for r in all_results if r["sharpe"]>=0.7 and r["ann"]>=15 and r["dd"]<=20)
            print(f"  {done}/{total} configs -> {len(all_results)} results, {passed} passing (Ann>=15,Sharpe>=0.7,DD<=20) [{elapsed:.0f}s]", flush=True)

elapsed = time.time()-t0
print(f"\nDone: {len(all_results)} results in {elapsed:.0f}s")

# Score
def score(r):
    s = 0
    if 40<=r["wr"]<=55: s+=1
    if r["dd"]<=20: s+=1
    if r["dd"]<=15: s+=2
    if r["sharpe"]>=0.7: s+=1
    if r["sharpe"]>=1.0: s+=3
    if r["ann"]>=15: s+=1
    if r["ann"]>=20: s+=2
    if r["ann"]>=25: s+=3
    if r["ann"]>=30: s+=5
    return s

for r in all_results: r["score"]=score(r)
all_results.sort(key=lambda x:x["score"],reverse=True)

# Top 30
print(f"\nTop 30:")
for i,r in enumerate(all_results[:30]):
    print(f"  {i+1:>2}. {r['strategy']:16s} {r['ticker']:8s} WR={r['wr']:5.1f}% DD={r['dd']:5.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:5.1f}% Tot={r['total']:7.1f}% Tr={r['trades']:4d} S={r['score']}")

# Check targets
targets=[("WR 40-55%",lambda r:40<=r["wr"]<=55),("DD<20%",lambda r:r["dd"]<=20),
         ("Sharpe>=1.0",lambda r:r["sharpe"]>=1.0),("Ann>=20%",lambda r:r["ann"]>=20)]
pass_counts=[sum(1 for r in all_results if ch(r)) for _,ch in targets]
print(f"\nPass rates:")
for (l,_),c in zip(targets,pass_counts):
    print(f"  {l}: {c}/{len(all_results)} ({c/max(len(all_results),1)*100:.1f}%)")

# Any passing 3+?
for i,r in enumerate(all_results):
    p=sum(1 for _,ch in targets if ch(r))
    if p>=3:
        print(f"\n*** {i+1}: {r['strategy']:16s} {r['ticker']:8s} passes {p}/4 targets! WR={r['wr']:.1f}% DD={r['dd']:.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}%")

# Any passing all 4?
for i,r in enumerate(all_results):
    p=sum(1 for _,ch in targets if ch(r))
    if p==4:
        print(f"\n★★★★★ ALL 4 TARGETS: {r['strategy']:16s} {r['ticker']:8s} WR={r['wr']:.1f}% DD={r['dd']:.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}%")

# Save
save_results = [{
    "strategy":r["strategy"],"ticker":r["ticker"],
    "params":{str(k):v for k,v in r["params"].items()},
    "metrics":{"win_rate":r["wr"]/100,"max_dd":r["dd"]/100,"sharpe":r["sharpe"],
               "annualized_return":r["ann"]/100,"total_return":r["total"]/100,"total_trades":r["trades"]},
    "score":r["score"]
} for r in all_results]
with open("focused_results.json","w") as f: json.dump(save_results,f,indent=2)
print(f"\nSaved {len(save_results)} results to focused_results.json")
