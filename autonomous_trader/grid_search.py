"""
Systematic Grid Search — Finds optimal parameters meeting all targets:
WR > 55-60%, DD < 10-12%, Sharpe > 0.8, Ann Return > 25%
"""
import sys, os, json, itertools, numpy as np
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest
from evaluator import Evaluator

data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD"],
                        "2020-01-01","2025-07-21")
ke = KnowledgeEngine()
factory = StrategyFactory(ke)
evaluator = Evaluator()

# Focus on TSMOM with DD control
strategies = [
    ("tsmom", {
        "lookback_fast": [8, 12, 16],
        "lookback_slow": [30, 45, 60],
        "t_stat_entry": [1.2, 1.5, 2.0],
        "t_stat_exit": [0.3, 0.5, 0.8],
        "vol_target_ann": [0.15, 0.20, 0.25, 0.30],
        "max_pos_pct": [0.05, 0.08, 0.10, 0.12, 0.15],
        "trailing_stop_pct": [0.05, 0.08, 0.10, 0.12, 0.15],
        "yz_window": [14],
        "regime_window": [30],
    }),
    ("donchian_trend", {
        "lookback_short": [10, 20, 30],
        "lookback_medium": [30, 50, 70],
        "vol_target": [0.15, 0.20, 0.25],
        "max_pos_pct": [0.05, 0.08, 0.10],
        "trailing_stop_pct": [0.05, 0.08, 0.10],
        "yz_window": [14],
    }),
]

print("=" * 72)
print("  SYSTEMATIC GRID SEARCH — TARGET-DRIVEN STRATEGY OPTIMIZATION")
print("=" * 72)
print(f"  Assets: {list(data.keys())}")
print(f"  Targets: WR>55%, DD<12%, Sharpe>0.8, AnnRet>25%")
print()

results = []
total = 0

for strat_name, param_grid in strategies:
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    total += len(combos)

print(f"  Total parameter combinations: {total}")
print()

count = 0
for strat_name, param_grid in strategies:
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))

    for combo in combos:
        count += 1
        params = dict(zip(keys, combo))

        config = ke.combine_concepts([("momentum",strat_name),
                                      ("risk_management","circuit_breakers"),
                                      ("regime_detection","vol_regime"),
                                      ("execution","cost_model")])
        config["components"] = [("momentum",strat_name),
                                ("risk_management","circuit_breakers"),
                                ("regime_detection","vol_regime"),
                                ("execution","cost_model")]
        config["params"] = config["params"]
        config["params"].update(params)

        sig_func = factory.generate_signal_function(config, params)

        # Test on each asset
        for ticker in data:
            try:
                r = run_backtest(data[ticker].copy(), sig_func)
                ev = evaluator.evaluate(r)
                strict = evaluator.evaluate_strict(r)

                wr = r.get("win_rate",0)
                dd = r.get("max_dd",1)
                sr = r.get("sharpe",0)
                ann = r.get("annualized_return",0)

                result_entry = {
                    "strategy": strat_name,
                    "ticker": ticker,
                    "params": params.copy(),
                    "win_rate": float(wr),
                    "max_dd": float(dd),
                    "sharpe": float(sr),
                    "ann_return": float(ann),
                    "score": float(ev["composite_score"]),
                    "passed": ev["passed"],
                    "strict_passed": strict["passed"],
                    "total_return": float(r.get("total_return",0)),
                    "profit_factor": float(r.get("profit_factor",0)),
                    "total_trades": int(r.get("total_trades",0)),
                }
                results.append(result_entry)

                if count % 50 == 0:
                    print(f"  [{count:4d}/{total}] {strat_name:15s} {ticker:8s} | "
                          f"WR:{wr*100:.0f}% DD:{dd*100:.0f}% SR:{sr:.2f} Ann:{ann*100:.0f}%"
                          f" {'PASS' if ev['passed'] else 'fail'}")

            except Exception as e:
                continue

# Sort and display
results.sort(key=lambda x: x["score"], reverse=True)

print(f"\n{'=' * 72}")
print(f"  TOP 10 RESULTS BY COMPOSITE SCORE")
print(f"{'=' * 72}")
print(f"  {'#':<4} {'Strategy':<15} {'Ticker':<8} {'WR%':<6} {'DD%':<6} {'Sharpe':<7} {'Ann%':<7} {'Score':<6}")
print(f"  {'-'*4} {'-'*15} {'-'*8} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*6}")
for i, r in enumerate(results[:10]):
    print(f"  {i+1:<4} {r['strategy']:<15} {r['ticker']:<8} "
          f"{r['win_rate']*100:<5.0f}% {r['max_dd']*100:<5.0f}% "
          f"{r['sharpe']:<7.2f} {r['ann_return']*100:<5.0f}% "
          f"{r['score']:<6.3f} {'PASS' if r['passed'] else ''}")

# Find strategies that PASS all targets
passed = [r for r in results if r["passed"]]
print(f"\n  {'=' * 72}")
print(f"  STRATEGIES THAT PASS ALL TARGETS: {len(passed)}")
print(f"  {'=' * 72}")
for r in passed[:20]:
    print(f"  {r['strategy']:15s} {r['ticker']:8s} | "
          f"WR:{r['win_rate']*100:.1f}% DD:{r['max_dd']*100:.1f}% "
          f"Sharpe:{r['sharpe']:.2f} Ann:{r['ann_return']*100:.1f}% "
          f"PF:{r['profit_factor']:.2f} Trades:{r['total_trades']}")

strict_pass = [r for r in results if r["strict_passed"]]
print(f"\n  STRICT TARGETS MET: {len(strict_pass)}")
for r in strict_pass[:10]:
    print(f"  {r['strategy']:15s} {r['ticker']:8s} | "
          f"WR:{r['win_rate']*100:.1f}% DD:{r['max_dd']*100:.1f}% "
          f"Sharpe:{r['sharpe']:.2f} Ann:{r['ann_return']*100:.1f}%")

if passed:
    best = passed[0]
    print(f"\n{'=' * 72}")
    print(f"  BEST STRATEGY THAT MEETS TARGETS")
    print(f"{'=' * 72}")
    print(f"  Strategy: {best['strategy']} on {best['ticker']}")
    print(f"  Params: {json.dumps(best['params'], indent=4)}")
    print(f"  WR: {best['win_rate']*100:.1f}%")
    print(f"  DD: {best['max_dd']*100:.1f}%")
    print(f"  Sharpe: {best['sharpe']:.2f}")
    print(f"  Ann Return: {best['ann_return']*100:.1f}%")
    print(f"  Score: {best['score']:.3f}")
else:
    print(f"\n  NO STRATEGY FOUND THAT MEETS ALL TARGETS")
    print(f"  Closest results:")
    for r in results[:5]:
        fails = []
        if r["win_rate"] < 0.55: fails.append(f"WR({r['win_rate']*100:.0f}%)")
        if r["max_dd"] > 0.12: fails.append(f"DD({r['max_dd']*100:.0f}%)")
        if r["sharpe"] < 0.8: fails.append(f"SR({r['sharpe']:.2f})")
        if r["ann_return"] < 0.25: fails.append(f"Ann({r['ann_return']*100:.0f}%)")
        print(f"  {r['strategy']:15s} {r['ticker']:8s} | Score:{r['score']:.3f} | FAILS: {', '.join(fails)}")

# Save results
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
with open(os.path.join("autonomous_trader","results",f"grid_search_{ts}.json"), "w") as f:
    json.dump(results[:100], f, indent=2, default=str)
print(f"\n  Results saved to results/grid_search_{ts}.json")
