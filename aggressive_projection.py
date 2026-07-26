"""
AGGRESSIVE PROJECTION — 1k to 1 Lac in Months (Not Years)
===========================================================
Based on: 100% capital per trade, 40% target, 15% stop, full compounding
Win rate: 30-40% (but wins are 2.5x bigger than losses)
No risk management. Full aggression.
"""
import numpy as np, math, json, os, sys
from datetime import datetime, timedelta
import warnings; warnings.filterwarnings('ignore')

INITIAL_CAP = 1000
START = datetime(2026, 7, 26)

print("=" * 72)
print("  AGGRESSIVE PROJECTION — 1k INR to 1 Lac in Months")
print("  Strategy: 100% capital/trade, +40% target, -15% stop, full compound")
print("=" * 72)

# ====================================================================
# THREE SCENARIOS
# ====================================================================
# Aggressive: 30-40% WR with 40% win / 15% loss = 2.67:1 R:R
# Each trade compounds FULL capital

SCENARIOS = {
    'Aggressive (30% WR)': {
        'win_rate': 0.30, 'win_pct': 0.35, 'loss_pct': 0.15,
        'trials_per_day': 8, 'color': '#ef4444', 'desc': '30% WR, +35%/-15%'
    },
    'Aggressive (35% WR)': {
        'win_rate': 0.35, 'win_pct': 0.35, 'loss_pct': 0.15,
        'trials_per_day': 8, 'color': '#f59e0b', 'desc': '35% WR, +35%/-15%'
    },
    'Aggressive (40% WR)': {
        'win_rate': 0.40, 'win_pct': 0.35, 'loss_pct': 0.15,
        'trials_per_day': 8, 'color': '#22c55e', 'desc': '40% WR, +35%/-15%'
    },
}

def simulate(wr, win_pct, loss_pct, trades_per_day, days, n_runs=5000):
    """Simulate aggressive compounding.
    Each trade risks FULL capital. Win = +win_pct, Loss = -loss_pct.
    """
    eqs = np.ones((n_runs, days + 1)) * INITIAL_CAP
    for r in range(n_runs):
        eq = INITIAL_CAP
        for d in range(days):
            for _ in range(trades_per_day):
                is_win = np.random.random() < wr
                ret = win_pct if is_win else -loss_pct
                eq *= (1 + ret)
                if eq <= 0: eq = 0.01; break
            eqs[r, d + 1] = eq
    return eqs

# ====================================================================
# TIME TARGETS
# ====================================================================
TARGETS = [
    ('1 Week', 7), ('2 Weeks', 14), ('3 Weeks', 21),
    ('1 Month', 30), ('2 Months', 60), ('3 Months', 90),
    ('4 Months', 120), ('5 Months', 150), ('6 Months', 180),
    ('1 Year', 365),
]

all_results = {}
for label, days in TARGETS:
    print(f"\n--- {label} ({days} days) ---")
    rdict = {}
    for sname, sparams in SCENARIOS.items():
        eqs = simulate(sparams['win_rate'], sparams['win_pct'], sparams['loss_pct'],
                       sparams['trials_per_day'], days, n_runs=5000)
        final = eqs[:, -1]
        
        p25 = np.percentile(final, 25)
        p50 = np.percentile(final, 50)
        p75 = np.percentile(final, 75)
        hit_lac = np.sum(final >= 100000) / len(final) * 100
        hit_10k = np.sum(final >= 10000) / len(final) * 100
        hit_5k = np.sum(final >= 5000) / len(final) * 100
        wiped = np.sum(final < 1) / len(final) * 100
        
        rdict[sname] = {'p25': p25, 'p50': p50, 'p75': p75,
                        'hit_lac': hit_lac, 'hit_10k': hit_10k, 'hit_5k': hit_5k, 'wiped': wiped, 'eqs': eqs}
        
        mult = p50 / INITIAL_CAP
        print(f"  {sparams['desc']:<35s}: Rs{p50:>10,.0f} ({mult:>5.1f}x)  "
              f"[Rs{p25:>8,.0f} - Rs{p75:>8,.0f}]  "
              f"Hit 1Lac={hit_lac:>5.1f}%  Wiped={wiped:>4.1f}%")
    all_results[label] = rdict

# ====================================================================
# FIND FASTEST PATH TO 1 LAC
# ====================================================================
print(f"\n{'='*72}")
print(f"  FASTEST PATH TO Rs1,00,000")
print(f"{'='*72}")

