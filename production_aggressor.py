"""
PRODUCTION AGGRESSOR — Real Solana Trading with Jupiter & DexScreener
=====================================================================
WARNING: This connects to REAL Solana mainnet. Use --paper flag first.
         Real funds are at risk. Start with small amounts.

Usage:
  python production_aggressor.py --paper       Paper trading (safe)
  python production_aggressor.py --real        REAL MONEY (risk!)
  python production_aggressor.py --dashboard   Web dashboard
  python production_aggressor.py --setup       Create wallet only
"""
import os, json, time, math, hashlib, base58, base64, pickle, sys, threading, random, urllib.request
try:
    import numpy as np
except ImportError:
    class _np: array = staticmethod(lambda x, **kw: x); zeros = staticmethod(lambda *a, **kw: [0]); full = staticmethod(lambda *a, **kw: a[-1] if a else 0)
    np = _np()
from datetime import datetime
from copy import deepcopy
from pathlib import Path
from typing import Optional
import warnings; warnings.filterwarnings('ignore')

BASE = Path(__file__).parent.absolute()
os.chdir(BASE)

# ====================================================================
# SOLANA IMPORTS (with ARM64/Termux fallback)
# ====================================================================
HAS_SOLDERS = False
try:
    from solders.pubkey import Pubkey
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solana.rpc.types import TxOpts
    from solana.transaction import Transaction
    HAS_SOLDERS = True
except ImportError:
    HAS_SOLDERS = False

# Pure-Python ed25519 (no deps needed, only hashlib)
def _ed25519_sign(seed_32: bytes, msg: bytes) -> bytes:
    p = 2**255 - 19
    L = 2**252 + 27742317777372353535851937790883648493
    d = -121665 * pow(121666, -1, p) % p
    Bx = 15112221349535891456845458038841102787007749669715824649066461222221761199150
    By = 46316835694926478169428394003475163141307991866260927520185503448234899940080
    B = (Bx % p, By % p)
    def modp(x): return x % p
    def add(P, Q):
        x1, y1 = P; x2, y2 = Q
        x3 = (x1*y2 + y1*x2) * pow(1 + d*x1*x2*y1*y2, -1, p) % p
        y3 = (y1*y2 + x1*x2) * pow(1 - d*x1*x2*y1*y2, -1, p) % p
        return (x3, y3)
    def mul(P, e):
        if e == 0: return (0, 1)
        Q = mul(P, e//2); Q = add(Q, Q)
        return add(Q, P) if e & 1 else Q
    def enc(P):
        x, y = P; inv = pow(1 + x, -1, p)
        return ((y * inv) % p).to_bytes(32, 'little')
    def dec(s):
        y = int.from_bytes(s, 'little') % p
        x = pow((y*y - 1) * pow(d*y*y + 1, -1, p), (p+3)//8, p)
        if (x*x - (y*y - 1) * pow(d*y*y + 1, -1, p)) % p: x = x * pow(2, (p-1)//4, p) % p
        return (x if x % 2 == 0 else p - x, y)
    h = hashlib.sha512(seed_32).digest()
    a = (int.from_bytes(h[:32], 'little') & ((1 << 254) - 8) | (1 << 254)) % L
    prefix = h[32:]
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), 'little') % L
    R = mul(B, r)
    k = int.from_bytes(hashlib.sha512(enc(R) + enc(mul(B, a)) + msg).digest(), 'little') % L
    s = (r + k * a) % L
    return enc(R) + s.to_bytes(32, 'little')

def _ed25519_pubkey(seed_32: bytes) -> bytes:
    L = 2**252 + 27742317777372353535851937790883648493
    p = 2**255 - 19
    d = -121665 * pow(121666, -1, p) % p
    Bx = 15112221349535891456845458038841102787007749669715824649066461222221761199150
    By = 46316835694926478169428394003475163141307991866260927520185503448234899940080
    B = (Bx % p, By % p)
    def add(P, Q):
        x1, y1 = P; x2, y2 = Q
        x3 = (x1*y2 + y1*x2) * pow(1 + d*x1*x2*y1*y2, -1, p) % p
        y3 = (y1*y2 + x1*x2) * pow(1 - d*x1*x2*y1*y2, -1, p) % p
        return (x3, y3)
    def mul(P, e):
        if e == 0: return (0, 1)
        Q = mul(P, e//2); Q = add(Q, Q)
        return add(Q, P) if e & 1 else Q
    def enc(P):
        x, y = P; inv = pow(1 + x, -1, p)
        return ((y * inv) % p).to_bytes(32, 'little')
    h = hashlib.sha512(seed_32).digest()
    a = (int.from_bytes(h[:32], 'little') & ((1 << 254) - 8) | (1 << 254)) % L
    return enc(mul(B, a))

class Pubkey:
    def __init__(self, val): self.val = val
    def __str__(self): return str(self.val)
    @staticmethod
    def from_string(s): return Pubkey(s)

class Keypair:
    def __init__(self): self._seed = os.urandom(64)
    @staticmethod
    def from_bytes(b): k = Keypair(); k._seed = b; return k
    @staticmethod
    def from_seed(s): k = Keypair(); k._seed = s + _ed25519_pubkey(s) if len(s) < 64 else s; return k
    @staticmethod
    def from_base58_string(s): k = Keypair(); raw = base58.b58decode(s); k._seed = raw if len(raw) == 64 else raw + _ed25519_pubkey(raw); return k
    def pubkey(self): return Pubkey(base58.b58encode(_ed25519_pubkey(self._seed[:32])).decode())
    def sign(self, msg): return _ed25519_sign(self._seed[:32], msg)
    def __bytes__(self): return self._seed[:64]

class AsyncClient:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def get_balance(self, *a, **kw):
        class R: value = 0
        return type('o',(),{'result':R()})()

Confirmed = 'confirmed'
HAS_SOLDERS = False

# ====================================================================
# CONFIG
# ====================================================================
TARGET = 999999999  # No limit — unlimited trading
MAX_REAL_RISK = 999999999  # No cap — risk all
PAPER_CAPITAL_INR = 1000  # Paper starting balance: ₹1000
INR_PER_USD = 85
SOLANA_RPC = 'https://api.mainnet-beta.solana.com'
JUPITER_API = 'https://quote-api.jup.ag/v6'
DEXSCREENER_API = 'https://api.dexscreener.com'
WSOL_MINT = 'So11111111111111111111111111111111111111112'
USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'

# Real token mints (actively traded on Jupiter, verified with pairs/liquidity)
REAL_MINTS = [
    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
    'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',  # dogwifhat
    '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',  # POPCAT
    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',   # JUP
    'ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82',   # BOME
    '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv',  # PENGU
    'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5',   # MEW
    '3srC8ksB2EiJynMGfk72mDk7joF56Aqz3NjwQEyEki7c',  # FARTCOIN
    'Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump',  # CHILLGUY
    '3S8qX1MsMqRbiwKg2cQyx7nis1oHMgaCuc9c4VfvVdPN',  # MOTHER
]
TOKEN_NAMES = {
    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 'BONK',
    'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 'WIF',
    '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': 'POPCAT',
    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',
    'ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82': 'BOME',
    '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv': 'PENGU',
    'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': 'MEW',
    '3srC8ksB2EiJynMGfk72mDk7joF56Aqz3NjwQEyEki7c': 'FARTCOIN',
    'Df6yfrKC8kZE3KNkrHERKzAetSxbrWeniQfyJY4Jpump': 'CHILLGUY',
    '3S8qX1MsMqRbiwKg2cQyx7nis1oHMgaCuc9c4VfvVdPN': 'MOTHER',
}

# Fee model (realistic for Solana)
FEE_BUY = 0.01  # 1% Jupiter fee + slippage
FEE_SELL = 0.01
SOL_GAS_ESTIMATE = 0.000005  # ~0.000005 SOL per tx (buy + sell = 2 txs)
# A trade must clear this before we bank it on the time exit — otherwise the
# 2% round-trip cost turns a "no move" trade into a guaranteed loss.
FEE_BREAKEVEN = FEE_BUY + FEE_SELL + 0.005  # ~2.5% minimum move worth taking
# Win-rate gate: strategies below this after MIN_WR_TARGET trades get disabled.
MIN_WIN_RATE = 0.40
MIN_WR_TARGET_TRADES = 10

STATE_FILE = 'prod_state.pkl'
WALLET_FILE = 'prod_wallet.json'
CONFIG_FILE = 'prod_config.json'

# ====================================================================
# PRODUCTION WALLET (Real SOL keypair)
# ====================================================================
class ProdWallet:
    """Manage a real Solana wallet from private key."""
    
    @staticmethod
    def create_from_private_key(private_key_b58: str) -> dict:
        """Import from existing Base58 private key (from Phantom/Backpack)."""
        try:
            keypair = Keypair.from_base58_string(private_key_b58)
            pubkey = str(keypair.pubkey())
            return {
                'address': pubkey,
                'private_key': private_key_b58,
                'created': datetime.now().isoformat(),
                'chain': 'SOL'
            }
        except Exception as e:
            raise ValueError(f'Invalid private key: {e}')
    
    @staticmethod
    def generate_new() -> dict:
        """Generate a new random Solana keypair."""
        keypair = Keypair()
        priv_b58 = base58.b58encode(bytes(keypair)).decode()
        return ProdWallet.create_from_private_key(priv_b58)
    
    @staticmethod
    def load_keypair(wallet: dict) -> Optional[Keypair]:
        """Load keypair from stored private_key."""
        try:
            if 'private_key' in wallet:
                return Keypair.from_base58_string(wallet['private_key'])
            # Legacy: new wallet has been generated for old format
            return None
        except:
            return None
    
    @staticmethod
    def get_balance(keypair: Keypair) -> float:
        """Get SOL balance via HTTP RPC (no solders needed)."""
        payload = json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'getBalance',
            'params': [str(keypair.pubkey())]
        }).encode()
        req = urllib.request.Request(SOLANA_RPC, data=payload, headers={
            'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return resp.get('result', {}).get('value', 0) / 1e9

# ====================================================================
# JUPITER TRADER (Real swap execution)
# ====================================================================
class JupiterTrader:
    """Execute real swaps via Jupiter API v1."""
    
    _last_api_call = 0
    _api_lock = threading.Lock()
    
    def __init__(self, keypair: Keypair = None, paper_mode: bool = True):
        self.keypair = keypair
        self.paper_mode = paper_mode
        self.last_quote = None
    
    def _rate_limit(self):
        """Ensure at least 0.8s between Jupiter API calls."""
        with self._api_lock:
            now = time.time()
            wait = 0.8 - (now - self._last_api_call)
            if wait > 0:
                time.sleep(wait)
            self.__class__._last_api_call = time.time()
    
    def _fetch(self, url: str) -> dict:
        """Synchronous HTTP fetch with 429 retry."""
        for att in range(3):
            try:
                self._rate_limit()
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read())
            except Exception as e:
                if '429' in str(e) and att < 2:
                    time.sleep(1.5 ** (att + 1))
                    continue
                raise
        return {}
    
    def _post(self, url: str, data: dict) -> dict:
        """Synchronous HTTP POST with 429 retry."""
        for att in range(3):
            try:
                self._rate_limit()
                payload = json.dumps(data).encode()
                req = urllib.request.Request(url, data=payload, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Content-Type': 'application/json'
                })
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except Exception as e:
                if '429' in str(e) and att < 2:
                    time.sleep(1.5 ** (att + 1))
                    continue
                raise
        return {}
    
    def quote(self, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int = 100) -> dict:
        """Get a swap quote from Jupiter."""
        url = (f'{JUPITER_API}/quote?inputMint={input_mint}&outputMint={output_mint}'
               f'&amount={amount_lamports}&slippageBps={slippage_bps}')
        self.last_quote = self._fetch(url)
        return self.last_quote
    
    def get_swap_instructions(self, quote_response: dict, user_pubkey: str) -> dict:
        """Get swap transaction instructions from Jupiter."""
        url = f'{JUPITER_API}/swap-instructions'
        payload = {
            'quoteResponse': quote_response,
            'userPublicKey': user_pubkey,
            'wrapAndUnwrapSol': True,
            'dynamicComputeUnitLimit': True,
            'prioritizationFeeLamports': 1000  # Small priority fee
        }
        return self._post(url, payload)
    
    def execute_swap(self, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int = 100) -> dict:
        """Execute a swap (paper or real)."""
        if not self.keypair and not self.paper_mode:
            return {'success': False, 'error': 'No keypair loaded'}
        if self.paper_mode:
            out_amount = int(amount_lamports * random.uniform(0.8, 1.2))
            return {'success': True, 'paper': True, 'input_amount': amount_lamports/1e9, 'output_amount': out_amount/1e6, 'price_impact_pct': random.uniform(0.1, 2.0)}
        # Real mode
        quote = self.quote(input_mint, output_mint, amount_lamports, slippage_bps)
        out_amount = int(quote.get('outAmount', 0))
        price_impact = float(quote.get('priceImpactPct', 0))
        try:
            txid = self._execute_real(quote)
            return {'success': True, 'paper': False, 'txid': txid, 'output_amount': out_amount, 'price_impact_pct': price_impact}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _execute_real(self, quote: dict) -> str:
        """Real swap via Jupiter v6 API using pure Python (no solders)."""
        self._rate_limit()
        # Step 1: Get swap transaction from Jupiter
        payload = json.dumps({
            'quoteResponse': quote,
            'userPublicKey': str(self.keypair.pubkey()),
            'wrapAndUnwrapSol': True,
            'dynamicComputeUnitLimit': True,
            'prioritizationFeeLamports': 1000
        }).encode()
        req = urllib.request.Request(f'{JUPITER_API}/swap', data=payload, headers={
            'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            swap_data = json.loads(r.read())
        tx_b64 = swap_data.get('swapTransaction', '')
        if not tx_b64:
            raise ValueError('No swapTransaction in response')
        tx_bytes = base64.b64decode(tx_b64)
        # Step 2: Parse and sign VersionedTransaction manually
        # Format: [compact_array(signatures)][message]
        n_sigs, sigs_len = 0, 0
        if tx_bytes[0] <= 0x7f:
            n_sigs = tx_bytes[0]
            sigs_len = 1 + n_sigs * 64
        else:
            n_sigs = int.from_bytes(tx_bytes[:2], 'little') & 0x3fff
            sigs_len = 2 + n_sigs * 64
        msg_bytes = tx_bytes[sigs_len:]
        sig = self.keypair.sign(msg_bytes)
        # Replace first signature (placeholder) with real one
        sig_start = 1 if tx_bytes[0] <= 0x7f else 2
        new_tx = tx_bytes[:sig_start] + sig + tx_bytes[sig_start+64:]
        new_tx_b64 = base64.b64encode(new_tx).decode()
        # Step 3: Submit to Solana RPC
        rpc_payload = json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'sendTransaction',
            'params': [new_tx_b64, {'encoding': 'base64', 'skipPreflight': False, 'maxRetries': 3}]
        }).encode()
        rpc_req = urllib.request.Request(SOLANA_RPC, data=rpc_payload, headers={
            'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'
        })
        with urllib.request.urlopen(rpc_req, timeout=30) as r:
            rpc_resp = json.loads(r.read())
        if 'result' in rpc_resp:
            return rpc_resp['result']
        raise ValueError(f'RPC error: {rpc_resp.get("error", {}).get("message", str(rpc_resp))}')
    
    def get_token_price(self, mint: str) -> Optional[float]:
        """Get token price from Jupiter."""
        try:
            url = f'{JUPITER_API}/quote?inputMint={mint}&outputMint={USDC_MINT}&amount=1000000&slippageBps=100'
            quote = self._fetch(url)
            out_amount = int(quote.get('outAmount', 0))
            if out_amount > 0:
                return out_amount / 1e6  # USDC has 6 decimals
            return None
        except:
            return None

