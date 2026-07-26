import pandas as pd
import numpy as np

ec = pd.read_csv('equity_curve_v3.csv', index_col=0, parse_dates=True)
ec.columns = ['nav']
ec['ret'] = ec['nav'].pct_change()

print('=== EQUITY CURVE ANALYSIS (v3 - Adaptive TSMOM Long+Short) ===')
print(f'Period: {ec.index[0].date()} to {ec.index[-1].date()}')
print(f'Total days: {len(ec)}')
print(f'Start NAV: ${ec.iloc[0,0]:,.2f}')
print(f'Peak NAV:  ${ec["nav"].max():,.2f} on {ec["nav"].idxmax().date()}')
print(f'Final NAV: ${ec.iloc[-1,0]:,.2f}')

ec['peak'] = ec['nav'].cummax()
ec['dd'] = (ec['peak'] - ec['nav']) / ec['peak']
print(f'Max DD%:   {ec["dd"].max()*100:.2f}% on {ec["dd"].idxmax().date()}')

for yr in sorted(ec.index.year.unique()):
    yr_data = ec[ec.index.year == yr]
    sn = yr_data.iloc[0]['nav']
    en = yr_data.iloc[-1]['nav']
    yr_ret = (en / sn - 1) * 100
    yr_peak = yr_data['nav'].max()
    yr_dd = (yr_peak - yr_data['nav'].min()) / yr_peak
    print(f'  {yr}: Return={yr_ret:+.2f}%  MaxDD={yr_dd*100:.2f}%  '
          f'Start=+${sn:,.0f} End=+${en:,.0f}')

mr = ec['ret'].resample('ME').apply(lambda x: (1+x).prod()-1) * 100
print(f'\nMonthly stats:')
print(f'  Positive months: {(mr > 0).sum()}/{len(mr)}')
print(f'  Avg monthly: {mr.mean():+.2f}%')
print(f'  Std monthly: {mr.std():+.2f}%')
print(f'  Best month:  {mr.max():+.2f}%')
print(f'  Worst month: {mr.min():+.2f}%')

# Rolling Sharpe
rs = ec['ret'].rolling(63).mean() / ec['ret'].rolling(63).std() * np.sqrt(252)
print(f'\nRolling 63d Sharpe:')
print(f'  Mean: {rs.mean():.3f}')
print(f'  Std:  {rs.std():.3f}')
print(f'  Min:  {rs.min():.3f}')
print(f'  Max:  {rs.max():.3f}')
