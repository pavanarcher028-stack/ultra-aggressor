"""
Self-Optimizing Loop — The core AI that iterates until ALL targets are met.
Focuses on: WR > 55-60%, DD < 10-12%, Sharpe 0.8-4, Ann Return > 25%
Smart exploration: stays on best strategy type, tunes risk parameters to hit targets.
"""
import sys, os, json, numpy as np
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest, CRYPTO_UNIVERSE
from evaluator import Evaluator


class Optimizer:
    def __init__(self, tickers=None, start="2020-01-01", end="2025-07-21",
                 initial_capital=10000, max_iterations=500):
        self.ke = KnowledgeEngine()
        self.factory = StrategyFactory(self.ke)
        self.evaluator = Evaluator()
        self.tickers = tickers or CRYPTO_UNIVERSE[:5]
        self.start, self.end, self.initial_capital = start, end, initial_capital
        self.max_iterations = max_iterations
        self.best_strategy = None
        self.best_score = -1
        self.best_result = None
        self.history = []
        self.iteration = 0
        self.patience = 0

    def run(self):
        data = load_crypto_data(self.tickers, self.start, self.end)
        if len(data) < 3:
            print("ERROR: Need >= 3 assets")
            return None

        print("=" * 72)
        print("  AUTONOMOUS TRADING AI — TARGET-DRIVEN OPTIMIZER")
        print("=" * 72)
        print(f"  Assets: {len(data)} | Iterations: {self.max_iterations}")
        print(f"  Targets: WR>55-60%, DD<10-12%, Sharpe>0.8-4, AnnRet>25%")
        print(f"\n  Starting optimization...\n")

        # Use TSMOM as base strategy (most promising)
        best_comp = [("momentum","tsmom"),("risk_management","circuit_breakers"),
                     ("regime_detection","vol_regime"),("execution","cost_model")]
        strategy_config = self.ke.combine_concepts(best_comp)
        strategy_config["components"] = best_comp
        strategy_params = strategy_config["params"]
        # Start with conservative params to control DD
        strategy_params["vol_target_ann"] = 0.25
        strategy_params["max_pos_pct"] = 0.10
        strategy_params["trailing_stop_pct"] = 0.08
        strategy_params["t_stat_entry"] = 1.8
        strategy_params["t_stat_exit"] = 0.8
        strategy_params["lookback_fast"] = 10
        strategy_params["lookback_slow"] = 40

        while self.iteration < self.max_iterations:
            self.iteration += 1
            if self.iteration % 25 == 1:
                print(f"\n{'='*60}")
                print(f"  ITERATION {self.iteration}/{self.max_iterations}")
                print(f"{'='*60}")

            # Smart mutation: tune toward targets
            if self.iteration > 1:
                # Every 20 iters try a fresh strategy config
                if self.iteration % 20 == 0:
                    new_type = np.random.choice(["tsmom", "donchian_trend", "csmom"])
                    best_comp = [
                        ("momentum", new_type),
                        ("risk_management","circuit_breakers"),
                        ("regime_detection","vol_regime"),
                        ("execution","cost_model"),
                    ]
                    strategy_config = self.ke.combine_concepts(best_comp)
                    strategy_config["components"] = best_comp
                    strategy_params = strategy_config["params"]
                    strategy_params["vol_target_ann"] = np.random.uniform(0.15, 0.40)
                    strategy_params["max_pos_pct"] = np.random.uniform(0.05, 0.20)
                    strategy_params["trailing_stop_pct"] = np.random.uniform(0.05, 0.15)
                else:
                    # Adaptive mutation based on what needs improvement
                    if self.best_result:
                        needs = []
                        if self.best_result.get("max_dd", 1) > 0.12:
                            needs.append("reduce_dd")
                        if self.best_result.get("win_rate", 0) < 0.55:
                            needs.append("increase_wr")
                        if self.best_result.get("sharpe", 0) < 0.8:
                            needs.append("increase_sharpe")
                        if self.best_result.get("annualized_return", 0) < 0.25:
                            needs.append("increase_return")

                        strategy_params = self.factory.mutate_strategy(
                            strategy_config, strategy_params, 0.25)

                        if "reduce_dd" in needs:
                            strategy_params["max_pos_pct"] = max(0.03, strategy_params.get("max_pos_pct", 0.1) * 0.9)
                            strategy_params["trailing_stop_pct"] = max(0.03, strategy_params.get("trailing_stop_pct", 0.1) * 0.9)
                            strategy_params["vol_target_ann"] = max(0.10, strategy_params.get("vol_target_ann", 0.3) * 0.95)
                        if "increase_return" in needs and len(needs) == 1:
                            strategy_params["max_pos_pct"] = min(0.25, strategy_params.get("max_pos_pct", 0.1) * 1.05)
                            strategy_params["vol_target_ann"] = min(0.5, strategy_params.get("vol_target_ann", 0.3) * 1.05)
                    else:
                        strategy_params = self.factory.mutate_strategy(
                            strategy_config, strategy_params, 0.3)

            signal_func = self.factory.generate_signal_function(strategy_config, strategy_params)

            # Backtest on all assets
            asset_results = {}
            for ticker in list(data.keys()):
                try:
                    r = run_backtest(data[ticker].copy(), signal_func, self.initial_capital)
                    asset_results[ticker] = r
                except:
                    continue

            if not asset_results:
                continue

            # Find best asset by composite score
            best_ticker = None
            best_info = None
            best_result = None
            best_score = -1

            for t, r in asset_results.items():
                ev = self.evaluator.evaluate(r)
                score = ev["composite_score"]
                if score > best_score:
                    best_score = score
                    best_ticker = t
                    best_info = {"score": score, "passed": ev["passed"]}
                    for k in ["sharpe","win_rate","max_dd","annualized_return","profit_factor"]:
                        best_info[k] = r.get(k, 0)
                    best_result = r

            if best_ticker and best_info["score"] > self.best_score:
                self.best_score = best_info["score"]
                self.best_strategy = {"config": strategy_config, "params": strategy_params.copy(), "ticker": best_ticker}
                self.best_result = best_result
                self.patience = 0
            else:
                self.patience += 1

            # Print progress every 5 iters
            if self.iteration % 5 == 0:
                comps = ", ".join([c[1] for c in strategy_config.get("components", [])])
                print(f"  [{self.iteration:3d}] {best_ticker:8s} | "
                      f"Score:{best_info['score']:.3f} | "
                      f"Sharpe:{best_info['sharpe']:.2f} | "
                      f"WR:{best_info['win_rate']*100:.1f}% | "
                      f"DD:{best_info['max_dd']*100:.1f}% | "
                      f"Ann:{best_info['annualized_return']*100:.1f}% | "
                      f"{'PASS' if best_info['passed'] else 'FAIL'} | {comps}")

            # Check strict targets
            se = self.evaluator.evaluate_strict(best_result)
            if se["passed"]:
                print(f"\n{'='*72}")
                print(f"  ALL TARGETS MET at iteration {self.iteration}!")
                print(f"{'='*72}")
                self._print_full_report(best_result, best_ticker)
                self._save_strategy(best_result, strategy_config, strategy_params, best_ticker)
                return best_result

            # If normal targets met, refine
            if best_info["passed"]:
                print(f"  [REFINE] Normal targets met! Refining to strict...")
                for ref in range(10):
                    rp = strategy_params.copy()
                    rp["max_pos_pct"] *= np.random.uniform(0.9, 1.1)
                    rp["vol_target_ann"] *= np.random.uniform(0.9, 1.1)
                    rf = self.factory.generate_signal_function(strategy_config, rp)
                    try:
                        rr = run_backtest(data[best_ticker].copy(), rf, self.initial_capital)
                        re = self.evaluator.evaluate_strict(rr)
                        if re["passed"]:
                            print(f"  STRICT TARGETS MET during refinement!")
                            self._print_full_report(rr, best_ticker)
                            self._save_strategy(rr, strategy_config, rp, best_ticker)
                            return rr
                    except:
                        continue

        print(f"\n{'='*72}")
        print(f"  MAX ITERATIONS ({self.max_iterations}) — Best Score: {self.best_score:.3f}")
        print(f"{'='*72}")
        if self.best_result:
            self._print_full_report(self.best_result, self.best_strategy["ticker"])
            self._save_strategy(self.best_result, self.best_strategy["config"],
                               self.best_strategy["params"], self.best_strategy["ticker"])
        return self.best_result

    def _print_full_report(self, result, ticker):
        sep = "=" * 72
        print(f"\n{sep}")
        print(f"  HEDGE FUND PERFORMANCE REPORT — {ticker}")
        print(sep)
        sections = [
            ("PERFORMANCE", [
                ("Total Return", f"{result['total_return']*100:+.2f}%"),
                ("Annualized Return", f"{result['annualized_return']*100:+.2f}%"),
                ("Max Drawdown", f"{result['max_dd']*100:.2f}%"),
                ("Sharpe Ratio", f"{result['sharpe']:.3f}"),
                ("Sortino Ratio", f"{result['sortino']:.3f}"),
                ("Calmar Ratio", f"{result['calmar']:.3f}"),
                ("Profit Factor", f"{result['profit_factor']:.3f}"),
            ]),
            ("TRADES", [
                ("Total Trades", f"{result['total_trades']}"),
                ("Trading Days", f"{result['total_days']}"),
                ("Win Rate (daily)", f"{result['win_rate']*100:.1f}%"),
                ("Monthly Win Rate", f"{result['monthly_win_rate']*100:.1f}%"),
                ("Avg Daily Return", f"{result['avg_daily_return']*100:+.4f}%"),
                ("Std Dev (daily)", f"{result['std_daily_return']*100:.4f}%"),
            ]),
            ("RISK", [
                ("Max Drawdown", f"{result['max_dd']*100:.2f}%"),
                ("Daily VaR (95%)", f"{result['daily_var_95']*100:+.4f}%"),
                ("Skewness", f"{result['skew']:.3f}"),
                ("Kurtosis", f"{result['kurtosis']:.3f}"),
            ]),
            ("TARGETS", [
                ("Win Rate > 55-60%", f"{result['win_rate']*100:.1f}% {'PASS' if result['win_rate']>=0.55 else 'FAIL'}"),
                ("Max DD < 10-12%", f"{result['max_dd']*100:.2f}% {'PASS' if result['max_dd']<=0.12 else 'FAIL'}"),
                ("Sharpe > 0.8", f"{result['sharpe']:.2f} {'PASS' if result['sharpe']>=0.8 else 'FAIL'}"),
                ("Ann Return > 25%", f"{result['annualized_return']*100:.2f}% {'PASS' if result['annualized_return']>=0.25 else 'FAIL'}"),
            ]),
        ]
        for title, items in sections:
            print(f"\n  {title}")
            print("  " + "-"*55)
            print("  {:<35} {:>15}".format("Metric","Value"))
            print("  {:<35} {:>15}".format("-"*35,"-"*15))
            for k,v in items:
                print("  {:<35} {:>15}".format(k,v))

        print(f"\n  YEARLY RETURNS")
        print("  " + "-"*55)
        for yr in sorted(result["yearly_returns"].keys()):
            yr_ret = result["yearly_returns"][yr]
            bar = "#"*max(1,min(int(abs(yr_ret)/3),25))
            print("  {:<10} {:>+8.2f}%  {}".format(yr,yr_ret,bar))
        print(f"\n{sep}")

    def _save_strategy(self, result, config, params, ticker):
        import json
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = os.path.join(results_dir, f"best_strategy_{ts}.json")
        data = {
            "timestamp": ts, "ticker": ticker,
            "components": config.get("components", []),
            "params": params,
            "performance": {k: float(result.get(k, 0)) for k in
                ["total_return","annualized_return","max_dd","sharpe","sortino",
                 "calmar","win_rate","profit_factor","total_trades"]}
        }
        with open(fp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  Saved: {fp}")
        result["equity_curve"].to_csv(os.path.join(results_dir, f"equity_curve_{ts}.csv"))
        print(f"  Equity curve saved")