# ====================================================================
# DEXSCREENER SCANNER (Find new tokens)
# ====================================================================
class DexScreenerScanner:
    """Fetch real token prices from DexScreener + CoinGecko."""
    
    # Known Solana meme coins with real market data
    WATCHLIST = [
        'So11111111111111111111111111111111111111112',  # SOL itself
        'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcG',  # WIF
        'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
        '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',  # POPCAT
        '3S8qX1MsMqRbiwKg2cQyx7nis1oHMgaCuc9c4VfvVdPN',  # MYRO
    ]
    
    def __init__(self):
        self._price_cache = {}
        self._data_cache = {}
        self._negative_cache = {}  # mints that returned no data (avoid re-querying dead coins)
        self._trend_cache = None   # (mints, timestamp) cached trending pool
        self._trend_ts = 0
    
    def get_market_data(self, mint: str) -> Optional[dict]:
        """Fetch full PUMP signal: 5-min price change, 5-min volume, liquidity, age.

        This is the data profitable meme sniper bots use: they buy coins
        PUMPING IN THE LAST 5 MINUTES (m5 % + m5 volume), not slow 24h drifters.
        """
        now = time.time()
        cached = self._data_cache.get(mint)
        if cached and now - cached[1] < 8:
            return cached[0]
        neg = self._negative_cache.get(mint)
        if neg and now - neg < 15:
            return None  # was dead 15s ago, don't hammer the API
        try:
            url = f'{DEXSCREENER_API}/latest/dex/tokens/{mint}'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            pairs = data.get('pairs', [])
            best = None
            for p in pairs:
                if p.get('chainId') != 'solana':
                    continue
                price = float(p.get('priceUsd', 0) or 0)
                if price <= 0:
                    continue
                pc = p.get('priceChange') or {}
                m5 = float(pc.get('m5', 0) or 0)
                h1 = float(pc.get('h1', 0) or 0)
                h24 = float(pc.get('h24', 0) or 0)
                vol = p.get('volume') or {}
                v5 = float(vol.get('m5', 0) or 0)
                v24 = float(vol.get('h24', 0) or 0)
                liq = float((p.get('liquidity') or {}).get('usd', 0) or 0)
                age = None
                try:
                    created = p.get('pairCreatedAt')
                    if created:
                        age = (now - created / 1000.0) / 3600.0  # hours
                except:
                    pass
                txns = p.get('txns', {}) or {}
                b5 = float((txns.get('m5') or {}).get('buys', 0) or 0)
                s5 = float((txns.get('m5') or {}).get('sells', 0) or 0)
                info = {'price': price, 'volume24h': v24, 'volume5m': v5,
                        'pump_5m': m5, 'pump_1h': h1, 'pump_24h': h24,
                        'liquidity': liq, 'age_hr': age,
                        'buy_sell_5m': (b5 / max(s5, 1))}
                if best is None or v5 > best.get('volume5m', 0):
                    best = info
            if best:
                self._data_cache[mint] = (best, now)
                self._price_cache[mint] = (best['price'], now)
                return best
        except:
            pass
        self._negative_cache[mint] = now
        return None
    
    def get_trending_mints(self, limit: int = 25) -> list:
        """Fetch the HOTTEST Solana pairs right now (trending + recent).

        DexScreener '/token-boosts' returns coins that are being actively
        boosted (attention = likely pumps). Fallback to top-pairs search.
        """
        now = time.time()
        if self._trend_cache and now - self._trend_ts < 20:
            return self._trend_cache[:limit]
        mints = []
        try:
            url = f'{DEXSCREENER_API}/token-boosts/latest/v1'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            for item in data or []:
                if item.get('chainId') != 'solana':
                    continue
                tok = item.get('tokenAddress')
                if tok:
                    mints.append(tok)
        except:
            pass
        if len(mints) < 5:
            try:
                pairs = self.get_top_pairs(limit)
                for p in pairs:
                    mints.append(p.get('baseToken', {}).get('address', ''))
            except:
                pass
        seen = []
        for m in mints:
            if m and m not in seen:
                seen.append(m)
        self._trend_cache = seen
        self._trend_ts = now
        return seen[:limit]
    
    def refresh_pool(self, mints: list) -> dict:
        """Fetch market data for MANY mints in ONE multi-token call (cached).
        Returns {mint: market_data}. All strategies read this shared cache so
        the loop never does 10 slow sequential fetches per tick."""
        now = time.time()
        fresh = {}
        todo = []
        for m in mints:
            if not m:
                continue
            if m in self._data_cache and now - self._data_cache[m][1] < 15:
                fresh[m] = self._data_cache[m][0]
            elif m in self._negative_cache and now - self._negative_cache[m] < 30:
                pass
            else:
                todo.append(m)
        if todo:
            try:
                url = f'{DEXSCREENER_API}/latest/dex/tokens/{",".join(todo[:30])}'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                by_mint = {}
                for p in data.get('pairs', []):
                    if p.get('chainId') != 'solana':
                        continue
                    addr = p.get('baseToken', {}).get('address', '')
                    price = float(p.get('priceUsd', 0) or 0)
                    if not addr or price <= 0:
                        continue
                    pc = p.get('priceChange') or {}
                    vol = p.get('volume') or {}
                    txns = p.get('txns', {}) or {}
                    b5 = float((txns.get('m5') or {}).get('buys', 0) or 0)
                    s5 = float((txns.get('m5') or {}).get('sells', 0) or 0)
                    info = {
                        'price': price,
                        'volume24h': float(vol.get('h24', 0) or 0),
                        'volume5m': float(vol.get('m5', 0) or 0),
                        'pump_5m': float(pc.get('m5', 0) or 0),
                        'pump_1h': float(pc.get('h1', 0) or 0),
                        'pump_24h': float(pc.get('h24', 0) or 0),
                        'liquidity': float((p.get('liquidity') or {}).get('usd', 0) or 0),
                        'age_hr': (now - p.get('pairCreatedAt', 0) / 1000.0) / 3600.0 if p.get('pairCreatedAt') else None,
                        'buy_sell_5m': (b5 / max(s5, 1)),
                    }
                    cur = by_mint.get(addr)
                    if cur is None or info['volume5m'] > cur['volume5m']:
                        by_mint[addr] = info
                for m in todo:
                    if m in by_mint:
                        self._data_cache[m] = (by_mint[m], now)
                        self._price_cache[m] = (by_mint[m]['price'], now)
                        fresh[m] = by_mint[m]
                    else:
                        self._negative_cache[m] = now
            except:
                for m in todo:
                    self._negative_cache[m] = now
        return fresh
    
    def get_price(self, mint: str) -> Optional[float]:
        """Fetch current price of a token from DexScreener."""
        now = time.time()
        cached = self._price_cache.get(mint)
        if cached and now - cached[1] < 6:
            return cached[0]
        neg = self._negative_cache.get(mint)
        if neg and now - neg < 20:
            return None  # dead coin, don't hammer the API
        
        try:
            import urllib.request
            url = f'{DEXSCREENER_API}/latest/dex/tokens/{mint}'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            pairs = data.get('pairs', [])
            for p in pairs:
                if p.get('chainId') == 'solana':
                    price = float(p.get('priceUsd', 0))
                    if price > 0:
                        self._price_cache[mint] = (price, now)
                        return price
        except:
            pass
        self._negative_cache[mint] = now
        return None
        
        # Fallback: CoinGecko SOL price (only for SOL itself)
        if mint == WSOL_MINT:
            try:
                import urllib.request
                url = 'https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read())
                price = float(data.get('solana', {}).get('usd', 0))
                if price > 0:
                    self._price_cache[mint] = (price, now)
                    return price
            except:
                pass
        return None
    
    def get_top_pairs(self, limit: int = 10) -> list:
        """Get top Solana pairs by volume from DexScreener."""
        try:
            import urllib.request
            url = f'{DEXSCREENER_API}/latest/dex/search?q=solana'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            pairs = data.get('pairs', [])
            sol_pairs = [p for p in pairs if p.get('chainId') == 'solana' and float(p.get('priceUsd', 0)) > 0]
            return sol_pairs[:limit]
        except:
            return []

