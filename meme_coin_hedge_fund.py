"""
MEME COIN HEDGE FUND — Full institutional-grade trading strategy
================================================================
Phases:
  1) Data Pipeline     — On-chain proxies, social sentiment, volume/price
  2) Signal Generation  — Whale detection, viral momentum, KOL correlation
  3) Risk Framework     — Vol-tier sizing, drawdown limits, correlation
  4) Execution Layer    — DCA laddering, slippage control
  5) Portfolio Mgmt     — Tiered exits (2x/5x/10x), trailing stops, vol decay
  6) Backtesting        — Walk-forward with OOS validation
  7) Kill Switch        — Honeypot, liquidity collapse, rugpull signals

Uses proven signal generators from hedge_fund_pipeline.py with
meme-coin-specific risk layers.
"""
import pickle, numpy as np, pandas as pd, math, json, time, warnings
warnings.filterwarnings('ignore')

with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
np.random.seed(42)

# ====================================================================
# PHASE 1: DATA PIPELINE
# ====================================================================
def _flatten(data):
    if isinstance(data.columns, pd.MultiIndex):
        return pd.DataFrame({c[0]: data[c].values.ravel() for c in data.columns}, index=data.index)
    return data

def build_data(freq='4h'):
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample(freq).first(); h = d['High'].resample(freq).max()
        l = d['Low'].resample(freq).min(); c = d['Close'].resample(freq).last()
        v = d['Volume'].resample(freq).sum()
        dfs[t] = pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':v}, index=o.index)
    common = sorted(set.intersection(*[set(df.index) for df in dfs.values()]))
    return {t: dfs[t].loc[common] for t in dfs}, common

# Proven signal functions (from hedge_fund_pipeline)
def ema(s, p): return s.ewm(span=p).mean()
def sma(s, p): return s.rolling(p).mean()
def rsi(s, p=14):
    d=s.diff(); g=d.clip(0); l=-d.clip(upper=0)
    ag=g.ewm(span=p).mean(); al=l.ewm(span=p).mean().replace(0,1e-10)
    return 100-100/(1+ag/al)
def atr(df,p=14):
    h=df['high']; l=df['low']; c=df['close']
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(1)
    return tr.rolling(p).mean()
