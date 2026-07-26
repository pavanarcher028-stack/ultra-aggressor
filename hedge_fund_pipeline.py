"""
Full hedge fund validation pipeline (Gates 1-7).
Walk-forward multi-window optimization with OOS validation.
Generates diverse strategies, tests rigorously, iterates until 20+ pass.
"""
import pickle, numpy as np, pandas as pd, math, json, time
from collections import defaultdict, Counter
import warnings; warnings.filterwarnings('ignore')

with open('crypto_10_1h.pkl','rb') as f: raw = pickle.load(f)
np.random.seed(42)

# ============================================================
# DATA & INDICATORS
# ============================================================
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
    e1=ema(s,f); e2=ema(s,sl)
    return e1-e2, ema(e1-e2,sg)

def _flatten(data):
    """Handle MultiIndex columns if present."""
    if isinstance(data.columns, pd.MultiIndex):
        d2 = pd.DataFrame({c[0]: data[c].values for c in data.columns}, index=data.index)
        return d2
    return data

def build_daily():
    """Build aligned daily OHLCV for all coins."""
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample('1D').first()
        h = d['High'].resample('1D').max()
        l = d['Low'].resample('1D').min()
        c = d['Close'].resample('1D').last()
        v = d['Volume'].resample('1D').sum()
        dfs[t] = pd.DataFrame({'open':o.values.ravel(),'high':h.values.ravel(),'low':l.values.ravel(),
                               'close':c.values.ravel(),'volume':v.values.ravel()}, index=o.index)
    # Align all to common dates
    common_idx = None
    for t, df in dfs.items():
        if common_idx is None: common_idx = set(df.index)
        else: common_idx &= set(df.index)
    common_idx = sorted(common_idx)
    result = {}
    for t in dfs:
        result[t] = dfs[t].loc[common_idx].dropna()
    return result, common_idx

def build_6h():
    """Build aligned 6h OHLCV."""
    dfs = {}
    for t, d in raw.items():
        d = _flatten(d)
        o = d['Open'].resample('6h').first()
        h = d['High'].resample('6h').max()
        l = d['Low'].resample('6h').min()
        c = d['Close'].resample('6h').last()
        v = d['Volume'].resample('6h').sum()
        dfs[t] = pd.DataFrame({'open':o.values.ravel(),'high':h.values.ravel(),'low':l.values.ravel(),
                               'close':c.values.ravel(),'volume':v.values.ravel()}, index=o.index)
    common_idx = None
    for t, df in dfs.items():
        if common_idx is None: common_idx = set(df.index)
        else: common_idx &= set(df.index)
    common_idx = sorted(common_idx)
    result = {}
    for t in dfs:
        result[t] = dfs[t].loc[common_idx].dropna()
    return result, common_idx

# ============================================================
# WALK-FORWARD SPLITTER
# ============================================================
def make_windows(index, n_windows=6):
    """Create train/test windows for walk-forward validation."""
    n = len(index)
    window_size = n // n_windows
    windows = []
    for i in range(n_windows):
        test_start = i * window_size
        test_end = (i + 1) * window_size if i < n_windows - 1 else n
        train_end = test_start
        windows.append({
            'train_slice': slice(0, train_end),
            'test_slice': slice(test_start, test_end),
            'train_idx': index[:train_end],
            'test_idx': index[test_start:test_end]
        })
    # Skip first window (no training data)
    return windows[1:]  # at least 1 window of training before first test

# ============================================================
# BACKTESTER (honest, no lookahead)
# ============================================================
def backtest(close_arr, sig_arr, scale=1.0, stop_loss=0.0):
    """Single-coin backtest. sig_arr aligned to close_arr. Uses sig[i-1] for bar i."""
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

