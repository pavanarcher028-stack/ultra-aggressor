import pickle, numpy as np, pandas as pd, math
with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def ema(s,p): return s.ewm(span=p).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.clip(0); l=-d.clip(upper=0)
    ag=g.ewm(span=p).mean(); al=l.ewm(span=p).mean().replace(0,1e-10)
    return 100-100/(1+ag/al)

def run(c_arr,s_arr):
    n=len(s_arr); eq=1.0; eqs=np.ones(n); trades=0; wins=0; pos=0.0; entry_eq=0.0; peak=1.0
    for i in range(1,n):
        s=s_arr[i-1] if i>0 else 0.0
        if np.isnan(s) or np.isinf(s): s=0.0
        turn=abs(s-pos)
        if turn>0:
            if abs(pos)>0:
                trades+=1
                if eq>entry_eq: wins+=1
            eq-=turn*0.0015*eq
            if abs(s)>0: entry_eq=eq
        pos=s; ret=c_arr[i]/c_arr[i-1]-1
        if pos>0: eq*=1+ret*abs(pos)
        elif pos<0: eq*=1-ret*abs(pos)-0.05/(252*4)*abs(pos)
        eqs[i]=eq; peak=max(peak,eq)
    rets=pd.Series(eqs).pct_change().dropna()
    tr=eqs[-1]-1; ny=n/(252*4)
    ann=(1+tr)**(1/max(ny,0.1))-1
    sr=rets.mean()/rets.std()*math.sqrt(252*4) if len(rets)>0 and rets.std()>0 else 0
    dd=(1-eqs/np.maximum.accumulate(eqs)).max()
    return wins/max(trades,1)*100, dd*100, sr, ann*100, trades, tr*100

def get_6h(symbol):
    d=raw[symbol]
    o=d['Open'].resample('6h').first()
    h=d['High'].resample('6h').max()
    l=d['Low'].resample('6h').min()
    c=d['Close'].resample('6h').last()
    return pd.DataFrame({'c':c.values.ravel()},index=o.index).dropna()

def get_daily(symbol):
    d=raw[symbol]
    o=d['Open'].resample('1D').first()
    h=d['High'].resample('1D').max()
    l=d['Low'].resample('1D').min()
    c=d['Close'].resample('1D').last()
    return pd.DataFrame({'c':c.values.ravel()},index=o.index).dropna()

tickers = ['ETH-USD','BTC-USD','SOL-USD','XRP-USD','LINK-USD','ADA-USD','AVAX-USD','DOT-USD','MATIC-USD','ATOM-USD']

print("=== STRATEGY GRADING (HONEST - NO LOOKAHEAD) ===")
print("Targets: WR=40-55%, DD<20%, SR>=1.0, Ann>=20%\n")

def grade(wr,dd,sr,ann):
    targets = [40<=wr<=55, dd<=20, sr>=1.0, ann>=20]
    passed = sum(targets)
    g = 'F'
    if passed>=4: g='A'
    elif passed>=3: g='B'
    elif passed>=2: g='C'
    elif passed>=1: g='D'
    return g, passed

results = []

print("--- Daily EMA Crossover ---")
for ticker in tickers[:5]:
    df = get_daily(ticker); arr = df['c'].values.ravel(); c = df['c']
    for f,s in [(3,50),(3,100),(5,50),(5,100),(10,30),(10,50)]:
        sig = np.where(ema(c,f).values > ema(c,s).values, 1.0, -1.0)
        wr,dd,sr,ann,td,tr = run(arr,sig)
        g,p = grade(wr,dd,sr,ann)
        results.append((g,p,wr,dd,sr,ann,'Daily EMA',ticker,f,s))

print("--- Daily RSI Trend (RSI>50 long, RSI<50 short) ---")
for ticker in tickers[:5]:
    df = get_daily(ticker); arr = df['c'].values.ravel(); c = df['c']
    for p in [7,14,21]:
        r = rsi(c,p).values
        sig = np.where(r>50, 1.0, -1.0)
        wr,dd,sr,ann,td,tr = run(arr,sig)
        g,pas = grade(wr,dd,sr,ann)
        results.append((g,pas,wr,dd,sr,ann,'Daily RSI',ticker,p))

