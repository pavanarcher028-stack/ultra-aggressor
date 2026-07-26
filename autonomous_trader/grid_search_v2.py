"""
Focused Grid Search — Tests only the most promising parameter zones on BTC & ETH
Targets: WR > 55%, DD < 12%, Sharpe > 0.8, Ann Return > 25%
"""
import sys, os, json, itertools, numpy as np
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest
from evaluator import Evaluator

data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD"],"2020-01-01","2025-07-21")
ke = KnowledgeEngine()
factory = StrategyFactory(ke)
evaluator = Evaluator()

# TSMOM: only 3 params varied (2 values each) = 8 combos per asset
tsmom_grid = {
    "lookback_fast": [10, 20],
    "lookback_slow": [40, 80],
    "t_stat_entry": [1.2, 2.0],
    "t_stat_exit": [0.5],
    "vol_target_ann": [0.25, 0.35],
    "max_pos_pct": [0.08, 0.12],
    "trailing_stop_pct": [0.08, 0.12],
}

# Donchian: minimal grid
donch_grid = {
    "lookback_short": [15, 30],
    "lookback_medium": [40, 60],
    "vol_target": [0.20, 0.30],
    "max_pos_pct": [0.08, 0.12],
    "trailing_stop_pct": [0.10],
}

# Pairs trading
pairs_grid = {
    "entry_zscore": [1.5, 2.5],
    "exit_zscore": [0.5],
    "coint_window": [40, 80],
    "max_pos_pct": [0.10],
    "trailing_stop_pct": [0.10],
}

print("=" * 72)
print("  FOCUSED GRID SEARCH — TARGETS: WR>55% DD<12% Sharpe>0.8 AnnRet>25%")
print("=" * 72)

all_results = []
total_combos = 0

for name, grid in [("tsmom", tsmom_grid), ("donchian", donch_grid), ("pairs", pairs_grid)]:
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total_combos += len(combos) * len(data)
    print(f"  {name}: {len(combos)} param sets x {len(data)} assets = {len(combos)*len(data)} tests")

print(f"\n  Total tests: {total_combos}")
print()

count = 0
for name, grid in [("tsmom", tsmom_grid), ("donchian", donch_grid), ("pairs", pairs_grid)]:
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))

    for combo in combos:
        params = dict(zip(keys, combo))
        config = ke.combine_concepts([("momentum",name),
            ("risk_management","circuit_breakers"),
            ("regime_detection","vol_regime"),
            ("execution","cost_model")])
        config["components"] = [("momentum",name),
            ("risk_management","circuit_breakers"),
            ("regime_detection","vol_regime"),
            ("execution","cost_model")]
        config["params"].update(params)
        sig_func = factory.generate_signal_function(config, params)

        for ticker in data:
            count += 1
            try:
                r = run_backtest(data[ticker].copy(), sig_func)
                ev = evaluator.evaluate(r)
                se = evaluator.evaluate_strict(r)
                all_results.append({
                    "strategy": name, "ticker": ticker, "params": params.copy(),
                    "wr": float(r["win_rate"]), "dd": float(r["max_dd"]),
                    "sharpe": float(r["sharpe"]), "ann": float(r["annualized_return"]),
                    "score": float(ev["composite_score"]),
                    "passed": ev["passed"], "strict": se["passed"],
                    "total_ret": float(r["total_return"]),
                    "pf": float(r["profit_factor"]), "trades": int(r["total_trades"]),
                })
                if count % 15 == 0:
                    print(f"  [{count:4d}/{total_combos}] {name:8s} {ticker:8s} "
                          f"WR:{r['win_rate']*100:.0f}% DD:{r['max_dd']*100:.0f}% "
                          f"SR:{r['sharpe']:.2f} Ann:{r['annualized_return']*100:.0f}%"
                          f" {'PASS' if ev['passed'] else 'FAIL'}")
            except:
                continue

all_results.sort(key=lambda x: x["score"], reverse=True)

print(f"\n{'=' * 72}")
print(f"  TOP 15 RESULTS BY COMPOSITE SCORE")
print(f"{'=' * 72}")
print(f"  {'#':<4} {'Strat':<8} {'Ticker':<8} {'WR%':<6} {'DD%':<6} {'Sharpe':<7} {'Ann%':<7} {'Score':<6}")
for i, r in enumerate(all_results[:15]):
    print(f"  {i+1:<4} {r['strategy']:<8} {r['ticker']:<8} "
          f"{r['wr']*100:<5.0f}% {r['dd']*100:<5.0f}% "
          f"{r['sharpe']:<7.2f} {r['ann']*100:<5.0f}% {r['score']:<6.3f}")

passed = [r for r in all_results if r["passed"]]
print(f"\n  STRATEGIES PASSING ALL TARGETS: {len(passed)}")
for r in passed:
    print(f"  {r['strategy']:8s} {r['ticker']:8s} | "
          f"WR:{r['wr']*100:.1f}% DD:{r['dd']*100:.1f}% "
          f"SR:{r['sharpe']:.2f} Ann:{r['ann']*100:.1f}% "
          f"PF:{r['pf']:.2f} Trades:{r['trades']}")

strict = [r for r in all_results if r["strict"]]
print(f"\n  STRICT TARGETS: {len(strict)}")
for r in strict:
    print(f"  {r['strategy']:8s} {r['ticker']:8s} | "
          f"WR:{r['wr']*100:.1f}% DD:{r['dd']*100:.1f}% "
          f"SR:{r['sharpe']:.2f} Ann:{r['ann']*100:.1f}%")

if passed:
    best = passed[0]
    print(f"\n{'=' * 72}")
    print(f"  BEST STRATEGY MEETING ALL TARGETS")
    print(f"{'=' * 72}")
    print(f"  Strategy: {best['strategy']} on {best['ticker']}")
    print(f"  Params: {json.dumps(best['params'], indent=4)}")
    print(f"  WR: {best['wr']*100:.1f}%")
    print(f"  DD: {best['dd']*100:.1f}%")
    print(f"  Sharpe: {best['sharpe']:.2f}")
    print(f"  Ann Return: {best['ann']*100:.1f}%")
    print(f"  Total Return: {best['total_ret']*100:.2f}%")
    print(f"  Score: {best['score']:.3f}")
else:
    print(f"\n  NO STRATEGY FOUND MEETING ALL TARGETS")
    print(f"  Top failures:")
    for r in all_results[:5]:
        fails = []
        if r["wr"] < 0.55: fails.append(f"WR({r['wr']*100:.0f}%)")
        if r["dd"] > 0.12: fails.append(f"DD({r['dd']*100:.0f}%)")
        if r["sharpe"] < 0.8: fails.append(f"SR({r['sharpe']:.2f})")
        if r["ann"] < 0.25: fails.append(f"Ann({r['ann']*100:.0f}%)")
        print(f"  {r['strategy']:8s} {r['ticker']:8s} Score:{r['score']:.3f} Fails: {', '.join(fails)}")

# Save
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
fp = os.path.join("autonomous_trader","results",f"grid_{ts}.json")
with open(fp,"w") as f:
    json.dump(all_results[:50], f, indent=2, default=str)
print(f"\n  Saved: {fp}")
