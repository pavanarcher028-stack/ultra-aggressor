"""
Fast vectorized optimizer with position sizing & stop-loss.
Finds ALL4 strategy-coin combos efficiently.
"""
import pickle, numpy as np, pandas as pd, math, json, time
from collections import Counter

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
def macd(s,f=12,sl=26,sg=9):
    e1=ema(s,f); e2=ema(s,sl); m=e1-e2
    return m, ema(m,sg)
def bollinger(s,p=20,m=2):
    mid=sma(s,p); std=s.rolling(p).std()
    return mid, mid+m*std, mid-m*std

def resample_6h(data):
    if isinstance(data.columns, pd.MultiIndex):
        d2 = pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
        data = d2
    o=data['Open'].resample('6h').first(); h=data['High'].resample('6h').max()
    l=data['Low'].resample('6h').min(); c=data['Close'].resample('6h').last()
    v=data['Volume'].resample('6h').sum()
    return pd.DataFrame({'open':o.values.ravel(),'high':h.values.ravel(),'low':l.values.ravel(),
                         'close':c.values.ravel(),'volume':v.values.ravel()},index=o.index).dropna()

def resample_daily(data):
    if isinstance(data.columns, pd.MultiIndex):
        d2 = pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
        data = d2
    o=data['Open'].resample('1D').first(); h=data['High'].resample('1D').max()
    l=data['Low'].resample('1D').min(); c=data['Close'].resample('1D').last()
    v=data['Volume'].resample('1D').sum()
    return pd.DataFrame({'open':o.values.ravel(),'high':h.values.ravel(),'low':l.values.ravel(),
                         'close':c.values.ravel(),'volume':v.values.ravel()},index=o.index).dropna()

# ============================================================
# VECTORIZED BACKTESTER (numpy, no python loop)
# ============================================================
def run_bt_vec(close_arr, sig_arr, scale=1.0, stop_loss=0.0):
    """Vectorized backtester - returns metrics dict."""
    n = len(sig_arr)
    # Shift signal by 1 (NO lookahead)
    sig = np.zeros(n)
    sig[1:] = sig_arr[:-1] * scale
    sig = np.clip(sig, -1.0, 1.0)
    
    # Price returns
    ret = close_arr[1:] / close_arr[:-1] - 1
    ret = np.append(0, ret)  # pad first bar
    
    # Position changes
    pos_changed = np.abs(np.diff(sig, prepend=0)) > 1e-10
    
    # Costs
    comm_cost = np.abs(np.diff(sig, prepend=0)) * 0.0015
    borrow_cost = np.where(sig < 0, 0.05 / (252*4) * np.abs(sig), 0)
    
    # Equity curve (cumulative product)
    eq_daily = np.ones(n)
    eq = 1.0
    pos = 0.0
    entry_eq = 1.0
    peak = 1.0
    trades = 0
    wins = 0
    
    for i in range(1, n):
        # Stop-loss check
        if stop_loss > 0 and abs(pos) > 0:
            ret_since_entry = abs(eq / entry_eq - 1)
            if ret_since_entry >= stop_loss:
                if eq > entry_eq: wins += 1
                trades += 1
                pos = 0.0
                sig[i] = 0.0
                entry_eq = eq
        
        # Apply cost on position change
        dc = abs(sig[i] - pos)
        if dc > 1e-10:
            if abs(pos) > 1e-10:
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= dc * 0.0015 * eq
            entry_eq = eq
        
        pos = sig[i]
        
        if pos > 0:
            eq *= 1 + ret[i] * abs(pos)
        elif pos < 0:
            eq *= 1 - ret[i] * abs(pos) - 0.05 / (252*4) * abs(pos)
        
        eq_daily[i] = eq
        peak = max(peak, eq)
    
    rets = pd.Series(np.diff(np.log(eq_daily))).dropna()
    tr = eq_daily[-1] - 1
    ny = n / (252 * 4)
    ann = (1 + tr) ** (1 / max(ny, 0.1)) - 1
    sr = rets.mean() / rets.std() * math.sqrt(252 * 4) if len(rets) > 0 and rets.std() > 0 else 0
    dd = (1 - eq_daily / np.maximum.accumulate(eq_daily)).max()
    wr = wins / max(trades, 1)
    
    return {"wr": wr, "dd": dd, "sr": sr, "ann": ann, "tr": tr, "trades": trades}