for sname, sparams in SCENARIOS.items():
    for days in [30, 60, 90, 120, 150, 180]:
        eqs = simulate(sparams['win_rate'], sparams['win_pct'], sparams['loss_pct'],
                       sparams['trials_per_day'], days, n_runs=2000)
        hit = np.sum(eqs[:, -1] >= 100000) / eqs.shape[0] * 100
        wiped = np.sum(eqs[:, -1] < 1) / eqs.shape[0] * 100
        p50 = np.median(eqs[:, -1])
        if hit > 0:
            print(f"  {sparams['desc']:<35s} {days:>3d} days: "
                  f"P50=Rs{p50:>10,.0f}  Hit 1Lac={hit:>5.1f}%  Wiped={wiped:>4.1f}%")
            break

# ====================================================================
# GENERATE CHART
# ====================================================================
print(f"\n{'='*72}")
print(f"  GENERATING CHART...")
print(f"{'='*72}")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    
    fig = plt.figure(figsize=(18, 12))
    colors = {'Aggressive (30% WR)': '#ef4444', 'Aggressive (35% WR)': '#f59e0b',
              'Aggressive (40% WR)': '#22c55e'}
    
    # CHART 1: 6-month equity curves
    ax1 = plt.subplot(2, 3, 1)
    ax1.set_title('6-Month Growth (Aggressive, 8 trades/day)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Portfolio (INR)', fontsize=10)
    ax1.set_xlabel('Trading Days', fontsize=10)
    ax1.set_yscale('log')
    ax1.axhline(y=100000, color='red', linestyle=':', alpha=0.5, linewidth=1.5, label='Rs1,00,000 Target')
    ax1.axhline(y=1000, color='gray', linestyle=':', alpha=0.2)
    
    for sname in ['Aggressive (30% WR)', 'Aggressive (35% WR)', 'Aggressive (40% WR)']:
        sp = SCENARIOS[sname]
        eqs = simulate(sp['win_rate'], sp['win_pct'], sp['loss_pct'],
                       sp['trials_per_day'], 180, n_runs=1000)
        median = np.median(eqs, axis=0)
        p25 = np.percentile(eqs, 25, axis=0)
        p75 = np.percentile(eqs, 75, axis=0)
        ax1.plot(median, color=colors[sname], linewidth=2, label=sp['desc'])
        ax1.fill_between(range(len(median)), p25, p75, color=colors[sname], alpha=0.08)
    
    ax1.legend(fontsize=9, loc='upper left')
    ax1.grid(True, alpha=0.2)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'Rs{x:,.0f}' if x < 1e5 else f'Rs{x/1e5:.1f}L'))
    
    # CHART 2: 1-month detailed
    ax2 = plt.subplot(2, 3, 2)
    ax2.set_title('1-Month Projection', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Portfolio (INR)', fontsize=10)
    ax2.set_xlabel('Trading Days', fontsize=10)
    ax2.axhline(y=100000, color='red', linestyle=':', alpha=0.3)
    
    sp = SCENARIOS['Aggressive (35% WR)']
    eqs = simulate(sp['win_rate'], sp['win_pct'], sp['loss_pct'], sp['trials_per_day'], 30, n_runs=2000)
    median = np.median(eqs, axis=0)
    p25 = np.percentile(eqs, 25, axis=0)
    p75 = np.percentile(eqs, 75, axis=0)
    p10 = np.percentile(eqs, 10, axis=0)
    p90 = np.percentile(eqs, 90, axis=0)
    ax2.plot(median, color='#f59e0b', linewidth=2, label='35% WR (median)')
    ax2.fill_between(range(len(median)), p25, p75, color='#f59e0b', alpha=0.15, label='P25-P75')
    ax2.fill_between(range(len(median)), p10, p90, color='#f59e0b', alpha=0.07, label='P10-P90')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.2)
    
    # CHART 3: Win rate vs return scatter
    ax3 = plt.subplot(2, 3, 3)
    ax3.set_title('Return Distribution (3 Months)', fontsize=12, fontweight='bold')
    ax3.set_xlabel('Final Multiple (x)', fontsize=10)
    ax3.set_ylabel('Frequency', fontsize=10)
    
    sp = SCENARIOS['Aggressive (35% WR)']
    eqs = simulate(sp['win_rate'], sp['win_pct'], sp['loss_pct'], sp['trials_per_day'], 90, n_runs=2000)
    finals = eqs[:, -1] / INITIAL_CAP
    finals = finals[finals < np.percentile(finals, 99)]
    ax3.hist(finals, bins=80, color='#f59e0b', alpha=0.7, edgecolor='white', linewidth=0.5)
    ax3.axvline(x=100, color='red', linestyle='--', linewidth=2, label='100x (1 Lac)')
    ax3.axvline(x=np.median(finals), color='#22c55e', linestyle='-', linewidth=2, label=f'Median: {np.median(finals):.1f}x')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.2)
    
    # CHART 4: Probability of hitting target
    ax4 = plt.subplot(2, 3, 4)
    ax4.set_title('Probability of Hitting Rs1,00,000', fontsize=12, fontweight='bold')
    ax4.set_xlabel('Trading Days', fontsize=10)
    ax4.set_ylabel('Probability (%)', fontsize=10)
    
    for sname, sp in SCENARIOS.items():
        probs = []
        for d in range(10, 211, 10):
            eqs = simulate(sp['win_rate'], sp['win_pct'], sp['loss_pct'], sp['trials_per_day'], d, n_runs=500)
            prob = np.sum(eqs[:, -1] >= 100000) / eqs.shape[0] * 100
            probs.append((d, prob))
        x = [p[0] for p in probs]; y = [p[1] for p in probs]
        ax4.plot(x, y, color=colors[sname], linewidth=2, marker='o', markersize=3, label=sp['desc'])
    
    ax4.axhline(y=50, color='gray', linestyle=':', alpha=0.5)
    ax4.text(210, 52, '50%', fontsize=9, color='gray')
    ax4.legend(fontsize=9)
    ax4.grid(True, alpha=0.2)
    ax4.set_ylim(0, 105)
    
    # CHART 5: Monthly returns boxplot
    ax5 = plt.subplot(2, 3, 5)
    ax5.set_title('Monthly Returns (35% WR, 8 trades/day)', fontsize=12, fontweight='bold')
    ax5.set_xlabel('Month', fontsize=10)
    ax5.set_ylabel('Return (%)', fontsize=10)
    
    sp = SCENARIOS['Aggressive (35% WR)']
    eqs = simulate(sp['win_rate'], sp['win_pct'], sp['loss_pct'], sp['trials_per_day'], 365, n_runs=2000)
    monthly = []
    for m in range(1, 13):
        d = m * 30
        if d >= eqs.shape[1]: break
        vals = (eqs[:, d] / eqs[:, max(d-30, 0)] - 1) * 100
        vals = vals[vals < np.percentile(vals, 99)]
        monthly.append(vals)
    
    bp = ax5.boxplot(monthly, patch_artist=True, showfliers=False)
    for patch in bp['boxes']: patch.set_facecolor('#f59e0b'); patch.set_alpha(0.5)
    ax5.axhline(y=0, color='red', linestyle=':', alpha=0.5)
    ax5.grid(True, alpha=0.2)
    
    # CHART 6: Summary table
    ax6 = plt.subplot(2, 3, 6)
    ax6.axis('off')
    ax6.set_title('Projection Summary (35% WR Scenario)', fontsize=12, fontweight='bold')
    
    sname = 'Aggressive (35% WR)'
    table_data = []
    for label, days in TARGETS[:8]:
        r = all_results[label][sname]
        mult = r['p50'] / INITIAL_CAP
        table_data.append([label, f"{days}", f"Rs{r['p25']:,.0f}", f"Rs{r['p50']:,.0f}",
                          f"Rs{r['p75']:,.0f}", f"{mult:.1f}x", f"{r['hit_lac']:.0f}%", f"{r['wiped']:.0f}%"])
    
    col_lbls = ['Period', 'Days', 'P25', 'P50', 'P75', 'Mult', '1Lac', 'Wiped']
    tbl = ax6.table(cellText=table_data, colLabels=col_lbls, loc='center', cellLoc='center', colWidths=[0.1]*8)
    tbl.auto_set_font_size(False); tbl.set_fontsize(7.5); tbl.scale(1, 1.6)
    for j in range(8):
        tbl[0, j].set_facecolor('#991b1b'); tbl[0, j].set_text_props(color='white', fontweight='bold')
    for i in range(1, len(table_data)+1):
        for j in range(8):
            if j == 6 and '100' in str(table_data[i-1][j]):
                pct = int(str(table_data[i-1][j]).replace('%',''))
                if pct >= 50: tbl[i,j].set_facecolor('#bbf7d0')
                elif pct >= 10: tbl[i,j].set_facecolor('#fef08a')
            if j == 7 and '0' in str(table_data[i-1][j]):
                pass
    
    plt.suptitle(f'AGGRESSIVE HFT PROJECTION — Rs{INITIAL_CAP:,} to Rs1,00,000\n'
                 f'Strategy: 100% capital/trade, +35%/-15%, 8 trades/day, full compounding',
                 fontsize=13, fontweight='bold', y=1.02)
    plt.tight_layout(pad=3)
    
    chart_path = 'aggressive_projection.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"  Chart saved: {chart_path}")
    
