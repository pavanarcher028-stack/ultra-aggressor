"""Check what metrics are actually achievable — print top 20 closest"""
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

random.seed(42)
results = []
ticker = "BTC-USD"
t0 = time.time()

print(f"Testing 200 random TSMOM configs on BTC, ETH, SOL...")
for i in range(200):
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
        for t in ["BTC-USD","ETH-USD","SOL-USD"]:
            if t not in data: continue
            r = run_backtest(data[t].copy(), sig)
            results.append({
                "ticker": t, "params": params,
                "wr": r["win_rate"]*100, "dd": r["max_dd"]*100,
                "sharpe": r["sharpe"], "ann": r["annualized_return"]*100,
                "total": r["total_return"]*100, "trades": r["total_trades"],
            })
    except:
        continue
    
    if (i+1) % 50 == 0:
        print(f"  {i+1}/200 done ({(time.time()-t0):.0f}s)")

# Show distribution
print(f"\n{'='*60}")
print(f"Total backtests: {len(results)}")
print(f"{'='*60}")

wrs = [r["wr"] for r in results]
dds = [r["dd"] for r in results]
shs = [r["sharpe"] for r in results]
ans = [r["ann"] for r in results]

print(f"\nWin Rate: min={min(wrs):.1f}% max={max(wrs):.1f}% avg={sum(wrs)/len(wrs):.1f}%")
print(f"Max DD:   min={min(dds):.1f}% max={max(dds):.1f}% avg={sum(dds)/len(dds):.1f}%")
print(f"Sharpe:   min={min(shs):.2f} max={max(shs):.2f} avg={sum(shs)/len(shs):.2f}")
print(f"Ann Ret:  min={min(ans):.1f}% max={max(ans):.1f}% avg={sum(ans)/len(ans):.1f}%")

# Top 15 by composite score (closest to targets)
def score(r):
    s = 0
    if 40 <= r["wr"] <= 55: s += 1
    if r["dd"] <= 20: s += 1
    if r["sharpe"] >= 1.0: s += 1
    if r["ann"] >= 20: s += 1
    return s

results.sort(key=lambda r: (score(r), r["sharpe"]), reverse=True)

print(f"\n{'='*60}")
print(f"TOP 20 CLOSEST TO TARGETS (sorted by targets hit + Sharpe)")
print(f"{'='*60}")
print(f"{'Ticker':<10} {'WR':>6} {'DD':>6} {'Sharpe':>7} {'Ann':>7} {'Total':>7} {'Trades':>7} {'Score':>6}")
print("-"*60)
for r in results[:20]:
    s = score(r)
    print(f"{r['ticker']:<10} {r['wr']:>5.1f}% {r['dd']:>5.1f}% {r['sharpe']:>7.2f} {r['ann']:>6.1f}% {r['total']:>6.1f}% {r['trades']:>7} {s:>5}/4")

# Show best params for highest Sharpe
best = results[0]
print(f"\n{'='*60}")
print(f"BEST RESULT (highest score):")
print(f"{'='*60}")
print(f"Ticker: {best['ticker']}")
print(f"Params: {best['params']}")
print(f"Metrics: WR={best['wr']:.1f}% DD={best['dd']:.1f}% Sharpe={best['sharpe']:.2f} Ann={best['ann']:.1f}% Total={best['total']:.1f}%")
