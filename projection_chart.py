"""
MEME HFT PROJECTION CHART — REALISTIC (Decay-Adjusted)
=======================================================
Based on HFT test: Rs500 -> Rs531.61 (+6.32%) in 500 ticks
BUT adjusted for: market regime changes, drawdowns, strategy decay,
slippage at scale, failed txns, and diminishing edge.

Uses decreasing daily return over time (no infinite compounding).
"""
import numpy as np, math, json, os, sys
from datetime import datetime
import warnings; warnings.filterwarnings('ignore')

INITIAL_CAP = 1000
START_DATE = datetime(2026, 7, 26)

# ====================================================================
# DECAY-ADJUSTED DAILY RETURNS
# ====================================================================
# No strategy sustains 3%/day. Realistic HFT/meme coin trading:
# - First month: higher returns (small capital, nimble)
# - After: edge decays as capital grows (slippage, market impact)
# - Long-term: reverts toward market returns

def daily_return_params(day):
    """Returns (mean_return, std_return) for a given day.
    Returns decay exponentially as capital grows.
    """
    # Initial phase (first 30 days): higher returns, high volatility
    if day <= 30:
        mean = 0.015  # 1.5%/day
        std = 0.06    # 6% daily vol
    # Growth phase (30-180 days): moderate decay
    elif day <= 180:
        decay = math.exp(-(day - 30) / 120)  # Exponential decay
        mean = 0.005 + 0.01 * decay  # 0.5% to 1.5%
        std = 0.04 + 0.02 * decay
    # Mature phase (180-365 days): settled
    elif day <= 365:
        mean = 0.003  # 0.3%/day
        std = 0.03
    # Long-term (1-4 years): mean reverts to slightly above market
    else:
        mean = 0.001  # 0.1%/day (36%/year — still good)
        std = 0.025
    
    return mean, std

# ====================================================================
# MONTE CARLO
# ====================================================================
def simulate_realistic(days, n_runs=2000, cap=INITIAL_CAP):
    """Simulate with decay-adjusted daily returns."""
    eqs = np.ones((n_runs, days + 1)) * cap
    for r in range(n_runs):
        eq = cap
        for d in range(days):
            mean, std = daily_return_params(d)
            ret = np.random.normal(mean, std)
            eq *= (1 + ret)
            eq = max(eq, 0.1)
            eqs[r, d + 1] = eq
    return eqs

def simulate_benchmark(days, n_runs=2000, cap=INITIAL_CAP):
    """Bank Nifty: ~12% annual = 0.047%/day, 15% annual vol = 0.94%/day."""
    daily_mean = 0.00047
    daily_std = 0.0094
    eqs = np.ones((n_runs, days + 1)) * cap
    for r in range(n_runs):
        eq = cap
        for d in range(days):
            ret = np.random.normal(daily_mean, daily_std)
            eq *= (1 + ret)
            eq = max(eq, 0.1)
            eqs[r, d + 1] = eq
    return eqs

# ====================================================================
# COMPUTE PROJECTIONS
# ====================================================================
TARGETS = [
    ('20 days (Aug 15)', 20),
    ('1 Month', 30),
    ('3 Months', 90),
    ('6 Months', 180),
    ('1 Year', 365),
    ('2 Years', 730),
    ('4 Years', 1460),
]

SCENARIOS = {
    'HFT Bot (Realistic)': {'color': '#3b82f6', 'sim': simulate_realistic},
    'HFT Bot (Optimistic)': {'color': '#22c55e', 'sim': lambda d, nr: simulate_realistic(d, nr) * 0 + simulate_realistic(d, nr, INITIAL_CAP) * 1.5 + 0},
    'Bank Nifty Index': {'color': '#6b7280', 'sim': simulate_benchmark},
    'FD / Fixed Deposit': {'color': '#f59e0b', 'sim': lambda d, n_runs=2000: np.ones((n_runs, d+1)) * INITIAL_CAP * (1.0002 ** np.arange(d+1))},
}

# HFT Optimistic: multiply returns by 1.5x
def simulate_optimistic(days, n_runs=2000):
    eqs = np.ones((n_runs, days + 1)) * INITIAL_CAP
    for r in range(n_runs):
        eq = INITIAL_CAP
        for d in range(days):
            mean, std = daily_return_params(d)
            mean *= 1.5
            ret = np.random.normal(mean, std)
            eq *= (1 + ret)
            eq = max(eq, 0.1)
            eqs[r, d + 1] = eq
    return eqs