# ====================================================================
# PRODUCTION TRADING ENGINE
# ====================================================================
class ProdTradingEngine:
    """Real trading engine with paper/real mode."""
    
    def __init__(self, capital_sol: float = 0, paper_mode: bool = True):
        self.capital = capital_sol  # In SOL
        self.initial_capital = capital_sol
        self.peak_capital = capital_sol
        self.positions = {}  # Active positions (abstract)
        self.trades = []
        self.wins = 0
        self.losses = 0
        self.paper_mode = paper_mode
        self.total_withdrawn = 0
        self.start_time = datetime.now()
        self.trader: Optional[JupiterTrader] = None
        self.scanner = DexScreenerScanner()
        self.wallet_balance_sol = 0.0
        self.last_price = 0.0
        self.equity_curve = [(0, capital_sol)]
        self.sol_price_usd = 130.0  # Approximate SOL/USD price
        
        # Strategy (from meta_aggressor)
        self.config = StrategyConfig()
        self.generation = 0
        self.win_rate_history = []
    
    @property
    def total_value(self) -> float:
        return self.capital
    
    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / max(total, 1) * 100
    
    def set_trader(self, keypair: Keypair):
        self.trader = JupiterTrader(keypair, paper_mode=self.paper_mode)
    
    def update_wallet_balance(self):
        """Detect NEW external SOL deposits only (not sell proceeds).

        wallet_balance_sol is tracked incrementally: real buys subtract the spent
        SOL, real sells add the returned SOL. So the only positive diff between
        the real RPC balance and this tracked baseline is an external deposit.
        This prevents double-counting sell proceeds as deposits.
        """
        if not (self.trader and self.trader.keypair):
            return
        try:
            new_bal = ProdWallet.get_balance(self.trader.keypair)
        except Exception as ex:
            if self.wallet_balance_sol == 0:
                print(f'  [BALANCE] RPC error (wallet reads as 0): {ex}')
            return  # keep old baseline on RPC failure
        diff = new_bal - self.wallet_balance_sol
        if diff > 0.0005:  # genuine deposit above gas/fee noise
            self.capital += diff
            self.peak_capital = max(self.peak_capital, self.capital)
            print(f'  [DEPOSIT] +{diff:.4f} SOL detected — capital now {self.capital:.4f} SOL')
            if hasattr(self, 'agent') and self.agent:
                s = getattr(self.agent, '_strats', {})
                if s:
                    share = diff / len(s)
                    for sd in s.values():
                        sd['capital'] = sd.get('capital', 0) + share
        self.wallet_balance_sol = new_bal
    
    def buy_token(self, mint: str, amount_sol: float) -> dict:
        """Buy a token using SOL (simulated or real)."""
        if not self.trader and not self.paper_mode:
            return {'success': False, 'error': 'No trader configured'}
        
        fee_sol = amount_sol * FEE_BUY
        
        if self.paper_mode:
            self.capital -= amount_sol  # Lock up the capital
            pos = {
                'mint': mint,
                'entry_sol': amount_sol,
                'fee': fee_sol,
                'entry_time': datetime.now().isoformat(),
                'paper': True
            }
            pid = f"{mint[:8]}_{datetime.now().timestamp()*1000:.0f}"
            self.positions[pid] = pos
            return {'success': True, 'pid': pid, 'position': pos}
        
        # Real mode
        amount_lamports = int(amount_sol * 1e9)
        result = self.trader.execute_swap(WSOL_MINT, mint, amount_lamports)
        if result.get('success'):
            self.capital -= amount_sol
            self.wallet_balance_sol = max(self.wallet_balance_sol - amount_sol, 0)
            token_amount = result.get('output_amount', 0)
            pos = {
                'mint': mint, 'entry_sol': amount_sol,
                'token_amount': token_amount,
                'entry_time': datetime.now().isoformat(),
                'paper': False
            }
            pid = f"{mint[:8]}_{datetime.now().timestamp()*1000:.0f}"
            self.positions[pid] = pos
            return {'success': True, 'pid': pid, 'position': pos, 'result': result, 'token_amount': token_amount}
        return result
    
    def sell_token(self, pid: str, ret_pct: float = None) -> dict:
        """Sell a token position. ret_pct = decimal return (e.g. 0.40 = +40%)."""
        pos = self.positions.get(pid)
        if not pos:
            return {'success': False, 'error': 'Position not found'}
        
        entry_sol = pos.get('entry_sol', 0)
        
        if self.paper_mode:
            if ret_pct is None:
                ret_pct = 0.0
            pnl = entry_sol * ret_pct - entry_sol * FEE_SELL
            total_return = entry_sol + pnl  # Capital returned after PnL
            
            self.capital += total_return
            
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_sol': entry_sol,
                'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'ret_pct': ret_pct * 100,
                'pnl': pnl,
                'paper': True
            }
            del self.positions[pid]
            return {'success': True, 'trade': tr, 'pnl': pnl}
        
        # Real mode
        token_amount = pos.get('token_amount', int(entry_sol * 1e9))
        result = self.trader.execute_swap(pos['mint'], WSOL_MINT, token_amount)
        if result.get('success'):
            out_sol = float(result.get('output_amount', 0)) / 1e9
            pnl = out_sol - entry_sol - entry_sol * FEE_SELL - SOL_GAS_ESTIMATE
            self.capital += out_sol
            self.wallet_balance_sol += out_sol
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'ret_pct': (out_sol/entry_sol - 1)*100 if entry_sol > 0 else 0,
                'pnl': pnl, 'paper': False
            }
            del self.positions[pid]
            return {'success': True, 'trade': tr, 'pnl': pnl}
        return result
    
    def withdraw(self, amount_sol: float) -> float:
        available = self.capital * 0.9
        if amount_sol > available:
            amount_sol = available
        if amount_sol < 0.001:
            return 0
        self.capital -= amount_sol
        self.total_withdrawn += amount_sol
        return amount_sol
    
    def summary(self) -> dict:
        # Try to get per-strategy data from agent
        strats_data = {}
        if hasattr(self, 'agent') and self.agent:
            s = getattr(self.agent, '_strats', {})
            for name, sd in s.items():
                cap = sd.get('capital', 0)
                wins = sd.get('wins', 0)
                losses = sd.get('losses', 0)
                total = wins + losses
                wr = (wins / total * 100) if total > 0 else 0
                params = sd.get('params', {})
                strats_data[name] = {
                    'cap': round(cap, 4),
                    'wins': wins, 'losses': losses,
                    'wr': round(wr, 1),
                    'active': len(sd.get('positions', {})),
                    'tp': params.get('target', 0),
                    'sl': params.get('stop', 0)
                }
        return {
            'capital': self.capital,
            'total_value': self.total_value,
            'peak': self.peak_capital,
            'return_pct': (self.total_value / max(self.initial_capital, 1e-9) - 1) * 100,
            'return_mult': self.total_value / max(self.initial_capital, 1e-9),
            'trades': len(self.trades),
            'wins': self.wins, 'losses': self.losses,
            'win_rate': self.win_rate,
            'active': sum(sd2.get('active', 0) for sd2 in strats_data.values()),
            'config': self.config.name,
            'generation': self.generation,
            'total_withdrawn': self.total_withdrawn,
            'paper_mode': self.paper_mode,
            'wallet_sol': self.wallet_balance_sol,
            'start_time': self.start_time.isoformat(),
            'target_pct': self.config.params.get('target', 0.35) * 100,
            'stop_pct': self.config.params.get('stop', 0.12) * 100,
            'strategies': strats_data
        }

# ====================================================================
# STRATEGY SYSTEM (from meta_aggressor)
# ====================================================================
STRATEGY_PARAMS = {
    'aggressive_35':  {'target': 0.30, 'stop': 0.08, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.08, 'trail_dist': 0.05, 'desc': '+30%/-8%, meme pump'},
    'aggressive_50':  {'target': 0.40, 'stop': 0.10, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.10, 'trail_dist': 0.06, 'desc': '+40%/-10%, moon shot'},
    'momentum_40':    {'target': 0.25, 'stop': 0.08, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.08, 'trail_dist': 0.05, 'desc': '+25%/-8%, momentum pump'},
    'breakout_45':    {'target': 0.35, 'stop': 0.09, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.09, 'trail_dist': 0.06, 'desc': '+35%/-9%, breakout pump'},
    'swing_60':       {'target': 0.50, 'stop': 0.12, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.12, 'trail_dist': 0.08, 'desc': '+50%/-12%, mega pump'},
    'momentum_50':    {'target': 0.30, 'stop': 0.08, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.09, 'trail_dist': 0.06, 'desc': '+30%/-8%, strong momentum'},
    'breakout_30':    {'target': 0.30, 'stop': 0.08, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.08, 'trail_dist': 0.05, 'desc': '+30%/-8%, clean breakout'},
    'aggressive_60':  {'target': 0.50, 'stop': 0.12, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.12, 'trail_dist': 0.08, 'desc': '+50%/-12%, max pump'},
    'swing_40':       {'target': 0.40, 'stop': 0.10, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.10, 'trail_dist': 0.07, 'desc': '+40%/-10%, steady rocket'},
    'momentum_30':    {'target': 0.30, 'stop': 0.08, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.08, 'trail_dist': 0.05, 'desc': '+30%/-8%, confirmed pump'},
}

