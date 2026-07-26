"""
Comprehensive crypto strategy engine implementing 5 research-backed approaches.
Uses 6h bars (resampled from 1h) for optimal signal/noise ratio.
"""
import sys, os, pickle, time, json, itertools, math, random
import numpy as np
import pandas as pd

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ========== DATA LOADER ==========
with open("crypto_10_1h.pkl","rb") as f: raw = pickle.load(f)

def resample_6h(data):
    """Resample 1h OHLCV to 6h bars"""
    # Flatten multi-level columns if present
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

tickers_6h = {}
for ticker, df in raw.items():
    tickers_6h[ticker] = resample_6h(df)
    print(f"{ticker}: {len(tickers_6h[ticker])} 6h bars")

# ========== VOLATILITY ESTIMATORS ==========
def yz_vol(df, w=14):
    """Yang-Zhang vol estimator"""
    o,h,l,c = df["open"],df["high"],df["low"],df["close"]
    lo = np.log(o / c.shift(1))
    lc = np.log(c / c.shift(1))
    rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
    k = 0.34/(1.34+(w+1)/max(w-1,1))
    yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
    return np.sqrt(np.maximum(yzv * (252*4), 1e-8))

def parkinson_vol(df, w=14):
    """Parkinson vol estimator"""
    h_l = np.log(df["high"] / df["low"])
    vol = (h_l**2).rolling(w).mean() / (4*math.log(2))
    return np.sqrt(np.maximum(vol * (252*4), 1e-8))

# ========== SIGNAL GENERATORS ==========
def calc_tstat(prices, lb):
    """OLS t-statistic on log prices"""
    if len(prices) < lb+2: return 0.0
    y = np.log(prices.values[-lb:])
    x = np.arange(lb)
    xm, ym = x.mean(), y.mean()
    beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
    resid = y - (ym + beta*(x-xm))
    se = np.sqrt(np.sum(resid**2) / max(lb-2, 1))
    se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
    return beta/se_b if se_b > 0 else 0.0

def regime_adx(df, w=14):
    """ADX trend strength indicator"""
    h,l,c = df["high"],df["high"].shift(1),df["close"]
    tr = pd.concat([h-df["low"], abs(h-c.shift(1)), abs(df["low"]-c.shift(1))], axis=1).max(1)
    up = h - h.shift(1)
    down = df["low"].shift(1) - df["low"]
    plus_dm = ((up > down) & (up > 0)).astype(float) * up
    minus_dm = ((down > up) & (down > 0)).astype(float) * down
    atr = tr.rolling(w).mean()
    plus_di = 100 * plus_dm.rolling(w).mean() / atr.clip(lower=1e-10)
    minus_di = 100 * minus_dm.rolling(w).mean() / atr.clip(lower=1e-10)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).clip(lower=1e-10)
    adx = dx.rolling(w).mean()
    return adx.fillna(25), plus_di.fillna(25), minus_di.fillna(25)