SCENARIOS['HFT Bot (Optimistic)']['sim'] = simulate_optimistic

print("=" * 72)
print("  MEME HFT PROJECTION — Decay-Adjusted Realistic Forecast")
print("  Based on: Rs500 -> Rs531.61 (+6.32%) in 500 ticks")
print("=" * 72)

results = {}
for label, days in TARGETS:
    print(f"\n  --- {label} ({days} days) ---")
    rdict = {}
    
    for sname, sp in SCENARIOS.items():
        eqs = sp['sim'](days, n_runs=2000)
        final = eqs[:, -1]
        
        p25 = np.percentile(final, 25)
        p50 = np.percentile(final, 50)
        p75 = np.percentile(final, 75)
        hit_lac = np.sum(final >= 100000) / len(final) * 100
        hit_10k = np.sum(final >= 10000) / len(final) * 100
        hit_zero = np.sum(final < 10) / len(final) * 100
        
        rdict[sname] = {
            'p25': float(p25), 'p50': float(p50), 'p75': float(p75),
            'hit_lac': hit_lac, 'hit_10k': hit_10k, 'hit_zero': hit_zero,
            'eqs': eqs
        }
        
        pnl_pct = (p50 / INITIAL_CAP - 1) * 100
        output = f"  {sname:<25s}: Rs{p50:>10,.0f}  [Rs{p25:>8,.0f} - Rs{p75:>8,.0f}]  +{pnl_pct:6.1f}%"
        print(f"{output}  Hit 1Lac={hit_lac:5.1f}%")
    
    results[label] = rdict