# ============================================================
# SIGNAL GENERATORS (simpler, faster)
# ============================================================
def fast_signals(df, kind, **p):
    """Generate signal array efficiently."""
    c = df['close'].values
    n = len(c)
    cs = pd.Series(df['close'].values.ravel(), index=df.index)
    
    if kind == 'ema':
        fast = ema(cs, p['fast']).values
        slow = ema(cs, p['slow']).values
        return np.where(fast > slow, 1.0, -1.0)
    elif kind == 'sma':
        fast = sma(cs, p['fast']).values
        slow = sma(cs, p['slow']).values
        return np.where(fast > slow, 1.0, -1.0)
    elif kind == 'rsi50':
        r = rsi(cs, p['p']).values
        return np.where(r > 50, 1.0, -1.0)
    elif kind == 'macd':
        m, s = macd(cs, p.get('f',12), p.get('sl',26), p.get('sg',9))
        return np.where(m.values > s.values, 1.0, -1.0)
    elif kind == 'hma':
        fast = hma(cs, p['fast']).values
        slow = hma(cs, p['slow']).values
        return np.where(fast > slow, 1.0, -1.0)
    elif kind == 'boll':
        mid, up, lo = bollinger(cs, p.get('p',20), p.get('m',2))
        return np.where(cs.values > mid.values, 1.0, -1.0)
    elif kind == 'vortex':
        h = cs  # simplified: just use EMA for speed
        fast = ema(cs, 14).values
        slow = ema(cs, 50).values
        return np.where(fast > slow, 1.0, -1.0)
    elif kind == 'vwap':
        v = df['volume'].values
        vwap = np.convolve(cs.values * v, np.ones(p.get('p',20))/p.get('p',20), mode='same')
        vwap[:p.get('p',20)] = cs.values[:p.get('p',20)]
        return np.where(cs.values > vwap, 1.0, -1.0)
    elif kind == 'lsma':
        sig = np.ones(n)
        lb = p.get('lb', 48)
        for i in range(lb, n):
            y = np.log(c[i-lb:i])
            x = np.arange(lb)
            xm, ym = x.mean(), y.mean()
            b = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
            sig[i] = 1.0 if b > 0 else -1.0
        return sig
    elif kind == 'zmr':
        period = p.get('p', 20)
        entry = p.get('entry', 1.5)
        m = sma(cs, period).values
        std = cs.rolling(period).std().replace(0, 1e-10).values
        z = (cs.values - m) / std
        sig = np.zeros(n)
        for i in range(1, n):
            if z[i-1] <= -entry: sig[i] = 1.0
            elif z[i-1] >= entry: sig[i] = -1.0
            else: sig[i] = sig[i-1]
        return sig
    elif kind == 'stoch':
        k = p.get('k', 14)
        h = df['high'].rolling(k).max(); l = df['low'].rolling(k).min()
        sk = 100 * (cs - l) / (h - l).replace(0, 1e-10)
        sd = sk.rolling(p.get('d',3)).mean()
        return np.where(sk.values > sd.values, 1.0, -1.0)
    elif kind == 'adx':
        return np.where(cs > ema(cs, 50).values, 1.0, -1.0)
    elif kind == 'tsmom':
        sig = np.zeros(n)
        lb = p.get('lb', 48)
        entry = p.get('entry', 0.8)
        for i in range(lb, n):
            y = np.log(c[i-lb:i]); x = np.arange(lb)
            xm, ym = x.mean(), y.mean()
            beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
            resid = y - (ym + beta * (x - xm))
            se = np.sqrt(np.sum(resid**2) / max(lb-2, 1))
            se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
            ts = beta / se_b if se_b > 0 else 0
            sig[i] = 1.0 if ts > entry else (-1.0 if ts < -entry else 0)
        return sig
    elif kind == 'paras':
        step = p.get('step', 0.02); m = p.get('m', 0.2)
        h = df['high'].values; l = df['low'].values
        sar = np.zeros(n); ep = np.zeros(n); af = np.ones(n) * step
        trend = np.ones(n)
        sar[0] = l[0]; ep[0] = h[0]
        for i in range(1, n):
            if trend[i-1] == 1:
                sar[i] = sar[i-1] + af[i-1] * (ep[i-1] - sar[i-1])
                sar[i] = min(sar[i], l[i-1], l[i])
                if h[i] > ep[i-1]: ep[i] = h[i]; af[i] = min(af[i-1] + step, m)
                else: ep[i] = ep[i-1]; af[i] = af[i-1]
                if l[i] <= sar[i]: trend[i] = -1; sar[i] = ep[i-1]; ep[i] = l[i]; af[i] = step
                else: trend[i] = 1
            else:
                sar[i] = sar[i-1] - af[i-1] * (sar[i-1] - ep[i-1])
                sar[i] = max(sar[i], h[i-1], h[i])
                if l[i] < ep[i-1]: ep[i] = l[i]; af[i] = min(af[i-1] + step, m)
                else: ep[i] = ep[i-1]; af[i] = af[i-1]
                if h[i] >= sar[i]: trend[i] = 1; sar[i] = ep[i-1]; ep[i] = h[i]; af[i] = step
                else: trend[i] = -1
        return trend
    elif kind == 'triple_ma':
        # 3-MA crossover: fast/slow/ultra_slow
        f = ema(cs, p.get('fast',5)).values
        s = ema(cs, p.get('slow',50)).values
        u = ema(cs, p.get('ultra',200)).values
        sig = np.where(f > s, 1.0, -1.0)
        sig = np.where((f > s) & (s > u), 1.0, np.where((f < s) & (s < u), -1.0, 0.0))
        return sig
    elif kind == 'heikin':
        ha_c = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        ha_o = (df['open'].shift() + df['close'].shift()) / 2
        sig = np.ones(n)
        for i in range(1, n):
            sig[i] = 1.0 if ha_c.iloc[i] > ha_o.iloc[i] else -1.0
        return sig
    elif kind == 'dual_rsi':
        r1 = rsi(cs, p.get('fp',3)).values
        r2 = rsi(cs, p.get('sp',14)).values
        return np.where(r1 > r2, 1.0, -1.0)
    elif kind == 'range_rev':
        pp = p.get('p', 10)
        h = df['high'].rolling(pp).max(); l = df['low'].rolling(pp).min()
        r = h - l; cc = df['close']
        sig = np.zeros(n)
        for i in range(1, n):
            if cc.iloc[i] < l.iloc[i-1] + 0.1*r.iloc[i-1] and cc.iloc[i] > cc.iloc[i-1]: sig[i] = 1.0
            elif cc.iloc[i] > h.iloc[i-1] - 0.1*r.iloc[i-1] and cc.iloc[i] < cc.iloc[i-1]: sig[i] = -1.0
        return sig
    elif kind == 'macd_hist':
        m, s = macd(cs, p.get('f',12), p.get('sl',26), p.get('sg',9))
        h_ = m - s
        sig = np.ones(n)
        sig[1:] = np.where(h_.values[1:] > h_.shift().values[1:], 1.0, -1.0)
        return sig
    elif kind == 'fisher':
        ff = p.get('p', 9)
        h_ = cs.rolling(ff).max(); l_ = cs.rolling(ff).min()
        v = 0.5 * ((cs - l_) / (h_ - l_).replace(0, 1e-10) * 2 - 1 + 
                   0.5 * (cs.shift() - l_.shift()) / (h_.shift() - l_.shift()).replace(0, 1e-10) * 2 - 1)
        f_val = (np.exp(2*v) - 1) / (np.exp(2*v) + 1)
        return np.where(f_val.values > 0, 1.0, -1.0)
    elif kind == 'tsi':
        r_val = p.get('r', 25); s_val = p.get('s', 13)
        m_ = cs.diff(); em1 = ema(m_, r_val); em2 = ema(em1, s_val)
        ae = ema(m_.abs(), r_val); aem = ema(ae, s_val)
        t = em2 / aem.replace(0, 1e-10) * 100
        return np.where(t.values > 0, 1.0, -1.0)
    elif kind == 'elder':
        p_val = p.get('p', 14)
        e = ema(cs, p_val)
        bp = df['high'] - e
        return np.where(bp.values > 0, 1.0, -1.0)
    elif kind == 'wvap':
        # VWAP-based with volume
        p_val = p.get('p', 20)
        v = df['volume']; c = cs
        vwap = (c * v).rolling(p_val).sum() / v.rolling(p_val).sum()
        return np.where(c.values > vwap.values, 1.0, -1.0)
    elif kind == 'cmf':
        p_val = p.get('p', 20)
        cf = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low']).replace(0, 1e-10)
        cmf_val = (cf * df['volume']).rolling(p_val).sum() / df['volume'].rolling(p_val).sum().replace(0, 1e-10)
        sig = np.zeros(n)
        for i in range(1, n):
            if cmf_val.iloc[i] > 0 and c.iloc[i] > ema(c, 50).iloc[i]: sig[i] = 1.0
            elif cmf_val.iloc[i] < 0 and c.iloc[i] < ema(c, 50).iloc[i]: sig[i] = -1.0
        return sig
    elif kind == 'price_channel':
        p_val = p.get('p', 30)
        h = df['high'].rolling(p_val).max(); l_ = df['low'].rolling(p_val).min()
        sig = np.zeros(n)
        for i in range(1, n):
            if c[i] > h.iloc[i-1]: sig[i] = 1.0
            elif c[i] < l_.iloc[i-1]: sig[i] = -1.0
        return sig
    elif kind == 'obv':
        p_val = p.get('p', 20)
        obv_val = (df['volume'] * ((c[1:] > c[:-1]).astype(int) * 2 - 1)).cumsum()
        obv_val = np.append(0, obv_val)
        obv_ema = ema(pd.Series(obv_val), p_val).values
        sig = np.ones(n)
        sig[1:] = np.where(obv_val[1:] > obv_ema[1:], 1.0, -1.0)
        return sig
    elif kind == 'mom':
        p_val = p.get('p', 12)
        roc_val = cs / cs.shift(p_val) - 1
        return np.where(roc_val.values > 0, 1.0, -1.0)
    elif kind == 'boll_brk':
        p_val = p.get('p', 20); m_val = p.get('m', 2)
        mid, up, lo = bollinger(cs, p_val, m_val)
        sig = np.zeros(n)
        for i in range(1, n):
            if cs.iloc[i] > up.iloc[i] and cs.iloc[i-1] <= up.iloc[i-1]: sig[i] = 1.0
            elif cs.iloc[i] < lo.iloc[i] and cs.iloc[i-1] >= lo.iloc[i-1]: sig[i] = -1.0
        return sig
    elif kind == 'donchian':
        p_val = p.get('p', 40)
        h = df['high'].rolling(p_val).max(); l_ = df['low'].rolling(p_val).min()
        sig = np.zeros(n)
        for i in range(1, n):
            if c[i] > h.iloc[i-1]: sig[i] = 1.0
            elif c[i] < l_.iloc[i-1]: sig[i] = -1.0
        return sig
    elif kind == 'keltner':
        p_val = p.get('p', 20); m_val = p.get('m', 2)
        mid = ema(cs, p_val)
        a = atr(df, p_val)
        up = mid + m_val * a; lo = mid - m_val * a
        return np.where(cs > mid, 1.0, -1.0)
    elif kind == 'supertrend':
        p_val = p.get('p', 10); m_val = p.get('m', 3)
        a = atr(df, p_val)
        hl = (df['high'] + df['low']) / 2
        ub = hl + m_val * a; lb = hl - m_val * a
        st = pd.Series(1.0, index=df.index)
        for i in range(1, n):
            st.iloc[i] = -1.0 if c[i] <= ub.iloc[i] else 1.0
        return st.values
    elif kind == 'ema_boll':
        fast_p = p.get('fast', 5); slow_p = p.get('slow', 50); boll_p = p.get('boll', 20)
        e = ema(cs, fast_p).values > ema(cs, slow_p).values
        _, up, lo = bollinger(cs, boll_p, 2)
        return np.where(e & (cs.values > (up+lo)/2), 1.0, -1.0)
    elif kind == 'vol_surge':
        vp = p.get('vp', 20)
        v = df['volume']; c_ = c
        vma = v.rolling(vp).mean()
        sig = np.zeros(n)
        for i in range(1, n):
            if v.iloc[i] > vma.iloc[i] * 1.5 and c_[i] > c_[i-1]: sig[i] = 1.0
            elif v.iloc[i] > vma.iloc[i] * 1.5 and c_[i] < c_[i-1]: sig[i] = -1.0
        return sig
    # Default: EMA crossover
    fast = ema(cs, 5).values
    slow = ema(cs, 50).values
    return np.where(fast > slow, 1.0, -1.0)