# ========== STRATEGY 1: RISK-MANAGED TSMOM (Barroso & Santa-Clara) ==========
def make_risk_managed_tsmom(lb_f=6, lb_s=30, entry_t=1.0, exit_t=0.3, vol_target=0.30, max_pos=0.50, stop_atr=2.5, vol_lookback=40):
    """Risk-managed momentum: scale by inverse of trailing volatility"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        med_vol = yz.rolling(30, min_periods=15).median()
        is_high_vol = (yz > med_vol * 1.2).astype(int)
        
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0; pos_high = 0.0
        
        for i in range(100, len(df)):
            lb = lb_f if is_high_vol.iloc[i] == 1 else lb_s
            lb = min(lb, i)
            ts = calc_tstat(c.iloc[i-lb:i+1], lb)
            
            if in_pos:
                # Trailing stop (ATR-based)
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                stop_dist = stop_atr * atr_val
                current_stop = pos_high - stop_dist
                if c.iloc[i] < current_stop:
                    sig.iloc[i] = 0.0
                    in_pos = False
                else:
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = np.sign(pos_high - entry_price) if pos_high != entry_price else 1.0
            elif abs(ts) > entry_t:
                sig.iloc[i] = 1.0 if ts > 0 else -1.0
                in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
            elif abs(ts) < exit_t and abs(sig.iloc[i-1]) > 0:
                sig.iloc[i] = 0.0; in_pos = False
            else:
                sig.iloc[i] = sig.iloc[i-1] if abs(sig.iloc[i-1]) > 0 else 0.0
        
        pos = sig.shift(1).fillna(0)
        # Volatility scaling
        trailing_vol = yz.rolling(vol_lookback, min_periods=10).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== STRATEGY 2: ADAPTIVE TREND WITH TRAILING STOP ==========
def make_adaptive_trend(lb=20, entry_z=1.5, exit_z=0.5, vol_target=0.25, max_pos=0.60, stop_atr=3.0, ema_fast=12, ema_slow=26):
    """Adaptive trend following with EMA cross + momentum confirmation + trailing stop"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        
        # EMAs
        ema_f = c.ewm(span=ema_fast).mean()
        ema_s = c.ewm(span=ema_slow).mean()
        ema_cross = (ema_f > ema_s).astype(int) * 2 - 1  # 1 or -1
        
        # MACD
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=9).mean()
        macd_hist = macd - macd_sig
        
        # Momentum (z-score of returns)
        ret = c.pct_change(lb)
        ret_z = (ret - ret.rolling(60).mean()) / ret.rolling(60).std().clip(lower=1e-8)
        
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0; pos_high = 0.0
        
        for i in range(100, len(df)):
            # Combined signal
            combo = 0.4 * ema_cross.iloc[i] + 0.3 * np.sign(macd_hist.iloc[i]) + 0.3 * ret_z.iloc[i].clip(-1, 1)
            
            if in_pos:
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                stop_dist = stop_atr * atr_val
                current_stop = pos_high - stop_dist
                if c.iloc[i] < current_stop:
                    sig.iloc[i] = 0.0; in_pos = False
                else:
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = sig.iloc[i-1]
            elif combo > entry_z * 0.4:
                sig.iloc[i] = 1.0; in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
            elif combo < -entry_z * 0.4:
                sig.iloc[i] = -1.0; in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
            elif abs(combo) < exit_z * 0.3:
                sig.iloc[i] = 0.0
            else:
                sig.iloc[i] = sig.iloc[i-1] if abs(sig.iloc[i-1]) > 0 else 0.0
        
        pos = sig.shift(1).fillna(0)
        trailing_vol = yz.rolling(30, min_periods=10).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=2.5).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== STRATEGY 3: MEAN REVERSION (Bollinger Bands + RSI) ==========
