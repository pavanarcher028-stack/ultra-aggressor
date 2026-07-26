"""
Stage 1: Load and cache all crypto data, then run smart random search.
"""
import sys, os, pickle, random, itertools, json, time
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from autonomous_trader.backtester import load_crypto_data, run_backtest, CRYPTO_UNIVERSE
from autonomous_trader.strategy_factory import StrategyFactory
from autonomous_trader.knowledge_engine import KnowledgeEngine

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crypto_data.pkl")

# Load or cache data
if os.path.exists(CACHE_FILE):
    print("Loading data from cache...")
    with open(CACHE_FILE, "rb") as f:
        data = pickle.load(f)
    print(f"Loaded {len(data)} assets from cache")
else:
    print("Downloading crypto data...")
    data = load_crypto_data(CRYPTO_UNIVERSE[:10])
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(data, f)
    print(f"Downloaded and cached {len(data)} assets")

for t in data:
    print(f"  {t}: {len(data[t])} rows")

# ─── TARGETS ───
TGT = {"min_wr": 0.40, "max_wr": 0.55, "max_dd": 0.20, "min_sharpe": 1.0, "min_ann": 0.20}

def passes(r):
    wr = r.get("win_rate", 0)
    dd = r.get("max_dd", 1)
    sh = r.get("sharpe", 0)
    ann = r.get("annualized_return", 0)
    return (TGT["min_wr"] <= wr <= TGT["max_wr"] and dd <= TGT["max_dd"] and
            sh >= TGT["min_sharpe"] and ann >= TGT["min_ann"])

def score(r):
    return r.get("sharpe",0)*2 + r.get("annualized_return",0)*3 - r.get("max_dd",1)*2 + r.get("win_rate",0)*2

ke = KnowledgeEngine()
factory = StrategyFactory(ke)

# ─── PARAM RANGES ───
param_ranges = {
    "tsmom": {
        "lookback_fast": (8, 25, int),
        "lookback_slow": (30, 100, int),
        "t_stat_entry": (1.2, 2.5, float),
        "t_stat_exit": (0.3, 1.0, float),
        "vol_target_ann": (0.20, 0.50, float),
        "max_pos_pct": (0.05, 0.20, float),
        "trailing_stop_pct": (0.05, 0.15, float),
        "yz_window": (14, 21, int),
        "regime_window": (21, 45, int),
    },
    "donchian": {
        "lookback_short": (15, 30, int),
        "lookback_medium": (40, 70, int),
        "vol_target": (0.20, 0.40, float),
        "yz_window": (14, 21, int),
        "max_pos_pct": (0.05, 0.15, float),
    },
    "csmom": {
        "formation_period": (1, 7, int),
    },
    "pairs": {
        "entry_zscore": (1.5, 3.0, float),
        "exit_zscore": (0.3, 0.8, float),
        "coint_window": (30, 90, int),
        "max_pos_pct": (0.05, 0.20, float),
    },
    "stat_arb": {
        "prediction_horizon": (60, 180, int),
    },
}

configs = {
    "tsmom": {"components": [("momentum","tsmom"),("risk_management","circuit_breakers"),
                              ("regime_detection","vol_regime"),("execution","cost_model")]},
    "donchian": {"components": [("momentum","donchian_trend"),("risk_management","circuit_breakers"),
                                 ("regime_detection","vol_regime"),("execution","cost_model")]},
    "csmom": {"components": [("momentum","csmom"),("risk_management","circuit_breakers"),
                              ("regime_detection","vol_regime"),("execution","cost_model")]},
    "pairs": {"components": [("mean_reversion","pairs_trading"),("risk_management","circuit_breakers"),
                              ("regime_detection","vol_regime"),("execution","cost_model")]},
    "stat_arb": {"components": [("mean_reversion","stat_arb_rf"),("risk_management","circuit_breakers"),
                                 ("regime_detection","vol_regime"),("execution","cost_model")]},
}

def random_params(ranges):
    p = {}
    for k, (lo, hi, typ) in ranges.items():
        if typ == int:
            p[k] = random.randint(lo, hi)
        else:
            p[k] = round(random.uniform(lo, hi), 3)
    return p

passing = []
attempts = 0
print(f"\nSearching for 50 passing strategies...")
print(f"Targets: WR 40-55%, DD<20%, Sharpe>=1, Ann>=20%")
print(f"Assets: {list(data.keys())}")
print()