print("--- Daily Z-score Mean Reversion ---")
for ticker in tickers[:5]:
    df = get_daily(ticker); arr = df['c'].values.ravel(); c = df['c']
    for period in [10,20,40]:
        m = c.rolling(period).mean(); std = c.rolling(period).std().replace(0,1e-10)
        z = ((c - m) / std).values
        sig = np.zeros(len(c))
        for i in range(1,len(c)):
            if z[i] <= -1.5: sig[i] = 1.0
            elif z[i] >= 1.5: sig[i] = -1.0
            else: sig[i] = sig[i-1]
        wr,dd,sr,ann,td,tr = run(arr,sig)
        g,pas = grade(wr,dd,sr,ann)
        results.append((g,pas,wr,dd,sr,ann,'Daily ZMR',ticker,period))

print("--- 6h EMA Crossover (long lookback) ---")
for ticker in tickers[:5]:
    df = get_6h(ticker); arr = df['c'].values.ravel(); c = df['c']
    for f,s in [(4,160),(8,160),(16,160),(4,320),(8,320)]:
        sig = np.where(ema(c,f).values > ema(c,s).values, 1.0, -1.0)
        wr,dd,sr,ann,td,tr = run(arr,sig)
        g,pas = grade(wr,dd,sr,ann)
        results.append((g,pas,wr,dd,sr,ann,'6h EMA',ticker,f,s))

print("--- 6h Bollinger Volatility Breakout ---")
for ticker in tickers[:5]:
    df = get_6h(ticker); arr = df['c'].values.ravel(); c = df['c']
    for p,std in [(20,2),(20,2.5),(40,2),(40,2.5)]:
        m = c.rolling(p).mean(); sd = c.rolling(p).std().replace(0,1e-10)
        upper = m + std * sd; lower = m - std * sd
        sig = np.zeros(len(c))
        for i in range(1,len(c)):
            if c.iloc[i] > upper.iloc[i]: sig[i] = 1.0  # breakout up
            elif c.iloc[i] < lower.iloc[i]: sig[i] = -1.0  # breakout down
            else: sig[i] = sig[i-1]
        wr,dd,sr,ann,td,tr = run(arr,sig)
        g,pas = grade(wr,dd,sr,ann)
        results.append((g,pas,wr,dd,sr,ann,'6h BB',ticker,p,std))

# Sort by pass count, then Sharpe
results.sort(key=lambda x: (-x[1], -x[4]))

print("\n\n=== BEST RESULTS (sorted by target pass count, then Sharpe) ===")
print(f"{'Grade':6s}{'Pass':5s}{'WR%':8s}{'DD%':8s}{'Sharpe':8s}{'Ann%':8s}{'Name':20s}{'Symbol':10s}{'Params'}")
print("="*100)
for g,pas,wr,dd,sr,ann,name,ticker,*par in results[:30]:
    pstr = ','.join(str(x) for x in par)
    print(f"{g:6s}{pas:<5d}{wr:<8.1f}{dd:<8.1f}{sr:<8.2f}{ann:<8.1f}{name:20s}{ticker:10s}{pstr}")

# Summary
print(f"\n\n=== SUMMARY ===")
grades = [r[0] for r in results]
for g in ['A','B','C','D','F']:
    cnt = grades.count(g)
    print(f"  Grade {g}: {cnt} strategy-coin combos")

best = [r for r in results if r[0]=='A' or r[0]=='B']
print(f"\nBest combos (A or B): {len(best)}")
for g,pas,wr,dd,sr,ann,name,ticker,*par in best:
    pstr = ','.join(str(x) for x in par)
    print(f"  {g} {ticker:8s} {name:15s}({pstr:15s}) WR={wr:.1f} DD={dd:.1f} SR={sr:.2f} Ann={ann:.1f}")