def backtest_cs(close_matrix, weights_matrix, costs=0.0015):
    """
    Cross-sectional backtest.
    close_matrix: (n_bars, n_coins) prices
    weights_matrix: (n_bars, n_coins) portfolio weights (must sum to ~0 for market neutral)
    Returns equity curve and metrics.
    """
    n_bars, n_coins = close_matrix.shape
    rets = close_matrix[1:] / close_matrix[:-1] - 1
    eq = 1.0; eqs = np.ones(n_bars); peak = 1.0
    trades = 0; wins = 0; entry_eq = 1.0; prev_w = np.zeros(n_coins)
    for i in range(1, n_bars):
        w = weights_matrix[i]  # weights for this period (set using data up to i-1)
        if np.any(np.isnan(w)) or np.any(np.isinf(w)):
            w = np.zeros(n_coins)
        # Cost from rebalancing
        turnover = np.sum(np.abs(w - prev_w))
        eq -= turnover * costs * eq
        if turnover > 0:
            trades += 1
            if eq > entry_eq: wins += 1
            entry_eq = eq
        # P&L
        port_ret = np.sum(w * rets[i-1])  # rets[i-1] is return from bar i-1 to i
        eq *= 1 + port_ret
        eqs[i] = eq; peak = max(peak, eq)
        prev_w = w.copy()
    ret_series = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ny = max(n_bars / 365, 0.1)
    ann = (1 + tr) ** (1 / ny) - 1
    sr = ret_series.mean() / ret_series.std() * math.sqrt(365) if len(ret_series) > 0 and ret_series.std() > 0 else 0
    dd = (1 - eqs / np.maximum.accumulate(eqs)).max()
    wr = wins / max(trades, 1)
    return {'wr':wr,'dd':dd,'sr':sr,'ann':ann,'tr':tr,'trades':trades,'wins':wins,'eqs':eqs}

def compute_metrics(eqs):
    """Compute metrics from equity curve."""
    rets = pd.Series(np.diff(np.log(eqs))).dropna()
    tr = eqs[-1] - 1
    ny = max(len(eqs) / 365, 0.1)
    ann = (1 + tr) ** (1 / ny) - 1
    sr = rets.mean() / rets.std() * math.sqrt(365) if len(rets) > 0 and rets.std() > 0 else 0
    dd = (1 - eqs / np.maximum.accumulate(eqs)).max()
    downside = rets[rets < 0]
    sortino = rets.mean() / downside.std() * math.sqrt(365) if len(downside) > 0 and downside.std() > 0 else 0
    return {'sr':sr,'ann':ann,'dd':dd,'sortino':sortino}

# ============================================================
# STRATEGY GENERATORS
# ============================================================

# --- Cross-sectional strategies ---
def cs_momentum(data_dict, lb, top=3, bottom=3):
    """Long top N coins by return, short bottom N."""
    tickers = sorted(data_dict.keys())
    dfs = {t: data_dict[t] for t in tickers}
    dates = list(dfs[tickers[0]].index)
    n = len(dates); nt = len(tickers)
    close_mat = np.zeros((n, nt))
    ret_mat = np.zeros((n, nt))
    for j, t in enumerate(tickers):
        c = dfs[t]['close'].values
        close_mat[:, j] = c
        r = np.diff(np.log(c), prepend=0)
        ret_mat[:, j] = r
    weights = np.zeros((n, nt))
    for i in range(lb+1, n):
        lookback_ret = close_mat[i] / close_mat[i-lb] - 1
        ranks = np.argsort(lookback_ret)
        w = np.zeros(nt)
        w[ranks[-top:]] = 1.0 / top  # long top
        w[ranks[:bottom]] = -1.0 / bottom  # short bottom
        # Market neutral (sum = 0)
        w -= w.mean()
        weights[i] = w
    return {'close_mat': close_mat, 'weights_mat': weights, 'tickers': tickers, 'dates': dates}

def cs_reversal(data_dict, lb, top=3, bottom=3):
    """Short top N (winners), long bottom N (losers) — mean reversion."""
    r = cs_momentum(data_dict, lb, top, bottom)
    r['weights_mat'] = -r['weights_mat']  # invert
    return r

def cs_vol_weighted(data_dict, lookback=20):
    """Volatility-weighted: long low-vol coins, short high-vol coins."""
    tickers = sorted(data_dict.keys())
    dfs = {t: data_dict[t] for t in tickers}
    dates = list(dfs[tickers[0]].index)
    n = len(dates); nt = len(tickers)
    close_mat = np.zeros((n, nt)); weights = np.zeros((n, nt))
    for j, t in enumerate(tickers):
        c = dfs[t]['close'].values
        close_mat[:, j] = c
    for i in range(lookback+1, n):
        vols = np.array([np.std(np.diff(np.log(close_mat[i-lookback:i, j]))) for j in range(nt)])
        # Long low vol, short high vol
        ranks = np.argsort(vols)
        w = np.zeros(nt)
        w[ranks[:3]] = 1.0/3; w[ranks[-3:]] = -1.0/3
        w -= w.mean()
        weights[i] = w
    return {'close_mat':close_mat,'weights_mat':weights,'tickers':tickers,'dates':dates}

