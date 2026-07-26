"""
Fix: Remove position cap bottleneck, test with full range.
The * 2 clip bug limits position to max_pos_pct — need bigger positions for 20%+ returns.
"""
import sys, os, time, pickle, random, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

CACHE = "crypto_data_3.pkl"
with open(CACHE, "rb") as f: data = pickle.load(f)

# Direct backtest with our own signal function (bypass factory limitations)
from autonomous_trader.backtester import run_backtest

def yz_vol(df, w=14):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    lo = np.log(o / c.shift(1))
    lc = np.log(c / c.shift(1))
    rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
    k = 0.34 / (1.34 + (w+1)/max(w-1, 1))
    yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv * 252, 1e-8))

def tstat(prices, lb):
    if len(prices) < lb: return 0.0
    y = np.log(prices.values[-lb:])
    x = np.arange(lb)
    xm, ym = x.mean(), y.mean()
    beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
    resid = y - (ym + beta*(x-xm))
    se = np.sqrt(np.sum(resid**2) / max(lb-2, 1))
    se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
    return beta / se_b if se_b > 0 else 0.0

def make_tsmom_signal(lb_fast=15, lb_slow=60, t_entry=1.5, t_exit=0.5,
                      vol_target=0.40, max_pos=0.50, ts_pct=0.15, yz_w=14, reg_w=30):
    """TSMOM with adjustable position sizing"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, yz_w)
        med = yz.rolling(reg_w, min_periods=max(reg_w//2, 5)).median()
        regime = (yz > med).astype(int)
        
        sig = pd.Series(0.0, index=df.index)
        warmup = max(lb_fast, lb_slow, yz_w, reg_w) + 2
        in_pos = False; entry_h = 0.0
        
        for i in range(warmup, len(df)):
            lb = lb_fast if regime.iloc[i] == 1 else lb_slow
            lb = min(lb, i)
            ts = tstat(c.iloc[i-lb:i+1], lb)
            
            prev = sig.iloc[i-1]
            if prev != 0:
                sig.iloc[i] = np.sign(prev) if abs(ts) >= t_exit else 0.0
            elif ts > t_entry:
                sig.iloc[i] = 1.0
            elif ts < -t_entry:
                sig.iloc[i] = -1.0
            else:
                sig.iloc[i] = 0.0
            
            if sig.iloc[i] != 0:
                if not in_pos:
                    in_pos = True
                    entry_h = c.iloc[i]
                entry_h = max(entry_h, c.iloc[i])
                dd = (entry_h - c.iloc[i]) / entry_h
                if dd > ts_pct:
                    sig.iloc[i] = 0.0
                    in_pos = False
            else:
                in_pos = False
        
        pos = sig.shift(1).fillna(0)
        vol_ratio = vol_target / yz.clip(lower=0.01)
        mult = vol_ratio.clip(upper=3.0).fillna(1.0)
        # FIXED: no * 2 bug, proper scaling
        df["signal"] = (pos * mult * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

random.seed(42)
results = []
t0 = time.time()
ticker = "BTC-USD"

print("Testing TSMOM with FIXED position sizing (max_pos up to 1.0 = 100% of NAV)", flush=True)
print(f"{'#':>4} {'LF':>3} {'LS':>3} {'TE':>4} {'MP':>5} {'VS':>5} {'TS':>5} {'WR':>6} {'DD':>6} {'Sharpe':>7} {'Ann':>7} {'Total':>7}", flush=True)
print("-"*85, flush=True)

for i in range(100):
    lf = random.choice([8,10,12,15,18,20,25])
    ls = random.choice([30,40,50,60,80])
    te = random.choice([1.0,1.2,1.5,1.8,2.0])
    tx = random.choice([0.3,0.5,0.8])
    va = random.choice([0.20,0.30,0.40,0.50,0.60])
    mp = random.choice([0.20,0.30,0.40,0.50,0.60,0.80,1.0])
    ts = random.choice([0.05,0.08,0.10,0.12,0.15,0.20])
    
    sig_func = make_tsmom_signal(lb_fast=lf, lb_slow=ls, t_entry=te, t_exit=tx,
                                 vol_target=va, max_pos=mp, ts_pct=ts)
    try:
        r = run_backtest(data[ticker].copy(), sig_func)
        wr=r["win_rate"]*100; dd=r["max_dd"]*100; sh=r["sharpe"]; an=r["annualized_return"]*100; tr=r["total_return"]*100
        print(f"{i+1:4d} {lf:3d} {ls:3d} {te:4.1f} {mp:5.2f} {va:5.2f} {ts:5.2f} {wr:>5.1f}% {dd:>5.1f}% {sh:>7.2f} {an:>6.1f}% {tr:>7.1f}%", flush=True)
        results.append({"wr":wr,"dd":dd,"sharpe":sh,"ann":an,"total":tr,"params":{"lf":lf,"ls":ls,"te":te,"tx":tx,"va":va,"mp":mp,"ts":ts}})
    except:
        print(f"{i+1:4d} ERROR", flush=True)

elapsed = time.time()-t0
print(f"\nDone in {elapsed:.0f}s", flush=True)

# Best results
print(f"\n{'='*60}", flush=True)
print("BEST BY SHARPE (>=1.0)", flush=True)
print(f"{'='*60}", flush=True)
for r in sorted(results, key=lambda x:x["sharpe"], reverse=True)[:10]:
    if r["sharpe"] >= 1.0:
        print(f"Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}% DD={r['dd']:.1f}% WR={r['wr']:.1f}% Total={r['total']:.1f}% Params={r['params']}", flush=True)

print(f"\n{'='*60}", flush=True)  
print("BEST BY ANNUAL RETURN (>=20%)", flush=True)
print(f"{'='*60}", flush=True)
for r in sorted(results, key=lambda x:x["ann"], reverse=True)[:10]:
    if r["ann"] >= 20:
        print(f"Ann={r['ann']:.1f}% Sharpe={r['sharpe']:.2f} DD={r['dd']:.1f}% WR={r['wr']:.1f}% Total={r['total']:.1f}% Params={r['params']}", flush=True)

# Count passing all targets
TGT = {"min_wr": 0.40, "max_wr": 0.55, "max_dd": 0.20, "min_sharpe": 1.0, "min_ann": 0.20}
passing = [r for r in results if 
    TGT["min_wr"] <= r["wr"] <= TGT["max_wr"] and r["dd"] <= TGT["max_dd"] and
    r["sharpe"] >= TGT["min_sharpe"] and r["ann"] >= TGT["min_ann"]]
print(f"\nPassing ALL targets: {len(passing)}/{len(results)}", flush=True)
for r in passing:
    print(f"  Sharpe={r['sharpe']:.2f} Ann={r['ann']:.1f}% DD={r['dd']:.1f}% WR={r['wr']:.1f}% Params={r['params']}", flush=True)