except ImportError:
    print(f"  matplotlib not available.")
    try:
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'matplotlib'], capture_output=True, timeout=60)
        print(f"  Installed. Re-run to generate chart.")
    except: pass

# ====================================================================
# FINAL TABLE
# ====================================================================
print(f"\n{'='*100}")
print(f"  AGGRESSIVE PROJECTION — Rs{INITIAL_CAP:,} to Rs1,00,000")
print(f"  35% WR Scenario | +35%/-15% per trade | 8 trades/day | Full compound")
print(f"{'='*100}")
print(f"  {'Period':<15s} {'Days':>5s} {'P25':>14s} {'P50':>14s} {'P75':>14s} {'Mult':>8s} {'Hit 1Lac':>10s} {'Wiped':>8s}")
print(f"  {'-'*15} {'-'*5} {'-'*14} {'-'*14} {'-'*14} {'-'*8} {'-'*10} {'-'*8}")

for label, days in TARGETS:
    r = all_results[label]['Aggressive (35% WR)']
    mult = r['p50'] / INITIAL_CAP
    print(f"  {label:<15s} {days:>5d} Rs{r['p25']:>11,.0f} Rs{r['p50']:>11,.0f} Rs{r['p75']:>11,.0f} {mult:>7.1f}x {r['hit_lac']:>8.1f}% {r['wiped']:>6.1f}%")

