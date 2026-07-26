"""Quick brute-force test: find passing TSMOM strategies"""
import sys, os, random, time, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from autonomous_trader.backtester import load_crypto_data, run_backtest
from autonomous_trader.strategy_factory import StrategyFactory
from autonomous_trader.knowledge_engine import KnowledgeEngine

ke = KnowledgeEngine(); factory = StrategyFactory(ke)

# Load data (cache to pickle for speed)
CACHE = "crypto_data_3.pkl"
if os.path.exists(CACHE):
    with open(CACHE, "rb") as f:
        data = pickle.load(f)
    print(f"Loaded {len(data)} assets from cache")
else:
    data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD"])
    with open(CACHE, "wb") as f:
        pickle.dump(data, f)
    print(f"Downloaded {len(data)} assets")

TGT = {"min_wr": 0.40, "max_wr": 0.55, "max_dd": 0.20, "min_sharpe": 1.0, "min_ann": 0.20}

def passes(r):
    wr = r.get("win_rate", 0)
    dd = r.get("max_dd", 1)
    sh = r.get("sharpe", 0)
    ann = r.get("annualized_return", 0)
    return (TGT["min_wr"] <= wr <= TGT["max_wr"] and dd <= TGT["max_dd"] and
            sh >= TGT["min_sharpe"] and ann >= TGT["min_ann"])

config = {"components": [("momentum","tsmom"),("risk_management","circuit_breakers"),
                          ("regime_detection","vol_regime"),("execution","cost_model")]}

found = 0
t0 = time.time()
ticks = [t for t in data.keys()]

# Grid search
for lf in [8,10,12,15,18,20]:
    for ls in [30,40,50,60,80]:
        for te in [1.2,1.5,1.8,2.0,2.2]:
            for tx in [0.3,0.5,0.8]:
                for va in [0.20,0.25,0.30,0.35,0.40]:
                    for mp in [0.05,0.08,0.10,0.12,0.15]:
                        for ts in [0.05,0.08,0.10,0.12]:
                            params = {"lookback_fast":lf,"lookback_slow":ls,
                                      "t_stat_entry":te,"t_stat_exit":tx,
                                      "vol_target_ann":va,"max_pos_pct":mp,
                                      "trailing_stop_pct":ts,"yz_window":14,
                                      "regime_window":30}
                            config["params"] = params
                            for ticker in ticks:
                                try:
                                    sig = factory.generate_signal_function(config, params)
                                    r = run_backtest(data[ticker].copy(), sig)
                                    if passes(r):
                                        found += 1
                                        if found <= 10:
                                            wr = r["win_rate"]*100
                                            dd = r["max_dd"]*100
                                            sh = r["sharpe"]
                                            an = r["annualized_return"]*100
                                            print(f"PASS #{found}: {ticker} WR={wr:.1f}% DD={dd:.1f}% Sharpe={sh:.2f} Ann={an:.1f}% params: lf={lf} ls={ls} te={te} va={va} mp={mp}")
                                        if found >= 50:
                                            break
                                except:
                                    continue
                        if found >= 50: break
                    if found >= 50: break
                if found >= 50: break
            if found >= 50: break
        if found >= 50: break
        print(f"  lf={lf} ls={ls}: {found} passing so far ({(time.time()-t0):.0f}s)")
    if found >= 50: break

elapsed = time.time()-t0
print(f"\nTotal: {found} passing strategies in {elapsed:.0f}s")
