"""
Autonomous Trading AI — Main Entry Point
Researches -> Generates -> Backtests -> Optimizes -> Loops until targets met
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from optimizer import Optimizer


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Trading AI — Self-Improving Hedge Fund"
    )
    parser.add_argument(
        "--tickers", nargs="+",
        default=["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
                 "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LINK-USD"],
        help="Crypto tickers to trade"
    )
    parser.add_argument("--start", default="2020-01-01", help="Backtest start date")
    parser.add_argument("--end", default="2025-07-21", help="Backtest end date")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    parser.add_argument("--iterations", type=int, default=100, help="Max optimization iterations")
    parser.add_argument("--quick", action="store_true", help="Quick test mode (fewer assets, fewer iterations)")

    args = parser.parse_args()

    if args.quick:
        args.tickers = ["BTC-USD", "ETH-USD", "SOL-USD"]
        args.iterations = 10

    print("\n" + "=" * 72)
    print("  AUTONOMOUS TRADING AI")
    print("  Self-Improving Hedge Fund System")
    print("=" * 72)
    print(f"\n  Knowledge ingested from: academic papers, books, investment blogs")
    print(f"  Strategy categories available:")
    print(f"    - Momentum (TSMOM, CSMOM, Donchian Trend)")
    print(f"    - Mean Reversion (Pairs Trading, Stat Arb)")
    print(f"    - Volatility Management (Scaling, YZ Estimator)")
    print(f"    - Risk Management (Circuit Breakers, Position Sizing)")
    print(f"    - Regime Detection (RF Regime, Vol Regime)")
    print(f"\n  Starting optimization loop...")
    print(f"  {len(args.tickers)} assets, {args.iterations} max iterations")

    opt = Optimizer(
        tickers=args.tickers,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
        max_iterations=args.iterations,
    )

    result = opt.run()

    if result:
        print("\n  SUMMARY:")
        print(f"    Final Balance: ${result['final_balance']:,.2f}")
        print(f"    Total Return: {result['total_return']*100:+.2f}%")
        print(f"    Max DD:       {result['max_dd']*100:.2f}%")
        print(f"    Sharpe:       {result['sharpe']:.3f}")
        print(f"    Win Rate:     {result['win_rate']*100:.1f}%")
        print(f"    Ann Return:   {result['annualized_return']*100:.2f}%")
        print(f"    Profit Fac:   {result['profit_factor']:.2f}")
        print(f"\n  TARGETS:")
        passed_wr = "PASS" if result['win_rate'] >= 0.55 else "FAIL"
        passed_dd = "PASS" if result['max_dd'] <= 0.12 else "FAIL"
        passed_sr = "PASS" if result['sharpe'] >= 0.8 else "FAIL"
        passed_ar = "PASS" if result['annualized_return'] >= 0.25 else "FAIL"
        print(f"    Win Rate > 55%:      {result['win_rate']*100:.1f}% [{passed_wr}]")
        print(f"    Max DD < 12%:        {result['max_dd']*100:.2f}% [{passed_dd}]")
        print(f"    Sharpe > 0.8:        {result['sharpe']:.2f} [{passed_sr}]")
        print(f"    Ann Return > 25%:    {result['annualized_return']*100:.2f}% [{passed_ar}]")
        print(f"\n  {'=' * 72}")
        print(f"  {'ALL TARGETS MET!' if all([passed_wr=='PASS',passed_dd=='PASS',passed_sr=='PASS',passed_ar=='PASS']) else 'SOME TARGETS NOT MET - REVIEW AND RERUN'}")
        print(f"  {'=' * 72}")
    else:
        print("\n  No valid result found. The system was unable to meet targets.")
        print("  Consider increasing iterations or adjusting the knowledge base.")

    return result


if __name__ == "__main__":
    result = main()