SIGNAL_MODES = {
    'momentum': {'desc': 'Buy when price + volume rising'},
    'reversal': {'desc': 'Buy after sharp drop + volume spike'},
    'breakout': {'desc': 'Buy when price breaks range with volume'},
}

class StrategyConfig:
    def __init__(self, params_key='aggressive_35', signal_key='momentum'):
        self.params = deepcopy(STRATEGY_PARAMS[params_key])
        self.signal = deepcopy(SIGNAL_MODES[signal_key])
        self.params_key = params_key
        self.signal_key = signal_key
        self.name = f"{params_key}+{signal_key}"
    
    def mutate(self):
        pkeys = list(STRATEGY_PARAMS.keys())
        skeys = list(SIGNAL_MODES.keys())
        self.params_key = random.choice(pkeys)
        self.signal_key = random.choice(skeys)
        self.params = deepcopy(STRATEGY_PARAMS[self.params_key])
        self.signal = deepcopy(SIGNAL_MODES[self.signal_key])
        self.name = f"{self.params_key}+{self.signal_key}"
        return self

# ====================================================================
# PRODUCTION AGENT
# ====================================================================
class ProductionAggressor:
    """Main production agent — connects to real Solana DEXs."""
    
    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.wallet_data = None
        self.keypair = None
        cap = 0
        if paper_mode:
            try:
                usd = PAPER_CAPITAL_INR / INR_PER_USD
                sp = DexScreenerScanner().get_price(WSOL_MINT) or 74.0
                cap = usd / sp
                print(f'  Paper capital: Rs.{PAPER_CAPITAL_INR} = {cap:.4f} SOL (${usd:.2f})')
            except Exception as e:
                print(f'  Paper capital fetch failed ({e}), using 0.15 SOL')
                cap = 0.15
        self.engine = ProdTradingEngine(cap, paper_mode)
        try:
            self.engine.sol_price_usd = DexScreenerScanner().get_price(WSOL_MINT) or 130.0
        except:
            self.engine.sol_price_usd = 130.0
        self.engine.agent = self
        self.running = False
        self.agent_thread = None
        self._strats = {}
        self._cycle_count = 0
    
    @property
    def deposit_address(self):
        return self.wallet_data.get('address', '') if self.wallet_data else ''
    
    def setup_wallet(self):
        """Setup wallet — import existing or create new."""
        if os.path.exists(WALLET_FILE):
            with open(WALLET_FILE) as f:
                self.wallet_data = json.load(f)
            self.keypair = ProdWallet.load_keypair(self.wallet_data)
            if not self.keypair:
                print('  Invalid wallet file. Delete and re-run.')
                return False
            print(f'  Wallet: {self.wallet_data["address"]}')
        elif self.paper_mode:
            # Paper mode: auto-generate a disposable wallet, no prompts
            self.wallet_data = ProdWallet.generate_new()
            with open(WALLET_FILE, 'w') as f:
                json.dump(self.wallet_data, f)
            self.keypair = ProdWallet.load_keypair(self.wallet_data)
            print(f'  Paper wallet (auto-generated): {self.wallet_data["address"]}')
        else:
            print('\n  No wallet found. Options:')
            print('  1. Import existing private key (from Phantom/Backpack)')
            print('  2. Generate new wallet')
            choice = input('  Enter [1/2]: ').strip()
            
            if choice == '1':
                priv = input('  Private key (Base58): ').strip()
                try:
                    self.wallet_data = ProdWallet.create_from_private_key(priv)
                except ValueError as e:
                    print(f'  Error: {e}')
                    return False
            else:
                self.wallet_data = ProdWallet.generate_new()
                print(f'\n  NEW WALLET GENERATED!')
                print(f'  Address: {self.wallet_data["address"]}')
                print(f'  Private key: {self.wallet_data["private_key"][:20]}...')
                print(f'  SAVE YOUR PRIVATE KEY!')
            
            with open(WALLET_FILE, 'w') as f:
                json.dump(self.wallet_data, f)
            self.keypair = ProdWallet.load_keypair(self.wallet_data)
            print(f'  Wallet saved.')
        
        # Connect trader
        self.engine.set_trader(self.keypair)
        
        # Check balance
        if not self.paper_mode:
            try:
                bal = ProdWallet.get_balance(self.keypair)
                print(f'  SOL Balance: {bal:.4f} SOL (${bal*130:.2f})')
                if bal < 0.01:
                    print('  WARNING: Very low SOL balance! Need SOL for gas.')
            except Exception as e:
                print(f'  Could not fetch balance: {e}')
        
        return True
    
    def start_agent(self):
        """Start the agent in background thread."""
        if self.running:
            return
        self.running = True
        self.agent_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.agent_thread.start()
        print(f'  Agent started in {"paper" if self.paper_mode else "REAL"} mode')
    
    def stop_agent(self):
        self.running = False
        if self.agent_thread:
            self.agent_thread.join(timeout=5)
        if not self.paper_mode:
            self.save_state()
    
    def save_state(self):
        """Persist strategy state so a restart never orphans real positions."""
        try:
            state = {
                'strats': self._strats,
                'cycle_count': self._cycle_count,
                'engine': {
                    'capital': self.engine.capital,
                    'initial_capital': self.engine.initial_capital,
                    'peak_capital': self.engine.peak_capital,
                    'positions': self.engine.positions,
                    'trades': self.engine.trades[-1000:],
                    'wins': self.engine.wins,
                    'losses': self.engine.losses,
                    'total_withdrawn': self.engine.total_withdrawn,
                },
                'saved_at': datetime.now().isoformat(),
            }
            with open(STATE_FILE, 'wb') as f:
                pickle.dump(state, f)
        except Exception as e:
            print(f'  [STATE] save failed: {e}')
    
    def load_state(self):
        """Restore state from a previous run so open positions survive restarts."""
        if not os.path.exists(STATE_FILE):
            return False
        try:
            with open(STATE_FILE, 'rb') as f:
                state = pickle.load(f)
            self._strats = state.get('strats', {})
            self._cycle_count = state.get('cycle_count', 0)
            eng = state.get('engine', {})
            self.engine.positions = eng.get('positions', {})
            self.engine.trades = eng.get('trades', [])
            self.engine.wins = eng.get('wins', 0)
            self.engine.losses = eng.get('losses', 0)
            self.engine.initial_capital = eng.get('initial_capital', self.engine.initial_capital)
            self.engine.peak_capital = eng.get('peak_capital', self.engine.peak_capital)
            self.engine.total_withdrawn = eng.get('total_withdrawn', 0)
            open_pos = len(self.engine.positions)
            for sd in self._strats.values():
                open_pos += len(sd.get('positions', {}))
            print(f'  [STATE] restored {len(self._strats)} strategies, {open_pos} open positions')
            return True
        except Exception as e:
            print(f'  [STATE] load failed ({e}), starting fresh')
            return False
    
    def _evolve_strategy(self):
        old_name = self.engine.config.name
        self.engine.config.mutate()
        self.engine.generation += 1
        wr = self.engine.win_rate
        print(f'  EVOLVE: {old_name} -> {self.engine.config.name} (WR={wr:.1f}%)')
    
    def _run_loop(self):
        """Main agent loop — 10 strategies with real or simulated execution."""
        tick = 0
        while self.running:
            try:
                # ========================================================
                # 10 STRATEGIES × VOLATILITY MODEL (same for paper & real)
                # ========================================================
                if not self._strats:
                    n_strats = len(STRATEGY_PARAMS)
                    init_cap = self.engine.capital / n_strats
                    label = 'PAPER' if self.paper_mode else 'REAL'
                    print(f'  Initializing {n_strats} strategies with {init_cap:.4f} SOL each [{label}]')
                    beh_map = {
                        'momentum_30':{'size':0.25,'freq':5,'vol':0.028,'drift':0.005},
                        'momentum_40':{'size':0.25,'freq':5,'vol':0.028,'drift':0.005},
                        'momentum_50':{'size':0.30,'freq':6,'vol':0.030,'drift':0.005},
                        'breakout_30':{'size':0.25,'freq':5,'vol':0.030,'drift':0.004},
                        'breakout_45':{'size':0.30,'freq':5,'vol':0.035,'drift':0.004},
                        'aggressive_35':{'size':0.35,'freq':5,'vol':0.025,'drift':0.003},
                        'aggressive_50':{'size':0.35,'freq':5,'vol':0.028,'drift':0.004},
                        'aggressive_60':{'size':0.40,'freq':6,'vol':0.030,'drift':0.004},
                        'swing_40':{'size':0.30,'freq':8,'vol':0.028,'drift':0.004},
                        'swing_60':{'size':0.40,'freq':10,'vol':0.030,'drift':0.005}
                    }
                    base_price = 100.0
                    try:
                        sp = self.engine.scanner.get_price('So11111111111111111111111111111111111111112')
                        if sp: base_price = sp
                    except: pass
                    print(f'  Base price: ${base_price:.2f}')
                    # Pool of coins: trending/hot right now + known safe meme coins
                    pool = []
                    try:
                        trending = self.engine.scanner.get_trending_mints(20)
                        pool = trending or []
                    except: pass
                    known = [m for m in REAL_MINTS if m not in pool]
                    pool = (pool + known)[:20]
                    if not pool:
                        pool = REAL_MINTS[:]
                    print(f'  Coin pool: {len(pool)} coins ({len(pool)-len(known)} trending + {len(known)} known)')
                    used_init = set()
                    for i, (sname, sp) in enumerate(STRATEGY_PARAMS.items()):
                        beh = beh_map.get(sname, {'size':0.20,'freq':4,'vol':0.025,'drift':0.003})
                        smint = None
                        for p in (pool + pool):  # walk twice: prefer unused, else reuse
                            if p not in used_init:
                                smint = p
                                used_init.add(p)
                                break
                        if smint is None:
                            smint = pool[i % len(pool)]
                        sprice = 0.0
                        mdata = None
                        try:
                            mdata = self.engine.scanner.get_market_data(smint)
                            if mdata: sprice = mdata['price']
                        except: pass
                        self._strats[sname] = {
                            'params': sp, 'beh': beh,
                            'capital': init_cap, 'positions': {},
                            'entry_prices': {}, 'sim_price': sprice,
                            'wins': 0, 'losses': 0, 'tick': i,
                            'mint': smint, 'mdata': mdata,
                            'last_swap_time': 0,
                            'price_hist': [], 'peak_prices': {}, 'cooldown_until': 0,
                            'disabled': False
                        }
                        print(f'    {sname:16s} {TOKEN_NAMES.get(smint, smint[:4]):8s} ${sprice if sprice>0 else 0:.6g}')
                    print(f'  {len(self._strats)} strategies ready.')
                
                tick = self._cycle_count
                self._cycle_count += 1
                
                total_cap = sum(s['capital'] for s in self._strats.values())
                self.engine.capital = total_cap
                
                # MEME SNIPER: refresh the hot pool ONCE per tick in a SINGLE
                # multi-token API call (cached 15s inside the scanner). All 10
                # strategies read from this shared cache — no more 10 slow
                # sequential fetches that stall the loop.
                fresh_pool = []
                try:
                    fresh_pool = self.engine.scanner.get_trending_mints(15)
                except: pass
                if not fresh_pool:
                    fresh_pool = [s['mint'] for s in self._strats.values()]
                pool_data = {}
                try:
                    pool_data = self.engine.scanner.refresh_pool(fresh_pool)
                except: pass
                
                for sname, s in self._strats.items():
                    sp = s['params']; beh = s['beh']
                    cap = s['capital']; target_pct = sp['target']; stop_pct = sp['stop']
                    size_pct = beh['size']; freq = beh['freq']
                    
                    # Use the shared pool cache — instant, no per-strategy fetch
                    md = pool_data.get(s['mint'])
                    if not md:
                        md = self.engine.scanner.get_market_data(s['mint'])
                    if md and md.get('price', 0) > 0:
                        s['sim_price'] = md['price']
                        s['mdata'] = md
                    cur_price = s['sim_price']
                    mdata = s.get('mdata') or {}
                    s['price_hist'].append(cur_price)
                    if len(s['price_hist']) > 12:
                        s['price_hist'] = s['price_hist'][-12:]
                    
                    # Momentum is already confirmed by the pump_5m gate below —
                    # no separate price_hist check needed (meme moves are instant).
                    mom_ok = True
                    
                    # PUMP gate: real meme sniper bots buy coins where volume and
                    # buy pressure are flowing RIGHT NOW. Aggressive by default —
                    # if a coin has real liquidity and fresh 5-min volume, we fire.
                    pump_ok = False
                    if mdata:
                        p5 = mdata.get('pump_5m', 0) or 0
                        v5 = mdata.get('volume5m', 0) or 0
                        v24 = mdata.get('volume24h', 0) or 0
                        liq = mdata.get('liquidity', 0) or 0
                        bsr = mdata.get('buy_sell_5m', 1) or 1
                        age = mdata.get('age_hr')
                        age_ok = (age is None) or (age < 100)  # skip ancient coins
                        # EARLY pump: fresh 5-min volume + buy pressure + real
                        # liquidity. We buy BEFORE the crowd does.
                        pump_ok = (v5 >= 400 and liq >= 1500
                                   and bsr >= 0.6 and age_ok)
                        # Continuation: already pumped hard but volume STILL flowing
                        if not pump_ok:
                            pump_ok = (v24 >= 15000 and v5 >= 400
                                       and bsr >= 0.6 and liq >= 2000 and age_ok)
                    else:
                        pump_ok = False  # no data = don't chase unknown dead coins
                    
                    # Rotation: meme sniper bots NEVER sit on one coin. When idle
                    # (no open positions) and this coin isn't pumping, swap to a
                    # DIFFERENT coin than every other strategy is already using.
                    if not s.get('disabled') and not pump_ok and not s['positions'] and s['tick'] % 6 == 0:
                        used = set()
                        for o in self._strats.values():
                            if o is not s and o.get('mint'):
                                used.add(o['mint'])
                        # Prefer a coin that currently passes the pump gate,
                        # then any unused fresh coin as fallback.
                        fresh_unused = [f for f in fresh_pool if f and f not in used and f != s['mint']]
                        hot_unused = []
                        for f in fresh_unused:
                            fd = pool_data.get(f)
                            if fd:
                                p5 = fd.get('pump_5m', 0) or 0
                                v5 = fd.get('volume5m', 0) or 0
                                liq = fd.get('liquidity', 0) or 0
                                bsr = fd.get('buy_sell_5m', 1) or 1
                                if v5 >= 400 and liq >= 1500 and bsr >= 0.6:
                                    hot_unused.append(f)
                        pick = (hot_unused or fresh_unused)
                        if pick:
                            s['mint'] = pick[0]
                            s['mdata'] = None
                            s['price_hist'] = []
                    
                    # Open new trade
                    is_real = not self.paper_mode
                    if (not s.get('disabled') and len(s['positions']) < 3 and cap > 0.001 and cur_price > 0
                            and s['tick'] % freq == 0 and mom_ok and pump_ok
                            and s['tick'] >= s.get('cooldown_until', 0)):
                        use_cap = cap * size_pct
                        mint = s['mint']
                        coin = TOKEN_NAMES.get(mint, mint[:4])
                        if is_real:
                            now = time.time()
                            if now - s.get('last_swap_time', 0) < 12:
                                continue
                            # Safety: verify real wallet has enough free SOL + gas before swap
                            try:
                                live_bal = ProdWallet.get_balance(self.keypair)
                            except Exception:
                                live_bal = self.engine.wallet_balance_sol
                            if live_bal < use_cap + SOL_GAS_ESTIMATE * 20:
                                print(f'  [{sname[:6]:6s}] SKIP BUY {coin}: need {use_cap:.4f} SOL + gas, wallet has {live_bal:.4f}')
                                continue
                            result = None
                            for attempt in range(3):
                                try:
                                    result = self.engine.buy_token(mint, use_cap)
                                    if result and result.get('success'):
                                        break
                                    if result and '429' in str(result.get('error','')):
                                        time.sleep(2 ** attempt)
                                        continue
                                except Exception as ex:
                                    if '429' in str(ex):
                                        time.sleep(2 ** attempt)
                                        continue
                                    result = {'error': str(ex)}
                                    break
                            if not (result and result.get('success')):
                                err = result.get('error','?') if result else 'timeout'
                                print(f'  [{sname[:6]:6s}] BUY FAILED: {err}')
                                continue
                            pid = result['pid']
                            s['last_swap_time'] = now
                            print(f'  [{sname[:6]:6s}] BUY  {use_cap:.4f} SOL {coin} (REAL)')
                        else:
                            pid = f"{sname}_{s['tick']}_{random.randint(1000,9999)}"
                            print(f'  [{sname[:6]:6s}] BUY  {use_cap:.4f} SOL {coin} @ ${cur_price:.6g}')
                        s['positions'][pid] = {
                            'mint': mint, 'entry_sol': use_cap,
                            'entry_time': datetime.now().isoformat(),
                            'entry_tick': s['tick']
                        }
                        s['entry_prices'][pid] = cur_price
                        s['peak_prices'][pid] = cur_price
                        # Realistic costs: 1% buy fee + 0.000005 SOL gas (paper mirrors real)
                        s['capital'] -= use_cap * (1 + FEE_BUY) + SOL_GAS_ESTIMATE
                        if is_real:
                            self.save_state()  # immediately persist so a crash never orphans a fresh buy
                    
                    # Evaluate positions with REAL price
                    for pid in list(s['positions'].keys()):
                        entry_price = s['entry_prices'].get(pid, cur_price)
                        if entry_price <= 0:
                            continue
                        pos = s['positions'][pid]
                        entry_val = pos.get('entry_sol', 0)
                        coin = TOKEN_NAMES.get(pos.get('mint',''), (pos.get('mint','') or '??')[:4])
                        pos_ret = (cur_price / entry_price) - 1
                        held = s['tick'] - pos.get('entry_tick', 0)
                        max_hold = max(30, freq * 12)  # time exit ~1-5 min (meme pumps reverse fast)
                        # Track peak and trailing stop
                        peak = max(s['peak_prices'].get(pid, entry_price), cur_price)
                        s['peak_prices'][pid] = peak
                        peak_ret = (peak / entry_price) - 1
                        trail = sp.get('use_trail', False)
                        trail_act = sp.get('trail_act', 0)
                        trail_dist = sp.get('trail_dist', 0)
                        hit = None
                        if pos_ret >= target_pct:
                            hit = 'TP'
                        elif trail and trail_act > 0 and peak_ret >= trail_act and pos_ret <= peak_ret - trail_dist:
                            hit = 'TRAIL'
                        elif pos_ret <= -stop_pct:
                            hit = 'SL'
                        elif held >= max_hold:
                            # Only bank a time exit if the move actually cleared
                            # fees+gas — otherwise a flat trade would just pay ~2%
                            # round-trip cost and lose for no reason. If it's flat,
                            # let TP/SL/TRAIL keep managing it (coin may still pump).
                            if pos_ret >= FEE_BREAKEVEN or pos_ret <= -stop_pct * 0.5:
                                hit = 'TIME'
                            elif held >= max_hold * 3:
                                hit = 'TIME'  # hard cap: never hold a dead trade forever
                        if not hit:
                            continue
                        if is_real:
                            r = None
                            for attempt in range(3):
                                try:
                                    r = self.engine.sell_token(pid)
                                    if r.get('success') or '429' not in str(r.get('error','')):
                                        break
                                    time.sleep(2 ** attempt)
                                except Exception as ex:
                                    if '429' in str(ex):
                                        time.sleep(2 ** attempt)
                                        continue
                                    r = {'error': str(ex)}
                                    break
                            if not (r and r.get('success')):
                                err = r.get('error','?') if r else 'timeout'
                                print(f'  [{sname[:6]:6s}] {hit} SELL FAILED: {err}')
                                continue
                            tr = dict(r['trade'])
                            tr['strategy'] = sname
                            tr['coin'] = coin
                            tr['entry_price'] = entry_price
                            tr['exit_price'] = cur_price
                            tr['hit'] = hit
                            self.engine.trades.append(tr)
                            s['capital'] += entry_val + tr.get('pnl', 0)
                            if hit == 'TP': s['wins'] += 1
                            else: s['losses'] += 1
                            print(f'  [{sname[:6]:6s}] {hit} {coin:6s} {pos_ret*100:+.1f}% | {tr.get("pnl",0):+.4f} SOL (REAL)')
                        else:
                            # 1% sell fee + 0.000005 SOL gas deducted (paper mirrors real)
                            pnl = entry_val * pos_ret - entry_val * FEE_SELL - SOL_GAS_ESTIMATE
                            s['capital'] += entry_val + pnl
                            if hit in ('TP', 'TRAIL'): s['wins'] += 1
                            else: s['losses'] += 1
                            self.engine.trades.append({
                                'mint': pos.get('mint',''), 'coin': coin, 'entry_sol': entry_val,
                                'entry_price': entry_price, 'exit_price': cur_price,
                                'entry_time': pos.get('entry_time',''), 'exit_time': datetime.now().isoformat(),
                                'ret_pct': pos_ret*100, 'pnl': pnl, 'paper': True, 'strategy': sname, 'hit': hit
                            })
                            print(f'  [{sname[:6]:6s}] {hit} {coin:6s} {pos_ret*100:+.1f}% | {pnl:+.4f} SOL')
                        del s['positions'][pid]
                        try: del s['entry_prices'][pid]
                        except: pass
                        try: del s['peak_prices'][pid]
                        except: pass
                        s['cooldown_until'] = s['tick'] + max(12, freq * 4)  # fast re-entry on next pump
                        if is_real:
                            self.save_state()  # persist immediately after closing a real position
                        if hit == 'TIME' and pos_ret > 0:
                            s['wins'] += 1
                            s['losses'] -= 1
                    
                    s['tick'] += 1
                    # WIN-RATE GATE: a strategy that can't hold ~40%+ win rate
                    # after enough trades gets disabled so it stops bleeding fees.
                    if not s.get('disabled'):
                        closed = s.get('wins', 0) + s.get('losses', 0)
                        if closed >= MIN_WR_TARGET_TRADES:
                            wr = s.get('wins', 0) / closed
                            if wr < MIN_WIN_RATE:
                                s['disabled'] = True
                                print(f'  [{sname[:6]:6s}] DISABLED: WR {wr*100:.0f}% < {MIN_WIN_RATE*100:.0f}% after {closed} trades')
                
                # Aggregate stats (recalculate after trades)
                self.engine.wins = sum(s['wins'] for s in self._strats.values())
                self.engine.losses = sum(s['losses'] for s in self._strats.values())
                self.engine.capital = sum(s['capital'] for s in self._strats.values())
                
                # Persist state periodically so restarts never orphan positions
                if tick % 10 == 0 or tick == 1:
                    self.save_state()
                
                # Initial wallet balance sync
                if tick == 0 and not self.paper_mode:
                    self.engine.update_wallet_balance()
                
                if tick % 5 == 0:
                    self.engine.equity_curve.append((tick, self.engine.capital))
                    if self.engine.capital >= TARGET:
                        print(f'\n*** TARGET {TARGET:.0f} SOL REACHED! ***\n')
                        self.engine.capital = TARGET
                        self.running = False
                        break
                
                # Auto-detect SOL deposits
                if not self.paper_mode and tick % 3 == 0:
                    self.engine.update_wallet_balance()
                
                # Periodic status
                if tick % 15 == 0:
                    total = self.engine.capital
                    if total < 0.001:
                        addr = self.deposit_address[:12] if self.deposit_address else '???'
                        print(f'  ⏳ Waiting for SOL... Send to {addr}... or click Deposit on web')
                    else:
                        wins = self.engine.wins
                        losses = self.engine.losses
                        active = sum(len(s.get('positions', {})) for s in self._strats.values())
                        print(f'  Capital: {total:.4f} SOL | Trades: {wins+losses} (W:{wins} L:{losses}) | Active: {active}')
                
                time.sleep(2)
                
            except KeyboardInterrupt:
                # Ignore stray Ctrl+C — keep trading. Stop via dashboard /api/stop.
                print('  Ctrl+C ignored (use dashboard /api/stop to halt).')
            except Exception as e:
                print(f'  Agent error: {e}')
                time.sleep(5)
            if not self.running:
                break
        # Final persist so a clean stop never orphans positions
        if not self.paper_mode:
            self.save_state()
    
    def print_status(self):
        s = self.engine.summary()
        mode = 'PAPER' if self.paper_mode else 'REAL'
        sol_usd = getattr(self.engine, 'sol_price_usd', 130.0)
        print(f'\n{"="*50}')
        print(f'  ULTRA AGGRESSOR [{mode}]')
        print(f'{"="*50}')
        print(f'  Capital:    {s["capital"]:.4f} SOL (${s["capital"]*sol_usd:.2f})')
        print(f'  Return:     {s["return_pct"]:+.2f}% ({s["return_mult"]:.1f}x)')
        print(f'  Trades:     {s["trades"]} (W:{s["wins"]} L:{s["losses"]}) WR:{s["win_rate"]:.1f}%')
        print(f'  Active:     {s["active"]} positions')
        print(f'  Withdrawn:  {s["total_withdrawn"]:.4f} SOL')
        print(f'{"="*50}\n')

