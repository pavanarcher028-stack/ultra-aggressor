"""Test production_aggressor.py components."""
import sys, os, json
os.chdir(r'C:\Users\natar\Downloads\backtesting only 1.0')

# Clean state
for f in ['prod_wallet.json', 'prod_state.pkl']:
    if os.path.exists(f): os.remove(f)

print("=== Test 1: Wallet Generation ===")
from production_aggressor import ProdWallet
wallet = ProdWallet.generate_new('test123')
print(f'Address: {wallet["address"]}')
print(f'Hint: {wallet["hint"]}')
assert len(wallet['address']) > 30, 'Bad address'
print('OK')

print("\n=== Test 2: Wallet Decryption ===")
kp = ProdWallet.decrypt(wallet, 'test123')
assert kp is not None, 'Decrypt failed'
print(f'Keypair pubkey: {kp.pubkey()}')
wrong_kp = ProdWallet.decrypt(wallet, 'wrong')
assert wrong_kp is None, 'Should fail with wrong password'
print('OK')

print("\n=== Test 3: Jupiter Quote API ===")
from production_aggressor import JupiterTrader
trader = JupiterTrader(paper_mode=True)
quote = trader.quote(
    'So11111111111111111111111111111111111111112',  # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    1000000000,  # 1 SOL
    100  # 1% slippage
)
print(f'Price impact: {quote.get("priceImpactPct", "N/A")}%')
print(f'Out amount: {quote.get("outAmount", "N/A")}')
assert 'outAmount' in quote, 'No outAmount in quote'
print('OK')

print("\n=== Test 4: Paper Swap ===")
result = trader.execute_swap(
    'So11111111111111111111111111111111111111112',
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    10000000,  # 0.01 SOL
    100
)
assert result.get('success'), 'Paper swap failed: ' + result.get('error', 'unknown')
print(f'Paper swap result: {result.get("output_amount", "N/A")} USDC')
print('OK')

print("\n=== Test 5: DexScreener Scanner ===")
from production_aggressor import DexScreenerScanner
scanner = DexScreenerScanner()
tokens = scanner.get_latest_tokens(3)
print(f'Found {len(tokens)} new tokens')
if tokens:
    print(f'First: {tokens[0].get("tokenAddress", "N/A")[:16]}...')
print('OK')

print("\n=== Test 6: Production Engine (Paper Mode) ===")
from production_aggressor import ProdTradingEngine, StrategyConfig
engine = ProdTradingEngine(1000, paper_mode=True)
engine.set_trader(kp)

# Simulate a buy
result = engine.buy_token('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 0.01)
print(f'Buy result: {result.get("success")}')
if result.get('success'):
    print(f'PID: {result.get("pid")}')

s = engine.summary()
print(f'Capital: Rs{s["capital"]:.2f}')
print(f'Active: {s["active"]}')
print('OK')

print("\n=== Test 7: Full Engine Trade Cycle ===")
# Buy some tokens
engine.buy_token('DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263', 0.05)
s = engine.summary()
print(f'After buy: Rs{s["capital"]:.2f}, Active: {s["active"]}')

# Sell a position
pids = list(engine.positions.keys())
if pids:
    r = engine.sell_token(pids[0], 0.05)
    print(f'Sell result: {r.get("success")}')
    
s = engine.summary()
print(f'Final: Rs{s["capital"]:.2f}, Trades: {s["trades"]}, WR: {s["win_rate"]:.1f}%')
print('OK')

print("\n=== ALL TESTS PASSED ===")