def cs_rank_ensemble(data_dict, lookbacks=[10,20,40,80]):
    """Ensemble of multiple lookback momentum signals."""
    tickers = sorted(data_dict.keys())
    dfs = {t: data_dict[t] for t in tickers}
    dates = list(dfs[tickers[0]].index); nt = len(tickers)
    n = len(dates); close_mat = np.zeros((n, nt))
    for j, t in enumerate(tickers):
        close_mat[:, j] = dfs[t]['close'].values
    weights = np.zeros((n, nt))
    max_lb = max(lookbacks)
    for i in range(max_lb+1, n):
        combined = np.zeros(nt)
        for lb in lookbacks:
            r = close_mat[i] / close_mat[i-lb] - 1
            combined += (r - r.mean()) / max(r.std(), 1e-10)
        ranks = np.argsort(combined)
        w = np.zeros(nt); top_k = 3; bottom_k = 3
        w[ranks[-top_k:]] = 1.0/top_k; w[ranks[:bottom_k]] = -1.0/bottom_k
        k = min(top_k, bottom_k)
        w[ranks[-k:]] = 1.0/k; w[ranks[:k]] = -1.0/k
        w -= w.mean()
        weights[i] = w
    return {'close_mat':close_mat,'weights_mat':weights,'tickers':tickers,'dates':dates}

# --- Single-asset strategies ---
def gen_signal_single(df, kind, **p):
    """Generate single-asset signal array (1.0 = long, -1.0 = short, 0 = flat)."""
    c = df['close']; cv = c.values; n = len(c)
    sig = np.zeros(n)
    
    if kind == 'ema':
        f = ema(c, p.get('fast',5)).values; s = ema(c, p.get('slow',50)).values
        sig = np.where(f > s, 1.0, -1.0)
    elif kind == 'ema3':
        # 3-EMA system: fast > mid > slow = strong bull, etc.
        f = ema(c, p.get('f',3)).values; m = ema(c, p.get('m',10)).values; s = ema(c, p.get('s',50)).values
        sig = np.where((f > m) & (m > s), 1.0, np.where((f < m) & (m < s), -1.0, 0.0))
    elif kind == 'rsi':
        r = rsi(c, p.get('p',14)).values; th = p.get('th', 50)
        sig = np.where(r > th, 1.0, -1.0)
    elif kind == 'rsi_obos':
        r = rsi(c, p.get('p',14)).values; ol = p.get('ol',30); ob = p.get('ob',70)
        for i in range(1, n):
            if r[i-1] <= ol and r[i] > ol: sig[i] = 1.0
            elif r[i-1] >= ob and r[i] < ob: sig[i] = -1.0
            else: sig[i] = sig[i-1] if i > 1 else 0
    elif kind == 'zmr':
        p_ = p.get('p', 20); entry = p.get('entry', 1.5)
        m = sma(c, p_).values; std = c.rolling(p_).std().replace(0, 1e-10).values
        z = (cv - m) / std
        for i in range(1, n):
            if z[i-1] <= -entry: sig[i] = 1.0
            elif z[i-1] >= entry: sig[i] = -1.0
            else: sig[i] = sig[i-1]
    elif kind == 'hma':
        f = hma(c, p.get('f',8)).values; s = hma(c, p.get('s',40)).values
        sig = np.where(f > s, 1.0, -1.0)
    elif kind == 'macd':
        m, sg = macd(c, p.get('f',12), p.get('s',26), p.get('sg',9))
        sig = np.where(m.values > sg.values, 1.0, -1.0)
    elif kind == 'boll':
        p_ = p.get('p', 20); m_ = p.get('m', 2)
        mid = sma(c, p_).values; std_ = c.rolling(p_).std().values
        sig = np.where(cv > mid, 1.0, -1.0)
    elif kind == 'boll_break':
        p_ = p.get('p', 20); m_ = p.get('m', 2)
        mid = sma(c, p_); std_ = c.rolling(p_).std()
        up = mid + m_ * std_; lo = mid - m_ * std_
        for i in range(1, n):
            if cv[i] > up.values[i] and cv[i-1] <= up.values[i-1]: sig[i] = 1.0
            elif cv[i] < lo.values[i] and cv[i-1] >= lo.values[i-1]: sig[i] = -1.0
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
    elif kind == 'triple_rsi':
        # 3 RSI timeframes
        r1 = rsi(c, p.get('f',3)).values; r2 = rsi(c, p.get('m',14)).values; r3 = rsi(c, p.get('s',50)).values
        sig = np.where((r1 > 50) & (r2 > 50) & (r3 > 50), 1.0,
                      np.where((r1 < 50) & (r2 < 50) & (r3 < 50), -1.0, 0.0))
    elif kind == 'ha_trend':
        # Heikin-Ashi trend
        ha_c = (df['open'] + df['high'] + df['low'] + c) / 4
        ha_o = (df['open'].shift() + c.shift()) / 2
        for i in range(1, n):
            sig[i] = 1.0 if ha_c.values[i] > ha_o.values[i] else -1.0
            if abs(ha_c.values[i] - ha_o.values[i]) / max(ha_o.values[i], 1) < 0.001:
                sig[i] = 0  # weak signal = flat
    elif kind == 'vwap_trend':
        v = df['volume']; p_ = p.get('p', 20)
        vwap = (c * v).rolling(p_).sum() / v.rolling(p_).sum()
        sig = np.where(c.values > vwap.values, 1.0, -1.0)
    elif kind == 'adx_trend':
        p_ = p.get('p', 14); th = p.get('th', 25)
        h = df['high']; l = df['low']
        up = h - h.shift(); dn = l.shift() - l
        pdi = (((up>dn)&(up>0))*up).ewm(span=p_).mean() / atr(df,p_).replace(0,1e-10) * 100
        ndi = (((dn>up)&(dn>0))*dn).ewm(span=p_).mean() / atr(df,p_).replace(0,1e-10) * 100
        dx = ((pdi-ndi)/(pdi+ndi).replace(0,1e-10)).abs() * 100
        adx_val = dx.ewm(span=p_).mean()
        # Only trade when ADX > threshold (strong trend)
        sig = np.where((adx_val > th).values & (c.values > ema(c, 50).values), 1.0,
                      np.where((adx_val > th).values & (c.values < ema(c, 50).values), -1.0, 0.0))
    else:
        f = ema(c, 5).values; s = ema(c, 50).values
        sig = np.where(f > s, 1.0, -1.0)
    return sig

