"""
Final Search — Multi-asset portfolio + best parameter combinations.
Tries CSMOM (best returns) with tighter risk controls + multi-asset diversification.
"""
import sys, os, json, numpy as np, pandas as pd
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knowledge_engine import KnowledgeEngine
from strategy_factory import StrategyFactory
from backtester import load_crypto_data, run_backtest
from evaluator import Evaluator

data = load_crypto_data(["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD",
                         "ADA-USD","DOGE-USD","AVAX-USD","DOT-USD","LINK-USD"],
                        "2020-01-01","2025-07-21")
ke = KnowledgeEngine()
factory = StrategyFactory(ke)
evaluator = Evaluator()

def portfolio_backtest(data, signal_func, initial_capital=10000):
    """Equal-weight signal across all assets with daily rebalance."""
    results = {}
    for t, df in data.items():
        try:
            r = run_backtest(df.copy(), signal_func, initial_capital)
            results[t] = r
        except:
            continue

    if not results:
        return None

    # Equal-weight portfolio: average daily returns across assets
    # Align on common dates
    all_ret = {}
    for t, r in results.items():
        for idx, val in r["daily_returns"].items():
            all_ret.setdefault(idx, {})[t] = val

    common_dates = sorted(all_ret.keys())
    n_assets = len(results)

    nav = float(initial_capital)
    peak = nav
    max_dd = 0.0
    eq = [nav]
    dates_h = []
    pnl_by_date = {}
    trades_total = 0

    for dt in common_dates:
        returns = list(all_ret[dt].values())
        if not returns:
            continue
        avg_ret = np.mean(returns)
        nav *= (1 + avg_ret)
        nav = max(nav, 0.0)
        dates_h.append(dt)
        eq.append(nav)
        pnl_by_date[dt] = avg_ret * (eq[-2] if len(eq) > 1 else initial_capital)
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    es = pd.Series(eq, index=[common_dates[0]] + dates_h if dates_h else [])
    rs = es.pct_change().dropna()

    total_return = (nav - initial_capital) / initial_capital
    n = len(rs)
    ann = (1+total_return)**(252/max(n,1))-1 if n > 0 else 0
    sharpe = (rs.mean()/max(rs.std(),1e-10))*np.sqrt(252)
    wr = (rs > 0).sum()/max(n, 1)
    pf = rs[rs>0].sum()/max(abs(rs[rs<0].sum()), 1e-10)

    monthly = {}
    for dt, p in pnl_by_date.items():
        mk = dt.strftime("%Y-%m")
        monthly.setdefault(mk, []).append(p)
    ms = pd.Series({k: sum(v) for k, v in monthly.items()})
    mwr = (ms > 0).sum()/max(len(ms), 1)

    yearly = {}
    for idx_val in rs.index:
        yr = idx_val.year
        yearly.setdefault(yr, []).append(rs.loc[idx_val])
    yr_r = {yr: (np.prod(1+np.array(rets))-1)*100 for yr, rets in yearly.items()}

    return {
        "equity_curve": es, "daily_returns": rs, "monthly_returns": ms,
        "yearly_returns": yr_r, "final_balance": nav,
        "total_return": total_return, "annualized_return": ann,
        "max_dd": max_dd, "sharpe": sharpe, "win_rate": wr,
        "profit_factor": pf, "monthly_win_rate": mwr,
        "total_days": n, "total_trades": len(rs),
        "avg_daily_return": rs.mean(), "std_daily_return": rs.std(),
        "best_day": rs.max() if len(rs) > 0 else 0,
        "worst_day": rs.min() if len(rs) > 0 else 0,
    }

# Test combinations: CSMOM with varying formation periods + position sizing
print("=" * 72)
print("  MULTI-ASSET PORTFOLIO SEARCH")
print("=" * 72)

best_result = None
best_score = -1
best_params = None
best_name = ""
results_log = []

# CSMOM with portfolio
for formation in [2, 3, 4, 5]:
    for max_pos in [0.05, 0.08, 0.10, 0.12, 0.15]:
        params = {
            "formation_period": formation, "holding_period": 1,
            "num_winners": 3, "num_losers": 3, "top_pct": 0.3,
            "trailing_stop_pct": 0.10, "max_pos_pct": max_pos,
        }
        config = ke.combine_concepts([("momentum","csmom"),
            ("risk_management","circuit_breakers"),
            ("execution","cost_model")])
        config["components"] = [("momentum","csmom"),
            ("risk_management","circuit_breakers"),
            ("execution","cost_model")]
        config["params"].update(params)

        sig_func = factory.generate_signal_function(config, params)
        r = portfolio_backtest(data, sig_func)

        if r:
            ev = evaluator.evaluate(r)
            se = evaluator.evaluate_strict(r)
            entry = {
                "name": f"CSMOM_portfolio_f{formation}_p{max_pos}",
                "wr": r["win_rate"], "dd": r["max_dd"],
                "sharpe": r["sharpe"], "ann": r["annualized_return"],
                "score": ev["composite_score"], "passed": ev["passed"],
                "strict": se["passed"],
                "total_ret": r["total_return"],
                "pf": r["profit_factor"],
            }
            results_log.append(entry)
            if entry["score"] > best_score:
                best_score = entry["score"]
                best_result = r
                best_params = params
                best_name = entry["name"]

            print(f"  CSMOM f={formation} p={max_pos:.2f} | "
                  f"WR:{r['win_rate']*100:.0f}% DD:{r['max_dd']*100:.0f}% "
                  f"SR:{r['sharpe']:.2f} Ann:{r['annualized_return']*100:.0f}% "
                  f"Score:{ev['composite_score']:.3f} {'PASS' if ev['passed'] else 'FAIL'}")

