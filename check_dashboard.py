import urllib.request, json
r = urllib.request.urlopen('http://localhost:8765/api/status', timeout=5)
d = json.loads(r.read())
s = d['summary']
print('Dashboard OK!')
print('  Value: Rs{:.0f}'.format(s['total_value']))
print('  Trades: {}'.format(s['trades']))
print('  WR: {:.1f}%'.format(s['win_rate']))
print('  Config: {}'.format(s['config']))
print('  Running: {}'.format(d['running']))
print('  Regime: {}'.format(d.get('regime', 'N/A')))
print('  Withdrawn: Rs{:.0f}'.format(s['total_withdrawn']))
# Check HTML dashboard
r2 = urllib.request.urlopen('http://localhost:8765/', timeout=5)
html = r2.read().decode()
print('  Dashboard HTML: {} bytes loaded'.format(len(html)))