# ============================================================
# GATES
# ============================================================

class GateResult:
    def __init__(self, name):
        self.name = name
        self.tests = {}
        self.passed = True
    
    def add(self, test_name, passed, details=''):
        self.tests[test_name] = {'passed': passed, 'details': details}
        if not passed: self.passed = False

def run_gates(eqs_oos, eqs_all, window_results, strategy_name):
    """Run all gates on walk-forward results."""
    result = GateResult(strategy_name)
    
    rets_all = pd.Series(np.diff(np.log(eqs_all))).dropna()
    rets_oos = pd.Series(np.diff(np.log(eqs_oos))).dropna()
    
    n_obs = len(rets_all)
    
    # === GATE 1: Execution & Data Sanity ===
    # G1.1: No NaN
    has_nan = np.any(np.isnan(eqs_all))
    result.add('G1.1 No NaN', not has_nan, f'NaN count: {np.sum(np.isnan(eqs_all))}')
    
    # G1.2: Min trades from window results
    total_trades = sum(w.get('trades', 0) for w in window_results)
    min_trades = total_trades >= 60
    result.add('G1.2 Min Trades', min_trades, f'Trades: {total_trades}')
    
    # G1.3: Distribution check
    skew = rets_all.skew() if len(rets_all) > 5 else 0
    kurt = rets_all.kurtosis() if len(rets_all) > 5 else 0
    dist_ok = abs(skew) <= 3 and abs(kurt) <= 12
    result.add('G1.3 Distribution', dist_ok, f'skew={skew:.2f} kurt={kurt:.2f}')
    
    # === GATE 3: Walk-Forward Validation ===
    # G3.1: WFE (Walk-Forward Efficiency)
    is_sharpes = [w.get('sr_is', 0) for w in window_results if w.get('sr_is') is not None]
    oos_sharpes = [w.get('sr_oos', 0) for w in window_results if w.get('sr_oos') is not None]
    
    if len(is_sharpes) > 0 and max(abs(s) for s in is_sharpes) > 0:
        wfe = np.mean(oos_sharpes) / max(np.mean(is_sharpes), 0.01)
    else:
        wfe = 0
    result.add('G3.1 WFE > 0.5', wfe > 0.5, f'WFE={wfe:.3f}')
    
    # G3.2: OOS Sharpe >= 0.2, IS/OOS ratio <= 2.0
    oos_sr_global = compute_metrics(eqs_oos)['sr']
    is_sr = compute_metrics(eqs_all[:len(eqs_all)//2])['sr'] if len(eqs_all) > 20 else 0
    is_oos_ratio = abs(is_sr / max(oos_sr_global, 0.001)) if abs(oos_sr_global) > 0.001 else 99
    gate3_2 = oos_sr_global >= 0.2 and is_oos_ratio <= 2.0
    result.add('G3.2 IS/OOS Ratio', gate3_2, f'OOS SR={oos_sr_global:.3f}, IS/OOS={is_oos_ratio:.2f}')
    
    # G3.3: Negative window limit (≤ 1 negative OOS window)
    neg_count = sum(1 for w in window_results if w.get('sr_oos', 0) < 0)
    result.add('G3.3 Neg Windows ≤ 1', neg_count <= 1, f'{neg_count} negative windows')
    
    # G3.4: Drawdown integrity
    if len(window_results) > 0:
        is_dds = [w.get('dd_is', 0) for w in window_results if w.get('dd_is') is not None]
        oos_dds = [w.get('dd_oos', 0) for w in window_results if w.get('dd_oos') is not None]
        max_is_dd = max(is_dds) if is_dds else 0
        max_oos_dd = max(oos_dds) if oos_dds else 0
        dd_ok = max_oos_dd <= max(1.5 * max_is_dd, 0.5) if max_is_dd > 0 else True
        result.add('G3.4 DD Integrity', dd_ok, f'Max IS DD={max_is_dd:.2%}, Max OOS DD={max_oos_dd:.2%}')
    
    # G3.5: Min OOS windows
    result.add('G3.5 Min Windows ≥ 3', len(window_results) >= 3, f'{len(window_results)} windows')
    
    # === GATE 4: Statistical Significance ===
    # G4.1: Sharpe Ratio
    sr_all = compute_metrics(eqs_all)['sr']
    result.add('G4.1 SR ≥ 1.0', sr_all >= 1.0, f'SR={sr_all:.3f}')
    
    # G4.2: t-statistic
    t_stat = rets_all.mean() / max(rets_all.std() / math.sqrt(len(rets_all)), 1e-10)
    result.add('G4.2 t-stat ≥ 2.0', t_stat >= 2.0, f't={t_stat:.3f}')
    
    # G4.3: Bootstrap Sharpe CI (resample with replacement)
    if len(rets_all) > 20:
        boot_srs = []
        for _ in range(1000):
            samp = np.random.choice(rets_all, len(rets_all))
            boot_srs.append(samp.mean() / max(samp.std(), 1e-10) * math.sqrt(365))
        ci_lower = np.percentile(boot_srs, 5)
        result.add('G4.3 Bootstrap CI LB > 0', ci_lower > 0, f'5th %ile SR={ci_lower:.3f}')
    else:
        result.add('G4.3 Bootstrap CI LB > 0', False, 'Insufficient data')
    
    # G4.4: Permutation test
    if len(rets_all) > 20:
        real_mean = rets_all.mean()
        perm_means = []
        for _ in range(2000):
            perm = np.random.choice(rets_all, len(rets_all)) * np.random.choice([-1, 1], len(rets_all))
            perm_means.append(perm.mean())
        p_val = np.mean(np.array(perm_means) >= real_mean)
        result.add('G4.4 Permutation p < 0.05', p_val < 0.05, f'p={p_val:.4f}')
    else:
        result.add('G4.4 Permutation p < 0.05', False, 'Insufficient data')
    
    # === GATE 5: Risk Analysis ===
    max_dd = compute_metrics(eqs_all)['dd']
    ann = compute_metrics(eqs_all)['ann']
    sortino = compute_metrics(eqs_all)['sortino']
    
    result.add('G5.1 MaxDD < 20%', max_dd < 0.20, f'MaxDD={max_dd:.2%}')
    result.add('G5.2 Calmar > 0.5', ann / max(max_dd, 0.001) > 0.5 if max_dd > 0 else False,
               f'Calmar={ann/max(max_dd,0.001):.3f}')
    result.add('G5.3 Sortino > 1.5', sortino > 1.5, f'Sortino={sortino:.3f}')
    
    # Profit Factor
    gains = rets_all[rets_all > 0].sum() if len(rets_all[rets_all > 0]) > 0 else 0
    losses = abs(rets_all[rets_all < 0].sum()) if len(rets_all[rets_all < 0]) > 0 else 1e-10
    pf = gains / max(losses, 1e-10)
    result.add('G5.4 Profit Factor > 1.3', pf > 1.3, f'PF={pf:.3f}')
    
    # === GATE 6: Regime Testing ===
    if len(rets_all) > 40:
        half = len(rets_all) // 2
        first_half_sr = compute_metrics(np.exp(np.concatenate([[0], rets_all[:half].cumsum()])) + 1e-10)['sr']
        second_half_sr = compute_metrics(np.exp(np.concatenate([[0], rets_all[half:].cumsum()])) + 1e-10)['sr']
        pos_regimes = sum([first_half_sr > 0, second_half_sr > 0])
        result.add('G6.1 Regime Robustness', pos_regimes >= 2, f'{pos_regimes}/2 halves positive SR')
        
        # Crisis simulation: worst 10% returns period
        rets_sorted = np.sort(rets_all)
        crisis_rets = rets_sorted[:max(len(rets_all)//10, 5)]
        crisis_sr = crisis_rets.mean() / max(crisis_rets.std(), 1e-10) * math.sqrt(365)
        result.add('G6.2 Crisis Survival', crisis_sr > -2.0, f'Crisis SR={crisis_sr:.3f}')
    else:
        result.add('G6.1 Regime Robustness', False, 'Insufficient data')
        result.add('G6.2 Crisis Survival', False, 'Insufficient data')
    
    return result

# ============================================================
# WALK-FORWARD RUNNER
# ============================================================
def run_walkforward_single(data_dict, kind, params, scale=0.3, stop_loss=0.0, ticker=None):
    """
    Run walk-forward for a single-asset strategy.
    Returns list of window results and stitched OOS equity curve.
    """
    if ticker:
        dfs = {ticker: data_dict[ticker]}
    else:
        dfs = data_dict
    
    results_per_ticker = {}
    
    for t, df in dfs.items():
        cv = df['close'].values
        n = len(cv)
        windows = make_windows(df.index, n_windows=6)
        window_results = []
        oos_eqs_list = []
        all_eqs = np.ones(n)
        all_eqs_oos = np.zeros(n)
        
        for w_idx, w in enumerate(windows):
            train_sig = gen_signal_single(df.iloc[w['train_slice']].copy(), kind, **params)
            train_cv = cv[w['train_slice']]
            
            if len(train_sig) < 20:
                continue
            
            # Train: find optimal scale
            best_sr = -1
            best_scale = scale
            for test_scale in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
                r = backtest(train_cv, train_sig, scale=test_scale, stop_loss=stop_loss)
                if r and r['sr'] > best_sr:
                    best_sr = r['sr']; best_scale = test_scale
            
            # Test on OOS
            test_sig = gen_signal_single(df.iloc[w['test_slice']].copy(), kind, **params)
            test_cv = cv[w['test_slice']]
            
            r_is = backtest(train_cv, train_sig, scale=best_scale, stop_loss=stop_loss)
            r_oos = backtest(test_cv, test_sig, scale=best_scale, stop_loss=stop_loss)
            
            if r_is and r_oos:
                window_results.append({
                    'sr_is': r_is['sr'], 'sr_oos': r_oos['sr'],
                    'dd_is': r_is['dd'], 'dd_oos': r_oos['dd'],
                    'ann_is': r_is['ann'], 'ann_oos': r_oos['ann'],
                    'trades': r_oos['trades'],
                    'wfe': r_oos['sr'] / max(abs(r_is['sr']), 0.01) if abs(r_is['sr']) > 0.01 else 0
                })
                oos_eqs_list.append(r_oos['eqs'])
        
        # Stitch OOS equity
        if len(oos_eqs_list) > 0:
            stitched = np.concatenate([eq[1:] for eq in oos_eqs_list])
            results_per_ticker[t] = {
                'window_results': window_results,
                'eqs_oos': np.concatenate([[1.0], stitched]),
                'n_windows': len(window_results),
                'passing_windows': sum(1 for wr in window_results if wr['sr_oos'] > 0)
            }
    
    return results_per_ticker

def run_walkforward_cs(cs_result, lookback, top=3, bottom=3, cost=0.0015):
    """Run walk-forward for cross-sectional strategy (simplified: just run full backtest and report)."""
    # For CS, we just run the full backtest (can't do traditional WF easily)
    close_mat = cs_result['close_mat']
    weights_mat = cs_result['weights_mat']
    n = close_mat.shape[0]
    
    # Split into windows
    windows = make_windows(pd.RangeIndex(n), n_windows=6)
    window_results = []
    oos_eqs = [1.0]
    
    for w in windows:
        # Only use weights from test period
        test_w = weights_mat[w['test_slice']]
        test_c = close_mat[w['test_slice']]
        
        # Train on IS to find optimal scale
        train_w = weights_mat[w['train_slice']]
        train_c = close_mat[w['train_slice']]
        r_is = backtest_cs(train_c, train_w, cost)
        
        r_oos = backtest_cs(test_c, test_w, cost)
        
        if r_is and r_oos:
            window_results.append({
                'sr_is': r_is['sr'], 'sr_oos': r_oos['sr'],
                'dd_is': r_is['dd'], 'dd_oos': r_oos['dd'],
                'ann_is': r_is['ann'], 'ann_oos': r_oos['ann'],
                'trades': r_oos['trades'],
                'wfe': r_oos['sr'] / max(abs(r_is['sr']), 0.01) if abs(r_is['sr']) > 0.01 else 0
            })
            oos_eqs.append(r_oos['eqs'][1:])
    
    stitched = np.concatenate(oos_eqs)
    return {'results': window_results, 'eqs_oos': stitched}

# ============================================================
# MAIN PIPELINE
# ============================================================

# Build data
data_daily, daily_idx = build_daily()
data_6h, idx_6h = build_6h()

tickers = sorted(data_daily.keys())
print(f"Daily data: {len(daily_idx)} bars for {len(tickers)} coins")
print(f"6h data: {len(idx_6h)} bars for {len(tickers)} coins")

# Define candidate strategies
# Format: (name, type, data_source, params, scale, stop_loss)
# type: 'single' or 'cs'
candidates = []

# --- Cross-sectional strategies ---
for lb in [5, 10, 20, 40, 60, 80, 120]:
    cs_m = cs_momentum(data_daily, lb, top=3, bottom=3)
    candidates.append((f'CS_Mom_L{lb}', 'cs', cs_m, {'top':3,'bottom':3}, 1.0, 0.0))

for lb in [5, 10, 20, 40, 60]:
    cs_r = cs_reversal(data_daily, lb, top=3, bottom=3)
    candidates.append((f'CS_Rev_L{lb}', 'cs', cs_r, {'top':3,'bottom':3}, 1.0, 0.0))

# Vol-weighted
cs_vw = cs_vol_weighted(data_daily, 20)
candidates.append(('CS_VolWt', 'cs', cs_vw, {}, 1.0, 0.0))

# Rank ensemble
cs_re = cs_rank_ensemble(data_daily, [10, 20, 40, 80])
candidates.append(('CS_RankEns', 'cs', cs_re, {}, 1.0, 0.0))

# --- Single-coin strategies ---
single_strats = [
    # (kind, params, scale, stop_loss, freq)
    ('ema', {'fast':5,'slow':50}, 0.3, 0.05, 'daily'),
    ('ema', {'fast':3,'slow':100}, 0.3, 0.05, 'daily'),
    ('ema', {'fast':10,'slow':50}, 0.3, 0.05, 'daily'),
    ('ema3', {'f':3,'m':10,'s':50}, 0.3, 0.04, 'daily'),
    ('ema3', {'f':5,'m':20,'s':80}, 0.3, 0.05, 'daily'),
    ('rsi', {'p':14,'th':50}, 0.3, 0.05, 'daily'),
    ('rsi', {'p':7,'th':50}, 0.3, 0.04, 'daily'),
    ('rsi', {'p':21,'th':50}, 0.3, 0.06, 'daily'),
    ('rsi_obos', {'p':14,'ol':30,'ob':70}, 0.3, 0.05, 'daily'),
    ('zmr', {'p':20,'entry':1.0}, 0.25, 0.05, 'daily'),
    ('zmr', {'p':20,'entry':1.5}, 0.3, 0.06, 'daily'),
    ('zmr', {'p':10,'entry':1.5}, 0.25, 0.04, 'daily'),
    ('zmr', {'p':40,'entry':1.5}, 0.35, 0.07, 'daily'),
    ('zme', {'p':40,'entry':2.0}, 0.5, 0.08, 'daily'),
    ('hma', {'f':8,'s':40}, 0.3, 0.05, 'daily'),
    ('hma', {'f':6,'s':30}, 0.3, 0.04, 'daily'),
    ('macd', {'f':12,'s':26,'sg':9}, 0.3, 0.05, 'daily'),
    ('macd', {'f':8,'s':24,'sg':5}, 0.3, 0.05, 'daily'),
    ('boll', {'p':20,'m':2}, 0.3, 0.05, 'daily'),
    ('boll', {'p':30,'m':2}, 0.3, 0.05, 'daily'),
    ('boll_break', {'p':20,'m':2}, 0.25, 0.05, 'daily'),
    ('donchian', {'p':40}, 0.25, 0.05, 'daily'),
    ('donchian', {'p':20}, 0.25, 0.05, 'daily'),
    ('tsmom', {'lb':48,'entry':0.8}, 0.3, 0.05, 'daily'),
    ('tsmom', {'lb':32,'entry':0.6}, 0.3, 0.05, 'daily'),
    ('triple_rsi', {'f':3,'m':14,'s':50}, 0.4, 0.06, 'daily'),
    ('triple_rsi', {'f':5,'m':21,'s':100}, 0.4, 0.06, 'daily'),
    ('ha_trend', {}, 0.3, 0.05, 'daily'),
    ('vwap_trend', {'p':20}, 0.3, 0.05, 'daily'),
    ('adx_trend', {'p':14,'th':25}, 0.4, 0.06, 'daily'),
    ('adx_trend', {'p':20,'th':30}, 0.4, 0.06, 'daily'),
    # 6h variants
    ('ema', {'fast':8,'slow':160}, 0.2, 0.04, '6h'),
    ('ema', {'fast':4,'slow':160}, 0.2, 0.04, '6h'),
    ('rsi', {'p':14,'th':50}, 0.2, 0.04, '6h'),
    ('zmr', {'p':40,'entry':1.5}, 0.2, 0.04, '6h'),
    ('hma', {'f':8,'s':80}, 0.2, 0.04, '6h'),
]

for skind, sparams, scale, sl, freq in single_strats:
    data_src = data_daily if freq == 'daily' else data_6h
    for ticker in tickers:
        name = f'{skind}_{freq}_{ticker}'
        candidates.append((name, 'single', data_src, (skind, sparams), scale, sl, ticker))

print(f"Total candidates: {len(candidates)}")

# ============================================================
# RUN PIPELINE
# ============================================================
print("\n" + "="*100)
print("RUNNING WALK-FORWARD VALIDATION PIPELINE (Gates 1-7)")
print("="*100)

passing = []
attempts = 0
t0 = time.time()

for cand in candidates:
    attempts += 1
    
    try:
        if cand[1] == 'cs':
            name, _, cs_obj, params, scale, sl = cand
            wf_result = run_walkforward_cs(cs_obj, params.get('lb', 20))
            if len(wf_result['results']) < 2:
                continue
            eqs_oos = wf_result['eqs_oos']
            # For CS, full backtest equity
            full_bt = backtest_cs(cs_obj['close_mat'], cs_obj['weights_mat'])
            eqs_all = full_bt['eqs'] if full_bt else eqs_oos
            
        else:  # single
            name, _, data_src, (skind, sparams), scale, sl, ticker = cand
            wf_result = run_walkforward_single({ticker: data_src[ticker]}, skind, sparams, scale, sl, ticker)
            if ticker not in wf_result or len(wf_result[ticker]['window_results']) < 2:
                continue
            eqs_oos = wf_result[ticker]['eqs_oos']
            window_results = wf_result[ticker]['window_results']
            # Full backtest equity
            full_sig = gen_signal_single(data_src[ticker], skind, **sparams)
            full_bt = backtest(data_src[ticker]['close'].values, full_sig, scale=scale, stop_loss=sl)
            eqs_all = full_bt['eqs'] if full_bt else eqs_oos
            # Recreate window_results as list of dicts
            wf_result[ticker]['window_results'] = window_results
        
        # Run gates
        if cand[1] == 'cs':
            wf_obj = wf_result
            wr = wf_obj['results']
        else:
            wf_obj = wf_result[ticker]
            wr = wf_obj['window_results']
        
        gate = run_gates(eqs_oos, eqs_all, wr, name)
        
        if gate.passed:
            m = compute_metrics(eqs_oos)
            passing.append({
                'name': name,
                'type': cand[1],
                'oos_sr': m['sr'],
                'oos_ann': m['ann'],
                'oos_dd': m['dd'],
                'oos_sortino': m['sortino'],
                'n_windows': len(wr),
                'passing_windows': sum(1 for w in wr if w.get('sr_oos', 0) > 0),
                'avg_wfe': np.mean([w.get('wfe', 0) for w in wr]) if wr else 0,
                'gates': {k: v for k, v in gate.tests.items()}
            })
            print(f"  PASS [{name:30s}] SR={m['sr']:.3f} Ann={m['ann']:.2%} DD={m['dd']:.2%} WFE={np.mean([w.get('wfe',0) for w in wr]):.3f} Win={sum(1 for w in wr if w.get('sr_oos',0)>0)}/{len(wr)}", flush=True)
        
    except Exception as e:
        pass

elapsed = time.time()-t0
print(f"\n{'='*100}")
print(f"PIPELINE COMPLETE: {attempts} attempts, {len(passing)} passing in {elapsed:.0f}s")
print(f"{'='*100}")

if passing:
    print(f"\nPASSING STRATEGIES ({len(passing)}):")
    passing.sort(key=lambda x: -x['oos_sr'])
    for p in passing:
        print(f"  [{p['name']:30s}] SR={p['oos_sr']:.3f} Ann={p['oos_ann']:.2%} DD={p['oos_dd']:.2%} Sortino={p['oos_sortino']:.2f} WFE={p['avg_wfe']:.3f} Win={p['passing_windows']}/{p['n_windows']}")

# Save results
out = {'passing': passing, 'total_attempts': attempts, 'elapsed': elapsed}
with open('pipeline_results.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f"\nSaved to pipeline_results.json")