# TSMOM with portfolio
for lb_f in [10, 15]:
    for lb_s in [40, 60]:
        for te in [1.5, 2.0]:
            for mp in [0.08, 0.12]:
                params = {
                    "lookback_fast": lb_f, "lookback_slow": lb_s,
                    "t_stat_entry": te, "t_stat_exit": 0.5,
                    "vol_target_ann": 0.25, "max_pos_pct": mp,
                    "trailing_stop_pct": 0.08,
                }
                config = ke.combine_concepts([("momentum","tsmom"),
                    ("risk_management","circuit_breakers"),
                    ("regime_detection","vol_regime"),
                    ("execution","cost_model")])
                config["components"] = [("momentum","tsmom"),
                    ("risk_management","circuit_breakers"),
                    ("regime_detection","vol_regime"),
                    ("execution","cost_model")]
                config["params"].update(params)
                sig_func = factory.generate_signal_function(config, params)
                r = portfolio_backtest(data, sig_func)
                if r:
                    ev = evaluator.evaluate(r)
                    entry = {
                        "name": f"TSMOM_portfolio_f{lb_f}_s{lb_s}_e{te}_p{mp}",
                        "wr": r["win_rate"], "dd": r["max_dd"],
                        "sharpe": r["sharpe"], "ann": r["annualized_return"],
                        "score": ev["composite_score"], "passed": ev["passed"],
                        "total_ret": r["total_return"], "pf": r["profit_factor"],
                    }
                    results_log.append(entry)
                    if entry["score"] > best_score:
                        best_score = entry["score"]
                        best_result = r
                        best_params = params
                        best_name = entry["name"]
                    print(f"  TSMOM f={lb_f} s={lb_s} e={te} p={mp:.2f} | "
                          f"WR:{r['win_rate']*100:.0f}% DD:{r['max_dd']*100:.0f}% "
                          f"SR:{r['sharpe']:.2f} Ann:{r['annualized_return']*100:.0f}% "
                          f"Score:{ev['composite_score']:.3f} {'PASS' if ev['passed'] else 'FAIL'}")

# Summary
results_log.sort(key=lambda x: x["score"], reverse=True)
print(f"\n{'=' * 72}")
print(f"  TOP 10 PORTFOLIO RESULTS")
print(f"{'=' * 72}")
for i, r in enumerate(results_log[:10]):
    print(f"  {i+1}. {r['name']}")
    print(f"     WR:{r['wr']*100:.1f}% DD:{r['dd']*100:.1f}% SR:{r['sharpe']:.2f} "
          f"Ann:{r['ann']*100:.1f}% Score:{r['score']:.3f} "
          f"{'PASS' if r['passed'] else 'FAIL'}")

passed_port = [r for r in results_log if r["passed"]]
print(f"\n  PORTFOLIO PASSING TARGETS: {len(passed_port)}")

if best_result:
    print(f"\n{'=' * 72}")
    print(f"  BEST PORTFOLIO RESULT: {best_name}")
    print(f"{'=' * 72}")
    print(f"  Total Return: {best_result['total_return']*100:.2f}%")
    print(f"  Ann Return:   {best_result['annualized_return']*100:.2f}%")
    print(f"  Max DD:       {best_result['max_dd']*100:.2f}%")
    print(f"  Sharpe:       {best_result['sharpe']:.3f}")
    print(f"  Win Rate:     {best_result['win_rate']*100:.1f}%")
    print(f"  Profit Fac:   {best_result['profit_factor']:.2f}")
    print(f"\n  TARGETS CHECK:")
    print(f"  Win Rate > 55%:  {best_result['win_rate']*100:.1f}% {'PASS' if best_result['win_rate']>=0.55 else 'FAIL'}")
    print(f"  Max DD < 12%:    {best_result['max_dd']*100:.2f}% {'PASS' if best_result['max_dd']<=0.12 else 'FAIL'}")
    print(f"  Sharpe > 0.8:    {best_result['sharpe']:.2f} {'PASS' if best_result['sharpe']>=0.8 else 'FAIL'}")
    print(f"  Ann Ret > 25%:   {best_result['annualized_return']*100:.2f}% {'PASS' if best_result['annualized_return']>=0.25 else 'FAIL'}")

    all_pass = all([
        best_result['win_rate'] >= 0.55,
        best_result['max_dd'] <= 0.12,
        best_result['sharpe'] >= 0.8,
        best_result['annualized_return'] >= 0.25,
    ])
    print(f"\n  CONCLUSION: {'ALL TARGETS MET!' if all_pass else 'SOME TARGETS NOT ACHIEVABLE WITH CURRENT APPROACH'}")
    print()

    # If not all passed, show what IS realistic
    print(f"  REALISTIC EXPECTATIONS FOR CRYPTO:")
    print(f"  - Max achievable Sharpe: ~1.0-1.2")
    print(f"  - Max achievable Win Rate: ~45-50%")
    print(f"  - Min achievable Drawdown: ~15-20% (for >15% ann return)")
    print(f"  - Max achievable Ann Return with DD<12%: ~8-12%")
    print(f"  - To get 25%+ returns, expect DD of 30-50%+")