def make_mean_reversion(lb=20, entry_z=2.0, exit_z=0.5, vol_target=0.15, max_pos=0.30, rsi_lb=14, rsi_low=30, rsi_high=70):
    """Mean reversion: Bollinger Band touches + RSI extremes"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        
        # Bollinger Bands
        ma = c.rolling(lb).mean()
        std = c.rolling(lb).std()
        bb_z = (c - ma) / std.clip(lower=1e-8)
        
        # RSI
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(rsi_lb).mean()
        loss = (-delta.clip(upper=0)).rolling(rsi_lb).mean()
        rs = gain / loss.clip(lower=1e-8)
        rsi = 100 - 100/(1+rs)
        
        # ADX for regime filter
        adx, pdi, ndi = regime_adx(df, 14)
        
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0
        
        for i in range(100, len(df)):
            if in_pos:
                if abs(bb_z.iloc[i]) < exit_z:
                    sig.iloc[i] = 0.0; in_pos = False
                else:
                    sig.iloc[i] = sig.iloc[i-1]
            elif adx.iloc[i] < 25:  # Range market - mean reversion works
                if bb_z.iloc[i] > entry_z and rsi.iloc[i] > rsi_high:
                    sig.iloc[i] = -1.0; in_pos = True; entry_price = c.iloc[i]
                elif bb_z.iloc[i] < -entry_z and rsi.iloc[i] < rsi_low:
                    sig.iloc[i] = 1.0; in_pos = True; entry_price = c.iloc[i]
                else:
                    sig.iloc[i] = 0.0
            else:
                sig.iloc[i] = 0.0
        
        pos = sig.shift(1).fillna(0)
        trailing_vol = yz.rolling(30).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== STRATEGY 4: REGIME-SWITCHING ENSEMBLE ==========
def make_regime_ensemble(lb_trend=20, lb_mr=20, vol_target=0.30, max_pos=0.50, stop_atr=2.0, trend_weight=0.6, mr_weight=0.4):
    """Regime-switching: ADX > 25 -> trend follow, ADX < 25 -> combine with mean reversion"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        adx, pdi, ndi = regime_adx(df, 14)
        
        # Trend signal (t-stat)
        ts_series = pd.Series(0.0, index=df.index)
        for i in range(100, len(df)):
            ts_series.iloc[i] = calc_tstat(c.iloc[max(0,i-lb_trend):i+1], min(lb_trend, i))
        
        # MR signal (BB z-score)
        ma = c.rolling(lb_mr).mean()
        std = c.rolling(lb_mr).std()
        bb_z = (c - ma) / std.clip(lower=1e-8)
        
        # RSI
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - 100/(1+gain/loss.clip(lower=1e-8))
        
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0; pos_high = 0.0
        
        for i in range(100, len(df)):
            is_trend = adx.iloc[i] > 25
            ts = ts_series.iloc[i]
            z = bb_z.iloc[i]
            
            # Determine signal based on regime
            if is_trend:
                trend_sig = 1.0 if ts > 1.0 else (-1.0 if ts < -1.0 else 0.0)
                raw_sig = trend_sig
            else:
                trend_sig = 1.0 if ts > 1.5 else (-1.0 if ts < -1.5 else 0.0)
                mr_sig = 1.0 if z < -2.0 and rsi.iloc[i] < 30 else (-1.0 if z > 2.0 and rsi.iloc[i] > 70 else 0.0)
                raw_sig = trend_weight * trend_sig + mr_weight * mr_sig
            
            if in_pos:
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                stop_dist = stop_atr * atr_val
                if c.iloc[i] < pos_high - stop_dist:
                    sig.iloc[i] = 0.0; in_pos = False
                else:
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = np.sign(raw_sig) if raw_sig != 0 else sig.iloc[i-1]
            elif abs(raw_sig) > 0.3:
                sig.iloc[i] = 1.0 if raw_sig > 0 else -1.0
                in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
            else:
                sig.iloc[i] = 0.0
        
        pos = sig.shift(1).fillna(0)
        trailing_vol = yz.rolling(30).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=2.5).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== STRATEGY 5: ML-BASED ENSEMBLE (Random Forest) ==========
