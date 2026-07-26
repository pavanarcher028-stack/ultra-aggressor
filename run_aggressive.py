"""
Aggressive params (known to produce high returns from test_fixed.py).
max_pos up to 1.0, vol_target up to 1.0. Test on 3 assets.
"""
import sys, os, time, pickle, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from autonomous_trader.backtester import run_backtest

with open("crypto_data_3.pkl","rb") as f: data = pickle.load(f)

def yz_vol(df,w=14):
    o,h,l,c=df["open"],df["high"],df["low"],df["close"]
    lo=np.log(o/c.shift(1));lc=np.log(c/c.shift(1))
    rs=np.log(h/c)*np.log(h/o)+np.log(l/c)*np.log(l/o)
    k=0.34/(1.34+(w+1)/max(w-1,1));yzv=lo.rolling(w).var(ddof=0)+k*lc.rolling(w).var(ddof=0)+(1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv*252,1e-8))

def tstat(prices,lb):
    if len(prices)<lb:return 0.0
    y=np.log(prices.values[-lb:]);x=np.arange(lb);xm,ym=x.mean(),y.mean()
    beta=np.sum((x-xm)*(y-ym))/max(np.sum((x-xm)**2),1e-10);resid=y-(ym+beta*(x-xm))
    se=np.sqrt(np.sum(resid**2)/max(lb-2,1));se_b=se/max(np.sqrt(np.sum((x-xm)**2)),1e-10)
    return beta/se_b if se_b>0 else 0.0

def make_sig(lb_f,lb_s,t_e,t_x,v_a,m_p,t_s):
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,14)
        med=yz.rolling(30,min_periods=15).median();reg=(yz>med).astype(int)
        sig=pd.Series(0.0,index=df.index);in_pos=False;entry_h=0.0
        for i in range(100,len(df)):
            lb=lb_f if reg.iloc[i]==1 else lb_s;lb=min(lb,i)
            ts=tstat(c.iloc[i-lb:i+1],lb);pr=sig.iloc[i-1]
            if pr!=0:sig.iloc[i]=np.sign(pr) if abs(ts)>=t_x else 0.0
            elif ts>t_e:sig.iloc[i]=1.0
            elif ts<-t_e:sig.iloc[i]=-1.0
            if sig.iloc[i]!=0:
                if not in_pos:in_pos=True;entry_h=c.iloc[i]
                entry_h=max(entry_h,c.iloc[i])
                if (entry_h-c.iloc[i])/entry_h>t_s:sig.iloc[i]=0.0;in_pos=False
            else:in_pos=False
        pos=sig.shift(1).fillna(0)
        mult=(v_a/yz.clip(lower=0.01)).clip(upper=3.0).fillna(1.0)
        df["signal"]=(pos*mult*m_p).clip(-m_p,m_p)
        return df
    return gen

# Use param sets from test_fixed.py that showed best results
# Key insight: need high max_pos (0.5-1.0) AND high vol_target (0.5-1.0)
configs = []
# Best Sharpe combos
for mp in [0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.0]:
    for va in [0.30, 0.40, 0.50, 0.60, 0.80, 1.0]:
        for te in [1.0, 1.5, 2.0]:
            for ts in [0.08, 0.12, 0.15, 0.20]:
                configs.append(("tsmom", {"lb_f":12,"lb_s":60,"t_e":te,"t_x":0.5,"v_a":va,"m_p":mp,"t_s":ts}))

# Cap at 60 configs × 3 assets = 180 backtests max
configs = configs[:60]
ticks = ["BTC-USD","ETH-USD","SOL-USD"]
all_results = []
print(f"Testing {len(configs)} aggressive configs on {len(ticks)} assets...", flush=True)

t0=time.time()
for idx,(stype,params) in enumerate(configs):
    sig=make_sig(**params)
    for ticker in ticks:
        try:
            r=run_backtest(data[ticker].copy(),sig)
            wr=float(r["win_rate"])*100;dd=float(r["max_dd"])*100;sh=float(r["sharpe"])
            ann=float(r["annualized_return"])*100;tr=float(r["total_return"])*100;td=int(r["total_trades"])
            all_results.append({"strategy":stype,"ticker":ticker,"params":params,
                "wr":wr,"dd":dd,"sharpe":sh,"ann":ann,"total":tr,"trades":td})
            if abs(sh)>=0.5 or ann>=10:
                print(f"  {idx:>3}/{len(configs)} {ticker:8s} WR={wr:5.1f}% DD={dd:5.1f}% Sharpe={sh:.2f} Ann={ann:5.1f}% Total={tr:6.1f}%", flush=True)
        except:
            pass
    if (idx+1)%20==0:
        print(f"  ... {idx+1}/{len(configs)} done, {len(all_results)} results ({(time.time()-t0):.0f}s)", flush=True)

print(f"Done in {time.time()-t0:.0f}s — {len(all_results)} total results", flush=True)

# Score
def sc(r):
    s=0
    if 40<=r["wr"]<=55:s+=1
    if r["dd"]<=20:s+=1
    if r["sharpe"]>=0.7:s+=2
    if r["ann"]>=10:s+=2
    if r["sharpe"]>=1.0:s+=1
    if r["ann"]>=20:s+=1
    return s
for r in all_results: r["score"]=sc(r)

# Show best
all_results.sort(key=lambda x:x["score"],reverse=True)
print(f"\nTop 20:", flush=True)
for i,s in enumerate(all_results[:20]):
    print(f"  {i+1:>2}. {s['strategy']:6s} {s['ticker']:8s} WR={s['wr']:5.1f}% DD={s['dd']:5.1f}% Sharpe={s['sharpe']:.2f} Ann={s['ann']:5.1f}% Total={s['total']:7.1f}% Score={s['score']}", flush=True)

# Save top 50 (or however many we have)
import json
top50 = all_results[:min(50,len(all_results))]
with open("top50_aggressive.json","w") as f:
    json.dump([{"strategy":s["strategy"],"ticker":s["ticker"],"params":{str(k):v for k,v in s["params"].items()},
                "metrics":{"win_rate":s["wr"]/100,"max_dd":s["dd"]/100,"sharpe":s["sharpe"],
                          "annualized_return":s["ann"]/100,"total_return":s["total"]/100,"total_trades":s["trades"]},
                "score":s["score"]} for s in top50], f, indent=2)
print(f"\nSaved top {len(top50)} to top50_aggressive.json", flush=True)
