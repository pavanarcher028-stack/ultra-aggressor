"""Quick analysis: 20 configs, 1 asset, flushed output"""
import sys, os, time, pickle, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from autonomous_trader.backtester import load_crypto_data, run_backtest
from autonomous_trader.strategy_factory import StrategyFactory
from autonomous_trader.knowledge_engine import KnowledgeEngine

ke = KnowledgeEngine(); factory = StrategyFactory(ke)

CACHE = "crypto_data_3.pkl"
with open(CACHE, "rb") as f: data = pickle.load(f)

config = {"components": [("momentum","tsmom"),("risk_management","circuit_breakers"),
                          ("regime_detection","vol_regime"),("execution","cost_model")]}

random.seed(99)
t0 = time.time()
print("Testing 20 random configs on BTC-USD...", flush=True)

results = []
for i in range(20):
    params = {
        "lookback_fast": random.choice([10,15,20,25]),
        "lookback_slow": random.choice([40,60,80,100]),
        "t_stat_entry": random.choice([1.2,1.5,1.8,2.0,2.2]),
        "t_stat_exit": random.choice([0.3,0.5,0.8]),
        "vol_target_ann": random.choice([0.20,0.25,0.30,0.35,0.40]),
        "max_pos_pct": random.choice([0.05,0.08,0.10,0.12,0.15,0.20]),
        "trailing_stop_pct": random.choice([0.05,0.08,0.10,0.12]),
        "yz_window": 14,
        "regime_window": 30,
    }
    config["params"] = params
    try:
        sig = factory.generate_signal_function(config, params)
        r = run_backtest(data["BTC-USD"].copy(), sig)
        wr=r["win_rate"]*100; dd=r["max_dd"]*100; sh=r["sharpe"]; an=r["annualized_return"]*100; tr=r["total_return"]*100
        print(f"  {i+1:>2}: WR={wr:>5.1f}% DD={dd:>5.1f}% Sharpe={sh:>6.2f} Ann={an:>6.1f}% Total={tr:>7.1f}%", flush=True)
        results.append({"wr":wr,"dd":dd,"sharpe":sh,"ann":an,"total":tr,"params":params})
    except Exception as e:
        print(f"  {i+1:>2}: ERROR {e}", flush=True)

elapsed = time.time()-t0
print(f"\nDone in {elapsed:.0f}s", flush=True)
print(f"\nBest Sharpe: {max(results, key=lambda x:x['sharpe'])}", flush=True)
print(f"Lowest DD:   {min(results, key=lambda x:x['dd'])}", flush=True)
print(f"Highest Ann: {max(results, key=lambda x:x['ann'])}", flush=True)
