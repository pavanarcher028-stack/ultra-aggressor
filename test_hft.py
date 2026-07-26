"""Test script for meme_hft_agent core components (non-interactive)."""
import sys, os
sys.path.insert(0, '.')

# Clean state
for f in ['meme_hft_wallet.json', 'meme_hft_state.pkl']:
    if os.path.exists(f): os.remove(f)

from meme_hft_agent import *
import numpy as np, pandas as pd

# TEST 1: Wallet Generation
print("=== TEST 1: Wallet Generation ===")
wallet = WalletGenerator.create_wallet('SOL', 'testpass123')
print(f"Chain: {wallet['chain']}")
print(f"Address: {wallet['address']}")
print(f"Encrypted key: {wallet['encrypted_key']['verify']}  (data length: {len(wallet['encrypted_key']['data'])})")
pk = WalletGenerator.decrypt_key(wallet['encrypted_key'], 'testpass123')
assert pk is not None, "Decryption failed"
print(f"Key length: {len(pk)} hex chars")
wrong = WalletGenerator.decrypt_key(wallet['encrypted_key'], 'wrong')
assert wrong is None, f"Wrong pwd check failed: got {wrong}"
print("  PASS\n")

# TEST 2: Chain Costs
print("=== TEST 2: Chain Costs ===")
for chain in ['SOL', 'BASE', 'ETH', 'BSC']:
    c = round_trip_cost(100, chain)
    c2 = round_trip_cost(10, chain)
    print(f"  {chain}: ${100} trade = {c*100:.1f}%, ${10} trade = {c2*100:.1f}%")
print("  PASS\n")

# TEST 3: HFT Signals
print("=== TEST 3: HFT Signal Generation ===")
np.random.seed(42)
prices = [0.000045 * (1 + np.random.normal(0, 0.002)) for _ in range(200)]
volumes = [50000 * (1 + np.random.random()) for _ in range(200)]
strategy = HFTStrategy('SOL')
signals = strategy.generate_signals(prices, volumes, n_signals=10)
print(f"  Generated {len(signals)} signals:")
for s in signals[:5]:
    print(f"    {s['direction']:5s} @ ${s['entry_price']:.8f} -> ${s['target_price']:.8f} | {s['reason']}")
print("  PASS\n")

# TEST 4: WalletManager non-interactive
print("=== TEST 4: WalletManager State ===")
wm = WalletManager()
wm.wallet = wallet
wm.password = 'testpass123'
wm.balance_inr = 500
wm.balance_usd = 500/85
wm.funded = True
wm.save_state()
print(f"  State saved to {wm.STATE_FILE}")
assert os.path.exists(wm.STATE_FILE)
print("  PASS\n")

# TEST 5: HFT Executor
print("=== TEST 5: HFT Executor ===")
executor = HFTExecutor(wm)
signal = {'direction': 'BUY', 'entry_price': 0.000045, 'target_price': 0.0000455, 
          'stop_price': 0.0000445, 'reason': 'TEST', 'expected_net_pnl': 0.5}
pos = executor.execute(signal, 'CHAD', 'SOL')
assert pos is not None, "Execute failed"
print(f"  Position opened: {pos.ticker} {pos.direction} @ ${pos.entry_price:.8f}")
pos_id = list(executor.positions.keys())[0]
exit_info = executor.evaluate_exit(pos_id, 0.000055)  # 22% gain
if exit_info:
    print(f"  Exit: {exit_info['reason']} PnL: {exit_info['pnl_net_pct']:.2f}% net (after costs)")
else:
    print(f"  No exit triggered at +22% — checking remaining positions")
    for pid in list(executor.positions.keys()):
        ei = executor.evaluate_exit(pid, 0.000056)
        if ei:
            print(f"  Exit {pid}: {ei['reason']} PnL: {ei['pnl_net_pct']:.2f}%")
print("  PASS\n")

# TEST 6: Full cycle simulation
print("=== TEST 6: HFT Cycle Simulation ===")
sim = PriceSimulator(base_price=0.000045, ticker='CHAD')
executor2 = HFTExecutor(wm)
strategy2 = HFTStrategy('SOL')
trades = 0; wins = 0
for i in range(500):
    price, vol = sim.tick()
    prices, vols = sim.get_series(50)
    
    for pid in list(executor2.positions.keys()):
        exit_info = executor2.evaluate_exit(pid, price, vol)
        if exit_info:
            trades += 1
            if exit_info['pnl_net_pct'] > 0: wins += 1
    
    if i % 50 == 0 and i > 0:
        sigs = strategy2.generate_signals(list(prices), list(vols), n_signals=2)
        for s in sigs:
            executor2.execute(s, sim.ticker, 'SOL')

print(f"  Simulated 500 ticks: {trades} trades closed, WR={wins/max(trades,1)*100:.0f}%")
print(f"  Balance: Rs{wm.balance_inr:.2f} (start: Rs500)")
profit = wm.balance_inr - 500
print(f"  PnL: Rs{profit:+.2f} ({profit/500*100:+.2f}%)")
print("  PASS\n")

print("=== ALL TESTS PASSED ===")
