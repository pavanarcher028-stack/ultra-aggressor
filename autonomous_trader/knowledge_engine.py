"""
Knowledge Engine — Ingested Research from Papers, Books, Blogs
Serves as the AI's knowledge base for strategy generation.
"""
import json
import random
from pathlib import Path


KNOWLEDGE_BASE = {
    "momentum": {
        "tsmom": {
            "description": "Time-series momentum: go long when asset's own past return is positive, short when negative",
            "papers": ["Huang et al 2024", "Yang 2025", "Han et al 2024"],
            "key_params": {
                "lookback_fast": {"type": "int", "range": [5, 30], "default": 15},
                "lookback_slow": {"type": "int", "range": [30, 120], "default": 60},
                "t_stat_entry": {"type": "float", "range": [0.5, 3.0], "default": 1.5},
                "t_stat_exit": {"type": "float", "range": [0.1, 2.0], "default": 0.5},
                "vol_target_ann": {"type": "float", "range": [0.2, 0.6], "default": 0.40},
                "max_pos_pct": {"type": "float", "range": [0.05, 0.30], "default": 0.20},
            },
            "expected_performance": "Sharpe 1.5-2.5 with vol management, 0.5-2% weekly",
        },
        "csmom": {
            "description": "Cross-sectional momentum: long winners, short losers across crypto universe",
            "papers": ["Liu et al 2022", "Lindroos & Meijanen 2024"],
            "key_params": {
                "formation_period": {"type": "int", "range": [1, 8], "default": 3},
                "holding_period": {"type": "int", "range": [1, 8], "default": 1},
                "num_winners": {"type": "int", "range": [1, 10], "default": 3},
                "num_losers": {"type": "int", "range": [1, 10], "default": 3},
                "top_pct": {"type": "float", "range": [0.1, 0.5], "default": 0.3},
            },
            "expected_performance": "3-4% weekly before costs, fades after 4 weeks",
        },
        "donchian_trend": {
            "description": "Donchian channel breakout trend following, ensemble of multiple lookbacks",
            "papers": ["SSRN 5209907", "Catching Crypto Trends 2025"],
            "key_params": {
                "lookback_short": {"type": "int", "range": [10, 40], "default": 20},
                "lookback_medium": {"type": "int", "range": [30, 80], "default": 50},
                "lookback_long": {"type": "int", "range": [60, 200], "default": 100},
                "vol_target": {"type": "float", "range": [0.2, 0.6], "default": 0.35},
                "rotation_top_n": {"type": "int", "range": [3, 15], "default": 10},
            },
            "expected_performance": "Sharpe > 1.5, alpha 10.8% vs BTC",
        },
    },
    "mean_reversion": {
        "pairs_trading": {
            "description": "Statistical arbitrage via cointegrated pairs trading with dynamic hedge ratios",
            "papers": ["Frontiers 2026", "Dynamic Cointegration 2021"],
            "key_params": {
                "coint_window": {"type": "int", "range": [30, 120], "default": 60},
                "entry_zscore": {"type": "float", "range": [1.0, 3.0], "default": 2.0},
                "exit_zscore": {"type": "float", "range": [0.0, 1.0], "default": 0.5},
                "lookback_half_life": {"type": "int", "range": [5, 50], "default": 21},
            },
            "expected_performance": "7-10 bps/day after costs",
        },
        "stat_arb_rf": {
            "description": "Random Forest on lagged returns, long top-3, short flop-3 predictions",
            "papers": ["MDPI JRFM 2019", "Krauss et al 2017"],
            "key_params": {
                "prediction_horizon": {"type": "int", "range": [30, 240], "default": 120},
                "num_features": {"type": "int", "range": [5, 40], "default": 20},
                "top_n_long": {"type": "int", "range": [1, 10], "default": 3},
                "bottom_n_short": {"type": "int", "range": [1, 10], "default": 3},
                "rebalance_freq": {"type": "int", "range": [60, 1440], "default": 120},
            },
            "expected_performance": "7.1 bps/day after 15bps costs",
        },
    },
    "volatility": {
        "vol_scaling": {
            "description": "Scale positions by inverse volatility, target constant volatility exposure",
            "papers": ["Barroso & Santa-Clara 2015", "Moreira & Muir 2017"],
            "key_params": {
                "vol_est_window": {"type": "int", "range": [10, 60], "default": 20},
                "target_vol": {"type": "float", "range": [0.15, 0.50], "default": 0.30},
                "max_scale": {"type": "float", "range": [1.0, 5.0], "default": 2.0},
                "min_scale": {"type": "float", "range": [0.0, 0.5], "default": 0.1},
            },
            "expected_performance": "Reduces kurtosis 68->106, 200%+ boost to raw returns",
        },
        "yz_vol_estimator": {
            "description": "Yang-Zhang range-based volatility estimator using OHLC data",
            "papers": ["Yang & Zhang 2000"],
            "key_params": {
                "yz_window": {"type": "int", "range": [7, 30], "default": 14},
            },
            "expected_performance": "More efficient than close-to-close vol estimation",
        },
    },
    "risk_management": {
        "circuit_breakers": {
            "description": "Trailing stops, portfolio DD halving, cash-only regimes",
            "papers": ["Multiple", "Safe-Haven Literature"],
            "key_params": {
                "trailing_stop_pct": {"type": "float", "range": [0.05, 0.25], "default": 0.15},
                "portfolio_dd_reduce": {"type": "float", "range": [0.05, 0.20], "default": 0.10},
                "portfolio_dd_restore": {"type": "float", "range": [0.02, 0.10], "default": 0.05},
            },
            "expected_performance": "Protects against tail events, preserves capital",
        },
        "position_sizing": {
            "description": "Volatility parity + Kelly criterion for position sizing",
            "papers": ["Multiple"],
            "key_params": {
                "kelly_fraction": {"type": "float", "range": [0.1, 1.0], "default": 0.25},
                "max_leverage": {"type": "float", "range": [1.0, 3.0], "default": 1.0},
                "min_conviction": {"type": "float", "range": [0.0, 0.5], "default": 0.1},
            },
            "expected_performance": "Optimal growth in log-utility framework",
        },
    },
    "regime_detection": {
        "rf_regime": {
            "description": "Random Forest regime switching between fast/slow lookbacks",
            "papers": ["Safe-Haven Adaptive Momentum"],
            "key_params": {
                "rf_train_window": {"type": "int", "range": [252, 756], "default": 504},
                "rf_retrain_days": {"type": "int", "range": [21, 126], "default": 63},
                "n_estimators": {"type": "int", "range": [50, 300], "default": 100},
            },
            "expected_performance": "Adapts faster to changing market conditions",
        },
        "vol_regime": {
            "description": "Volatility-based regime: fast/slow lookback based on vol vs median",
            "papers": ["Multiple"],
            "key_params": {
                "regime_window": {"type": "int", "range": [10, 60], "default": 30},
            },
            "expected_performance": "Simpler alternative to ML-based regime detection",
        },
    },
    "execution": {
        "cost_model": {
            "description": "Transaction cost modeling including commission, slippage, market impact",
            "papers": ["Multiple"],
            "key_params": {
                "commission_pct": {"type": "float", "range": [0.0005, 0.003], "default": 0.001},
                "slippage_pct": {"type": "float", "range": [0.0002, 0.002], "default": 0.0005},
                "borrow_cost_apr": {"type": "float", "range": [0.01, 0.15], "default": 0.05},
            },
            "expected_performance": "Critical for realistic backtesting",
        },
    },
}