# SUMMARY
r1m = all_results['1 Month']['Aggressive (35% WR)']
r3m = all_results['3 Months']['Aggressive (35% WR)']
r5m = all_results['5 Months']['Aggressive (35% WR)']
r6m = all_results['6 Months']['Aggressive (35% WR)']

print(f"\n{'='*100}")
print(f"  THE MATH: Why This Works")
print(f"{'='*100}")
print(f"""
  Each trade: 35% WIN or 15% LOSS with 35% win rate
  Expected value per trade: 0.35*(0.35) + 0.65*(-0.15) = +0.025 (+2.5% per trade)
  At 8 trades/day: ~20% expected daily return
  But VOLATILITY is extreme — you will have losing streaks of 5-10 trades

  Rs{INITIAL_CAP:,} START on {START.strftime('%d %b %Y')}:

  1 MONTH (30 days):
    Median: Rs{r1m['p50']:,.0f} | Chance of hitting 1 Lac: {r1m['hit_lac']:.1f}%
    Chance of being wiped: {r1m['wiped']:.1f}%
    Best 25%: Rs{r1m['p75']:,.0f}+ | Worst 25%: Rs{r1m['p25']:,.0f}-

  3 MONTHS (90 days):
    Median: Rs{r3m['p50']:,.0f} | Chance of hitting 1 Lac: {r3m['hit_lac']:.1f}%
    Chance of being wiped: {r3m['wiped']:.1f}%

  5 MONTHS (150 days):
    Median: Rs{r5m['p50']:,.0f} | Chance of hitting 1 Lac: {r5m['hit_lac']:.1f}%

  6 MONTHS (180 days):
    Median: Rs{r6m['p50']:,.0f} | Chance of hitting 1 Lac: {r6m['hit_lac']:.1f}%

  WARNING: {r1m['wiped']:.0f}%-{r6m['wiped']:.0f}% chance of being COMPLETELY WIPED OUT.
  This is REAL aggression. You CAN and PROBABLY WILL lose everything.
  Only risk what you can afford to lose completely.
""")

# Save
with open('aggressive_projection.json', 'w') as f:
    json.dump({
        'generated': datetime.now().isoformat(),
        'scenario': '35% WR, +35%/-15%, 8 trades/day, full compound',
        'projections': {label: {'p25': all_results[label]['Aggressive (35% WR)']['p25'],
                                'p50': all_results[label]['Aggressive (35% WR)']['p50'],
                                'p75': all_results[label]['Aggressive (35% WR)']['p75']}
                       for label, _ in TARGETS}
    }, f, indent=2)
print(f"  JSON: aggressive_projection.json")
