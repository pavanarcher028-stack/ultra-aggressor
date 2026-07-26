"""Quick debug test for strategy signal generation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest

ke = KnowledgeEngine()
factory = StrategyFactory(ke)
config = ke.combine_concepts([
    ("momentum","tsmom"),
    ("risk_management","circuit_breakers"),
    ("regime_detection","vol_regime"),
    ("execution","cost_model"),
])
config["components"] = [
    ("momentum","tsmom"),
    ("risk_management","circuit_breakers"),
    ("regime_detection","vol_regime"),
    ("execution","cost_model"),
]
params = config["params"]
print("Params:", {k:v for k,v in params.items() if k in [
    "lookback_fast","lookback_slow","t_stat_entry","t_stat_exit",
    "vol_target_ann","max_pos_pct","trailing_stop_pct"]})

sig_func = factory.generate_signal_function(config, params)
data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD"])
for t in data:
    df = sig_func(data[t].copy())
    non_zero = (df["signal"] != 0).sum()
    mean_sig = df["signal"].abs().mean()
    print(f"{t}: non-zero sig: {non_zero}/{len(df)} = {non_zero/len(df)*100:.1f}%, mean |sig|: {mean_sig:.4f}")

if "BTC-USD" in data:
    result = run_backtest(data["BTC-USD"].copy(), sig_func)
    print(f"BTC: Ret={result['total_return']*100:.2f}% Sharpe={result['sharpe']:.3f} DD={result['max_dd']*100:.2f}% WR={result['win_rate']*100:.1f}%")
