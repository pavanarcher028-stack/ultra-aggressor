import json
with open('focused_results.json') as f: data = json.load(f)
data.sort(key=lambda x: x['score'], reverse=True)
print('Top 20:')
for i,r in enumerate(data[:20]):
    m=r['metrics']
    print(f"{i+1:>2}. {r['strategy']:16s} {r['ticker']:8s} WR={m['win_rate']*100:5.1f}% DD={m['max_dd']*100:5.1f}% Sharpe={m['sharpe']:.2f} Ann={m['annualized_return']*100:5.1f}% S={r['score']}")
max_ann = max(data, key=lambda x: x['metrics']['annualized_return'])
max_sr = max(data, key=lambda x: x['metrics']['sharpe'])
print(f"Max Ann: {max_ann['strategy']} {max_ann['ticker']} Ann={max_ann['metrics']['annualized_return']*100:.1f}% Sharpe={max_ann['metrics']['sharpe']:.2f} DD={max_ann['metrics']['max_dd']*100:.1f}%")
print(f"Max Sharpe: {max_sr['strategy']} {max_sr['ticker']} Ann={max_sr['metrics']['annualized_return']*100:.1f}% Sharpe={max_sr['metrics']['sharpe']:.2f} DD={max_sr['metrics']['max_dd']*100:.1f}%")
targets=[('WR',lambda m:40<=m['win_rate']*100<=55),('DD',lambda m:m['max_dd']*100<=20),('Sharpe',lambda m:m['sharpe']>=1.0),('Ann',lambda m:m['annualized_return']*100>=20)]
for l,ch in targets:
    c=sum(1 for r in data if ch(r['metrics']))
    print(f"{l}: {c}/{len(data)} ({c/len(data)*100:.1f}%)")