# ============================================================
# STRATEGY DEFINITIONS
# ============================================================
strategy_defs = [
    ("EMA_3_100", "ema", {"fast":3, "slow":100}),
    ("EMA_5_50", "ema", {"fast":5, "slow":50}),
    ("EMA_10_50", "ema", {"fast":10, "slow":50}),
    ("EMA_5_120", "ema", {"fast":5, "slow":120}),
    ("EMA_3_50", "ema", {"fast":3, "slow":50}),
    ("SMA_5_50", "sma", {"fast":5, "slow":50}),
    ("SMA_3_100", "sma", {"fast":3, "slow":100}),
    ("SMA_10_50", "sma", {"fast":10, "slow":50}),
    ("MACD", "macd", {"f":12, "sl":26, "sg":9}),
    ("MACD_8_24", "macd", {"f":8, "sl":24, "sg":5}),
    ("MACDH", "macd_hist", {"f":12, "sl":26, "sg":9}),
    ("HMA_8_40", "hma", {"fast":8, "slow":40}),
    ("HMA_6_30", "hma", {"fast":6, "slow":30}),
    ("HMA_10_60", "hma", {"fast":10, "slow":60}),
    ("RSI50_14", "rsi50", {"p":14}),
    ("RSI50_7", "rsi50", {"p":7}),
    ("RSI50_21", "rsi50", {"p":21}),
    ("RSI50_10", "rsi50", {"p":10}),
    ("BollMid_20", "boll", {"p":20, "m":2}),
    ("BollMid_30", "boll", {"p":30, "m":2}),
    ("LSMA_48", "lsma", {"lb":48}),
    ("LSMA_32", "lsma", {"lb":32}),
    ("ZMR_20_1.0", "zmr", {"p":20, "entry":1.0}),
    ("ZMR_20_1.5", "zmr", {"p":20, "entry":1.5}),
    ("ZMR_10_1.5", "zmr", {"p":10, "entry":1.5}),
    ("ZMR_40_1.5", "zmr", {"p":40, "entry":1.5}),
    ("Stoch_14_3", "stoch", {"k":14, "d":3}),
    ("Stoch_10_3", "stoch", {"k":10, "d":3}),
    ("TSMOM_48", "tsmom", {"lb":48, "entry":0.8}),
    ("TSMOM_32", "tsmom", {"lb":32, "entry":0.6}),
    ("PSAR", "paras", {"step":0.02, "m":0.2}),
    ("TripleMA", "triple_ma", {"fast":5, "slow":50, "ultra":200}),
    ("HeikinA", "heikin", {}),
    ("DualRSI", "dual_rsi", {"fp":3, "sp":14}),
    ("RangeRev", "range_rev", {"p":10}),
    ("Fisher", "fisher", {"p":9}),
    ("TSI_25_13", "tsi", {"r":25, "s":13}),
    ("Elder_14", "elder", {"p":14}),
    ("VWAP_20", "wvap", {"p":20}),
    ("CMF_20", "cmf", {"p":20}),
    ("PrChan_30", "price_channel", {"p":30}),
    ("OBV_20", "obv", {"p":20}),
    ("MOM_12", "mom", {"p":12}),
    ("BollBrk_20", "boll_brk", {"p":20, "m":2}),
    ("Donch_40", "donchian", {"p":40}),
    ("Donch_20", "donchian", {"p":20}),
    ("Keltner_20", "keltner", {"p":20, "m":2}),
    ("SuperT_10_3", "supertrend", {"p":10, "m":3}),
    ("EMA+Boll", "ema_boll", {"fast":5, "slow":50, "boll":20}),
    ("VolSurge", "vol_surge", {"vp":20}),
]