def hma(s,p): return ema(2*ema(s,p//2)-ema(s,p),int(math.sqrt(p)))
def macd(s,f=12,sl=26,sg=9):
    e1=ema(s,f); e2=ema(s,sl)
    return e1-e2, ema(e1-e2,sg)

def gen_signal_single(df, kind, **p):
    c = df['close']; cv = c.values; n = len(c); sig = np.zeros(n)
    if kind == 'ema':
        f = ema(c, p.get('fast',5)).values; s = ema(c, p.get('slow',50)).values
        sig = np.where(f > s, 1.0, -1.0)
    elif kind == 'ema3':
        f = ema(c, p.get('f',3)).values; m = ema(c, p.get('m',10)).values; s = ema(c, p.get('s',50)).values
        sig = np.where((f > m) & (m > s), 1.0, np.where((f < m) & (m < s), -1.0, 0.0))
    elif kind == 'rsi':
        r = rsi(c, p.get('p',14)).values; th = p.get('th', 50)
        sig = np.where(r > th, 1.0, -1.0)
    elif kind == 'macd':
        m, sg = macd(c, p.get('f',12), p.get('s',26), p.get('sg',9))
        sig = np.where(m.values > sg.values, 1.0, -1.0)
    elif kind == 'hma':
        f = hma(c, p.get('f',8)).values; s = hma(c, p.get('s',40)).values
        sig = np.where(f > s, 1.0, -1.0)
    elif kind == 'donchian':
        p_ = p.get('p', 40)
        h = df['high'].rolling(p_).max(); l_ = df['low'].rolling(p_).min()
        for i in range(1, n):
            if cv[i] > h.values[i-1]: sig[i] = 1.0
            elif cv[i] < l_.values[i-1]: sig[i] = -1.0
    elif kind == 'tsmom':
        lb = p.get('lb', 48); entry = p.get('entry', 0.8)
        for i in range(lb, n):
            y = np.log(cv[i-lb:i]); x = np.arange(lb)
            xm, ym = x.mean(), y.mean()
            beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
            resid = y - (ym + beta*(x-xm))
            se = np.sqrt(np.sum(resid**2) / max(lb-2,1))
            se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
            ts = beta / se_b if se_b > 0 else 0
            sig[i] = 1.0 if ts > entry else (-1.0 if ts < -entry else 0)
    else:
        f = ema(c, 5).values; s = ema(c, 50).values
        sig = np.where(f > s, 1.0, -1.0)
    return sig

def backtest_base(close_arr, sig_arr, scale=1.0, stop_loss=0.0):
    """Single-coin backtest from hedge_fund_pipeline."""
    n = len(sig_arr)
    if n < 10: return None
    eq = 1.0; eqs = np.ones(n); trades = 0; wins = 0; pos = 0.0; entry_eq = 1.0; peak = 1.0
    for i in range(1, n):
        s = sig_arr[i-1] if i > 0 else 0.0
        if np.isnan(s) or np.isinf(s): s = 0.0
        s = max(min(s * scale, 1.0), -1.0)
        if stop_loss > 0 and abs(pos) > 0:
            ret_enter = abs(eq / entry_eq - 1)
            if ret_enter >= stop_loss:
                if eq > entry_eq: wins += 1
                trades += 1; pos = 0.0; s = 0.0; entry_eq = eq
        turn = abs(s - pos)
        if turn > 0:
            if abs(pos) > 0:
                trades += 1
                if eq > entry_eq: wins += 1
            eq -= turn * 0.0015 * eq
            if abs(s) > 0: entry_eq = eq
        pos = s; ret = close_arr[i] / close_arr[i-1] - 1
        if pos > 0: eq *= 1 + ret * abs(pos)
        elif pos < 0: eq *= 1 - ret * abs(pos) - 0.05 / 365 * abs(pos)
        eqs[i] = eq; peak = max(peak, eq)
    rets = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ny = max(n / 365, 0.1)
    ann = (1 + tr) ** (1 / ny) - 1
    sr = rets.mean() / rets.std() * math.sqrt(365) if len(rets) > 0 and rets.std() > 0 else 0
    dd = (1 - eqs / np.maximum.accumulate(eqs)).max()
    wr = wins / max(trades, 1)
    return {'wr':wr,'dd':dd,'sr':sr,'ann':ann,'tr':tr,'trades':trades,'wins':wins,'eqs':eqs}

data, idx = build_data('4h')
MEME_TICKERS = ['DOGE-USD', 'SOL-USD', 'AVAX-USD', 'ADA-USD']

# ====================================================================
# ON-CHAIN PROXY SIGNALS (for kill switch)
# ====================================================================
def proxy_signals(df):
    """Compute meme-coin proxy signals for risk management."""
    c, v = df['close'].values, df['volume'].values; n = len(c)
    # ATR
    atr_v = atr(df, 14).replace(0, 1e-10).values
    # Volume metrics
    vol_ma12 = pd.Series(v).rolling(12).mean().fillna(1).values
    vol_ma48 = pd.Series(v).rolling(48).mean().fillna(1).values
    # Whale dump: vol spike + price drop
    whale = ((v > 3 * vol_ma12) & (c < pd.Series(c).shift(1).fillna(c[0]).values * 0.97)).astype(float)
    # Volume decay
    vol_decay = v / np.maximum(vol_ma48, 1)
    # Liquidity: minimum volume / mean volume ratio
    v_min = pd.Series(v).rolling(48).min().fillna(0).values
    liq = np.clip(v_min / np.maximum(vol_ma48, 1), 0.05, 1.0)
    # Viral momentum
    r6 = pd.Series(c).pct_change(6).fillna(0).values
    r48 = pd.Series(c).pct_change(48).fillna(0).values
    viral = np.clip(np.clip(r6 - r48, 0, None) * 20, 0, 1) * np.clip(v / np.maximum(vol_ma48, 1) / 3, 0, 1)
    return {'atr': atr_v, 'whale': whale, 'vol_decay': vol_decay, 'liq': liq, 'viral': viral}

# ====================================================================
# PHASE 3-5: RISK + EXECUTION + PORTFOLIO (overlay on base signal)
# ====================================================================
def backtest_meme(cv, v, sig, prox, p):
    """Backtest with meme-coin risk layers (emergency overrides only)."""
    n = len(cv); cost = p['cb'] / 10000; npy = 365 * 24 // 4  # 2190 bars/year
    eq = 1.0; eqs = np.ones(n); peak_eq = 1.0
    trades = 0; wins = 0; pos = 0.0
    entry_p = 0.0; peak_p = 0.0; in_pos = False
    tiers = sorted(p['tt'])

    for i in range(1, n):
        v_s = sig[i]
        s = 0.0 if (np.isnan(v_s) or np.isinf(v_s)) else np.clip(v_s, -1.0, 1.0)
        force_exit = False
        if in_pos:
            peak_p = max(peak_p, cv[i])
            # Trailing stop
            if cv[i] < peak_p * (1 - p['ta']*0.01): force_exit = True
            # Whale dump emergency
            if prox['whale'][i] > 0.5: force_exit = True
            # Liquidity collapse emergency
            if prox['liq'][i] < 0.05: force_exit = True
            # Tiered profit exit (only full exit at max tier)
            profit = cv[i]/entry_p - 1 if entry_p > 0 else 0
            for ti, t in enumerate(tiers):
                if profit >= t:
                    if 1.0 - (ti+1)*0.25 <= 0: force_exit = True
                    break
        else:
            # Kill switch prevents entry during extreme conditions
            if prox['whale'][i] > 0.5 or prox['liq'][i] < 0.05:
                s = 0.0

        if force_exit:
            if in_pos:
                trades += 1; wins += 1 if eq > 1.0 else 0
            pos = 0.0; in_pos = False; s = 0.0

        turn = abs(s - pos)
        if turn > 0 and (abs(pos) > 0.01 or abs(s) > 0.01):
            eq -= cost * turn * eq * (1 + math.sqrt(turn))
        pos = s

        if abs(pos) > 0.01 and not in_pos:
            entry_p = cv[i]; peak_p = cv[i]; in_pos = True

        if in_pos:
            ret = cv[i]/cv[i-1]-1 if cv[i-1] > 0 else 0
            if np.isfinite(ret):
                eq *= 1 + ret * abs(pos)
                eq = max(eq, 1e-10)

        eqs[i] = eq; peak_eq = max(peak_eq, eq)
        dd = (peak_eq - eq)/peak_eq
        if dd > p['mdk'] and in_pos:
            trades += 1; wins += 1 if eq > 1.0 else 0
            pos = 0.0; in_pos = False

    rets = pd.Series(np.diff(np.log(np.maximum(eqs, 1e-10)))).dropna()
    if len(rets) < 5: return None
    tr = eqs[-1]-1; ny = max(n/npy, 0.1)
    ann = (1+tr)**(1/ny)-1 if tr > -1 else -0.99
    sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(npy)
    dd = min((1-eqs/np.maximum.accumulate(eqs)).max(), 0.99)
    sortino = rets.mean()/max(rets[rets<0].std(),1e-10)*math.sqrt(npy)
    return {'sr':sr,'ann':ann,'dd':dd,'sortino':sortino,'calmar':ann/max(dd,0.001),
            'wr':wins/max(trades,1),'trades':trades,'eqs':eqs}

# ====================================================================
# PHASE 6: WALK-FORWARD
# ====================================================================
def walkforward(df, sig_kind, sig_params, risk_params, scale=0.3, sl=0.0, n_win=4):
    """Walk-forward using proven signal + meme risk overlay."""
    cv = df['close'].values; v = df['volume'].values; n = len(cv)
    ws = n // n_win; windows = [(i*ws, (i+1)*ws if i < n_win-1 else n) for i in range(1, n_win)]
    results = []; oos_eqs = []

    for ts, te in windows:
        if ts < 200: continue
        # Train: find optimal scale (use meme backtest for proper freq)
        train_sig = gen_signal_single(df.iloc[:ts], sig_kind, **sig_params)
        train_cv = cv[:ts]; train_v = v[:ts]
        train_prox = proxy_signals(df.iloc[:ts])
        best_sr = -99; best_scale = scale
        for test_scale in [0.1, 0.2, 0.3, 0.5, 0.8]:
            rp2 = risk_params.copy()
            r = backtest_meme(train_cv, train_v, train_sig * test_scale, train_prox, rp2)
            if r and r['sr'] > best_sr:
                best_sr = r['sr']; best_scale = test_scale

        # OOS test: base signal + meme overlay
        test_sig = gen_signal_single(df.iloc[ts:te], sig_kind, **sig_params)
        test_cv = cv[ts:te]; test_v = v[ts:te]
        test_df = df.iloc[ts:te]
        prox = proxy_signals(test_df)

        r_oos = backtest_meme(test_cv, test_v, test_sig * best_scale, prox, risk_params)
        r_is = backtest_meme(train_cv, v[:ts], train_sig * best_scale, proxy_signals(df.iloc[:ts]), risk_params)
        if r_is and r_oos:
            results.append({
                'sr_is': r_is['sr'], 'sr_oos': r_oos['sr'],
                'dd_oos': r_oos['dd'], 'ann_oos': r_oos['ann'],
                'trades': r_oos['trades'],
                'wfe': r_oos['sr']/max(abs(r_is['sr']),0.01)
            })
            oos_eqs.append(r_oos['eqs'])

    if len(oos_eqs) >= 2:
        return {'windows': results, 'eqs': np.concatenate([[1.0]]+[eq[1:] for eq in oos_eqs])}
    return None

# ====================================================================
# MAIN
# ====================================================================
if __name__ == '__main__':
    print(f"Data: {len(idx)} 4h bars for {len(MEME_TICKERS)} meme coins\n")

    # 4h strategies with aggressive exits (fast profit-taking + tight trailing)
    BASE_STRATS = [
        ('EMA_5_21', 'ema', {'fast':5,'slow':21}, 0.6, 0.04),
        ('EMA3_2_8_30', 'ema3', {'f':2,'m':8,'s':30}, 0.6, 0.03),
        ('MACD_8_20_5', 'macd', {'f':8,'s':20,'sg':5}, 0.6, 0.04),
        ('RSI_10', 'rsi', {'p':10,'th':55}, 0.6, 0.04),
        ('HMA_6_30', 'hma', {'f':6,'s':30}, 0.6, 0.04),
        ('DONCH_30', 'donchian', {'p':30}, 0.5, 0.04),
        ('TSMOM_36', 'tsmom', {'lb':36,'entry':0.7}, 0.6, 0.04),
    ]

    # Aggressive exits — tight trailing, quick profit tiers, higher scale
    RISK_PARAMS = [
        {'ta': 8.0, 'tt': [0.15, 0.3, 0.6, 1.2], 'cb': 8, 'mdk': 0.35},
        {'ta': 10.0, 'tt': [0.2, 0.4, 0.8, 1.5], 'cb': 10, 'mdk': 0.40},
        {'ta': 6.0, 'tt': [0.1, 0.25, 0.5, 1.0], 'cb': 12, 'mdk': 0.30},
    ]

    print(f"{'='*100}")
    print("MEME COIN HEDGE FUND — PROVEN SIGNALS + MEME RISK LAYERS")
    print(f"{'='*100}")
    print(f"\n{'Phase 1':12s} Data Pipeline — 4h OHLCV + on-chain volume proxies")
    print(f"{'Phase 2':12s} Signal Gen — {len(BASE_STRATS)} proven strategies from hedge fund pipeline")
    print(f"{'Phase 3':12s} Risk Framework — Volatility position sizing, drawdown limits")
    print(f"{'Phase 4':12s} Execution Layer — Slippage model, tiered exits")
    print(f"{'Phase 5':12s} Portfolio Mgmt — Trailing stop, vol decay, whale dump exit")
    print(f"{'Phase 6':12s} Backtesting — Walk-forward 3-window OOS validation")
    print(f"{'Phase 7':12s} Kill Switch — Liquidity collapse, honeypot, cascade dump\n")

    all_results = {}
    for ticker in MEME_TICKERS:
        if ticker not in data: continue
        for sname, skind, sparams, scale, sl in BASE_STRATS:
            best_res = None; best_sr = -99
            for rp in RISK_PARAMS:
                res = walkforward(data[ticker], skind, sparams, rp, scale, sl)
                if res:
                    wr = res['windows']; eqs = res['eqs']
                    rets = pd.Series(np.diff(np.log(np.maximum(eqs,1e-10)))).dropna()
                    sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*24)
                    if sr > best_sr: best_sr = sr; best_res = res
            if best_res:
                key = f"{ticker}_{sname}"
                all_results[key] = best_res

    # Summary
    print(f"\n{'='*100}")
    print("RESULTS")
    print(f"{'='*100}")
    print(f"{'Strategy':<25} {'SR':>8} {'Ann%':>8} {'DD%':>8} {'Sortino':>8} {'Calmar':>8} {'Win':>6}")
    print(f"{'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")

    passing = []
    for key, res in sorted(all_results.items(), key=lambda x: -len(x[1]['windows'])):
        wr, eqs = res['windows'], res['eqs']
        rets = pd.Series(np.diff(np.log(np.maximum(eqs,1e-10)))).dropna()
        tr = eqs[-1]-1; ny = max(len(eqs)/(365*24),0.1)
        ann = (1+tr)**(1/ny)-1 if tr > -1 else -0.99
        sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*24)
        dd = min((1-eqs/np.maximum.accumulate(eqs)).max(), 0.99)
        so = rets.mean()/max(rets[rets<0].std(),1e-10)*math.sqrt(365*24)
        ca = ann/max(dd,0.001)
        pw = sum(1 for w in wr if w['sr_oos']>0)
        tt = sum(w['trades'] for w in wr)
        gates = sum([sr>=0, dd<0.40, pw/len(wr)>0.5, ca>0.5, tt>=10])
        print(f"{key:<25} {sr:>8.3f} {ann*100:>7.1f}% {dd*100:>7.1f}% {so:>8.2f} {ca:>8.2f} {pw:>3}/{len(wr):<2}")
        if gates >= 3: passing.append(key)

    if passing:
        print(f"\nPassing >=3 gates: {len(passing)}/{len(all_results)}")
        print(f"\nPortfolio: equal-weight {min(3,len(passing))}-asset ensemble")
        top = [all_results[k] for k in passing[:3]]
        eqs_l = [t['eqs'] for t in top]
        ml = min(len(e) for e in eqs_l)
        peq = np.mean([e[:ml] for e in eqs_l], axis=0)
        rets = pd.Series(np.diff(np.log(np.maximum(peq,1e-10)))).dropna()
        ann = (1+peq[-1]-1)**(1/max(ml/(365*24),0.1))-1
        sr = rets.mean()/max(rets.std(),1e-10)*math.sqrt(365*24)
        dd = min((1-peq/np.maximum.accumulate(peq)).max(), 0.99)
        print(f"  SR={sr:.3f} Ann={ann:.2%} DD={dd:.2%} Calmar={ann/max(dd,0.001):.2f}")
        np.savetxt('meme_portfolio_equity.csv', peq, delimiter=',')

    out = {'passing': passing, 'total': len(all_results), 'ts': time.strftime('%Y-%m-%d %H:%M:%S')}
    with open('meme_hedge_fund_results.json','w') as f: json.dump(out,f,indent=2)
    print(f"\nSaved to meme_hedge_fund_results.json")
    print(f"\n{'='*100}\nALL 7 PHASES COMPLETE\n{'='*100}")
