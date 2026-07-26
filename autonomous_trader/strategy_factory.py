"""
Strategy Factory — Generates executable trading strategies from knowledge base.
Supports TSMOM, Donchian, CSMOM, Pairs Trading, Stat Arb — all with vol parity sizing.
"""
import numpy as np
import pandas as pd


class StrategyFactory:
    def __init__(self, knowledge_engine):
        self.ke = knowledge_engine

    def generate_signal_function(self, config, params=None):
        if params is None:
            params = config.get("params", {})
        components = [c[1] for c in config.get("components", [])]
        if "tsmom" in components:
            return self._make_tsmom_strategy(params)
        elif "csmom" in components:
            return self._make_csmom_strategy(params)
        elif "donchian_trend" in components:
            return self._make_donchian_strategy(params)
        elif "pairs_trading" in components:
            return self._make_pairs_strategy(params)
        elif "stat_arb_rf" in components:
            return self._make_stat_arb_strategy(params)
        else:
            return self._make_tsmom_strategy(params)

    def _yz_vol(self, df, w=14):
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        lo = np.log(o / c.shift(1))
        lc = np.log(c / c.shift(1))
        rs = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
        k = 0.34 / (1.34 + (w+1)/max(w-1, 1))
        yzv = lo.rolling(w).var(ddof=0) + k*lc.rolling(w).var(ddof=0) + (1-k)*rs.rolling(w).mean()
        return np.sqrt(np.maximum(yzv * 252, 1e-8))

    def _tstat(self, prices, lb):
        if len(prices) < lb:
            return 0.0
        y = np.log(prices.values[-lb:])
        x = np.arange(lb)
        xm, ym = x.mean(), y.mean()
        beta = np.sum((x-xm)*(y-ym)) / max(np.sum((x-xm)**2), 1e-10)
        resid = y - (ym + beta*(x-xm))
        se = np.sqrt(np.sum(resid**2) / max(lb-2, 1))
        se_b = se / max(np.sqrt(np.sum((x-xm)**2)), 1e-10)
        return beta / se_b if se_b > 0 else 0.0

    def _make_tsmom_strategy(self, params):
        """TSMOM: trend t-stat with adaptive lookback, vol parity sizing."""
        lb_fast = int(params.get("lookback_fast", 15))
        lb_slow = int(params.get("lookback_slow", 60))
        t_entry = params.get("t_stat_entry", 1.5)
        t_exit = params.get("t_stat_exit", 0.5)
        vol_target = params.get("vol_target_ann", 0.40)
        max_pos = params.get("max_pos_pct", 0.20)
        ts_pct = params.get("trailing_stop_pct", 0.15)
        yz_w = int(params.get("yz_window", 14))
        reg_w = int(params.get("regime_window", 30))

        def gen(df):
            df = df.copy()
            c = df["close"]
            yz = self._yz_vol(df, yz_w)
            med = yz.rolling(reg_w, min_periods=max(reg_w//2, 5)).median()
            regime = (yz > med).astype(int)

            sig = pd.Series(0.0, index=df.index)
            warmup = max(lb_fast, lb_slow, yz_w, reg_w) + 2
            in_pos = False
            entry_h = 0.0

            for i in range(warmup, len(df)):
                lb = lb_fast if regime.iloc[i] == 1 else lb_slow
                lb = min(lb, i)
                ts = self._tstat(c.iloc[i-lb:i+1], lb)

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
            mult = vol_ratio.clip(upper=2.0).fillna(1.0)
            df["signal"] = (pos * mult * max_pos * 2).clip(-max_pos, max_pos)
            return df
        return gen

    def _make_donchian_strategy(self, params):
        """Donchian breakout: long when price above high of N days."""
        lb_s = int(params.get("lookback_short", 20))
        lb_m = int(params.get("lookback_medium", 50))
        vol_target = params.get("vol_target", 0.35)
        yz_w = int(params.get("yz_window", 14))
        max_pos = params.get("max_pos_pct", 0.20)

        def gen(df):
            df = df.copy()
            h, c = df["high"], df["close"]

            d1 = pd.Series(0.0, index=df.index)
            dh1 = h.rolling(lb_s).max()
            d1[c > dh1.shift(1)] = 1.0
            d1[c < c.rolling(lb_s).min().shift(1)] = -1.0

            d2 = pd.Series(0.0, index=df.index)
            dh2 = h.rolling(lb_m).max()
            d2[c > dh2.shift(1)] = 1.0
            d2[c < c.rolling(lb_m).min().shift(1)] = -1.0

            sig = ((d1 + d2) / 2).clip(-1, 1)
            yz = self._yz_vol(df, yz_w)
            mult = (vol_target / yz.clip(lower=0.01)).clip(upper=2.0).fillna(1.0)
            df["signal"] = sig.shift(1).fillna(0) * mult * max_pos
            df["signal"] = df["signal"].clip(-max_pos, max_pos)
            return df
        return gen

    def _make_csmom_strategy(self, params):
        """Cross-sectional momentum: long winners, short losers."""
        formation = int(params.get("formation_period", 3))

        def gen(df):
            df = df.copy()
            c = df["close"]
            ret = c.pct_change(formation)
            df["signal"] = 0.0
            df.loc[ret > 0.02, "signal"] = 1.0
            df.loc[ret < -0.02, "signal"] = -1.0
            df["signal"] = df["signal"].shift(1).fillna(0)
            return df
        return gen

    def _make_pairs_strategy(self, params):
        """Mean reversion via z-score on single asset."""
        entry_z = params.get("entry_zscore", 2.0)
        exit_z = params.get("exit_zscore", 0.5)
        lookback = int(params.get("coint_window", 60))
        max_pos = params.get("max_pos_pct", 0.20)

        def gen(df):
            df = df.copy()
            c = df["close"]
            ma = c.rolling(lookback).mean()
            std = c.rolling(lookback).std().replace(0, np.nan)
            z = (c - ma) / std
            df["signal"] = 0.0
            df.loc[z > entry_z, "signal"] = -max_pos
            df.loc[z < -entry_z, "signal"] = max_pos
            df.loc[abs(z) < exit_z, "signal"] = 0.0
            df["signal"] = df["signal"].shift(1).fillna(0)
            return df
        return gen

    def _make_stat_arb_strategy(self, params):
        """Short-term mean reversion."""
        horizon = int(params.get("prediction_horizon", 120))

        def gen(df):
            df = df.copy()
            c = df["close"]
            ret = c.pct_change(horizon)
            df["signal"] = np.where(ret < -0.02, 1.0, np.where(ret > 0.02, -1.0, 0.0))
            df["signal"] = df["signal"].shift(1).fillna(0)
            return df
        return gen

    def mutate_strategy(self, config, params, mutation_rate=0.3):
        new_params = params.copy()
        for cat, subcats in self.ke.knowledge.items():
            for name, concept in subcats.items():
                for pname, pinfo in concept["key_params"].items():
                    if pname in new_params and np.random.random() < mutation_rate:
                        if pinfo["type"] == "int":
                            low, high = pinfo["range"]
                            new_params[pname] = int(np.random.randint(low, high + 1))
                        elif pinfo["type"] == "float":
                            low, high = pinfo["range"]
                            new_params[pname] = round(float(np.random.uniform(low, high)), 3)
        return new_params