# Strategy weights — TSMOM most likely to pass, so weight it higher
weights = {"tsmom": 4, "csmom": 1, "donchian": 2, "pairs": 2, "stat_arb": 1}
strat_names = list(weights.keys())
strat_weights = [weights[s] for s in strat_names]

t0 = time.time()
while len(passing) < 50 and attempts < 50000:
    attempts += 1
    
    # Pick strategy type (weighted random)
    strat_name = random.choices(strat_names, weights=strat_weights, k=1)[0]
    config = configs[strat_name]
    params = random_params(param_ranges[strat_name])
    config["params"] = params
    
    try:
        signal_func = factory.generate_signal_function(config, params)
    except:
        continue
    
    # Test on random assets (1-3 per iteration for speed)
    test_assets = random.sample(list(data.keys()), min(random.randint(1,3), len(data)))
    
    for ticker in test_assets:
        try:
            r = run_backtest(data[ticker].copy(), signal_func)
            if passes(r):
                sc = score(r)
                entry = {
                    "strategy": strat_name,
                    "ticker": ticker,
                    "params": {k: v if isinstance(v, (int,float)) else float(v) for k,v in params.items()},
                    "metrics": {
                        "win_rate": float(r["win_rate"]),
                        "max_dd": float(r["max_dd"]),
                        "sharpe": float(r["sharpe"]),
                        "annualized_return": float(r["annualized_return"]),
                        "total_return": float(r["total_return"]),
                        "total_trades": int(r["total_trades"]),
                    },
                    "score": float(sc),
                }
                # Deduplicate
                dup = False
                for p in passing:
                    if (p["strategy"] == strat_name and p["ticker"] == ticker and
                        abs(p["metrics"]["sharpe"] - entry["metrics"]["sharpe"]) < 0.05 and
                        abs(p["metrics"]["max_dd"] - entry["metrics"]["max_dd"]) < 0.01):
                        dup = True
                        break
                if not dup:
                    passing.append(entry)
                    
                    if len(passing) % 5 == 0:
                        elapsed = time.time() - t0
                        rate = attempts / elapsed if elapsed > 0 else 0
                        eta = (50 - len(passing)) / (rate * (50/len(passing))) / 60 if len(passing) > 0 else 0
                        print(f"  Found {len(passing)}/50 passing (attempts: {attempts}, {elapsed:.0f}s elapsed)")
                    if len(passing) >= 50:
                        break
        except:
            continue
    
    if attempts % 1000 == 0:
        elapsed = time.time() - t0
        print(f"  Attempt {attempts}: {len(passing)} passing so far ({elapsed:.0f}s)")

elapsed = time.time() - t0
print(f"\nDone in {elapsed:.0f}s after {attempts} attempts")
print(f"Total passing strategies found: {len(passing)}")

# Sort by score, take top 50
passing.sort(key=lambda x: x["score"], reverse=True)
top50 = passing[:50]

print(f"\nTOP 50 PASSING STRATEGIES:")
print(f"{'#':>3} {'Strat':<10} {'Ticker':<10} {'WR':>6} {'DD':>6} {'Sharpe':>7} {'Ann%':>7} {'Total%':>8} {'Trades':>7}")
print(f"{'-'*70}")
for i, s in enumerate(top50):
    m = s["metrics"]
    print(f"{i+1:>3} {s['strategy']:<10} {s['ticker']:<10} {m['win_rate']*100:>5.1f}% {m['max_dd']*100:>5.1f}% {m['sharpe']:>7.2f} {m['annualized_return']*100:>6.1f}% {m['total_return']*100:>7.1f}% {m['total_trades']:>7}")

# Save results
results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autonomous_trader", "results")
os.makedirs(results_dir, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

save_data = []
for s in top50:
    save_data.append({
        "strategy": s["strategy"],
        "ticker": s["ticker"],
        "params": {k: float(v) if isinstance(v,(int,float)) else v for k,v in s["params"].items()},
        "metrics": {k: float(v) for k,v in s["metrics"].items()},
        "score": float(s["score"]),
    })
fp = os.path.join(results_dir, f"passing_50_{ts}.json")
with open(fp, "w") as f:
    json.dump(save_data, f, indent=2)
print(f"\nSaved to {fp}")

# Also save the Python file for the next stage
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_found_50.py"), "w") as f:
    f.write(f"FOUND_DATA = {json.dumps(save_data, indent=2)}")
print("Saved _found_50.py for PPTX generation")