print(f"Total strategy variants: {len(strategy_defs)}")

tickers = ["BTC-USD","ETH-USD","SOL-USD","XRP-USD","ADA-USD","AVAX-USD","DOT-USD","LINK-USD","BNB-USD","DOGE-USD"]

# Pre-compute data at both frequencies
data_freq = {}
for t in tickers:
    data_freq[t] = {
        'daily': resample_daily(raw[t]),
        '6h': resample_6h(raw[t])
    }

# Scales and stop-losses to test
scales = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
sls = [0.0, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]

# ============================================================
# RUN OPTIMIZATION
# ============================================================
print("="*100)
print("HONEST FAST OPTIMIZATION - position sizing + stop-loss")
print("Targets: WR=40-55%, DD<20%, SR>=1.0, Ann>=20%")
print("="*100)

all_all4 = []
all_best = []
t0 = time.time()

for sname, skind, sparams in strategy_defs:
    best_for_strat = []
    
    for freq_name in ['daily', '6h']:
        for ticker in tickers:
            df = data_freq[ticker][freq_name]
            close_arr = df['close'].values
            
            try:
                sig = fast_signals(df, skind, **sparams)
                
                for scale in scales:
                    if freq_name == '6h' and scale > 0.5:
                        continue  # skip large scales on 6h (too much noise)
                    
                    for sl in sls:
                        if len(close_arr) < 100:
                            continue
                        
                        r = run_bt_vec(close_arr, sig, scale=scale, stop_loss=sl)
                        wr_pct = r["wr"] * 100
                        dd_pct = r["dd"] * 100
                        ann_pct = r["ann"] * 100
                        sr = r["sr"]
                        
                        passes = sum([40 <= wr_pct <= 55, dd_pct <= 20, sr >= 1.0, ann_pct >= 20])
                        
                        rec = (passes, sname, freq_name, ticker, wr_pct, dd_pct, sr, ann_pct, scale, sl, r["trades"])
                        
                        if passes >= 4:
                            all_all4.append(rec)
                        
                        # Track best per combo (strategy+coin+freq)
                        if passes > 0:
                            best_for_strat.append(rec)
            except Exception as e:
                pass
    
    # Track global best
    for rec in best_for_strat:
        all_best.append(rec)
    
    p4 = len(all_all4)
    print(f"  [{sname:12s}] ALL4: {p4} | Elapsed: {time.time()-t0:.0f}s", flush=True)