class KnowledgeEngine:
    def __init__(self):
        self.knowledge = KNOWLEDGE_BASE
        self.research_file = Path(__file__).parent / "knowledge" / "research_findings.md"

    def get_all_concepts(self):
        """Return all strategy concepts across all categories."""
        concepts = []
        for category, subcats in self.knowledge.items():
            for name, data in subcats.items():
                concepts.append({
                    "category": category,
                    "name": name,
                    "description": data["description"],
                    "papers": data["papers"],
                    "params": data["key_params"],
                })
        return concepts

    def get_concept(self, category, name):
        """Get a specific strategy concept."""
        return self.knowledge.get(category, {}).get(name, None)

    def combine_concepts(self, concept_names):
        """Combine multiple concepts into a hybrid strategy."""
        combined = {
            "description_parts": [],
            "papers": [],
            "params": {},
            "components": [],
        }
        for cat, name in concept_names:
            concept = self.knowledge.get(cat, {}).get(name)
            if concept:
                combined["description_parts"].append(concept["description"])
                combined["papers"].extend(concept["papers"])
                combined["params"].update({
                    k: v["default"] for k, v in concept["key_params"].items()
                })
                combined["components"].append(f"{cat}/{name}")
        combined["papers"] = list(set(combined["papers"]))
        return combined

    def random_mutation(self, params, mutation_rate=0.3):
        """Randomly mutate parameters within their valid ranges."""
        mutated = {}
        for cat, subcats in self.knowledge.items():
            for name, concept in subcats.items():
                for pname, pinfo in concept["key_params"].items():
                    if pname in params and random.random() < mutation_rate:
                        if pinfo["type"] == "int":
                            low, high = pinfo["range"]
                            params[pname] = random.randint(low, high)
                        elif pinfo["type"] == "float":
                            low, high = pinfo["range"]
                            params[pname] = round(random.uniform(low, high), 3)
        return params

    def random_strategy_config(self):
        """Generate a random strategy configuration from knowledge base."""
        momentum_variants = list(self.knowledge["momentum"].keys())
        risk_variants = list(self.knowledge["risk_management"].keys())
        regime_variants = list(self.knowledge["regime_detection"].keys())
        exec_variant = "cost_model"

        components = [
            ("momentum", random.choice(momentum_variants)),
            ("risk_management", random.choice(risk_variants)),
            ("regime_detection", random.choice(regime_variants)),
            ("execution", exec_variant),
        ]

        if random.random() < 0.3:
            components.append(("volatility", "vol_scaling"))

        config = self.combine_concepts(components)
        config["components"] = components
        return config
