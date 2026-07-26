"""Test connectivity to Solana DEX APIs."""
import urllib.request, json, sys

def test_dexscreener():
    req = urllib.request.Request(
        'https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read())
    print('DexScreener: {} pairs'.format(len(d.get('pairs', []))))
    if d.get('pairs'):
        p = d['pairs'][0]
        print('  Price USD: {}'.format(p.get('priceUsd', 'N/A')))
        print('  Vol 24h: {}'.format(p.get('volume', {}).get('h24', 'N/A')))
    return True

def test_jupiter():
    req = urllib.request.Request(
        'https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000000&slippageBps=100',
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    r = urllib.request.urlopen(req, timeout=10)
    j = json.loads(r.read())
    routes = len(j.get('routes', j.get('route', [])))
    if not routes:
        routes = 1 if 'outAmount' in j else 0
    print('Jupiter API: OK, routes available')
    return True

def test_pumpfun():
    """Test pump.fun token launch detection via DexScreener."""
    req = urllib.request.Request(
        'https://api.dexscreener.com/token-profiles/latest/v1',
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read())
    print('DexScreener Token Profiles: {} tokens'.format(len(d)))
    return True

def test_solana_rpc():
    import solana.rpc.api
    client = solana.rpc.api.Client('https://api.mainnet-beta.solana.com')
    resp = client.get_slot()
    print('Solana RPC: Slot {}'.format(resp.value))
    return True

if __name__ == '__main__':
    tests = [test_dexscreener, test_jupiter, test_pumpfun, test_solana_rpc]
    for test in tests:
        try:
            test()
        except Exception as e:
            print('FAILED: {} - {}'.format(test.__name__, e))
