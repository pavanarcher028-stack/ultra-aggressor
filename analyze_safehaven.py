import pandas as pd
import numpy as np

ec = pd.read_csv('equity_curve_safehaven.csv', index_col=0, parse_dates=True)
ec.columns = ['nav']
ec['peak'] = ec['nav'].cummax()
ec['dd'] = (ec['peak'] - ec['nav']) / ec['peak']

print('=== SAFE-HAVEN STRATEGY EQUITY CURVE ===')
start_nav = ec.iloc[0,0]; peak_nav = ec['nav'].max(); final_nav = ec.iloc[-1,0]
peak_date = ec['nav'].idxmax().date()
print(f'Start: {ec.index[0].date()}  NAV=+${start_nav:,.0f}')
print(f'Peak:  {peak_date}  NAV=+${peak_nav:,.0f}')
print(f'Final: {ec.index[-1].date()}  NAV=+${final_nav:,.0f}')
print(f'Max DD: {ec["dd"].max()*100:.2f}%')

for yr in sorted(ec.index.year.unique()):
    yd = ec[ec.index.year == yr]
    if len(yd) < 2:
        continue
    ret = (yd['nav'].iloc[-1] / yd['nav'].iloc[0] - 1) * 100
    peak_dd = (yd['peak'].max() - yd['nav'].min()) / yd['peak'].max() * 100
    print(f'  {yr}: {ret:+.2f}%  (peak DD: {peak_dd:.1f}%)')

mr = ec['nav'].resample('ME').apply(lambda x: (x.iloc[-1]/x.iloc[0]-1)*100).dropna()
wins = (mr > 0).sum(); total = len(mr)
print(f'\nMonthly: mean={mr.mean():+.2f}% | std={mr.std():.2f}% | win={wins}/{total}')
print(f'Best: {mr.max():+.2f}% | Worst: {mr.min():+.2f}%')

print(f'\nCAGR: {((final_nav/start_nav)**(252/len(ec))-1)*100:.2f}%')
print(f'Sharpe (ann): {ec["nav"].pct_change().dropna().mean()/ec["nav"].pct_change().dropna().std()*np.sqrt(252):.3f}')

# Sortino
rets = ec['nav'].pct_change().dropna()
neg = rets[rets < 0]
ds = neg.std() if len(neg) > 0 else 0.0001
sortino = rets.mean() / ds * np.sqrt(252)
print(f'Sortino (ann): {sortino:.3f}')