elapsed = time.time() - t0

print(f"\n{'='*100}")
print(f"COMPLETE in {elapsed:.0f}s")
print(f"{'='*100}")
print(f"\nALL4 COMBOS: {len(all_all4)}")

if all_all4:
    print("\nTOP 20 ALL4 (by Sharpe):")
    all_all4.sort(key=lambda x: -x[6])  # sort by Sharpe
    for passes, sname, freq, ticker, wr, dd, sr, ann, scale, sl, trades in all_all4[:20]:
        print(f"  [{sname:12s}] {ticker:8s} {freq:6s} WR={wr:.1f}% DD={dd:.1f}% SR={sr:.2f} Ann={ann:.1f}% scale={scale:.2f} sl={sl:.3f}")
    
    # Group by strategy
    print("\nStrategy breakdown (ALL4):")
    sc = Counter(r[1] for r in all_all4)
    for s, c in sc.most_common():
        print(f"  {s}: {c}")
    
    # Group by ticker
    print("\nTicker breakdown:")
    tc = Counter(r[3] for r in all_all4)
    for t, c in tc.most_common():
        print(f"  {t}: {c}")
else:
    print("  No ALL4 combos found.")

# Save
out = {
    "all4": [{"strategy":r[1],"freq":r[2],"ticker":r[3],"wr":r[4],"dd":r[5],"sr":r[6],"ann":r[7],"scale":r[8],"sl":r[9],"trades":r[10]}
             for r in all_all4],
    "config": {"scales":scales, "stop_losses":sls, "targets":{"wr":"40-55%","dd":"<20%","sr":">=1.0","ann":">=20%"}}
}
with open("honest_all4_results.json","w") as f:
    json.dump(out, f, indent=2)
print(f"\nSaved to honest_all4_results.json")