# ====================================================================
# FASTAPI DASHBOARD (with real data)
# ====================================================================
AGENT_STATE = {'agent': None, 'running': False}
AGENT_LOCK = threading.Lock()

def create_prod_dashboard():
    """Create Flask dashboard."""
    from flask import Flask, request, jsonify, redirect
    
    app = Flask(__name__)
    
    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Ultra Aggressor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pulse{0%,100%{opacity:.3}50%{opacity:1}}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
body{background:#0a0a0f;color:#e4e4e7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:10px}
.container{max-width:800px;margin:0 auto}
.header{text-align:center;padding:16px 0 12px}
.header h1{font-size:18px;font-weight:800;letter-spacing:2px;color:#fafafa}
.header .row{display:flex;justify-content:center;gap:6px;margin-top:6px;flex-wrap:wrap}
.bdg{font-size:8px;padding:2px 8px;border-radius:12px;font-weight:600;letter-spacing:.5px;border:1px solid rgba(255,255,255,.08)}
.bdg-real{background:rgba(251,113,133,.12);color:#fb7185;border-color:rgba(251,113,133,.2)}
.bdg-live{background:rgba(52,211,153,.1);color:#4ade80;border-color:rgba(52,211,153,.18)}
.bdg-unlim{background:rgba(250,204,21,.08);color:#facc15;border-color:rgba(250,204,21,.15)}
.cap-card{background:#13131a;border-radius:14px;padding:16px;text-align:center;margin-bottom:10px;border:1px solid rgba(255,255,255,.06);animation:rise .5s ease-out}
.cap-card .lbl{font-size:8px;color:#71717a;text-transform:uppercase;letter-spacing:2px;margin-bottom:2px}
.cap-card .val{font-size:34px;font-weight:800;color:#fafafa}
.cap-card .val .unit{font-size:13px;color:#52525b;font-weight:600}
.cap-card .row{display:flex;justify-content:center;gap:16px;font-size:8px;color:#52525b;margin-top:6px}
.cap-card .row .n{color:#a1a1aa;font-weight:600}
.cap-card .bar{margin-top:6px;height:2px;background:rgba(255,255,255,.04);border-radius:2px;overflow:hidden}
.cap-card .bar .fill{height:100%;background:#60a5fa;border-radius:2px;transition:width .6s}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;margin-bottom:10px}
.s-card{background:#13131a;border-radius:10px;padding:8px 4px;text-align:center;border:1px solid rgba(255,255,255,.04)}
.s-card .sl{font-size:7px;color:#52525b;text-transform:uppercase;letter-spacing:1px}
.s-card .sv{font-size:15px;font-weight:700;margin-top:1px}
.s-card .ss{font-size:7px;color:#52525b;margin-top:1px}
.grn{color:#4ade80}
.red{color:#fb7185}
.blu{color:#60a5fa}
.gld{color:#facc15}
.strat-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:10px}
.strat-item{background:#13131a;border-radius:8px;padding:6px 8px;border:1px solid rgba(255,255,255,.04)}
.strat-item .st{display:flex;justify-content:space-between;align-items:center;margin-bottom:1px}
.strat-item .sn{font-size:8px;font-weight:700;color:#a1a1aa}
.strat-item .sc{font-size:7px;color:#52525b}
.strat-item .sm{display:flex;gap:6px;font-size:7px;color:#52525b}
.strat-item .sb{height:1.5px;background:rgba(255,255,255,.04);border-radius:2px;overflow:hidden;margin-top:2px}
.strat-item .sb .f{height:100%;border-radius:2px;transition:width .4s}
.btn-wrapper{text-align:center;margin-bottom:10px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 24px;border:none;border-radius:10px;font-weight:600;font-size:11px;cursor:pointer;transition:all .2s;background:#1e1e2a;color:#a1a1aa;border:1px solid rgba(255,255,255,.06)}
.btn:hover{background:#2a2a3a;transform:translateY(-1px)}
.btn-primary{background:#2563eb;color:#fff;border:none}
.btn-primary:hover{background:#3b82f6}
.cpanel{display:none;margin-top:8px;padding:12px;background:#13131a;border-radius:10px;border:1px solid rgba(255,255,255,.06)}
.cpanel.open{display:block}
.cpanel input{width:100%;background:#0a0a0f;border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:10px;color:#fafafa;font-size:11px;font-family:monospace;margin-bottom:8px}
.cpanel input:focus{outline:none;border-color:#3b82f6}
.wbox{display:none;background:#13131a;border:1px solid rgba(96,165,250,.15);border-radius:10px;padding:10px;margin-bottom:10px;text-align:center}
.wbox .wl{font-size:8px;color:#60a5fa;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;margin-bottom:4px}
.wbox .wa{font-size:9px;color:#93c5fd;word-break:break-all;font-family:monospace;background:#0a0a0f;border-radius:6px;padding:8px;cursor:pointer;border:1px solid rgba(96,165,250,.1)}
.wbox .wr{display:flex;justify-content:center;gap:12px;font-size:7px;color:#52525b;margin-top:4px}
.trade-section{background:#13131a;border-radius:10px;border:1px solid rgba(255,255,255,.04);overflow:hidden}
.trade-section .th{padding:6px 12px;font-size:8px;font-weight:600;color:#52525b;text-transform:uppercase;letter-spacing:1.5px;border-bottom:1px solid rgba(255,255,255,.04)}
.trade-table{width:100%;border-collapse:collapse;font-size:9px}
.trade-table th{padding:4px 8px;text-align:left;font-size:7px;color:#52525b;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid rgba(255,255,255,.04);font-weight:600}
.trade-table td{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,.02)}
.trade-table tr:last-child td{border-bottom:none}
.footer{text-align:center;padding:10px;font-size:8px;color:#374151}
.live-dot{display:inline-block;width:4px;height:4px;border-radius:50%;background:#4ade80;margin-right:3px;animation:pulse 1.5s ease-in-out infinite}
#notif{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#1e1e2a;color:#fafafa;font-size:10px;padding:8px 16px;border-radius:8px;border:1px solid rgba(255,255,255,.06);display:none;z-index:100;white-space:nowrap}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>ULTRA AGGRESSOR</h1>
    <div class="row">
      <span class="bdg bdg-real" id="badgeMode">REAL</span>
      <span class="bdg bdg-live"><span class="live-dot"></span> LIVE</span>
      <span class="bdg bdg-unlim">&infin; UNLIMITED</span>
    </div>
  </div>
  
  <div class="cap-card">
    <div class="lbl">Capital</div>
    <div class="val"><span id="capValue">0.0000</span> <span class="unit">SOL</span></div>
    <div class="row"><span>Wallet: <span class="n" id="walletBal2">0.0000</span> SOL</span><span>Peak: <span class="n" id="peakVal2">0.0000</span> SOL</span></div>
    <div class="bar"><div class="fill" id="capBar" style="width:0%"></div></div>
  </div>
  
  <div class="wbox" id="walletBox">
    <div class="wl">WALLET</div>
    <div class="wa" id="walletAddr" onclick="var t=this,a=t.textContent;navigator.clipboard.writeText(a);notif('Copied!')">loading...</div>
    <div class="wr"><span>Address &mdash; click to copy</span><span>Balance: <span id="walletBal">0.0000</span> SOL</span></div>
  </div>
  
  <div class="stats">
    <div class="s-card"><div class="sl">Return</div><div class="sv gld" id="retValue">0.00%</div><div class="ss"><span id="retMult">1.0</span>x</div></div>
    <div class="s-card"><div class="sl">Win Rate</div><div class="sv blu" id="wrValue">0%</div><div class="ss"><span id="tradeCount">0</span> trades</div></div>
    <div class="s-card"><div class="sl">W / L</div><div class="sv"><span class="grn" id="winCount">0</span><span style="color:#374151">/</span><span class="red" id="lossCount">0</span></div><div class="ss"><span id="activeCount">0</span> active</div></div>
    <div class="s-card"><div class="sl">Active</div><div class="sv blu" id="apiTradeCount">0</div><div class="ss"><span id="totalCapital">0 SOL</span></div></div>
  </div>
  
  <div class="btn-wrapper">
    <button class="btn btn-primary" onclick="toggleConnect()">+ Connect Wallet</button>
    <button class="btn" onclick="startAgent()" id="startBtn" style="background:#059669;color:#fff">&#9654; Start</button>
    <button class="btn" onclick="stopAgent()" id="stopBtn" style="display:none;background:#dc2626;color:#fff">&#9632; Stop</button>
    <button class="btn" onclick="showJson()">{ } JSON</button>
  </div>
  
  <div class="cpanel" id="cpanel">
    <input id="pkeyInput" type="password" placeholder="Paste Base58 private key..." onkeydown="if(event.key==='Enter')connectWallet()">
    <button class="btn btn-primary" onclick="connectWallet()" style="width:100%;justify-content:center">Connect</button>
    <div style="margin-top:6px;font-size:7px;color:#52525b;text-align:center">Phantom/Backpack: Settings &gt; Export Private Key</div>
  </div>
  
  <div id="stratGrid" class="strat-grid"></div>
  
  <div class="trade-section">
    <div class="th">Trade History</div>
    <table class="trade-table">
      <thead><tr><th>#</th><th>Coin</th><th>Bought at</th><th>Sold at</th><th>Profit</th></tr></thead>
      <tbody id="tradeBody"></tbody>
    </table>
    <div style="padding:16px;text-align:center;color:#52525b;font-size:10px" id="emptyState">No trades yet</div>
  </div>
  
  <pre id="debug" style="margin:8px 0;padding:8px;background:rgba(251,113,133,.05);border:1px solid rgba(251,113,133,.12);border-radius:8px;font-size:8px;color:#fb7185;overflow:auto;max-height:140px;display:none;white-space:pre-wrap"></pre>
  <div class="footer"><span class="live-dot"></span> <span id="lastUpdate">--</span> &middot; <span id="stratCount">0</span> strats</div>
</div>
<div id="notif"></div>
<script>
function $(id){return document.getElementById(id)}
function notif(m){var n=$('notif');n.textContent=m;n.style.display='block';setTimeout(function(){n.style.display='none'},2000)}
function toggleConnect(){var p=$('cpanel');p.className=p.className==='cpanel open'?'cpanel':'cpanel open'}
function fetchData(){
  var x=new XMLHttpRequest();
  x.open('GET','/api/status',true);
  x.onload=function(){
    if(x.status!=200)return;
    try{
      var d=JSON.parse(x.responseText),s=d.summary||{};
      var cap=typeof s.capital=='number'?s.capital:0;
      var ic=typeof s.initial_capital=='number'?s.initial_capital:0;
      var peak=typeof s.peak=='number'?s.peak:0;
      var e=$;
      if(e('capValue'))e('capValue').textContent=cap.toFixed(4);
      if(e('peakVal2'))e('peakVal2').textContent=peak.toFixed(4);
      if(e('totalCapital'))e('totalCapital').textContent=cap.toFixed(4)+' SOL';
      if(e('capBar'))e('capBar').style.width=(ic>0?Math.min(100,cap/ic*100):0).toFixed(2)+'%';
      if(e('retValue'))e('retValue').textContent=Number(s.return_pct||0).toFixed(2)+'%';
      if(e('retMult'))e('retMult').textContent=Number(s.return_mult||0).toFixed(2);
      if(e('wrValue'))e('wrValue').textContent=Number(s.win_rate||0).toFixed(1)+'%';
      if(e('tradeCount'))e('tradeCount').textContent=s.trades||0;
      if(e('winCount'))e('winCount').textContent=s.wins||0;
      if(e('lossCount'))e('lossCount').textContent=s.losses||0;
      if(e('activeCount'))e('activeCount').textContent=s.active||0;
      if(e('apiTradeCount'))e('apiTradeCount').textContent=s.active||0;
      if(e('badgeMode'))e('badgeMode').textContent=s.paper_mode?'PAPER':'REAL';
      var wb=e('walletBox');
      if(d.wallet){
        wb.style.display='block';
        if(e('walletAddr'))e('walletAddr').textContent=d.wallet;
        if(e('walletBal'))e('walletBal').textContent=(d.wallet_balance||0).toFixed(4);
        if(e('walletBal2'))e('walletBal2').textContent=(d.wallet_balance||0).toFixed(4);
      }else wb.style.display='none';
      if(e('stratCount'))e('stratCount').textContent=Object.keys(d.strategies||{}).length;
      var sg=e('stratGrid');
      if(sg){
        var entries=Object.entries(d.strategies||{});
        if(entries.length){
          sg.innerHTML=entries.map(function(n){var p=n[1],wr=p.wr||0,win=p.wins||0,loss=p.losses||0,act=p.active||0,cv=p.cap||0,total=win+loss||1,wrR=win/total,bc=wrR>=.7?'#4ade80':wrR>=.4?'#facc15':'#fb7185';return '<div class=\"strat-item\"><div class=\"st\"><span class=\"sn\">'+n[0].slice(0,8)+'</span><span class=\"sc\">'+cv.toFixed(3)+' SOL</span></div><div class=\"sm\"><span class=\"'+(wr>=50?'grn':'red')+'\">'+(win+loss>0?wr.toFixed(0):'--')+'%</span><span class=\"grn\">'+win+'W</span><span class=\"red\">'+loss+'L</span>'+(act?'<span style=\"color:#60a5fa\">'+act+'</span>':'')+'</div><div class=\"sb\"><div class=\"f\" style=\"width:'+Math.round(wrR*100)+'%;background:'+bc+'\"></div></div></div>'}).join('');
        }else sg.innerHTML='<div style="grid-column:1/-1;text-align:center;color:#52525b;padding:16px;font-size:9px">Initializing...</div>';
      }
      var tb=e('tradeBody'),es=e('emptyState');
      if(tb&&es){
        if(d.trades&&d.trades.length){
          es.style.display='none';
          tb.innerHTML=d.trades.slice(-30).reverse().map(function(t,i){var c=t.pnl>0?'grn':'red',sg=t.pnl>0?'+':'';var fmt=function(x){return x>=0.01?Number(x).toFixed(4):Number(x).toExponential(2)};return '<tr><td style=\"color:#52525b\">'+(i+1)+'</td><td style=\"color:#a5b4fc;font-weight:600\">'+(t.coin||'??')+'</td><td>$'+fmt(t.entry_price||0)+'</td><td>$'+fmt(t.exit_price||0)+'</td><td class=\"'+c+'\">'+sg+(t.pnl||0).toFixed(4)+' SOL <span style=\"opacity:.6\">('+sg+(t.ret_pct||0).toFixed(1)+'%)</span></td></tr>'}).join('');
        }else{es.style.display='block';tb.innerHTML=''}
      }
      if(d.running){if(e('startBtn'))e('startBtn').style.display='none';if(e('stopBtn'))e('stopBtn').style.display='inline-flex'}
      else{if(e('startBtn'))e('startBtn').style.display='inline-flex';if(e('stopBtn'))e('stopBtn').style.display='none'}
      if(e('lastUpdate'))e('lastUpdate').textContent=new Date().toLocaleTimeString();
    }catch(ex){var db=e('debug');if(db){db.style.display='block';db.textContent='JS Error: '+(ex.message||ex)}}
  };
  x.send();
}
function startAgent(){
  var x=new XMLHttpRequest();
  x.open('POST','/api/start',true);
  x.onload=function(){if(x.status==200){notif('Agent started');fetchData()}else notif('Start failed')};
  x.send();
}
function stopAgent(){
  var x=new XMLHttpRequest();
  x.open('POST','/api/stop',true);
  x.onload=function(){if(x.status==200){notif('Agent stopped');fetchData()}else notif('Stop failed')};
  x.send();
}
function connectWallet(){
  var key=$('pkeyInput').value.trim();
  if(key.length<50)return notif('Invalid key length');
  var x=new XMLHttpRequest();
  x.open('POST','/api/connect-wallet',true);
  x.setRequestHeader('Content-Type','application/json');
  x.onload=function(){
    if(x.status==200){toggleConnect();notif('Wallet connected!');fetchData()}
    else{try{var d=JSON.parse(x.responseText);notif(d.error||'Failed')}catch(e){notif('Failed')}}
  };
  x.send(JSON.stringify({private_key:key}));
}
function showJson(){
  var x=new XMLHttpRequest();
  x.open('GET','/api/status',true);
  x.onload=function(){var db=$('debug');db.style.display='block';db.textContent=x.responseText};
  x.send();
}
setInterval(fetchData,3000);fetchData();
</script>
</body>
</html>"""
    
    @app.route("/")
    def dashboard():
        r = app.make_response(DASHBOARD_HTML)
        r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        r.headers['Pragma'] = 'no-cache'
        r.headers['Expires'] = '0'
        return r
    
    @app.route("/api/status")
    def api_status():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and agent.engine:
                trades = []
                for t in agent.engine.trades[-30:]:
                    m = t.get('mint','')
                    trades.append({
                        'coin': t.get('coin') or TOKEN_NAMES.get(m, m[:4].upper() if m else '??'),
                        'mint': m,
                        'entry_sol': t.get('entry_sol', 0),
                        'entry_price': t.get('entry_price', 0),
                        'exit_price': t.get('exit_price', 0),
                        'ret_pct': t.get('ret_pct', 0),
                        'pnl': t.get('pnl', 0),
                        'entry_time': t.get('entry_time',''),
                        'exit_time': t.get('exit_time',''),
                        'paper': t.get('paper', True),
                        'strategy': t.get('strategy', ''),
                        'hit': t.get('hit', '')
                    })
                wallet_addr = ''
                if agent.wallet_data:
                    wallet_addr = agent.wallet_data.get('address', '')
                sm = agent.engine.summary()
                sm['initial_capital'] = agent.engine.initial_capital
                strats_data = sm.get('strategies', {})
                strat_count = len(strats_data)
                trade_count = len(trades)
                cap_str = f'{sm.get("capital",0):.4f}'
                print(f'  API: {strat_count} strats, {trade_count} trades, {cap_str} SOL')
                return {
                    'summary': sm,
                    'trades': trades,
                    'strategies': strats_data,
                    'wallet': wallet_addr,
                    'wallet_balance': agent.engine.wallet_balance_sol,
                    'deposit_address': agent.deposit_address if agent.wallet_data else '',
                    'running': AGENT_STATE.get('running', False)
                }
            print('  API: no agent yet')
            return {'summary': {'capital': 0, 'trades': 0}, 'trades': [], 'strategies': {}}
    
    @app.route("/api/debug")
    def api_debug():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent:
                return {
                    'has_strats': bool(agent._strats),
                    'strat_keys': list(agent._strats.keys()) if agent._strats else [],
                    'has_prices': bool(agent._real_prices),
                    'price_keys': list(agent._real_prices.keys()) if agent._real_prices else [],
                    'capital': agent.engine.capital,
                    'trades_count': len(agent.engine.trades)
                }
            return {'error': 'no agent'}
    
    @app.route("/api/deposit", methods=['POST'])
    def api_deposit():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and agent.engine:
                data = request.get_json(silent=True) or {}
                sol_amt = float(data.get('sol', 0.1))
                agent.engine.capital += sol_amt
                agent.engine.peak_capital = max(agent.engine.peak_capital, agent.engine.capital)
                # Distribute to strategies
                s = getattr(agent, '_strats', {})
                if s:
                    share = sol_amt / len(s)
                    for sd in s.values():
                        sd['capital'] = sd.get('capital', 0) + share
                return {'success': True, 'amount': sol_amt}
            return {'success': False}, 400
    
    @app.route("/api/withdraw", methods=['POST'])
    def api_withdraw():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and agent.engine:
                data = request.get_json(silent=True) or {}
                amt = float(data.get('amount', 0))
                dest = str(data.get('address', '')).strip()
                if amt < 0.001:
                    return {'success': False, 'error': 'Minimum 0.001 SOL'}, 400
                if not dest or len(dest) < 30:
                    return {'success': False, 'error': 'Enter a valid destination address'}, 400
                actual = agent.engine.withdraw(amt)
                if actual > 0:
                    return {'success': True, 'amount': actual, 'to': dest[:8]+'...'+dest[-4:]}
                return {'success': False, 'error': 'Insufficient funds'}, 400
            return {'success': False}, 400
    
    @app.route("/deposit", methods=['POST'])
    def deposit_form():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and agent.engine:
                sol_amt = float(request.form.get('sol', 0.1))
                agent.engine.capital += sol_amt
                agent.engine.peak_capital = max(agent.engine.peak_capital, agent.engine.capital)
                s = getattr(agent, '_strats', {})
                if s:
                    share = sol_amt / len(s)
                    for sd in s.values():
                        sd['capital'] = sd.get('capital', 0) + share
        return redirect('/')

    @app.route("/withdraw", methods=['POST'])
    def withdraw_form():
        amt = float(request.form.get('amount', 0))
        dest = str(request.form.get('address', '')).strip()
        if amt >= 0.001 and dest and len(dest) >= 30:
            with AGENT_LOCK:
                agent = AGENT_STATE.get('agent')
                if agent and agent.engine:
                    agent.engine.withdraw(amt)
        return redirect('/')

    @app.route("/api/connect-wallet", methods=['POST'])
    def api_connect_wallet():
        data = request.get_json(silent=True) or {}
        priv = str(data.get('private_key', '')).strip()
        if not priv or len(priv) < 50:
            return {'success': False, 'error': 'Invalid private key'}, 400
        try:
            wallet = ProdWallet.create_from_private_key(priv)
        except Exception as e:
            return {'success': False, 'error': str(e)}, 400
        with open(WALLET_FILE, 'w') as f:
            json.dump(wallet, f)
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent:
                agent.wallet_data = wallet
                agent.keypair = ProdWallet.load_keypair(wallet)
                agent.engine.set_trader(agent.keypair)
                bal = ProdWallet.get_balance(agent.keypair)
                agent.engine.wallet_balance_sol = bal
                agent.engine.capital = bal
                agent.engine.initial_capital = bal
                agent.engine.peak_capital = bal
                print(f'  [WALLET] Connected: {wallet["address"][:12]}... Balance: {bal:.4f} SOL')
        return {'success': True, 'address': wallet['address']}

    @app.route("/api/start", methods=['POST'])
    def api_start():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and not AGENT_STATE.get('running', False):
                agent.start_agent()
                AGENT_STATE['running'] = True
                return {'success': True}
            return {'success': False, 'error': 'Already running or no agent'}, 400

    @app.route("/api/stop", methods=['POST'])
    def api_stop():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and AGENT_STATE.get('running', False):
                agent.stop_agent()
                AGENT_STATE['running'] = False
                return {'success': True}
            return {'success': False, 'error': 'Not running'}, 400

    return app

# ====================================================================
# MAIN
# ====================================================================
if __name__ == '__main__':
    import sys
    import signal
    import traceback
    # Log ANY uncaught exception to crash.log so silent deaths are diagnosable
    def _crash_logger(exc_type, exc, tb):
        try:
            with open('crash.log', 'a') as f:
                f.write(''.join(traceback.format_exception(exc_type, exc, tb)) + '\n')
        except Exception:
            pass
        print('FATAL:', exc)
    sys.excepthook = _crash_logger
    
    # Ctrl+C = clean stop: closes the trading loop, saves state, exits.
    # The loop checks self.running and breaks on the next tick (max ~2s delay).
    _agent_ref = {'agent': None}
    def _handle_ctrl_c(signum, frame):
        a = _agent_ref['agent']
        print('\n  Ctrl+C received — stopping cleanly, saving state...')
        if a is not None:
            a.running = False
            with AGENT_LOCK:
                AGENT_STATE['running'] = False
    signal.signal(signal.SIGINT, _handle_ctrl_c)
    
    if '--setup' in sys.argv:
        agent = ProductionAggressor(paper_mode=True)
        agent.setup_wallet()
        agent.print_status()
    
    elif '--paper' in sys.argv or '--dashboard' in sys.argv:
        port = int(os.environ.get('PORT', '8765'))
        print('=' * 60)
        print('  PRODUCTION AGGRESSOR — PAPER MODE')
        print('  No real funds will be used.')
        print('  Dashboard: http://0.0.0.0:{}'.format(port))
        print('=' * 60)
        
        if '--fresh' in sys.argv and os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
                print('  Fresh start: cleared previous state.')
            except Exception as e:
                print(f'  Could not clear state: {e}')
        
        agent = ProductionAggressor(paper_mode=True)
        if agent.setup_wallet():
            restored = agent.load_state()
            if restored:
                print('  Resumed previous session state.')
            else:
                print('  No previous state — starting fresh.')
            with AGENT_LOCK:
                AGENT_STATE['agent'] = agent
                AGENT_STATE['running'] = True
            _agent_ref['agent'] = agent
            agent.print_status()
            print('\n  Agent running. Stop it via dashboard /api/stop.')
            app = create_prod_dashboard()
            # Flask in a background thread so a stray Ctrl+C to the main thread
            # can NEVER kill the trading loop.
            flask_thread = threading.Thread(
                target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
                daemon=True)
            flask_thread.start()
            print('  [HEARTBEAT] entering trading loop')
            agent.running = True
            # Main thread = trading loop. Ignores Ctrl+C, trades until told to stop.
            agent._run_loop()
    
    elif '--real' in sys.argv:
        port = int(os.environ.get('PORT', '8765'))
        print('!' * 60)
        print('  ULTRA AGGRESSOR — REAL MODE')
        print('  Dashboard: http://0.0.0.0:{}'.format(port))
        print('  Trading with real SOL from your wallet!')
        print('  Max risk: ALL CAPITAL')
        print('!' * 60)
        
        agent = ProductionAggressor(paper_mode=False)
        
        if '--fresh' in sys.argv and os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
                print('  Fresh start: cleared previous state.')
            except Exception as e:
                print(f'  Could not clear state: {e}')
        
        # Auto-create wallet (no prompts, no password)
        if not os.path.exists(WALLET_FILE):
            wallet = ProdWallet.generate_new()
            with open(WALLET_FILE, 'w') as f:
                json.dump(wallet, f)
            agent.wallet_data = wallet
            agent.keypair = ProdWallet.load_keypair(wallet)
            agent.engine.set_trader(agent.keypair)
            print(f'  Wallet: {wallet["address"][:12]}...')
            print(f'  Send SOL to this address to trade.')
        else:
            with open(WALLET_FILE) as f:
                agent.wallet_data = json.load(f)
            agent.keypair = ProdWallet.load_keypair(agent.wallet_data)
            if not agent.keypair:
                # Old encrypted format or corrupt — regenerate
                print('  Old wallet format detected, generating new wallet...')
                wallet = ProdWallet.generate_new()
                with open(WALLET_FILE, 'w') as f:
                    json.dump(wallet, f)
                agent.wallet_data = wallet
                agent.keypair = ProdWallet.load_keypair(wallet)
            agent.engine.set_trader(agent.keypair)
            print(f'  Wallet: {agent.wallet_data.get("address","")[:12]}...')
        
        # Capital = actual SOL balance
        try:
            bal = ProdWallet.get_balance(agent.keypair)
            print(f'  SOL balance: {bal:.4f} SOL (${bal*130:.2f})')
            if bal < 0.01:
                print(f'  ⚠ Need SOL for gas! Minimum 0.01 SOL recommended.')
        except:
            bal = 0.0
            print('  Could not check balance')
        agent.engine.capital = bal
        agent.engine.initial_capital = bal
        agent.engine.peak_capital = bal
        agent.engine.wallet_balance_sol = bal
        
        # Restore any open positions from a previous run so they are never orphaned
        restored = agent.load_state()
        if restored:
            print('  Recovered previous session state.')
        else:
            print('  No previous state — starting fresh.')
        
        with AGENT_LOCK:
            AGENT_STATE['agent'] = agent
            AGENT_STATE['running'] = True
        _agent_ref['agent'] = agent
        
        print(f'\n  REAL TRADING ACTIVE — Dashboard at http://0.0.0.0:{port}\n')
        app = create_prod_dashboard()
        # Flask in a background thread so a stray Ctrl+C can NEVER kill trading.
        flask_thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
            daemon=True)
        flask_thread.start()
        agent.running = True
        # Main thread = trading loop.
        agent._run_loop()
    
    else:
        print('Production Aggressor — Real Solana Trading System')
        print()
        print('Usage:')
        print('  --setup      Create/import wallet')
        print('  --paper      Paper trading (simulated, safe)')
        print('  --real       REAL TRADING (risk!)')
        print('  --dashboard  Web dashboard')