# ====================================================================
# CHART
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
    colors = {'HFT Bot (Realistic)': '#3b82f6', 'HFT Bot (Optimistic)': '#22c55e',
              'Bank Nifty Index': '#6b7280', 'FD / Fixed Deposit': '#f59e0b'}
    
    # CHART 1: Equity curves (log scale, 4 years)
    ax1 = plt.subplot(2, 3, 1)
    ax1.set_title('Growth Over 4 Years (Realistic)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Portfolio Value (INR)', fontsize=10)
    ax1.set_xlabel('Trading Days', fontsize=10)
    ax1.set_yscale('log')
    ax1.axhline(y=100000, color='red', linestyle=':', alpha=0.4, linewidth=1, label='Rs1,00,000 Target')
    
    days_4y = 1460
    for sname in ['HFT Bot (Realistic)', 'HFT Bot (Optimistic)', 'Bank Nifty Index', 'FD / Fixed Deposit']:
        sp = SCENARIOS[sname]
        eqs = sp['sim'](days_4y, n_runs=1000)
        median = np.median(eqs, axis=0)
        p25 = np.percentile(eqs, 25, axis=0)
        p75 = np.percentile(eqs, 75, axis=0)
        
        ax1.plot(median, color=colors[sname], linewidth=2, label=sname)
        ax1.fill_between(range(len(median)), p25, p75, color=colors[sname], alpha=0.08)
    
    ax1.legend(fontsize=8, loc='upper left')
    ax1.grid(True, alpha=0.2)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'Rs{x:,.0f}' if x < 1e6 else f'Rs{x/1e5:.1f}L'))
    
    # CHART 2: 1 Year detailed (linear)
    ax2 = plt.subplot(2, 3, 2)
    ax2.set_title('1 Year Projection (Realistic)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Portfolio Value (INR)', fontsize=10)
    ax2.set_xlabel('Trading Days', fontsize=10)
    ax2.axhline(y=100000, color='red', linestyle=':', alpha=0.4)
    
    for sname in ['HFT Bot (Realistic)', 'Bank Nifty Index']:
        sp = SCENARIOS[sname]
        eqs = sp['sim'](365, n_runs=1000)
        median = np.median(eqs, axis=0)
        p25 = np.percentile(eqs, 25, axis=0)
        p75 = np.percentile(eqs, 75, axis=0)
        ax2.plot(median, color=colors[sname], linewidth=2, label=sname)
        ax2.fill_between(range(len(median)), p25, p75, color=colors[sname], alpha=0.1)
    
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.2)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'Rs{x:,.0f}'))
    
    # CHART 3: Return distribution at 1 year
    ax3 = plt.subplot(2, 3, 3)
    ax3.set_title('Return Distribution (1 Year)', fontsize=12, fontweight='bold')
    ax3.set_xlabel('Return Multiple (x)', fontsize=10)
    ax3.set_ylabel('Frequency', fontsize=10)
    
    r1y = results['1 Year']['HFT Bot (Realistic)']
    finals = r1y['eqs'][:, -1] / INITIAL_CAP
    finals = finals[finals < np.percentile(finals, 98)]
    
    ax3.hist(finals, bins=60, color='#3b82f6', alpha=0.7, edgecolor='white', linewidth=0.5)
    ax3.axvline(x=100, color='red', linestyle='--', linewidth=2, label='100x (1 Lac)')
    ax3.axvline(x=np.median(finals), color='#22c55e', linestyle='-', linewidth=2, 
                label=f'Median: {np.median(finals):.1f}x')
    ax3.axvline(x=1, color='gray', linestyle=':', alpha=0.5)
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.2)
    
    # CHART 4: Probability of hitting target over time
    ax4 = plt.subplot(2, 3, 4)
    ax4.set_title('Probability of Hitting Rs1,00,000', fontsize=12, fontweight='bold')
    ax4.set_xlabel('Trading Days', fontsize=10)
    ax4.set_ylabel('Probability (%)', fontsize=10)
    
    for sname in ['HFT Bot (Realistic)', 'HFT Bot (Optimistic)']:
        probs = []
        for d in range(30, min(1095, 1461), 30):
            sp = SCENARIOS[sname]
            eqs = sp['sim'](d, n_runs=500)
            prob = np.sum(eqs[:, -1] >= 100000) / eqs.shape[0] * 100
            probs.append((d, prob))
        
        x = [p[0] for p in probs]
        y = [p[1] for p in probs]
        ax4.plot(x, y, color=colors[sname], linewidth=2, marker='o', markersize=3, label=sname)
    
    ax4.axhline(y=50, color='gray', linestyle=':', alpha=0.5)
    ax4.legend(fontsize=9)
    ax4.grid(True, alpha=0.2)
    ax4.set_ylim(0, 105)
    
    # CHART 5: Monthly PnL heatmap (conceptual)
    ax5 = plt.subplot(2, 3, 5)
    ax5.set_title('Monthly Return Distribution', fontsize=12, fontweight='bold')
    ax5.set_xlabel('Month', fontsize=10)
    ax5.set_ylabel('Return (%)', fontsize=10)
    
    sp = SCENARIOS['HFT Bot (Realistic)']
    eqs = sp['sim'](365, n_runs=1000)
    monthly_rets = []
    for m in range(1, 13):
        day = m * 30
        if day >= eqs.shape[1]: break
        vals = eqs[:, day] / eqs[:, max(day-30, 0)] - 1
        vals = vals * 100
        vals = vals[vals < np.percentile(vals, 99)]
        monthly_rets.append(vals)
    
    bp = ax5.boxplot(monthly_rets, patch_artist=True, showfliers=False)
    for patch in bp['boxes']:
        patch.set_facecolor('#3b82f6')
        patch.set_alpha(0.5)
    ax5.axhline(y=0, color='red', linestyle=':', alpha=0.5)
    ax5.grid(True, alpha=0.2)
    
    # CHART 6: Summary table
    ax6 = plt.subplot(2, 3, 6)
    ax6.axis('off')
    ax6.set_title('Key Projections (Realistic)', fontsize=12, fontweight='bold')
    
    table_data = []
    for label, days in TARGETS[:5]:
        r = results[label]['HFT Bot (Realistic)']
        mult = r['p50'] / INITIAL_CAP
        table_data.append([label.split('(')[0].strip(), f"{days}", f"Rs{r['p25']:,.0f}", 
                          f"Rs{r['p50']:,.0f}", f"Rs{r['p75']:,.0f}", f"{mult:.1f}x",
                          f"{r['hit_lac']:.0f}%", f"{r['hit_10k']:.0f}%"])
    
    col_lbls = ['Period', 'Days', 'P25', 'P50', 'P75', 'Mult', '1Lac', '10K']
    tbl = ax6.table(cellText=table_data, colLabels=col_lbls, loc='center', cellLoc='center',
                    colWidths=[0.12]*8)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    tbl.scale(1, 1.6)
    
    for j in range(8):
        tbl[0, j].set_facecolor('#1e3a5f')
        tbl[0, j].set_text_props(color='white', fontweight='bold')
    for i in range(1, len(table_data)+1):
        for j in range(8):
            if j >= 5 and '100' in table_data[i-1][j]:
                pct = int(table_data[i-1][j].replace('%',''))
                if pct >= 80: tbl[i, j].set_facecolor('#bbf7d0')
                elif pct >= 30: tbl[i, j].set_facecolor('#fef08a')
    
    plt.suptitle(f'MEME HFT AGENT — Return Projection (Start: Rs{INITIAL_CAP:,} on {START_DATE.strftime("%d %b %Y")})',
                 fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout(pad=3)
    
    chart_path = 'meme_hft_projection.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"  Chart saved: {chart_path}")
    
except ImportError:
    print(f"  [WARN] matplotlib not available. Installing...")
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'matplotlib'], capture_output=True)
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        print(f"  matplotlib installed. Re-run to generate chart.")
    except:
        print(f"  Could not install matplotlib. Data saved to JSON only.")

