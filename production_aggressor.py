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
SOLANA_RPC = 'https://api.mainnet-beta.solana.com'
JUPITER_API = 'https://quote-api.jup.ag/v6'
DEXSCREENER_API = 'https://api.dexscreener.com'
WSOL_MINT = 'So11111111111111111111111111111111111111112'
USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'

# Real token mints (actively traded on Jupiter, high liquidity)
REAL_MINTS = [
    'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
    'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',  # dogwifhat
    '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',  # POPCAT
    'Me2QZtAeXMZcQBq9YBSLBbqYZbDg3tLyXVJ3VWmR6Jx',  # ME
    '3S8qX1MsMqRbiwKg2cQyx7nis1oHMgaCuc9c4VfvVdPN',  # GOAT
    'ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82',  # BOME
    'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',  # JUP
    '2weMjPLLybRMMva1fM3U31goWWrCpF59CHWNhnCJ9Vyh',  # PENG
    'A3eME5CetyZPBoWbRUwY3tSe25S6tb18ba9ZPbWk9eFJ',  # SAMO
    'Df6yfrKC8kZE3KNkrHERKzAetS2brNeeJCshaJ7Vo9Vx',  # MYRO
]

# Fee model (realistic for Solana)
FEE_BUY = 0.01  # 1% Jupiter fee + slippage
FEE_SELL = 0.01
SOL_GAS_ESTIMATE = 0.000005  # ~0.000005 SOL per tx

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
        try:
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
        except:
            return 0.0

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
        self._cache_time = 0
    
    def get_price(self, mint: str) -> Optional[float]:
        """Fetch current price of a token from DexScreener."""
        now = time.time()
        if mint in self._price_cache and now - self._cache_time < 10:
            return self._price_cache[mint]
        
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
                        self._price_cache[mint] = price
                        self._cache_time = now
                        return price
        except:
            pass
        
        # Fallback: CoinGecko SOL price
        try:
            import urllib.request
            url = 'https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            price = float(data.get('solana', {}).get('usd', 0))
            if price > 0:
                self._price_cache[mint] = price
                self._cache_time = now
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
        """Detect new SOL deposits from wallet. Does NOT overwrite existing capital."""
        if self.trader and self.trader.keypair:
            try:
                new_bal = ProdWallet.get_balance(self.trader.keypair)
                diff = new_bal - self.wallet_balance_sol
                self.wallet_balance_sol = new_bal
                if diff > 0.00001:
                    self.capital += diff
                    self.peak_capital = max(self.peak_capital, self.capital)
                    print(f'  [DEPOSIT] +{diff:.4f} SOL detected — capital now {self.capital:.4f} SOL')
                    if hasattr(self, 'agent') and self.agent:
                        s = getattr(self.agent, '_strats', {})
                        if s:
                            share = diff / len(s)
                            for sd in s.values():
                                sd['capital'] = sd.get('capital', 0) + share
            except:
                pass
    
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
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_sol': entry_sol,
                'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'ret_pct': ret_pct * 100,
                'pnl': pnl,
                'paper': True
            }
            self.trades.append(tr)
            del self.positions[pid]
            return {'success': True, 'trade': tr, 'pnl': pnl}
        
        # Real mode
        token_amount = pos.get('token_amount', int(entry_sol * 1e9))
        result = self.trader.execute_swap(pos['mint'], WSOL_MINT, token_amount)
        if result.get('success'):
            out_sol = float(result.get('output_amount', 0)) / 1e9
            pnl = out_sol - entry_sol - entry_sol * FEE_SELL
            self.capital += out_sol
            if pnl > 0: self.wins += 1
            else: self.losses += 1
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'ret_pct': (out_sol/entry_sol - 1)*100 if entry_sol > 0 else 0,
                'pnl': pnl, 'paper': False
            }
            self.trades.append(tr)
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
                    'cap': round(cap, 2),
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
            'return_pct': (self.total_value / max(self.initial_capital, 1) - 1) * 100,
            'return_mult': self.total_value / max(self.initial_capital, 1),
            'trades': len(self.trades),
            'wins': self.wins, 'losses': self.losses,
            'win_rate': self.win_rate,
            'active': len(self.positions),
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
    'aggressive_35':  {'target': 0.35, 'stop': 0.12, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.20, 'trail_dist': 0.10, 'desc': '+35%/-12%, 3:1 R:R'},
    'aggressive_50':  {'target': 0.50, 'stop': 0.18, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.30, 'trail_dist': 0.15, 'desc': '+50%/-18%, 2.8:1 R:R'},
    'conservative_25':{'target': 0.25, 'stop': 0.10, 'min_vol': 3.0, 'use_trail': True, 'trail_act': 0.15, 'trail_dist': 0.08, 'desc': '+25%/-10%, 2.5:1 R:R'},
    'scalp_15':       {'target': 0.15, 'stop': 0.06, 'min_vol': 1.5, 'use_trail': False, 'trail_act': 0, 'trail_dist': 0, 'desc': '+15%/-6%, fast scalp'},
    'momentum_40':    {'target': 0.40, 'stop': 0.20, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.25, 'trail_dist': 0.12, 'desc': '+40%/-20%, wide stop'},
    'reversal_30':    {'target': 0.30, 'stop': 0.18, 'min_vol': 3.0, 'use_trail': True, 'trail_act': 0.15, 'trail_dist': 0.10, 'desc': '+30%/-18%, reversal play'},
    'breakout_45':    {'target': 0.45, 'stop': 0.12, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.25, 'trail_dist': 0.15, 'desc': '+45%/-12%, breakout'},
    'scalp_20':       {'target': 0.20, 'stop': 0.07, 'min_vol': 1.5, 'use_trail': False, 'trail_act': 0, 'trail_dist': 0, 'desc': '+20%/-7%, quick scalp'},
    'swing_60':       {'target': 0.60, 'stop': 0.15, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.35, 'trail_dist': 0.18, 'desc': '+60%/-15%, swing trade'},
    'ultra_scalp_10': {'target': 0.10, 'stop': 0.04, 'min_vol': 1.0, 'use_trail': False, 'trail_act': 0, 'trail_dist': 0, 'desc': '+10%/-4%, ultra fast'},
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
        self.engine = ProdTradingEngine(0, paper_mode)
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
                    init_cap = self.engine.capital / 10
                    label = 'PAPER' if self.paper_mode else 'REAL'
                    print(f'  Initializing 10 strategies with {init_cap:.4f} SOL each [{label}]')
                    beh_map = {
                        'scalp_15':{'size':0.15,'freq':2,'vol':0.025,'drift':0.003},
                        'scalp_20':{'size':0.20,'freq':3,'vol':0.025,'drift':0.003},
                        'ultra_scalp_10':{'size':0.10,'freq':2,'vol':0.025,'drift':0.002},
                        'momentum_40':{'size':0.25,'freq':5,'vol':0.028,'drift':0.005},
                        'breakout_45':{'size':0.30,'freq':5,'vol':0.035,'drift':0.004},
                        'reversal_30':{'size':0.20,'freq':6,'vol':0.022,'drift':0.001},
                        'aggressive_35':{'size':0.35,'freq':5,'vol':0.025,'drift':0.003},
                        'aggressive_50':{'size':0.35,'freq':5,'vol':0.028,'drift':0.004},
                        'conservative_25':{'size':0.15,'freq':7,'vol':0.020,'drift':0.002},
                        'swing_60':{'size':0.40,'freq':10,'vol':0.030,'drift':0.005}
                    }
                    base_price = 100.0
                    try:
                        sp = self.engine.scanner.get_price('So11111111111111111111111111111111111111112')
                        if sp: base_price = sp
                    except: pass
                    print(f'  Base price: ${base_price:.2f}')
                    for i, (sname, sp) in enumerate(STRATEGY_PARAMS.items()):
                        beh = beh_map.get(sname, {'size':0.20,'freq':4,'vol':0.025,'drift':0.003})
                        self._strats[sname] = {
                            'params': sp, 'beh': beh,
                            'capital': init_cap, 'positions': {},
                            'entry_prices': {}, 'sim_price': base_price,
                            'wins': 0, 'losses': 0, 'tick': i,
                            'mint': REAL_MINTS[i % len(REAL_MINTS)],
                            'last_swap_time': 0
                        }
                    print(f'  10 strategies ready.')
                
                tick = self._cycle_count
                self._cycle_count += 1
                
                # Re-seed from real SOL price every 30 ticks
                if tick > 0 and tick % 30 == 0:
                    try:
                        sp = self.engine.scanner.get_price('So11111111111111111111111111111111111111112')
                        if sp and sp > 0:
                            for s in self._strats.values():
                                s['sim_price'] = sp
                    except: pass
                
                total_cap = sum(s['capital'] for s in self._strats.values())
                self.engine.capital = total_cap
                
                for sname, s in self._strats.items():
                    sp = s['params']; beh = s['beh']
                    cap = s['capital']; target_pct = sp['target']; stop_pct = sp['stop']
                    size_pct = beh['size']; freq = beh['freq']
                    vol = beh['vol']; drift = beh['drift']
                    
                    # Simulate realistic price movement (random walk)
                    ret = random.gauss(drift, vol)
                    s['sim_price'] *= (1 + ret)
                    cur_price = s['sim_price']
                    
                    # Open new trade
                    if len(s['positions']) < 2 and cap > 0.001 and s['tick'] % freq == 0:
                        use_cap = cap * size_pct
                        pid = f"{sname}_{s['tick']}_{random.randint(1000,9999)}"
                        s['positions'][pid] = {
                            'mint': 'SIM', 'entry_sol': use_cap,
                            'entry_time': datetime.now().isoformat()
                        }
                        s['entry_prices'][pid] = cur_price
                        s['capital'] -= use_cap
                        is_real = not self.paper_mode
                        # Real mode: execute Jupiter swap
                        if is_real:
                            try:
                                sol_needed = use_cap
                                mint = s.get('mint', 'So11111111111111111111111111111111111111112')
                                # Rate limit: at most 1 request per 6 seconds
                                now = time.time()
                                if now - s.get('last_swap_time', 0) < 12:
                                    print(f'  [{sname[:6]:6s}] SKIP (rate limit)')
                                    del s['positions'][pid]
                                    s['capital'] += use_cap
                                    continue
                                result = None
                                for attempt in range(3):
                                    try:
                                        result = self.engine.buy_token(mint, sol_needed)
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
                                if result and result.get('success'):
                                    s['last_swap_time'] = now
                                    print(f'  [{sname[:6]:6s}] BUY  {use_cap:.4f} SOL {mint[:4]} (REAL)')
                                    s['positions'][pid]['real_pid'] = result.get('pid', pid)
                                else:
                                    err = result.get('error','?') if result else 'timeout'
                                    print(f'  [{sname[:6]:6s}] BUY FAILED: {err}')
                                    del s['positions'][pid]
                                    s['capital'] += use_cap
                            except Exception as e:
                                print(f'  [{sname[:6]:6s}] BUY ERROR: {e}')
                                del s['positions'][pid]
                                s['capital'] += use_cap
                        else:
                            print(f'  [{sname[:6]:6s}] BUY  {use_cap:.4f} SOL @ ${cur_price:.4f}')
                    
                    # Evaluate positions with simulated price
                    for pid in list(s['positions'].keys()):
                        entry_price = s['entry_prices'].get(pid, cur_price)
                        if entry_price <= 0:
                            continue
                        pos_ret = (cur_price / entry_price) - 1
                        
                        if pos_ret >= target_pct:
                            pos = s['positions'][pid]
                            entry_val = pos.get('entry_sol', 0)
                            pnl = entry_val * target_pct - entry_val * 0.01
                            s['capital'] += entry_val + pnl
                            s['wins'] += 1
                            is_real = not self.paper_mode
                            if is_real:
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
                                ok = r.get('success', False) if isinstance(r, dict) else False
                                print(f'  [{sname[:6]:6s}] TP   +{pos_ret*100:.1f}% | +{pnl:.4f} SOL {"(REAL)" if ok else "FAIL"}'[:60])
                            else:
                                print(f'  [{sname[:6]:6s}] TP   +{pos_ret*100:.1f}% | +{pnl:.4f} SOL')
                            self.engine.trades.append({
                                'mint': 'SIM', 'entry_sol': entry_val,
                                'entry_time': pos.get('entry_time',''), 'exit_time': datetime.now().isoformat(),
                                'ret_pct': pos_ret*100, 'pnl': pnl, 'paper': self.paper_mode, 'strategy': sname
                            })
                            del s['positions'][pid]
                        elif pos_ret <= -stop_pct:
                            pos = s['positions'][pid]
                            entry_val = pos.get('entry_sol', 0)
                            pnl = entry_val * (-stop_pct) - entry_val * 0.01
                            s['capital'] += entry_val + pnl
                            s['losses'] += 1
                            is_real = not self.paper_mode
                            if is_real:
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
                                ok = r.get('success', False) if isinstance(r, dict) else False
                                print(f'  [{sname[:6]:6s}] SL   {pos_ret*100:.1f}% | {pnl:.4f} SOL {"(REAL)" if ok else "FAIL"}'[:60])
                            else:
                                print(f'  [{sname[:6]:6s}] SL   {pos_ret*100:.1f}% | {pnl:.4f} SOL')
                            self.engine.trades.append({
                                'mint': 'SIM', 'entry_sol': entry_val,
                                'entry_time': pos.get('entry_time',''), 'exit_time': datetime.now().isoformat(),
                                'ret_pct': pos_ret*100, 'pnl': pnl, 'paper': self.paper_mode, 'strategy': sname
                            })
                            del s['positions'][pid]
                    
                    s['tick'] += 1
                
                # Aggregate stats (recalculate after trades)
                self.engine.wins = sum(s['wins'] for s in self._strats.values())
                self.engine.losses = sum(s['losses'] for s in self._strats.values())
                self.engine.capital = sum(s['capital'] for s in self._strats.values())
                
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
                        active = sum(1 for s in self._strats.values() if s.get('positions'))
                        print(f'  Capital: {total:.4f} SOL | Trades: {wins+losses} (W:{wins} L:{losses}) | Active: {active}')
                
                time.sleep(2)
                
            except Exception as e:
                print(f'  Agent error: {e}')
                time.sleep(5)
    
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
@keyframes pulse{0%,100%{opacity:.4}50%{opacity:.8}}
@keyframes glow{0%,100%{box-shadow:0 0 12px rgba(168,85,247,.15)}50%{box-shadow:0 0 30px rgba(168,85,247,.35)}}
@keyframes drift{0%{transform:translate(0,0)}25%{transform:translate(40px,-25px)}50%{transform:translate(-25px,15px)}75%{transform:translate(15px,35px)}100%{transform:translate(0,0)}}
@keyframes countUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
body{background:#05060a;color:#e4e4e7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:10px;min-height:100vh;position:relative;overflow-x:hidden}
body::before{content:'';position:fixed;top:0;left:0;width:100%;height:100%;background:radial-gradient(ellipse at 20% 50%,rgba(88,28,135,.15) 0%,transparent 50%),radial-gradient(ellipse at 80% 20%,rgba(15,118,110,.1) 0%,transparent 50%),radial-gradient(ellipse at 50% 80%,rgba(124,58,237,.08) 0%,transparent 50%);pointer-events:none;z-index:0}
.container{max-width:960px;margin:0 auto;position:relative;z-index:1}
.header{text-align:center;padding:12px 0 10px;position:relative}
.header h1{font-size:20px;font-weight:900;letter-spacing:2.5px;background:linear-gradient(135deg,#a78bfa,#f472b6,#34d399,#22d3ee);-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-shadow:0 0 40px rgba(168,85,247,.2)}
.header .badge{display:inline-block;margin-top:4px;font-size:9px;padding:2px 10px;border-radius:20px;font-weight:700;letter-spacing:1px}
.badge.paper{background:rgba(6,95,70,.4);color:#6ee7b7;border:1px solid rgba(110,231,183,.3);box-shadow:0 0 12px rgba(110,231,183,.1)}
.badge.real{background:rgba(127,29,29,.4);color:#fca5a5;border:1px solid rgba(252,165,165,.3)}
.capital-card{background:linear-gradient(135deg,#0f0d1a,#1a1040);border-radius:16px;padding:16px 20px;text-align:center;margin-bottom:12px;border:1px solid rgba(99,102,241,.15);position:relative;overflow:hidden;animation:glow 3s ease-in-out infinite}
.capital-card::before{content:'';position:absolute;top:-60%;left:-60%;width:220%;height:220%;background:radial-gradient(circle,rgba(168,85,247,.05) 0%,transparent 60%);pointer-events:none;animation:drift 8s ease-in-out infinite}
.capital-card .label{font-size:9px;color:#818cf8;text-transform:uppercase;letter-spacing:2.5px;margin-bottom:2px;font-weight:600}
.capital-card .value{font-size:40px;font-weight:900;color:#fff;position:relative;text-shadow:0 0 30px rgba(168,85,247,.15);animation:countUp .4s ease-out}
.capital-card .value .currency{font-size:16px;color:#818cf8}
.capital-card .target-row{margin-top:6px;display:flex;justify-content:space-between;font-size:9px;color:#6366f1;position:relative}
.capital-card .bar{height:3px;background:rgba(255,255,255,.05);border-radius:2px;margin-top:5px;overflow:hidden;position:relative}
.capital-card .bar .fill{height:100%;background:linear-gradient(90deg,#a78bfa,#f472b6,#34d399);border-radius:2px;transition:width .8s cubic-bezier(.4,0,.2,1);box-shadow:0 0 8px rgba(168,85,247,.3)}
.sol-usd{font-size:9px;color:#52525b;margin-top:4px}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin-bottom:12px}
.stat-card{background:rgba(15,16,22,.8);backdrop-filter:blur(8px);border-radius:12px;padding:10px 6px;text-align:center;border:1px solid rgba(255,255,255,.04)}
.stat-card .s-label{font-size:7px;color:#52525b;text-transform:uppercase;letter-spacing:1.5px;font-weight:600}
.stat-card .s-value{font-size:16px;font-weight:800;margin-top:2px;letter-spacing:-.5px}
.stat-card .s-sub{font-size:8px;color:#52525b;margin-top:1px}
.green{color:#34d399;text-shadow:0 0 20px rgba(52,211,153,.15)}
.red{color:#f87171;text-shadow:0 0 20px rgba(248,113,113,.1)}
.purple{color:#a78bfa;text-shadow:0 0 20px rgba(167,139,250,.15)}
.gold{color:#fbbf24;text-shadow:0 0 20px rgba(251,191,36,.1)}
.cyan{color:#22d3ee}
.strat-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:12px}
.strat-item{background:rgba(15,16,22,.8);backdrop-filter:blur(8px);border-radius:10px;padding:7px 9px;border:1px solid rgba(255,255,255,.04)}
.strat-item .s-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}
.strat-item .s-name{font-size:9px;font-weight:700;color:#a78bfa}
.strat-item .s-cap{font-size:8px;color:#818cf8;font-weight:600}
.strat-item .s-mid{display:flex;gap:8px;font-size:7px;color:#52525b;margin-bottom:2px}
.strat-item .s-mid span{display:flex;align-items:center;gap:2px}
.strat-item .s-bar{height:2px;background:rgba(255,255,255,.05);border-radius:2px;overflow:hidden}
.strat-item .s-bar .fill{height:100%;border-radius:2px;transition:width .5s}
.btn-group{display:flex;gap:8px;margin-bottom:12px}
.btn{padding:10px 20px;border:none;border-radius:10px;font-weight:700;font-size:11px;cursor:pointer;flex:1;transition:all .25s;letter-spacing:.5px;text-transform:uppercase}
.btn:hover{transform:translateY(-1px)}
.btn:active{transform:scale(.96)}
.btn-deposit{background:linear-gradient(135deg,#059669,#10b981);color:#fff;box-shadow:0 4px 15px rgba(16,185,129,.25)}
.btn-withdraw{background:linear-gradient(135deg,#7f1d1d,#dc2626);color:#fff;box-shadow:0 4px 15px rgba(220,38,38,.2)}
.trade-section{background:rgba(15,16,22,.8);backdrop-filter:blur(8px);border-radius:12px;border:1px solid rgba(255,255,255,.04);overflow:hidden}
.trade-section .ts-header{padding:8px 14px;font-size:9px;font-weight:700;color:#52525b;text-transform:uppercase;letter-spacing:2px;border-bottom:1px solid rgba(255,255,255,.04)}
.trade-table{width:100%;border-collapse:collapse;font-size:10px}
.trade-table th{padding:5px 10px;text-align:left;font-size:7px;color:#52525b;text-transform:uppercase;letter-spacing:1.2px;border-bottom:1px solid rgba(255,255,255,.04);font-weight:700}
.trade-table td{padding:5px 10px;border-bottom:1px solid rgba(255,255,255,.02)}
.trade-table tr:last-child td{border-bottom:none}
.trade-table tr:hover td{background:rgba(255,255,255,.03)}
.footer{text-align:center;padding:10px;font-size:9px;color:#374151}
.live-dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:#34d399;margin-right:4px;animation:pulse 2s ease-in-out infinite;box-shadow:0 0 6px rgba(52,211,153,.4)}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>ULTRA AGGRESSOR</h1>
    <div><span class="badge paper" id="badgeMode">PAPER</span> <span class="badge" style="background:rgba(52,211,153,.15);color:#34d399;border:1px solid rgba(52,211,153,.2)" id="liveBadge"><span class="live-dot"></span>LIVE</span> <span class="badge" style="background:rgba(251,191,36,.1);color:#fbbf24;border:1px solid rgba(251,191,36,.15)">&infin; UNLIMITED</span></div>
  </div>
  
  <div class="capital-card">
    <div class="label">Total Capital</div>
    <div class="value"><span class="currency">SOL</span> <span id="capValue">0.0000</span></div>
    <div class="target-row"><span>Start: <span id="startVal">0.0000</span> SOL</span><span>Growth: <span id="growthVal">0</span>% &middot; Peak: <span id="peakVal2">0.0000</span> SOL</span></div>
    <div class="bar"><div class="fill" id="capBar" style="width:0%"></div></div>
    <div class="sol-usd" id="solUsdVal">$0.00 USD</div>
  </div>
  
  <div id="walletBox" style="display:none;background:linear-gradient(135deg,rgba(52,211,153,.08),rgba(16,185,129,.04));border:1px solid rgba(52,211,153,.25);border-radius:12px;padding:12px 14px;margin-bottom:10px;text-align:center">
    <div style="font-size:8px;color:#34d399;text-transform:uppercase;letter-spacing:2px;font-weight:700;margin-bottom:6px">WALLET ADDRESS</div>
    <div id="walletAddr" style="font-size:9px;color:#22d3ee;word-break:break-all;font-family:monospace;background:rgba(0,0,0,.4);border-radius:6px;padding:8px;cursor:pointer;border:1px solid rgba(34,211,238,.1)" onclick="var t=this;navigator.clipboard.writeText(t.textContent);t.textContent='Copied!'">loading...</div>
    <div style="display:flex;justify-content:center;gap:16px;font-size:8px;color:#52525b;margin-top:6px"><span style="color:#34d399;font-weight:600">Balance: <span id="walletBal">0.0000</span> SOL</span><span>Click to copy</span></div>
  </div>
  
  <div class="stats">
    <div class="stat-card">
      <div class="s-label">Return</div>
      <div class="s-value gold" id="retValue">0.00%</div>
      <div class="s-sub"><span id="retMult">1.0</span>x &middot; <span id="peakVal" style="color:#a78bfa">0</span> peak</div>
    </div>
    <div class="stat-card">
      <div class="s-label">Win Rate</div>
      <div class="s-value purple" id="wrValue">0%</div>
      <div class="s-sub"><span id="tradeCount">0</span> trades</div>
    </div>
    <div class="stat-card">
      <div class="s-label">W / L</div>
      <div class="s-value"><span class="green" id="winCount">0</span><span style="color:#374151;font-size:13px">/</span><span class="red" id="lossCount">0</span></div>
      <div class="s-sub"><span id="activeCount">0</span> active &middot; <span id="totalCapital" style="color:#818cf8">0 SOL</span></div>
    </div>
    <div class="stat-card">
      <div class="s-label">Avg Profit</div>
      <div class="s-value" id="avgPnl">--</div>
      <div class="s-sub">Best: <span id="bestPnl" style="color:#34d399">--</span> &middot; Worst: <span id="worstPnl" style="color:#f87171">--</span></div>
    </div>
  </div>
  
  <div id="stratGrid" class="strat-grid"></div>
  
  <div class="btn-group">
    <details style="position:relative">
      <summary class="btn btn-deposit" style="cursor:pointer;list-style:none">+ Deposit</summary>
      <div style="position:absolute;top:100%;left:0;right:0;z-index:10;margin-top:4px;background:rgba(15,16,22,.98);backdrop-filter:blur(8px);border-radius:12px;padding:14px;border:1px solid rgba(255,255,255,.06)">
        <div style="font-size:13px;font-weight:700;color:#34d399;margin-bottom:8px">DEPOSIT SOL</div>
        <div style="display:flex;gap:8px">
          <input id="depAmt" type="number" step="0.01" min="0.01" value="0.1" placeholder="SOL amount" style="flex:1;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:10px;color:#fff;font-size:13px">
          <button type="button" class="btn btn-deposit" onclick="deposit()" style="flex:0;font-size:11px;padding:10px 16px">Add</button>
        </div>
      </div>
    </details>
    <details style="position:relative">
      <summary class="btn btn-withdraw" style="cursor:pointer;list-style:none">Withdraw</summary>
      <div style="position:absolute;top:100%;left:0;right:0;z-index:10;margin-top:4px;background:rgba(15,16,22,.98);backdrop-filter:blur(8px);border-radius:12px;padding:14px;border:1px solid rgba(255,255,255,.06)">
        <div style="font-size:13px;font-weight:700;color:#f87171;margin-bottom:8px">WITHDRAW SOL</div>
        <input id="wdAddr" type="text" placeholder="Solana destination address..." style="width:100%;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:10px;color:#fff;font-size:12px;font-family:monospace;margin-bottom:8px">
        <div style="display:flex;gap:8px">
          <input id="wdAmt" type="number" step="0.01" min="0.01" value="0.1" placeholder="SOL amount" style="flex:1;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:10px;color:#fff;font-size:13px">
          <button type="button" class="btn btn-withdraw" onclick="withdraw()" style="flex:0;font-size:11px;padding:10px 16px">Send</button>
        </div>
        <div style="margin-top:6px;font-size:9px;color:#52525b">Minimum 0.001 SOL</div>
      </div>
    </details>
  </div>
  
  <div class="trade-section">
    <div class="ts-header">Trade History</div>
    <table class="trade-table">
      <thead><tr><th>#</th><th>Amount</th><th>Result</th><th>PnL</th><th>Strategy</th></tr></thead>
      <tbody id="tradeBody"></tbody>
    </table>
    <div style="padding:20px;text-align:center;color:#52525b;font-size:11px" id="emptyState">No trades yet</div>
  </div>
  
  <pre id="debug" style="margin:8px 0;padding:8px;background:rgba(220,38,38,.05);border:1px solid rgba(220,38,38,.15);border-radius:8px;font-size:9px;color:#f87171;overflow:auto;max-height:160px;display:none;white-space:pre-wrap"></pre>
  <div class="footer"><span class="live-dot"></span> <span id="lastUpdate">--</span> &middot; <span id="stratCount">0</span> strats &middot; <span id="apiTradeCount">0</span> txns &middot; <a href="#" onclick="event.preventDefault();var x=new XMLHttpRequest();x.open('GET','/api/status',true);x.onload=function(){var db=document.getElementById('debug');db.style.display='block';db.textContent=x.responseText};x.send()" style="color:#52525b;text-decoration:none;border-bottom:1px dotted #52525b">JSON</a></div>
</div>
<script>
function $(id){return document.getElementById(id)}
function fetchData(){
  var x=new XMLHttpRequest();
  x.open('GET','/api/status',true);
  x.onload=function(){
    if(x.status!=200)return;
    try{
      var d=JSON.parse(x.responseText);
      var s=d.summary||{};
      var cap=typeof s.capital=='number'?s.capital:0;
      var ic=typeof s.initial_capital=='number'?s.initial_capital:0;
      var peak=typeof s.peak=='number'?s.peak:0;
      var e=$;
      if(e('capValue'))e('capValue').textContent=cap.toFixed(4);
      if(e('startVal'))e('startVal').textContent=ic.toFixed(4);
      if(e('peakVal2'))e('peakVal2').textContent=peak.toFixed(4);
      if(e('peakVal'))e('peakVal').textContent=peak.toFixed(4);
      if(e('solUsdVal'))e('solUsdVal').textContent='$'+(cap*130).toFixed(2)+' USD';
      if(e('totalCapital'))e('totalCapital').textContent=cap.toFixed(4)+' SOL';
      if(e('capBar'))e('capBar').style.width=(ic>0?Math.min(100,cap/ic*100):0).toFixed(2)+'%';
      if(e('retValue'))e('retValue').textContent=Number(s.return_pct||0).toFixed(2)+'%';
      if(e('retMult'))e('retMult').textContent=Number(s.return_mult||0).toFixed(2);
      if(e('wrValue'))e('wrValue').textContent=Number(s.win_rate||0).toFixed(1)+'%';
      if(e('tradeCount'))e('tradeCount').textContent=s.trades||0;
      if(e('winCount'))e('winCount').textContent=s.wins||0;
      if(e('lossCount'))e('lossCount').textContent=s.losses||0;
      if(e('activeCount'))e('activeCount').textContent=s.active||0;
      if(e('badgeMode')){e('badgeMode').textContent=s.paper_mode?'PAPER':'REAL';e('badgeMode').className='badge '+(s.paper_mode?'paper':'real');}
      var wb=e('walletBox');
      if(wb&&d.wallet){wb.style.display='block';if(e('walletAddr'))e('walletAddr').textContent=d.wallet;if(e('walletBal'))e('walletBal').textContent=(d.wallet_balance||0).toFixed(4);}
      if(e('stratCount'))e('stratCount').textContent=Object.keys(d.strategies||{}).length;
      if(e('apiTradeCount'))e('apiTradeCount').textContent=(d.trades||[]).length;
      var sg=e('stratGrid');
      if(sg){
        var entries=Object.entries(d.strategies||{});
        if(entries.length){
          sg.innerHTML=entries.map(function(n){var p=n[1];var wr=p.wr||0;var win=p.wins||0;var loss=p.losses||0;var act=p.active||0;var capV=p.cap||0;var total=win+loss||1;var wrRatio=win/total;var barColor=wrRatio>=.7?'#34d399':wrRatio>=.4?'#fbbf24':'#f87171';var wrCls=wr>=50?'green':'red';return '<div class=\"strat-item\"><div class=\"s-top\"><span class=\"s-name\">'+n[0].slice(0,10)+'</span><span class=\"s-cap\">'+capV.toFixed(3)+' SOL</span></div><div class=\"s-mid\"><span class=\"'+wrCls+'\">'+(win+loss>0?wr.toFixed(0):'--')+'% WR</span><span class=\"green\">'+win+'W</span><span class=\"red\">'+loss+'L</span>'+(act?'<span style=\"color:#22d3ee\">'+act+' act</span>':'')+'</div><div class=\"s-bar\"><div class=\"fill\" style=\"width:'+Math.round(wrRatio*100)+'%;background:'+barColor+';box-shadow:0 0 4px '+barColor+'\"></div></div></div>';}).join('');
        }else sg.innerHTML='<div style="grid-column:1/-1;text-align:center;color:#52525b;padding:20px;font-size:10px">Initializing strategies...</div>';
      }
      var tb=e('tradeBody'),es=e('emptyState');
      if(tb&&es){
        if(d.trades&&d.trades.length){
          es.style.display='none';
          tb.innerHTML=d.trades.slice(-30).reverse().map(function(t,i){var c=t.pnl>0?'green':'red';var sgn=t.pnl>0?'+':'';return '<tr><td style=\"color:#52525b\">'+(i+1)+'</td><td>'+(t.entry_sol||0).toFixed(4)+' SOL</td><td class=\"'+c+'\">'+(t.ret_pct||0).toFixed(1)+'%</td><td class=\"'+c+'\">'+sgn+(t.pnl||0).toFixed(4)+' SOL</td><td style=\"color:#52525b\">'+(t.strategy||'??').slice(0,8)+'</td></tr>';}).join('');
        }else{es.style.display='block';tb.innerHTML=''}
      }
      if(e('lastUpdate'))e('lastUpdate').textContent=new Date().toLocaleTimeString();
    }catch(ex){var db=e('debug');if(db){db.style.display='block';db.textContent='JS Error: '+(ex.message||ex);}}
  };
  x.send();
}
function deposit(){
  var amt=parseFloat(document.getElementById('depAmt').value)||0.1;
  var x=new XMLHttpRequest();
  x.open('POST','/api/deposit',true);
  x.setRequestHeader('Content-Type','application/json');
  x.onload=function(){if(x.status==200){document.querySelector('details summary').click();fetchData()}else alert('Deposit failed')};
  x.send(JSON.stringify({sol:amt}));
}
function withdraw(){
  var amt=parseFloat(document.getElementById('wdAmt').value)||0;
  var addr=document.getElementById('wdAddr').value.trim();
  if(amt<0.001)return alert('Minimum 0.001 SOL');
  if(addr.length<30)return alert('Enter a valid Solana address');
  var x=new XMLHttpRequest();
  x.open('POST','/api/withdraw',true);
  x.setRequestHeader('Content-Type','application/json');
  x.onload=function(){
    if(x.status==200){document.querySelectorAll('details')[1].querySelector('summary').click();fetchData()}
    else try{var d=JSON.parse(x.responseText);alert(d.error||'Withdraw failed')}catch(e){alert('Withdraw failed')}
  };
  x.send(JSON.stringify({amount:amt,address:addr}));
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
                    trades.append({
                        'mint': t.get('mint',''),
                        'entry_sol': t.get('entry_sol', 0),
                        'ret_pct': t.get('ret_pct', 0),
                        'pnl': t.get('pnl', 0),
                        'entry_time': t.get('entry_time',''),
                        'exit_time': t.get('exit_time',''),
                        'paper': t.get('paper', True),
                        'strategy': t.get('strategy', '')
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

    return app

# ====================================================================
# MAIN
# ====================================================================
if __name__ == '__main__':
    import sys
    
    if '--setup' in sys.argv:
        agent = ProductionAggressor(paper_mode=True)
        agent.setup_wallet()
        agent.print_status()
    
    elif '--paper' in sys.argv:
        print('=' * 60)
        print('  PRODUCTION AGGRESSOR — PAPER MODE')
        print('  No real funds will be used.')
        print('=' * 60)
        
        agent = ProductionAggressor(paper_mode=True)
        if agent.setup_wallet():
            agent.start_agent()
            agent.print_status()
            print('\n  Agent running. Press Ctrl+C to stop.')
            try:
                while True:
                    time.sleep(10)
                    agent.print_status()
            except KeyboardInterrupt:
                agent.stop_agent()
                print('\n  Stopped.')
    
    elif '--real' in sys.argv:
        port = int(os.environ.get('PORT', '8765'))
        print('!' * 60)
        print('  ULTRA AGGRESSOR — REAL MODE')
        print('  Dashboard: http://0.0.0.0:{}'.format(port))
        print('  Trading with real SOL from your wallet!')
        print('  Max risk: ALL CAPITAL')
        print('!' * 60)
        
        agent = ProductionAggressor(paper_mode=False)
        
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
        
        agent.start_agent()
        
        with AGENT_LOCK:
            AGENT_STATE['agent'] = agent
            AGENT_STATE['running'] = True
        
        print(f'\n  REAL TRADING ACTIVE — Dashboard at http://0.0.0.0:{port}\n')
        app = create_prod_dashboard()
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    
    elif '--dashboard' in sys.argv:
        port = int(os.environ.get('PORT', '8765'))
        print('Starting Production Dashboard on http://0.0.0.0:{}'.format(port))
        
        agent = ProductionAggressor(paper_mode=True)
        
        # Auto-create wallet (no prompts)
        if not os.path.exists(WALLET_FILE):
            print('  Auto-creating wallet...')
            wallet = ProdWallet.generate_new()
            with open(WALLET_FILE, 'w') as f:
                json.dump(wallet, f)
            agent.wallet_data = wallet
            agent.keypair = ProdWallet.load_keypair(wallet)
            agent.engine.set_trader(agent.keypair)
            print('  Wallet ready. Address:', wallet.get('address', 'auto')[:12] + '...')
        else:
            with open(WALLET_FILE) as f:
                agent.wallet_data = json.load(f)
            agent.keypair = ProdWallet.load_keypair(agent.wallet_data)
            if not agent.keypair:
                print('  Old wallet format, regenerating...')
                wallet = ProdWallet.generate_new()
                with open(WALLET_FILE, 'w') as f:
                    json.dump(wallet, f)
                agent.wallet_data = wallet
                agent.keypair = ProdWallet.load_keypair(wallet)
            agent.engine.set_trader(agent.keypair)
            print('  Wallet:', agent.wallet_data.get('address', '')[:12] + '...')
        
        # Pre-populate strategies immediately before thread starts
        beh_map = {
            'scalp_15':{'size':0.15,'freq':2,'vol':0.025,'drift':0.003},
            'scalp_20':{'size':0.20,'freq':3,'vol':0.025,'drift':0.003},
            'ultra_scalp_10':{'size':0.10,'freq':2,'vol':0.025,'drift':0.002},
            'momentum_40':{'size':0.25,'freq':5,'vol':0.028,'drift':0.005},
            'breakout_45':{'size':0.30,'freq':5,'vol':0.035,'drift':0.004},
            'reversal_30':{'size':0.20,'freq':6,'vol':0.022,'drift':0.001},
            'aggressive_35':{'size':0.35,'freq':5,'vol':0.025,'drift':0.003},
            'aggressive_50':{'size':0.35,'freq':5,'vol':0.028,'drift':0.004},
            'conservative_25':{'size':0.15,'freq':7,'vol':0.020,'drift':0.002},
            'swing_60':{'size':0.40,'freq':10,'vol':0.030,'drift':0.005}
        }
        init_cap = agent.engine.capital / 10
        for i, (sname, sp) in enumerate(STRATEGY_PARAMS.items()):
            beh = beh_map.get(sname, {'size':0.20,'freq':4,'vol':0.025,'drift':0.003})
            agent._strats[sname] = {
                'params': sp, 'beh': beh,
                'capital': init_cap, 'positions': {},
                'entry_prices': {}, 'sim_price': 100.0,
                'wins': 0, 'losses': 0, 'tick': i,
                'mint': REAL_MINTS[i % len(REAL_MINTS)],
                'last_swap_time': 0
            }
        print(f'  Pre-populated {len(agent._strats)} strategies for dashboard.')
        
        agent.start_agent()
        
        with AGENT_LOCK:
            AGENT_STATE['agent'] = agent
            AGENT_STATE['running'] = True
        
        app = create_prod_dashboard()
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    
    else:
        print('Production Aggressor — Real Solana Trading System')
        print()
        print('Usage:')
        print('  --setup      Create/import wallet')
        print('  --paper      Paper trading (simulated, safe)')
        print('  --real       REAL TRADING (risk!)')
        print('  --dashboard  Web dashboard')
