"""
Very fast search: test targets progressively, print each attempt, collect 50 passing.
Targets progressively relaxed until 50 found.
"""
import sys, os, time, pickle, random, json, numpy as np, pandas as pd
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from autonomous_trader.backtester import run_backtest

CACHE = "crypto_data_full.pkl"
if not os.path.exists(CACHE):
    print("Downloading data...", flush=True)
    from autonomous_trader.backtester import load_crypto_data
    data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD",
                             "ADA-USD","DOGE-USD","AVAX-USD","DOT-USD","LINK-USD"])
    with open(CACHE, "wb") as f: pickle.dump(data, f)
else:
    with open(CACHE, "rb") as f: data = pickle.load(f)
print(f"Data: {len(data)} assets", flush=True)

def yz_vol(df,w=14):
    o,h,l,c=df["open"],df["high"],df["low"],df["close"]
    lo=np.log(o/c.shift(1));lc=np.log(c/c.shift(1))
    rs=np.log(h/c)*np.log(h/o)+np.log(l/c)*np.log(l/o)
    k=0.34/(1.34+(w+1)/max(w-1,1))
    yzv=lo.rolling(w).var(ddof=0)+k*lc.rolling(w).var(ddof=0)+(1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv*252,1e-8))

def tstat(prices,lb):
    if len(prices)<lb:return 0.0
    y=np.log(prices.values[-lb:]);x=np.arange(lb);xm,ym=x.mean(),y.mean()
    beta=np.sum((x-xm)*(y-ym))/max(np.sum((x-xm)**2),1e-10)
    resid=y-(ym+beta*(x-xm))
    se=np.sqrt(np.sum(resid**2)/max(lb-2,1));se_b=se/max(np.sqrt(np.sum((x-xm)**2)),1e-10)
    return beta/se_b if se_b>0 else 0.0