# ====================================================================
# FINAL TABLE
# ====================================================================
print(f"\n{'='*100}")
print(f"  PROJECTION SUMMARY — MEME HFT AGENT (Realistic, Decay-Adjusted)")
print(f"{'='*100}")
print(f"  {'Period':<20s} {'Days':>5s} {'P25':>14s} {'P50':>14s} {'P75':>14s} {'Mult':>8s} {'Hit 1Lac':>10s}")
print(f"  {'-'*20} {'-'*5} {'-'*14} {'-'*14} {'-'*14} {'-'*8} {'-'*10}")

for label, days in TARGETS:
    r = results[label]['HFT Bot (Realistic)']
    mult = r['p50'] / INITIAL_CAP
    print(f"  {label:<20s} {days:>5d} Rs{r['p25']:>11,.0f} Rs{r['p50']:>11,.0f} Rs{r['p75']:>11,.0f} {mult:>7.1f}x {r['hit_lac']:>8.1f}%")

print(f"\n{'='*100}")
r_20d = results['20 days (Aug 15)']['HFT Bot (Realistic)']
r_1m = results['1 Month']['HFT Bot (Realistic)']
r_1y = results['1 Year']['HFT Bot (Realistic)']
r_4y = results['4 Years']['HFT Bot (Realistic)']

print(f"""
  START: Rs{INITIAL_CAP:,} on {START_DATE.strftime('%d %b %Y')}
  Strategy: Meme coin HFT scalping with cost-adjusted execution
  Note: Returns decay over time as capital grows (slippage, market impact)

  Aug 15, 2026 (20 days):
    Median: Rs{r_20d['p50']:,.0f} | Range (P25-P75): Rs{r_20d['p25']:,.0f} - Rs{r_20d['p75']:,.0f}
    vs Bank Nifty: Rs{INITIAL_CAP * (1.00047)**20:,.0f}

  1 Month:
    Median: Rs{r_1m['p50']:,.0f} | Hit Rs10,000: {r_1m['hit_10k']:.1f}% | Hit Rs1Lac: {r_1m['hit_lac']:.1f}%

  1 Year:
    Median: Rs{r_1y['p50']:,.0f} ({r_1y['p50']/INITIAL_CAP:.0f}x)
    Range (P25-P75): Rs{r_1y['p25']:,.0f} - Rs{r_1y['p75']:,.0f}
    Hit Rs1Lac: {r_1y['hit_lac']:.0f}%
    vs Bank Nifty: Rs{INITIAL_CAP * (1.00047)**365:,.0f}
    vs FD (7.5%%): Rs{INITIAL_CAP * (1+0.075)**1:,.0f}

  4 Years:
    Median: Rs{r_4y['p50']:,.0f}
    Hit Rs1Lac: {r_4y['hit_lac']:.0f}%

  WARNING: These are statistical projections based on limited test data.
  HFT/meme coin trading carries extreme risk of total capital loss.
  Never invest money you cannot afford to lose.
""")

# Save JSON
out = {'generated': datetime.now().isoformat(), 'starting_capital': INITIAL_CAP,
       'projections': {}}
for label, days in TARGETS:
    r = results[label]['HFT Bot (Realistic)']
    out['projections'][label] = {'days': days, 'p25': r['p25'], 'p50': r['p50'], 'p75': r['p75']}

with open('meme_hft_projection.json', 'w') as f:
    json.dump(out, f, indent=2)
print(f"  JSON: meme_hft_projection.json")
