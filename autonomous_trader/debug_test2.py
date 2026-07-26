"""Debug: check equity curve values."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest
import numpy as np

ke = KnowledgeEngine()
factory = StrategyFactory(ke)
config = ke.combine_concepts([("momentum","tsmom"),("risk_management","circuit_breakers"),("regime_detection","vol_regime"),("execution","cost_model")])
config["components"] = [("momentum","tsmom"),("risk_management","circuit_breakers"),("regime_detection","vol_regime"),("execution","cost_model")]
params = config["params"]
sig_func = factory.generate_signal_function(config, params)
data = load_crypto_data(["BTC-USD"])

df = data["BTC-USD"].copy()
result = run_backtest(df, sig_func)

ec = result["equity_curve"]
print(f"First 5: {ec.values[:5]}")
print(f"Last 5: {ec.values[-5:]}")
print(f"Min: {ec.min():.2f}, Max: {ec.max():.2f}")
print(f"Total return: {result['total_return']*100:.4f}%")
rs = result["daily_returns"]
print(f"Daily returns: mean={rs.mean()*100:.6f}%, std={rs.std()*100:.4f}%")
print(f"Max day: {rs.max()*100:.4f}%, Min day: {rs.min()*100:.4f}%")

# Check signal stats on the original df
df2 = sig_func(df)
sig = df2["signal"]
print(f"\nSignal stats:")
print(f"  non-zero: {(sig!=0).sum()}/{len(sig)}")
print(f"  mean abs: {sig.abs().mean():.4f}")
print(f"  std: {sig.std():.4f}")
print(f"  max: {sig.max():.4f}, min: {sig.min():.4f}")

# Check YZ vol
o, h, l, c = df["open"], df["high"], df["low"], df["close"]
yz_window = 14
lo = np.log(o / c.shift(1))
lc = np.log(c / c.shift(1))
rs2 = np.log(h/c)*np.log(h/o) + np.log(l/c)*np.log(l/o)
k = 0.34 / (1.34 + (yz_window+1)/max(yz_window-1, 1))
yz_var = lo.rolling(yz_window).var(ddof=0) + k*lc.rolling(yz_window).var(ddof=0) + (1-k)*rs2.rolling(yz_window).mean()
yz_vol = np.sqrt(np.maximum(yz_var * 252, 1e-8))
print(f"\nYZ Vol stats (ann %):")
print(f"  mean: {yz_vol.mean()*100:.1f}%")
print(f"  median: {yz_vol.median()*100:.1f}%")
print(f"  iann: {np.nanpercentile(yz_vol, 25)*100:.1f}%")