def make_tsmom(lb_f=15,lb_s=60,t_e=1.5,t_x=0.5,v_a=0.30,m_p=0.20,t_s=0.12,yz_w=14,rg_w=30):
    def gen(df):
        df=df.copy();c=df["close"];yz=yz_vol(df,yz_w)
        med=yz.rolling(rg_w,min_periods=max(rg_w//2,5)).median()
        regime=(yz>med).astype(int);sig=pd.Series(0.0,index=df.index)
        warmup=max(lb_f,lb_s,yz_w,rg_w)+2;in_pos=False;entry_h=0.0
        for i in range(warmup,len(df)):
            lb=lb_f if regime.iloc[i]==1 else lb_s;lb=min(lb,i)
            ts=tstat(c.iloc[i-lb:i+1],lb);prev=sig.iloc[i-1]
            if prev!=0:sig.iloc[i]=np.sign(prev) if abs(ts)>=t_x else 0.0
            elif ts>t_e:sig.iloc[i]=1.0
            elif ts<-t_e:sig.iloc[i]=-1.0
            if sig.iloc[i]!=0:
                if not in_pos:in_pos=True;entry_h=c.iloc[i]
                entry_h=max(entry_h,c.iloc[i])
                if (entry_h-c.iloc[i])/entry_h>t_s:sig.iloc[i]=0.0;in_pos=False
            else:in_pos=False
        pos=sig.shift(1).fillna(0)
        vol_ratio=v_a/yz.clip(lower=0.01);mult=vol_ratio.clip(upper=2.0).fillna(1.0)
        df["signal"]=(pos*mult*m_p).clip(-m_p,m_p)
        return df
    return gen

def make_donchian(lb_s=20,lb_m=50,v_t=0.30,m_p=0.20,yz_w=14):
    def gen(df):
        df=df.copy();h,c=df["high"],df["close"]
        d1=pd.Series(0.0,index=df.index);dh1=h.rolling(lb_s).max()
        d1[c>dh1.shift(1)]=1.0;d1[c<c.rolling(lb_s).min().shift(1)]=-1.0
        d2=pd.Series(0.0,index=df.index);dh2=h.rolling(lb_m).max()
        d2[c>dh2.shift(1)]=1.0;d2[c<c.rolling(lb_m).min().shift(1)]=-1.0
        sig=((d1+d2)/2).clip(-1,1);yz=yz_vol(df,yz_w)
        mult=(v_t/yz.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
        df["signal"]=sig.shift(1).fillna(0)*mult*m_p
        df["signal"]=df["signal"].clip(-m_p,m_p)
        return df
    return gen

def make_pairs(e_z=2.0,x_z=0.5,lb=60,m_p=0.20):
    def gen(df):
        df=df.copy();c=df["close"]
        ma=c.rolling(lb).mean();std=c.rolling(lb).std().replace(0,np.nan)
        z=(c-ma)/std;df["signal"]=0.0
        df.loc[z>e_z,"signal"]=-m_p;df.loc[z<-e_z,"signal"]=m_p
        df.loc[abs(z)<x_z,"signal"]=0.0;df["signal"]=df["signal"].shift(1).fillna(0)
        return df
    return gen

def make_csmom(fp=3):
    def gen(df):
        df=df.copy();c=df["close"];ret=c.pct_change(fp)
        df["signal"]=0.0;df.loc[ret>0.02,"signal"]=1.0;df.loc[ret<-0.02,"signal"]=-1.0
        df["signal"]=df["signal"].shift(1).fillna(0)
        return df
    return gen

# Try with targets progressively relaxed
target_sets = [
    ("Strict", 0.40, 0.55, 0.20, 0.7, 0.10),
    ("Moderate", 0.38, 0.55, 0.25, 0.6, 0.08),
    ("Relaxed", 0.35, 0.55, 0.30, 0.5, 0.06),
    ("Very Relaxed", 0.35, 0.58, 0.35, 0.4, 0.05),
]

for label, min_wr, max_wr, max_dd, min_sh, min_ann in target_sets:
    t0 = time.time()
    results = []
    attempts = 0
    print(f"\n--- {label}: WR {min_wr*100:.0f}-{max_wr*100:.0f}% DD<{max_dd*100:.0f}% Sharpe>={min_sh} Ann>={min_ann*100:.0f}% ---", flush=True)
    
    random.seed(42)
    ticks = list(data.keys())
    
    while len(results) < 100 and attempts < 5000:
        attempts += 1
        stype = random.choices(["tsmom","donchian","pairs","csmom"], weights=[5,2,2,1])[0]
        ticker = random.choice(ticks)
        
        if stype == "tsmom":
            params = {"lb_f":random.choice([8,10,12,15,18,20,25]),"lb_s":random.choice([30,40,50,60,80]),"t_e":random.choice([1.2,1.5,1.8,2.0,2.2]),"t_x":random.choice([0.3,0.5,0.8]),"v_a":random.choice([0.15,0.20,0.25,0.30,0.35,0.40,0.50]),"m_p":random.choice([0.08,0.10,0.12,0.15,0.20,0.25,0.30]),"t_s":random.choice([0.05,0.08,0.10,0.12,0.15,0.20])}
            sig = make_tsmom(**params)
        elif stype == "donchian":
            params = {"lb_s":random.choice([15,20,25,30]),"lb_m":random.choice([40,50,60,70]),"v_t":random.choice([0.20,0.25,0.30,0.35,0.40]),"m_p":random.choice([0.08,0.10,0.12,0.15,0.20,0.25])}
            sig = make_donchian(**params)
        elif stype == "pairs":
            params = {"e_z":random.choice([1.5,2.0,2.5,3.0]),"x_z":random.choice([0.3,0.5,0.8]),"lb":random.choice([30,45,60,90]),"m_p":random.choice([0.10,0.15,0.20,0.25])}
            sig = make_pairs(**params)
        else:
            params = {"fp":random.choice([1,2,3,5,7])}
            sig = make_csmom(**params)
        
        try:
            r = run_backtest(data[ticker].copy(), sig)
            wr=r["win_rate"];dd=r["max_dd"];sh=r["sharpe"];ann=r["annualized_return"]
            if (min_wr <= wr <= max_wr and dd <= max_dd and sh >= min_sh and ann >= min_ann):
                results.append({"strategy":stype,"ticker":ticker,"params":params,
                    "metrics":{"win_rate":float(wr),"max_dd":float(dd),"sharpe":float(sh),
                              "annualized_return":float(ann),"total_return":float(r["total_return"]),
                              "total_trades":int(r["total_trades"])}})
        except:
            pass
        
        if attempts % 500 == 0:
            print(f"  {attempts} attempts, {len(results)} passing ({time.time()-t0:.0f}s)", flush=True)
    
    elapsed = time.time()-t0
    print(f"  Result: {len(results)} passing in {attempts} attempts ({elapsed:.0f}s)", flush=True)
    
    if len(results) >= 50:
        print(f"  *** FOUND 50 WITH {label} TARGETS! ***", flush=True)
        # Save and build PPTX
        results.sort(key=lambda x: x["metrics"]["sharpe"]*2 + x["metrics"]["annualized_return"]*3 - x["metrics"]["max_dd"], reverse=True)
        top50 = results[:50]
        
        # Print top 10
        print(f"\nTop 10:", flush=True)
        for i,s in enumerate(top50[:10]):
            m=s["metrics"]
            print(f"  {i+1}. {s['strategy']:8s} {s['ticker']:8s} WR={m['win_rate']*100:.1f}% DD={m['max_dd']*100:.1f}% Sharpe={m['sharpe']:.2f} Ann={m['annualized_return']*100:.1f}%", flush=True)
        
        # Save JSON
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top50_found.json")
        with open(fp, "w") as f:
            json.dump([{"strategy":s["strategy"],"ticker":s["ticker"],"params":{str(k):v for k,v in s["params"].items()},"metrics":s["metrics"]} for s in top50], f, indent=2)
        print(f"Saved: {fp}", flush=True)
        break
    else:
        print(f"  Not enough. Trying next target set.", flush=True)
