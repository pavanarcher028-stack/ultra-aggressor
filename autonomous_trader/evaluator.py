"""
Evaluator — Checks strategy performance against target thresholds.
Targets: WinRate > 55-60%, DD < 10-12%, Sharpe 0.8-4, ROI 25%+ annual
"""
import numpy as np


class Evaluator:
    def __init__(self, targets=None):
        self.targets = targets or {
            "win_rate": {"min": 0.55, "max": 1.0},
            "max_dd": {"min": 0.0, "max": 0.12},
            "sharpe": {"min": 0.8, "max": 4.0},
            "annualized_return": {"min": 0.25, "max": None},
            "profit_factor": {"min": 1.3, "max": None},
            "total_trades": {"min": 20, "max": None},
        }
        self.strict_targets = {
            "win_rate": {"min": 0.60, "max": 1.0},
            "max_dd": {"min": 0.0, "max": 0.10},
            "sharpe": {"min": 1.2, "max": 4.0},
            "annualized_return": {"min": 0.30, "max": None},
            "profit_factor": {"min": 1.5, "max": None},
            "total_trades": {"min": 30, "max": None},
        }

    def evaluate(self, result):
        """Evaluate a single backtest result against targets."""
        scores = {}
        passed_all = True
        details = {}

        metrics = {
            "win_rate": result.get("win_rate", 0),
            "max_dd": result.get("max_dd", 1),
            "sharpe": result.get("sharpe", 0),
            "annualized_return": result.get("annualized_return", 0),
            "profit_factor": result.get("profit_factor", 0),
            "total_trades": result.get("total_trades", 0),
        }

        for metric, value in metrics.items():
            target = self.targets.get(metric, {})
            passed = True

            if target.get("min") is not None and value < target["min"]:
                passed = False
            if target.get("max") is not None and value > target["max"]:
                passed = False

            if target.get("min") is not None and target.get("max") is not None:
                score = min((value - target["min"]) / (target["max"] - target["min"] + 1e-10), 1.0)
            elif target.get("min") is not None:
                score = value / target["min"]
            else:
                score = 0.0

            scores[metric] = max(0, min(score, 2.0))
            details[metric] = {"value": value, "target": target, "passed": passed}
            if not passed:
                passed_all = False

        composite_score = np.mean(list(scores.values())) if scores else 0.0

        return {
            "passed": passed_all,
            "composite_score": composite_score,
            "details": details,
            "all_results": result,
        }

    def evaluate_strict(self, result):
        """Evaluate against stricter targets."""
        original_targets = self.targets
        self.targets = self.strict_targets
        result = self.evaluate(result)
        self.targets = original_targets
        return result

    def needs_improvement(self, result):
        """Determine which metrics need improvement."""
        eval_result = self.evaluate(result)
        needs = {}
        for metric, detail in eval_result["details"].items():
            if not detail["passed"]:
                gap = detail["target"].get("min", 0) - detail["value"]
                needs[metric] = {
                    "value": detail["value"],
                    "target": detail["target"].get("min", 0),
                    "gap": gap,
                }
        return needs

    def best_portfolio_result(self, results_dict):
        """Find the best performing asset in a multi-asset backtest."""
        best = None
        best_score = -1
        for ticker, result in results_dict.items():
            eval_result = self.evaluate(result)
            if eval_result["composite_score"] > best_score:
                best_score = eval_result["composite_score"]
                best = {"ticker": ticker, "result": result, "evaluation": eval_result}
        return best
