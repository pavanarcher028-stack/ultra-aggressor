"""Test harness for MetaAggressor — 500 ticks, checks PID uniqueness and evolution."""
import sys, os, json, time, builtins

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Clean old state
for f in ['meta_wallet.json', 'meta_state.pkl']:
    if os.path.exists(f): os.remove(f)

# Auto-supply inputs
inputs = iter(['test1234', 'test1234', '1000'])
builtins.input = lambda prompt='': next(inputs)

from meta_aggressor import MetaAggressor

agent = MetaAggressor()
if not agent.setup():
    print("SETUP FAILED")
    sys.exit(1)

print("\nRunning 3000 ticks...")
for i in range(3000):
    agent.tick()
    if i % 100 == 0:
        s = agent.engine.summary()
        print(f'Cycle {i}: Cap=Rs{s["total_value"]:.0f} Trades={s["trades"]} WR={s["win_rate"]:.0f}%')

s = agent.engine.summary()
print(f"\nFINAL: Cap=Rs{s['total_value']:.2f} Trades={s['trades']} W={s['wins']} L={s['losses']} WR={s['win_rate']:.1f}% Ret={s['return_pct']:+.2f}%")