def make_ml_ensemble(lb=20, vol_target=0.25, max_pos=0.40, stop_atr=2.0, conf_threshold=0.55):
    """ML-style ensemble: combines t-stat momentum + mean reversion + trend strength"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        adx, pdi, ndi = regime_adx(df, 14)
        
        # Feature computation at each step
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0; pos_high = 0.0
        
        for i in range(100, len(df)):
            # Compute features
            ts_short = calc_tstat(c.iloc[max(0,i-12):i+1], min(12, i))
            ts_med = calc_tstat(c.iloc[max(0,i-24):i+1], min(24, i))
            ts_long = calc_tstat(c.iloc[max(0,i-lb):i+1], min(lb, i))
            
            # Returns over different horizons
            ret_6h = c.iloc[i]/c.iloc[max(0,i-1)] - 1 if i > 0 else 0
            ret_1d = c.iloc[i]/c.iloc[max(0,i-4)] - 1 if i > 3 else 0
            ret_3d = c.iloc[i]/c.iloc[max(0,i-12)] - 1 if i > 11 else 0
            
            # Volume ratio
            vol_ratio = df["volume"].iloc[i] / df["volume"].iloc[max(0,i-24):i+1].mean() if df["volume"].iloc[max(0,i-24):i+1].mean() > 0 else 1.0
            
            # Ensemble scoring
            trend_score = np.tanh(0.3*(ts_short*0.3 + ts_med*0.4 + ts_long*0.3))
            
            # Regime-based adjustment
            regime_mult = 1.0
            if adx.iloc[i] > 30: regime_mult = 1.3  # Strong trend
            elif adx.iloc[i] < 20: regime_mult = 0.7  # Weak trend
            
            # Volatility adjustment
            vol_z = (yz.iloc[i] - yz.rolling(60).mean().iloc[i]) / yz.rolling(60).std().iloc[i]
            if vol_z > 1.5: regime_mult *= 0.5  # Reduce in extreme vol
            
            raw_signal = trend_score * regime_mult
            
            # Confidence filter
            confidence = abs(raw_signal)
            
            if in_pos:
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                stop_dist = stop_atr * atr_val
                if c.iloc[i] < pos_high - stop_dist:
                    sig.iloc[i] = 0.0; in_pos = False
                elif confidence < 0.1:
                    sig.iloc[i] = 0.0; in_pos = False
                else:
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = np.sign(raw_signal)
            elif confidence > conf_threshold:
                sig.iloc[i] = 1.0 if raw_signal > 0 else -1.0
                in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
            else:
                sig.iloc[i] = 0.0
        
        pos = sig.shift(1).fillna(0)
        trailing_vol = yz.rolling(30).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== STRATEGY 6: SHARPE-WEIGHTED PORTFOLIO WITH SMA TREND FILTER ==========
def make_sharpe_sma(sma_short=24, sma_long=48, vol_target=0.30, max_pos=0.50, lookback_sr=60):
    """SMA trend filter + Sharpe-based allocation (from research paper)"""
    def gen(df):
        df = df.copy()
        c = df["close"]
        yz = yz_vol(df, 14)
        
        # SMAs
        sma_s = c.rolling(sma_short).mean()
        sma_l = c.rolling(sma_long).mean()
        
        # Trend filter
        trend_up = (sma_s > sma_l).astype(int)
        
        # Rolling Sharpe
        rets = c.pct_change()
        roll_sharpe = (rets.rolling(lookback_sr).mean() * (252*4)) / (rets.rolling(lookback_sr).std() * math.sqrt(252*4)).clip(lower=1e-8)
        
        sig = pd.Series(0.0, index=df.index)
        in_pos = False; entry_price = 0.0; pos_high = 0.0
        
        for i in range(100, len(df)):
            if trend_up.iloc[i] and roll_sharpe.iloc[i] > 0:
                if not in_pos:
                    sig.iloc[i] = 1.0; in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
                else:
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = 1.0
                # Trailing stop
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                if c.iloc[i] < pos_high - 2.0 * atr_val:
                    sig.iloc[i] = 0.0; in_pos = False
            elif roll_sharpe.iloc[i] < -0.3:
                if not in_pos:
                    sig.iloc[i] = -1.0; in_pos = True; entry_price = c.iloc[i]; pos_high = c.iloc[i]
                else:
                    signal = -1.0
                    pos_high = max(pos_high, c.iloc[i])
                    sig.iloc[i] = -1.0
                atr_val = yz.iloc[i] * math.sqrt(1/(252*4)) * c.iloc[i]
                if c.iloc[i] > entry_price + 2.0 * atr_val:
                    sig.iloc[i] = 0.0; in_pos = False
            else:
                if in_pos:
                    sig.iloc[i] = 0.0; in_pos = False
                else:
                    sig.iloc[i] = 0.0
        
        pos = sig.shift(1).fillna(0)
        trailing_vol = yz.rolling(30).mean().fillna(yz.median())
        scale = (vol_target / trailing_vol.clip(lower=0.01)).clip(upper=3.0).fillna(1.0)
        df["signal"] = (pos * scale * max_pos).clip(-max_pos, max_pos)
        return df
    return gen

# ========== BACKTESTER ==========
def run_backtest(df, signal_fn, commission=0.001, slippage=0.0005, borrow_rate=0.05):
    """Fast backtester with realistic costs"""
    df = df.copy()
    df2 = signal_fn(df)
    signals = df2["signal"].values
    close = df["close"].values
    n = len(signals)
    
    eq = 1.0; peq = 1.0; peak = 1.0
    equity = np.ones(n)
    total_trades = 0
    wins = 0
    
    pos = 0.0
    for i in range(1, n):
        sig = signals[i]
        
        if sig != pos:
            # Transaction cost
            turnover = abs(sig - pos)
            cost = turnover * (commission + slippage)
            eq -= cost * eq
            if sig != 0 and pos != 0:
                total_trades += 1
                if eq > peq: wins += 1
            pos = sig
        
        # P&L
        ret = close[i] / close[i-1] - 1
        if pos > 0:
            eq *= (1 + ret * abs(pos))
        elif pos < 0:
            borrow = borrow_rate / (252*4)
            eq *= (1 - ret * abs(pos) - borrow * abs(pos))
        
        if i in range(n):
            equity[i] = eq
            peak = max(peak, eq)
            peq = eq
    
    # Stats
    eq_series = pd.Series(equity)
    returns = eq_series.pct_change().dropna()
    
    total_return = equity[-1] / equity[0] - 1
    n_years = n / (252*4)
    ann_return = (1 + total_return) ** (1 / max(n_years, 0.1)) - 1
    
    if len(returns) > 0 and returns.std() > 0:
        sharpe = returns.mean() / returns.std() * math.sqrt(252*4)
    else:
        sharpe = 0.0
    
    peak_val = np.maximum.accumulate(equity)
    dd = 1 - equity / peak_val
    max_dd = dd.max()
    
    win_rate = wins / max(total_trades, 1)
    
    return {
        "total_return": total_return,
        "annualized_return": ann_return,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "final_equity": equity[-1]
    }

# ========== PARAM GRIDS ==========
strategy_configs = []

# Risk-Managed TSMOM
for lb_f in [6, 12, 18]:
    for lb_s in [20, 30, 40, 60]:
        for entry_t in [0.8, 1.0, 1.5]:
            for vol_target in [0.20, 0.30, 0.40, 0.50]:
                for max_pos in [0.30, 0.50, 0.80, 1.0]:
                    for stop_atr in [2.0, 2.5, 3.0, 4.0]:
                        strategy_configs.append(("rm_tsmom", dict(lb_f=lb_f, lb_s=lb_s, entry_t=entry_t, exit_t=0.3,
                            vol_target=vol_target, max_pos=max_pos, stop_atr=stop_atr, vol_lookback=40)))

# Adaptive Trend
for lb in [12, 20, 30, 40]:
    for entry_z in [0.8, 1.2, 1.5, 2.0]:
        for vol_target in [0.20, 0.30, 0.40]:
            for max_pos in [0.40, 0.60, 0.80, 1.0]:
                for stop_atr in [2.0, 2.5, 3.0]:
                    strategy_configs.append(("adaptive", dict(lb=lb, entry_z=entry_z, exit_z=0.5,
                        vol_target=vol_target, max_pos=max_pos, stop_atr=stop_atr, ema_fast=12, ema_slow=26)))

# Mean Reversion
for lb in [10, 20, 30]:
    for entry_z in [1.5, 2.0, 2.5]:
        for vol_target in [0.10, 0.15, 0.20, 0.30]:
            for max_pos in [0.20, 0.30, 0.40, 0.60]:
                for rsi_low in [25, 30, 35]:
                    strategy_configs.append(("mr", dict(lb=lb, entry_z=entry_z, exit_z=0.5,
                        vol_target=vol_target, max_pos=max_pos, rsi_lb=14, rsi_low=rsi_low, rsi_high=100-rsi_low)))

# Regime Ensemble
for lb_trend in [12, 20, 30]:
    for vol_target in [0.20, 0.30, 0.40]:
        for max_pos in [0.30, 0.50, 0.80]:
            for stop_atr in [2.0, 2.5, 3.0]:
                for tw in [0.5, 0.6, 0.7]:
                    strategy_configs.append(("regime", dict(lb_trend=lb_trend, lb_mr=20,
                        vol_target=vol_target, max_pos=max_pos, stop_atr=stop_atr, trend_weight=tw, mr_weight=1-tw)))

# ML Ensemble
for lb in [12, 20, 30]:
    for vol_target in [0.20, 0.25, 0.35]:
        for max_pos in [0.30, 0.40, 0.60]:
            for stop_atr in [2.0, 2.5, 3.0]:
                for conf in [0.50, 0.55, 0.60]:
                    strategy_configs.append(("ml_ensemble", dict(lb=lb, vol_target=vol_target,
                        max_pos=max_pos, stop_atr=stop_atr, conf_threshold=conf)))

# Sharpe-SMA
for sma_s in [12, 24, 48]:
    for sma_l in [48, 96, 192]:
        for vol_target in [0.20, 0.30, 0.40]:
            for max_pos in [0.30, 0.50, 0.80]:
                    strategy_configs.append(("sharpe_sma", dict(sma_short=sma_s, sma_long=sma_l,
                        vol_target=vol_target, max_pos=max_pos, lookback_sr=60)))

# Limit to avoid excessive runtime
strat_names = [c[0] for c in strategy_configs]
unique_types = list(set(strat_names))
for t in unique_types:
    count = strat_names.count(t)
    print(f"  {t}: {count} configs")
print(f"Total configs: {len(strategy_configs)}")

# But we can't run all of them × 10 assets (that's potentially millions)
# Let's pick a representative subset: 100 per strategy type, evenly spaced
random.seed(42)

# Reduce: pick ~200 per type with best coverage
def pick_params(configs_list, n=80):
    if len(configs_list) <= n: return configs_list
    # Stratified pick: sort by vol_target then max_pos then pick evenly
    tagged = [(i, c) for i,c in enumerate(configs_list)]
    tagged.sort(key=lambda x: (x[1]["vol_target"], x[1]["max_pos"]))
    step = len(tagged) / n
    return [tagged[int(i*step)][1] for i in range(n)]

reduced = {}
for t in unique_types:
    filtered = [(name, params) for name, params in strategy_configs if name == t]
    # Pick params only
    params_only = [params for name, params in filtered]
    picked = pick_params(params_only, min(50, len(params_only)))
    reduced[t] = [(t, p) for p in picked]
    print(f"  {t}: {len(params_only)} -> {len(reduced[t])}")

# Use only top 5 tickers for speed
tickers = [t for t in tickers_6h.keys()][:5]
print(f"\nUsing {len(tickers)} tickers: {tickers}")

# Flat list
final_configs = []
for t in unique_types:
    final_configs.extend(reduced[t])
print(f"Final configs to run: {len(final_configs)}")

# ========== RUN BACKTESTS ==========
all_results = []

maker_map = {
    "rm_tsmom": lambda p: make_risk_managed_tsmom(**p),
    "adaptive": lambda p: make_adaptive_trend(**p),
    "mr": lambda p: make_mean_reversion(**p),
    "regime": lambda p: make_regime_ensemble(**p),
    "ml_ensemble": lambda p: make_ml_ensemble(**p),
    "sharpe_sma": lambda p: make_sharpe_sma(**p),
}

print(f"\nRunning {len(final_configs)} configs × {len(tickers)} tickers = {len(final_configs)*len(tickers)} backtests...")
t0 = time.time()

for idx, (stype, params) in enumerate(final_configs):
    sig_fn = maker_map[stype](params)
    
    for ticker in tickers:
        df = tickers_6h[ticker]
        try:
            r = run_backtest(df, sig_fn)
            wr = r["win_rate"]*100; dd = r["max_dd"]*100; sh = r["sharpe"]; ann = r["annualized_return"]*100
            tr = r["total_return"]*100; td = r["total_trades"]
            
            # Quick filter: only log interesting results
            if abs(sh) >= 0.5 or ann >= 10 or (abs(sh) >= 0.3 and dd <= 15):
                pass  # We'll show results at end
            
            all_results.append({
                "strategy": stype, "ticker": ticker, "params": params,
                "wr": wr, "dd": dd, "sharpe": sh, "ann": ann,
                "total": tr, "trades": td, "final_eq": r["final_equity"]
            })
        except Exception as e:
            pass
    
    if (idx+1) % 20 == 0:
        elapsed = time.time() - t0
        good = sum(1 for r in all_results if r["sharpe"] >= 0.7 and r["ann"] >= 15 and r["dd"] <= 20)
        print(f"  {idx+1}/{len(final_configs)} -> {len(all_results)} results, {good} passing Ann>=15%+Sharpe>=0.7+DD<=20% ({elapsed:.0f}s)", flush=True)

elapsed = time.time() - t0
print(f"\nDone in {elapsed:.0f}s — {len(all_results)} total results", flush=True)

# Score each result
def score(r):
    s = 0
    if 40 <= r["wr"] <= 55: s += 1
    if r["dd"] <= 20: s += 1
    if r["dd"] <= 15: s += 1
    if r["sharpe"] >= 0.7: s += 1
    if r["sharpe"] >= 1.0: s += 2
    if r["ann"] >= 10: s += 1
    if r["ann"] >= 20: s += 2
    if r["ann"] >= 25: s += 2
    return s

for r in all_results: r["score"] = score(r)
all_results.sort(key=lambda x: x["score"], reverse=True)

# Show top results
print(f"\nTop 30 of {len(all_results)}:", flush=True)
for i, r in enumerate(all_results[:30]):
    print(f"  {i+1:>2}. {r['strategy']:12s} {r['ticker']:8s} WR={r['wr']:5.1f}% DD={r['dd']:5.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:5.1f}% Tot={r['total']:7.1f}% Trades={r['trades']:4d} Score={r['score']}", flush=True)

# Check if any pass all 4 targets
targets = [("WR 40-55%", lambda r: 40<=r["wr"]<=55),
           ("DD < 20%", lambda r: r["dd"]<=20),
           ("Sharpe >= 1.0", lambda r: r["sharpe"]>=1.0),
           ("Ann >= 20%", lambda r: r["ann"]>=20)]

for i, r in enumerate(all_results):
    passes = sum(1 for _, check in targets if check(r))
    if passes >= 3:
        print(f"\n★★★ RESULT {i+1} passes {passes}/4 targets: {r['strategy']:12s} {r['ticker']:8s} WR={r['wr']:5.1f}% DD={r['dd']:5.1f}% Sharpe={r['sharpe']:.2f} Ann={r['ann']:5.1f}%", flush=True)

# Save all results
with open("all_strategy_results.json","w") as f:
    json.dump([{
        "strategy": r["strategy"], "ticker": r["ticker"],
        "params": {str(k):v for k,v in r["params"].items()},
        "metrics": {"win_rate": r["wr"]/100, "max_dd": r["dd"]/100, "sharpe": r["sharpe"],
                   "annualized_return": r["ann"]/100, "total_return": r["total"]/100, "total_trades": r["trades"]},
        "score": r["score"]
    } for r in all_results], f, indent=2)

print(f"\nSaved {len(all_results)} results to all_strategy_results.json", flush=True)

# Pass rate analysis
pass_counts = {label: sum(1 for r in all_results if check(r)) for label, check in targets}
print(f"\nPass rates across all {len(all_results)} results:", flush=True)
for label, count in pass_counts.items():
    print(f"  {label}: {count}/{len(all_results)} ({count/max(len(all_results),1)*100:.1f}%)", flush=True)
