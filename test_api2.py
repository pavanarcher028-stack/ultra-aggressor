"""Test all working APIs."""
import urllib.request, json

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())

# 1. Jupiter API v1 swap
print("=== Jupiter API v1 ===")
j = fetch_json('https://api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000000&slippageBps=100')
print('Keys:', list(j.keys()))
print('Price impact:', j.get('priceImpactPct', 'N/A'))
print('Output amount:', j.get('outAmount', 'N/A'))
print('Route count:', len(j.get('routePlan', [])))

# 2. Get swap instructions
print("\n=== Jupiter Swap Instructions ===")
j2 = fetch_json('https://api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=10000000&slippageBps=100')
print('OK - can get quotes')

# 3. DexScreener new tokens
print("\n=== DexScreener Latest Tokens ===")
d = fetch_json('https://api.dexscreener.com/token-profiles/latest/v1')
print('New tokens:', len(d))
if d:
    t = d[0]
    print('First token:', t.get('tokenAddress', 'N/A')[:12] + '...')
    print('Chain:', t.get('chainId', 'N/A'))

# 4. DexScreener token search
print("\n=== DexScreener Search ===")
d2 = fetch_json('https://api.dexscreener.com/latest/dex/search?q=SOL')
print('Results:', len(d2.get('pairs', [])))

# 5. Jupiter price API
print("\n=== Jupiter Price API ===")
try:
    j3 = fetch_json('https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112')
    price = j3.get('data', {}).get('So11111111111111111111111111111111111111112', {}).get('price', 'N/A')
    print('SOL Price: $' + str(price))
except Exception as e:
    print('Price API:', e)

print("\nAll API tests complete!")
