"""Quick sampling: try 100 random TSMOM param sets, see metrics distribution"""
import sys, os, time, pickle, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from autonomous_trader.backtester import load_crypto_data, run_backtest
from autonomous_trader.strategy_factory import StrategyFactory
from autonomous_trader.knowledge_engine import KnowledgeEngine

ke = KnowledgeEngine(); factory = StrategyFactory(ke)

CACHE = "crypto_data_3.pkl"
if os.path.exists(CACHE):
    with open(CACHE, "rb") as f: data = pickle.load(f)
else:
    data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD"])
    with open(CACHE, "wb") as f: pickle.dump(data, f)
print(f"Data: {len(data)} assets")

config = {"components": [("momentum","tsmom"),("risk_management","circuit_breakers"),
                          ("regime_detection","vol_regime"),("execution","cost_model")]}

TGT = {"min_wr": 0.40, "max_wr": 0.55, "max_dd": 0.20, "min_sharpe": 1.0, "min_ann": 0.20}
def passes(r):
    wr=r.get("win_rate",0); dd=r.get("max_dd",1); sh=r.get("sharpe",0); ann=r.get("annualized_return",0)
    return TGT["min_wr"]<=wr<=TGT["max_wr"] and dd<=TGT["max_dd"] and sh>=TGT["min_sharpe"] and ann>=TGT["min_ann"]

# Sample 100 random configs
random.seed(42)
found = 0
t0 = time.time()
ticker = "BTC-USD"

print(f"Testing 100 random TSMOM configs on {ticker}...")
print(f"{'#':>4} {'WR':>6} {'DD':>6} {'Sharpe':>7} {'Ann':>7} {'Total':>7} {'PASS':>5}")
print("-"*45)

for i in range(100):
    params = {
        "lookback_fast": random.choice([8,10,12,15,18,20,25]),
        "lookback_slow": random.choice([30,40,50,60,80,100]),
        "t_stat_entry": random.choice([1.0,1.2,1.5,1.8,2.0,2.2,2.5]),
        "t_stat_exit": random.choice([0.3,0.5,0.8,1.0]),
        "vol_target_ann": random.choice([0.15,0.20,0.25,0.30,0.35,0.40,0.50]),
        "max_pos_pct": random.choice([0.03,0.05,0.08,0.10,0.12,0.15,0.20,0.25]),
        "trailing_stop_pct": random.choice([0.03,0.05,0.08,0.10,0.12,0.15,0.20]),
        "yz_window": random.choice([14,21]),
        "regime_window": random.choice([21,30,45]),
    }
    config["params"] = params
    try:
        sig = factory.generate_signal_function(config, params)
        r = run_backtest(data[ticker].copy(), sig)
        p = passes(r)
        if p:
            found += 1
            wr=r["win_rate"]*100; dd=r["max_dd"]*100; sh=r["sharpe"]; an=r["annualized_return"]*100; tr=r["total_return"]*100
            print(f"{i:4d} {wr:5.1f}% {dd:5.1f}% {sh:7.2f} {an:6.1f}% {tr:6.1f}% {'YES':>5}")
    except:
        continue
    
    if (i+1) % 20 == 0:
        print(f"  ... {i+1}/100 done, {found} passing so far ({(time.time()-t0):.0f}s)")

print(f"\nTotal: {found}/100 passed all targets in {(time.time()-t0):.0f}s")
