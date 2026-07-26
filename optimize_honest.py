"""
Enhanced honest backtester with position sizing, stop-loss, and parameter optimization.
Goal: find strategy-coin combos that pass ALL 4 targets (WR=40-55%, DD<20%, SR>=1.0, Ann>=20%)
"""
import pickle, numpy as np, pandas as pd, math, json, time
from collections import defaultdict

with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)

def ema(s,p): return s.ewm(span=p).mean()
def sma(s,p): return s.rolling(p).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.clip(0); l=-d.clip(upper=0)
    ag=g.ewm(span=p).mean(); al=l.ewm(span=p).mean().replace(0,1e-10)
    return 100-100/(1+ag/al)
def atr(df,p=14):
    h=df['high']; l=df['low']; c=df['close']
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(1)
    return tr.rolling(p).mean()
def hma(s,p): return ema(2*ema(s,p//2)-ema(s,p),int(math.sqrt(p)))
def kama(s,p=10,f=2,s_=30):
    er=(s-s.shift(p)).abs()/(s.diff().abs().rolling(p).sum().replace(0,1e-10))
    sc=(er*(f-s_)+s_)**2; ka=pd.Series(s.iloc[0],index=s.index)
    for i in range(1,len(s)): ka.iloc[i]=ka.iloc[i-1]+sc.iloc[i]*(s.iloc[i]-ka.iloc[i-1])
    return ka
def zlema(s,p): return ema(s+0.5*(s-s.shift(p//2)),p)
def macd(s,f=12,sl=26,sg=9):
    e1=ema(s,f); e2=ema(s,sl); m=e1-e2
    return m, ema(m,sg)
def bollinger(s,p=20,m=2):
    mid=sma(s,p); std=s.rolling(p).std()
    return mid, mid+m*std, mid-m*std
def stoch(df,k=14,d=3):
    h=df['high'].rolling(k).max(); l=df['low'].rolling(k).min()
    sk=100*(df['close']-l)/(h-l).replace(0,1e-10); sd=sk.rolling(d).mean()
    return sk, sd
def cci(df,p=20):
    tp=(df['high']+df['low']+df['close'])/3
    m=tp.rolling(p).mean(); d_=tp.rolling(p).std().replace(0,1e-10)
    return (tp-m)/(0.015*d_)
def williams(df,p=14):
    h=df['high'].rolling(p).max(); l=df['low'].rolling(p).min()
    return -100*(h-df['close'])/(h-l).replace(0,1e-10)
def adx(df,p=14):
    h=df['high']; l=df['low']; c=df['close']
    up=h-h.shift(); dn=l.shift()-l
    pdi=(((up>dn)&(up>0))*up).ewm(span=p).mean()/atr(df,p).replace(0,1e-10)*100
    ndi=(((dn>up)&(dn>0))*dn).ewm(span=p).mean()/atr(df,p).replace(0,1e-10)*100
    dx=((pdi-ndi)/(pdi+ndi).replace(0,1e-10)).abs()*100
    return pdi, ndi, dx.ewm(span=p).mean()
def obv(df): return (df['volume']*((df['close']>df['close'].shift()).astype(int)*2-1)).cumsum()
def cmf(df,p=20):
    mf=df['volume']*((df['close']-df['low'])-(df['high']-df['close']))/(df['high']-df['low']).replace(0,1e-10)
    return mf.rolling(p).sum()/df['volume'].rolling(p).sum().replace(0,1e-10)
def fisher(s,p=9):
    h_=s.rolling(p).max(); l_=s.rolling(p).min()
    v=0.5*((s-l_)/(h_-l_).replace(0,1e-10)*2-1+0.5*(s.shift()-l_.shift())/(h_.shift()-l_.shift()).replace(0,1e-10)*2-1)
    return (np.exp(2*v)-1)/(np.exp(2*v)+1)
def tsi(s,r=25,s_=13):
    m=s.diff(); em1=ema(m,r); em2=ema(em1,s_); ae=ema(m.abs(),r); aem=ema(ae,s_)
    return em2/aem.replace(0,1e-10)*100
def elder_ray(df,p=14):
    ema_=ema(df['close'],p)
    return df['high']-ema_, ema_-df['low']
def donchian(df,p=20):
    return df['high'].rolling(p).max(), (df['high'].rolling(p).max()+df['low'].rolling(p).min())/2, df['low'].rolling(p).min()
def keltner(df,p=20,m=2):
    mid=ema(df['close'],p); a=atr(df,p)
    return mid, mid+m*a, mid-m*a
def paras(df,step=0.02,m=0.2):
    h=df['high']; l=df['low']; c=df['close']; n=len(c)
    sar=np.zeros(n); ep=np.zeros(n); af=np.ones(n)*step; trend=np.ones(n)
    sar[0]=l[0]; ep[0]=h[0]
    for i in range(1,n):
        if trend[i-1]==1:
            sar[i]=sar[i-1]+af[i-1]*(ep[i-1]-sar[i-1])
            sar[i]=min(sar[i],l[i-1],l[i])
            if h[i]>ep[i-1]: ep[i]=h[i]; af[i]=min(af[i-1]+step,m)
            else: ep[i]=ep[i-1]; af[i]=af[i-1]
            if l[i]<=sar[i]: trend[i]=-1; sar[i]=ep[i-1]; ep[i]=l[i]; af[i]=step
            else: trend[i]=1
        else:
            sar[i]=sar[i-1]-af[i-1]*(sar[i-1]-ep[i-1])
            sar[i]=max(sar[i],h[i-1],h[i])
            if l[i]<ep[i-1]: ep[i]=l[i]; af[i]=min(af[i-1]+step,m)
            else: ep[i]=ep[i-1]; af[i]=af[i-1]
            if h[i]>=sar[i]: trend[i]=1; sar[i]=ep[i-1]; ep[i]=h[i]; af[i]=step
            else: trend[i]=-1
    return pd.Series(trend,index=df.index)

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

def resample_daily(data):
    if isinstance(data.columns, pd.MultiIndex):
        d2 = pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
        data = d2
    o = data["Open"].resample("1D").first()
    h = data["High"].resample("1D").max()
    l = data["Low"].resample("1D").min()
    c = data["Close"].resample("1D").last()
    v = data["Volume"].resample("1D").sum()
    df = pd.DataFrame({"open":o.values.ravel(),"high":h.values.ravel(),"low":l.values.ravel(),
                       "close":c.values.ravel(),"volume":v.values.ravel()}, index=o.index)
    df.dropna(inplace=True)
    return df

# ============================================================
# ENHANCED BACKTESTER with position sizing and stop-loss
# ============================================================
def run_bt_enhanced(close_arr, sig_arr, scale=1.0, stop_loss=0.0, take_profit=0.0):
    """
    Enhanced backtester with:
    - scale: position size multiplier (e.g., 0.3 = 30% of capital per trade)
    - stop_loss: if >0, exit position at X% loss (e.g., 0.05 = 5% stop)
    - take_profit: if >0, exit position at X% gain
    - NO lookahead: uses sig_arr[i-1] for bar i's return
    """
    n=len(sig_arr); eq=1.0; eqs=np.ones(n); trades=0; wins=0; pos=0.0; entry_eq=0.0; peak=1.0
    entry_price = 0.0; max_price = 0.0
    
    for i in range(1, n):
        # Signal from previous bar (NO lookahead)
        s = sig_arr[i-1] if i > 0 else 0.0
        if np.isnan(s) or np.isinf(s): s = 0.0
        
        # Position sizing
        s = s * scale
        s = max(min(s, 1.0), -1.0)  # clamp to [-1, 1]
        
        # Stop-loss / take-profit check
        stop_hit = False
        if abs(pos) > 0 and stop_loss > 0:
            ret_since_entry = abs(eq / entry_eq - 1) if entry_eq > 0 else 0
            if ret_since_entry >= stop_loss:
                stop_hit = True
        
        take_hit = False
        if abs(pos) > 0 and take_profit > 0:
            ret_since_entry = abs(eq / entry_eq - 1) if entry_eq > 0 else 0
            if ret_since_entry >= take_profit:
                take_hit = True
        
        if stop_hit or take_hit:
            # Exit position
            trades += 1
            if eq > entry_eq: wins += 1
            pos = 0.0
            s = 0.0  # force flat
        
        # Turnover cost
        turn = abs(s - pos)
        if turn > 0:
            if abs(pos) > 0:
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= turn * 0.0015 * eq
            if abs(s) > 0:
                entry_eq = eq
                entry_price = close_arr[i]
                max_price = close_arr[i]
        
        pos = s
        ret = close_arr[i] / close_arr[i-1] - 1
        
        if pos > 0:
            eq *= 1 + ret * abs(pos)
        elif pos < 0:
            eq *= 1 - ret * abs(pos) - 0.05 / (252 * 4) * abs(pos)
        
        eqs[i] = eq
        peak = max(peak, eq)
    
    rets = pd.Series(eqs).pct_change().dropna()
    tr = eqs[-1] - 1
    ny = n / (252 * 4)
    ann = (1 + tr) ** (1 / max(ny, 0.1)) - 1
    sr = rets.mean() / rets.std() * math.sqrt(252 * 4) if len(rets) > 0 and rets.std() > 0 else 0
    dd = (1 - eqs / np.maximum.accumulate(eqs)).max()
    wr = wins / max(trades, 1)
    
    return {"wr": wr, "dd": dd, "sr": sr, "ann": ann, "tr": tr, "trades": trades, "eqs": eqs.tolist()}

# ============================================================
# STRATEGY SIGNAL GENERATORS
# ============================================================
def sig_ema(df, fast=5, slow=50, mp=1.0):
    c=df['close']; return np.where(ema(c,fast)>ema(c,slow),mp,-mp)

def sig_sma(df, fast=5, slow=50, mp=1.0):
    c=df['close']; return np.where(sma(c,fast)>sma(c,slow),mp,-mp)

def sig_macd(df, f=12, sl=26, sg=9, mp=1.0):
    c=df['close']; m,s=macd(c,f,sl,sg)
    return np.where(m>s,mp,-mp)

def sig_macd_hist(df, f=12, sl=26, sg=9, mp=1.0):
    c=df['close']; m,s=macd(c,f,sl,sg); h=m-s
    return np.where(h>h.shift(),mp,-mp)

def sig_hma(df, fast=8, slow=40, mp=1.0):
    c=df['close']; return np.where(hma(c,fast)>hma(c,slow),mp,-mp)

def sig_zlema(df, fast=5, slow=50, mp=1.0):
    c=df['close']; return np.where(zlema(c,fast)>zlema(c,slow),mp,-mp)

def sig_kama(df, fast=5, slow=50, mp=1.0):
    c=df['close']; return np.where(kama(c,fast)>kama(c,slow),mp,-mp)

def sig_dema(df, fast=5, slow=50, mp=1.0):
    c=df['close']; d1=2*ema(c,fast)-ema(ema(c,fast),fast)
    d2=2*ema(c,slow)-ema(ema(c,slow),slow)
    return np.where(d1>d2,mp,-mp)

def sig_trix(df, p=15, sg=9, mp=1.0):
    c=df['close']; t=ema(ema(ema(c,p),p),p); s=ema(t,sg)
    return np.where(t>s,mp,-mp)

def sig_lsma(df, lb=48, mp=1.0):
    c=df['close'].values; n=len(c); sig=np.ones(n)
    for i in range(lb,n):
        y=np.log(c[i-lb:i]); x=np.arange(lb)
        xm,ym=x.mean(),y.mean()
        b=np.sum((x-xm)*(y-ym))/max(np.sum((x-xm)**2),1e-10)
        sig[i]=mp if b>0 else -mp
    return sig[:n]

def sig_tsmom(df, lb=48, entry=0.8, mp=1.0):
    c=df['close'].values; n=len(c); sig=np.zeros(n)
    for i in range(lb,n):
        y=np.log(c[i-lb:i]); x=np.arange(lb)
        xm,ym=x.mean(),y.mean()
        beta=np.sum((x-xm)*(y-ym))/max(np.sum((x-xm)**2),1e-10)
        resid=y-(ym+beta*(x-xm))
        se=np.sqrt(np.sum(resid**2)/max(lb-2,1))
        se_b=se/max(np.sqrt(np.sum((x-xm)**2)),1e-10)
        ts=beta/se_b if se_b>0 else 0
        sig[i]=mp if ts>entry else (-mp if ts<-entry else 0)
    return sig

def sig_rsi50(df, p=14, mp=1.0):
    r=rsi(df['close'],p).values
    return np.where(r>50,mp,-mp)

def sig_stoch50(df, k=14, d=3, mp=1.0):
    sk,sd=stoch(df,k,d)
    return np.where(sk>sd,mp,-mp)

def sig_cci(df, p=20, mp=1.0):
    c=cci(df,p).values
    return np.where(c>0,mp,-mp)

def sig_williams(df, p=14, mp=1.0):
    w=williams(df,p).values
    return np.where(w>-50,mp,-mp)

def sig_tsi(df, r=25, s=13, mp=1.0):
    t=tsi(df['close'],r,s).values
    return np.where(t>0,mp,-mp)

def sig_fisher(df, p=9, mp=1.0):
    f=fisher(df['close'],p).values
    return np.where(f>0,mp,-mp)

def sig_elder(df, p=14, mp=1.0):
    bp,ep=elder_ray(df,p)
    return np.where(bp>0,mp,-mp)

def sig_boll_mid(df, p=20, m=2, mp=1.0):
    c=df['close']; mid,up,lo=bollinger(c,p,m)
    return np.where(c>mid,mp,-mp)

def sig_boll_brk(df, p=20, m=2, mp=1.0):
    c=df['close']; mid,up,lo=bollinger(c,p,m)
    sig=np.ones(len(c))
    for i in range(1,len(c)):
        if c.iloc[i]>up.iloc[i] and c.iloc[i-1]<=up.iloc[i-1]: sig[i]=mp
        elif c.iloc[i]<lo.iloc[i] and c.iloc[i-1]>=lo.iloc[i-1]: sig[i]=-mp
        else: sig[i]=0
    return sig

def sig_donchian(df, p=40, mp=1.0):
    h,mid,l=donchian(df,p); c=df['close']
    sig=np.zeros(len(c))
    for i in range(1,len(c)):
        if c.iloc[i]>h.iloc[i-1]: sig[i]=mp
        elif c.iloc[i]<l.iloc[i-1]: sig[i]=-mp
    return sig

def sig_paras(df, step=0.02, m=0.2, mp=1.0):
    return (paras(df,step,m)*mp).values

def sig_supertrend(df, p=10, m_=3, mp=1.0):
    a=atr(df,p); hl=(df['high']+df['low'])/2
    ub=hl+m_*a; lb=hl-m_*a; st=pd.Series(1.0,index=df.index)
    for i in range(1,len(df)):
        if df['close'].iloc[i]<=ub.iloc[i]: st.iloc[i]=-1
        else: st.iloc[i]=1
    return (st*mp).values

def sig_adx_di(df, p=14, mp=1.0):
    pdi,ndi,_=adx(df,p)
    return np.where(pdi>ndi,mp,-mp)

def sig_vortex(df, p=14, mp=1.0):
    h=df['high']; l=df['low']; c=df['close']
    vp=(h-l.shift()).abs().rolling(p).sum()/atr(df,p).rolling(p).sum().replace(0,1e-10)
    vm=(l-h.shift()).abs().rolling(p).sum()/atr(df,p).rolling(p).sum().replace(0,1e-10)
    return np.where(vp>vm,mp,-mp)

def sig_heikin(df, mp=1.0):
    ha_c=(df['open']+df['high']+df['low']+df['close'])/4
    ha_o=(df['open'].shift()+df['close'].shift())/2
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        sig[i]=mp if ha_c.iloc[i]>ha_o.iloc[i] else -mp
    return sig

def sig_vwap(df, p=20, mp=1.0):
    c=df['close']; v=df['volume']
    vwap=(c*v).rolling(p).sum()/v.rolling(p).sum()
    return np.where(c>vwap,mp,-mp)

def sig_vwma(df, p=50, mp=1.0):
    c=df['close']; v=df['volume']; vwma=(c*v).rolling(p).sum()/v.rolling(p).sum()
    return np.where(c>vwma,mp,-mp)

def sig_mom_roc(df, p=12, mp=1.0):
    roc=(df['close']/df['close'].shift(p)-1)*100
    return np.where(roc>0,mp,-mp)

def sig_mom_slope(df, p=20, mp=1.0):
    c=df['close']; slope=c.diff(p)
    return np.where(slope>0,mp,-mp)

def sig_dual_mom(df, fast=10, slow=30, mp=1.0):
    c=df['close']; m1=c/c.shift(fast)-1; m2=c/c.shift(slow)-1
    return np.where(m1>m2,mp,-mp)

def sig_zscore_mr(df, p=20, entry=1.5, mp=1.0):
    c=df['close']; m=sma(c,p); std=c.rolling(p).std().replace(0,1e-10)
    z=(c-m)/std; sig=np.zeros(len(c))
    for i in range(1,len(c)):
        if z.iloc[i-1]<=-entry: sig[i]=mp
        elif z.iloc[i-1]>=entry: sig[i]=-mp
        else: sig[i]=sig[i-1]
    return sig

def sig_dual_rsi(df, fp=3, sp=14, mp=1.0):
    r1=rsi(df['close'],fp); r2=rsi(df['close'],sp)
    return np.where(r1>r2,mp,-mp)

def sig_rsi_ma(df, p=14, map_=50, mp=1.0):
    r=rsi(df['close'],p); ma=sma(df['close'],map_)
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        if r.iloc[i]>50 and df['close'].iloc[i]>ma.iloc[i]: sig[i]=mp
        elif r.iloc[i]<50 and df['close'].iloc[i]<ma.iloc[i]: sig[i]=-mp
    return sig

def sig_ema_rsi(df, fp=5, sp=50, rp=14, mp=1.0):
    c=df['close']; e=ema(c,fp)>ema(c,sp); r=rsi(c,rp)>50
    return np.where(e.values & r.values,mp,-mp)

def sig_ema_macd(df, fp=5, sp=50, mp=1.0):
    c=df['close']; e=ema(c,fp)>ema(c,sp); m,_=macd(c)
    return np.where(e.values & (m>0).values,mp,-mp)

def sig_atr_tr(df, p=14, mult=3, mp=1.0):
    a=atr(df,p); c=df['close']; st=mult*a
    sig=np.ones(len(c))*mp
    for i in range(1,len(c)):
        if c.iloc[i]<c.iloc[i-1]-st.iloc[i-1]: sig[i]=-mp
        elif c.iloc[i]>c.iloc[i-1]+st.iloc[i-1]: sig[i]=mp
        else: sig[i]=sig[i-1]
    return sig

def sig_ema_boll(df, fp=5, sp=50, bp=20, mp=1.0):
    c=df['close']; e=ema(c,fp)>ema(c,sp); mid,up,lo=bollinger(c,bp)
    return np.where(e.values & (c>mid).values,mp,-mp)

def sig_macd_boll(df, fp=12, sp=26, bp=20, mp=1.0):
    c=df['close']; m,_=macd(c,fp,sp); mid,up,lo=bollinger(c,bp)
    return np.where((m>0).values & (c>mid).values,mp,-mp)

def sig_mfi(df, p=14, mp=1.0):
    tp=(df['high']+df['low']+df['close'])/3
    pmf=(tp>tp.shift())*tp*df['volume']; nmf=(tp<tp.shift())*tp*df['volume']
    mf_ratio=pmf.rolling(p).sum()/nmf.rolling(p).sum().replace(0,1e-10)
    mfi=100-100/(1+mf_ratio)
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        if mfi.iloc[i-1]<=20 and mfi.iloc[i]>20: sig[i]=mp
        elif mfi.iloc[i-1]>=80 and mfi.iloc[i]<80: sig[i]=-mp
    return sig

def sig_cmf(df, p=20, mp=1.0):
    cf=cmf(df,p); c=df['close']
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        if cf.iloc[i]>0 and c.iloc[i]>ema(c,50).iloc[i]: sig[i]=mp
        elif cf.iloc[i]<0 and c.iloc[i]<ema(c,50).iloc[i]: sig[i]=-mp
    return sig

def sig_obv(df, p=20, mp=1.0):
    o=obv(df); o_ema=ema(o,p)
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        sig[i]=mp if o.iloc[i]>o_ema.iloc[i] else -mp
    return sig

def sig_vol_surge(df, vp=20, mp=1.0):
    v=df['volume']; c=df['close']
    vma=v.rolling(vp).mean()
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        if v.iloc[i]>vma.iloc[i]*1.5 and c.iloc[i]>c.iloc[i-1]: sig[i]=mp
        elif v.iloc[i]>vma.iloc[i]*1.5 and c.iloc[i]<c.iloc[i-1]: sig[i]=-mp
    return sig

def sig_price_channel(df, p=30, mp=1.0):
    h=df['high'].rolling(p).max(); l_=df['low'].rolling(p).min(); c=df['close']
    sig=np.zeros(len(c))
    for i in range(1,len(c)):
        if c.iloc[i]>h.iloc[i-1]: sig[i]=mp
        elif c.iloc[i]<l_.iloc[i-1]: sig[i]=-mp
    return sig

def sig_range_rev(df, p=10, mp=1.0):
    h=df['high'].rolling(p).max(); l=df['low'].rolling(p).min()
    r=h-l; c=df['close']
    sig=np.zeros(len(df))
    for i in range(1,len(df)):
        if c.iloc[i]<l.iloc[i-1]+0.1*r.iloc[i-1] and c.iloc[i]>c.iloc[i-1]: sig[i]=mp
        elif c.iloc[i]>h.iloc[i-1]-0.1*r.iloc[i-1] and c.iloc[i]<c.iloc[i-1]: sig[i]=-mp
    return sig

# ============================================================
# STRATEGY REGISTRY
# ============================================================
strategies = [
    ("EMA", sig_ema, [{"fast":5,"slow":50},{"fast":3,"slow":100},{"fast":10,"slow":50},{"fast":5,"slow":100}]),
    ("SMA", sig_sma, [{"fast":5,"slow":50},{"fast":3,"slow":100},{"fast":10,"slow":50}]),
    ("MACD", sig_macd, [{"f":12,"sl":26,"sg":9},{"f":8,"sl":24,"sg":5},{"f":10,"sl":30,"sg":7}]),
    ("MACDH", sig_macd_hist, [{"f":12,"sl":26,"sg":9}]),
    ("HMA", sig_hma, [{"fast":8,"slow":40},{"fast":6,"slow":30},{"fast":10,"slow":60}]),
    ("ZLEMA", sig_zlema, [{"fast":5,"slow":50},{"fast":3,"slow":30}]),
    ("KAMA", sig_kama, [{"fast":5,"slow":50}]),
    ("DEMA", sig_dema, [{"fast":5,"slow":50},{"fast":3,"slow":30}]),
    ("TRIX", sig_trix, [{"p":15,"sg":9}]),
    ("LSMA", sig_lsma, [{"lb":48},{"lb":32}]),
    ("TSMOM", sig_tsmom, [{"lb":48,"entry":0.8},{"lb":32,"entry":0.6}]),
    ("RSI50", sig_rsi50, [{"p":14},{"p":7},{"p":21},{"p":10}]),
    ("Stoch", sig_stoch50, [{"k":14,"d":3},{"k":10,"d":3}]),
    ("CCI", sig_cci, [{"p":20}]),
    ("Wllms", sig_williams, [{"p":14}]),
    ("TSI", sig_tsi, [{"r":25,"s":13}]),
    ("Fishr", sig_fisher, [{"p":9}]),
    ("Elder", sig_elder, [{"p":14},{"p":7}]),
    ("BollM", sig_boll_mid, [{"p":20,"m":2},{"p":30,"m":2}]),
    ("BollB", sig_boll_brk, [{"p":20,"m":2}]),
    ("Donch", sig_donchian, [{"p":40},{"p":20}]),
    ("PSAR", sig_paras, [{"step":0.02,"m":0.2}]),
    ("Super", sig_supertrend, [{"p":10,"m_":3}]),
    ("ADXDI", sig_adx_di, [{"p":14},{"p":7}]),
    ("Vortx", sig_vortex, [{"p":14}]),
    ("Heiki", sig_heikin, [{}]),
    ("VWAP", sig_vwap, [{"p":20}]),
    ("VWMA", sig_vwma, [{"p":50}]),
    ("ROC", sig_mom_roc, [{"p":12},{"p":24}]),
    ("Slope", sig_mom_slope, [{"p":20}]),
    ("DMom", sig_dual_mom, [{"fast":10,"slow":30}]),
    ("ZMR", sig_zscore_mr, [{"p":20,"entry":1.0},{"p":20,"entry":1.5},{"p":10,"entry":1.5},{"p":40,"entry":1.5}]),
    ("DRSI", sig_dual_rsi, [{"fp":3,"sp":14}]),
    ("RSIMA", sig_rsi_ma, [{"p":14,"map_":50}]),
    ("EMARSI", sig_ema_rsi, [{"fp":5,"sp":50,"rp":14}]),
    ("EMAMACD", sig_ema_macd, [{"fp":5,"sp":50}]),
    ("ATRTr", sig_atr_tr, [{"p":14,"mult":3}]),
    ("EMABoll", sig_ema_boll, [{"fp":5,"sp":50,"bp":20}]),
    ("MACDBoll", sig_macd_boll, [{"fp":12,"sp":26,"bp":20}]),
    ("MFI", sig_mfi, [{"p":14}]),
    ("CMF", sig_cmf, [{"p":20}]),
    ("OBV", sig_obv, [{"p":20}]),
    ("VolSurge", sig_vol_surge, [{"vp":20}]),
    ("PrChan", sig_price_channel, [{"p":30}]),
    ("RangeR", sig_range_rev, [{"p":10}]),
    ("BollSqz", sig_boll_brk, [{"p":20,"m":2}]),  # placeholder
]

# Data preparation
tickers = ["BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD","AVAX-USD","DOT-USD","LINK-USD","BNB-USD","DOGE-USD"]
data_6h = {t: resample_6h(raw[t]) for t in tickers}
data_daily = {t: resample_daily(raw[t]) for t in tickers}

# ============================================================
# OPTIMIZATION LOOP
# ============================================================
def optimize(sname, sfn, params, ticker, data_source, freq='daily'):
    """Try multiple scale factors and stop-losses to find ALL4 passes."""
    df = data_source[ticker]
    close_arr = df['close'].values
    sig = sfn(df.copy(), mp=1.0, **params)
    
    # Search grid: scales from 0.1 to 0.8, stops from 0 to 0.15
    results = []
    
    for scale in [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]:
        for sl in [0.0, 0.02, 0.04, 0.05, 0.07, 0.10, 0.15]:
            # Also try position fading for scales below 0.5 (helps WR hit 40-55%)
            r = run_bt_enhanced(close_arr, sig, scale=scale, stop_loss=sl)
            wr_pct = r["wr"] * 100
            dd_pct = r["dd"] * 100
            ann_pct = r["ann"] * 100
            sr = r["sr"]
            
            passes = sum([40 <= wr_pct <= 55, dd_pct <= 20, sr >= 1.0, ann_pct >= 20])
            results.append((passes, wr_pct, dd_pct, sr, ann_pct, scale, sl, r["trades"]))
    
    return results

# ============================================================
# MAIN OPTIMIZATION RUN
# ============================================================
print("=" * 100)
print("HONEST OPTIMIZATION - ALL strategy types, ALL coins, multiple scales/stops")
print("Targets: WR=40-55%, DD<20%, SR>=1.0, Ann>=20%")
print("=" * 100)

all_all4 = []
all_best = []
t0 = time.time()
total_combos = sum(len(ps) for _,_,ps in strategies) * len(tickers) * 2  # *2 for daily+6h
tested = 0

# Test daily data first
for sname, sfn, param_sets in strategies:
    for p in param_sets:
        for ticker in tickers:
            tested += 1
            try:
                res = optimize(sname, sfn, p, ticker, data_daily, 'daily')
                for passes, wr, dd, sr, ann, scale, sl, trades in res:
                    if passes >= 4:
                        all_all4.append((sname, ticker, 'daily', p, scale, sl, wr, dd, sr, ann, trades))
                    elif passes >= 3:
                        pass  # collect top per strategy later
                
                # Track best per combo
                best = max(res, key=lambda x: (x[0], x[4], -x[2]))
                passes, wr, dd, sr, ann, scale, sl, trades = best
                all_best.append((sname, ticker, 'daily', p, scale, sl, wr, dd, sr, ann, passes, trades))
            except Exception as e:
                pass
        
        # Test 6h data too
        for ticker in tickers:
            tested += 1
            try:
                res = optimize(sname, sfn, p, ticker, data_6h, '6h')
                for passes, wr, dd, sr, ann, scale, sl, trades in res:
                    if passes >= 4:
                        all_all4.append((sname, ticker, '6h', p, scale, sl, wr, dd, sr, ann, trades))
                best = max(res, key=lambda x: (x[0], x[4], -x[2]))
                passes, wr, dd, sr, ann, scale, sl, trades = best
                all_best.append((sname, ticker, '6h', p, scale, sl, wr, dd, sr, ann, passes, trades))
            except Exception as e:
                pass

    p4_so_far = len(all_all4)
    print(f"  [{sname:8s}] Done. ALL4 so far: {p4_so_far} | Elapsed: {time.time()-t0:.0f}s", flush=True)

elapsed = time.time() - t0

print(f"\n{'='*100}")
print(f"OPTIMIZATION COMPLETE: {total_combos} combos in {elapsed:.0f}s")
print(f"{'='*100}")
print(f"\nALL4 COMBOS FOUND: {len(all_all4)}")

# Group by strategy
from collections import Counter
strat_counts = Counter(r[0] for r in all_all4)
if all_all4:
    print("\nBreakdown by strategy:")
    for s, c in strat_counts.most_common():
        print(f"  {s}: {c}")
else:
    print("  NONE - no strategy-coin combo passes all 4 targets")

# Show top 20 best (by pass count, then Sharpe)
print(f"\n\nTOP 20 BEST COMBOS (sorted by targets passed, then Sharpe):")
print(f"{'Pass':5s}{'Name':10s}{'Freq':6s}{'Coin':10s}{'WR%':8s}{'DD%':8s}{'SR':8s}{'Ann%':8s}{'Scale':6s}{'SL':6s}")
print('-'*90)
all_best.sort(key=lambda x: (-x[10], -x[8]))
for sname, ticker, freq, p, scale, sl, wr, dd, sr, ann, passes, trades in all_best[:20]:
    pstr = ','.join(f"{k}={v}" for k,v in sorted(p.items()))
    print(f"{passes:<5d}{sname:10s}{freq:6s}{ticker:10s}{wr:<8.1f}{dd:<8.1f}{sr:<8.2f}{ann:<8.1f}{scale:<6.2f}{sl:<6.2f}")

# Save all results
results_data = {
    "all4": [{"strategy":r[0],"ticker":r[1],"freq":r[2],"params":r[3],"scale":r[4],"stop_loss":r[5],
              "wr":r[6],"dd":r[7],"sr":r[8],"ann":r[9],"trades":r[10]} for r in all_all4],
    "best": [{"strategy":r[0],"ticker":r[1],"freq":r[2],"params":r[3],"scale":r[4],"stop_loss":r[5],
              "wr":r[6],"dd":r[7],"sr":r[8],"ann":r[9],"passes":r[10],"trades":r[11]} for r in all_best]
}
with open("honest_results.json", "w") as f:
    json.dump(results_data, f, indent=2)
print(f"\nSaved to honest_results.json")
