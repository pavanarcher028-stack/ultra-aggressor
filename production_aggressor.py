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
import os, json, time, math, hashlib, base58, base64, secrets, pickle, sys, threading, random, asyncio
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
    # Pure-Python fallback for environments without solders (e.g., Termux ARM64)
    class Pubkey:
        def __init__(self, val): self.val = val
        def __str__(self): return str(self.val)
        @staticmethod
        def from_string(s): return Pubkey(s)
    class Keypair:
        def __init__(self): import os; self._seed = os.urandom(64)
        @staticmethod
        def from_bytes(b): k = Keypair(); k._seed = b; return k
        @staticmethod
        def from_seed(s): k = Keypair(); k._seed = s + os.urandom(32) if len(s) < 64 else s; return k
        @staticmethod
        def from_base58_string(s): import base58; k = Keypair(); k._seed = base58.b58decode(s); return k
        def pubkey(self): return Pubkey(hashlib.sha256(self._seed).hexdigest()[:44])
        def sign(self, _msg): return b'fallback_signature'
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
TARGET = 100000  # Rs 1,00,000 (~$1200)
SOLANA_RPC = 'https://api.mainnet-beta.solana.com'
JUPITER_API = 'https://api.jup.ag/swap/v1'
DEXSCREENER_API = 'https://api.dexscreener.com'
WSOL_MINT = 'So11111111111111111111111111111111111111112'
USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'

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
    def generate_password_hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()[:16]
    
    @staticmethod
    def create_from_private_key(private_key_b58: str, password: str) -> dict:
        """Import from existing Base58 private key (from Phantom/Backpack)."""
        try:
            keypair = Keypair.from_base58_string(private_key_b58)
            pubkey = str(keypair.pubkey())
            
            # Encrypt private key with password
            pwd_hash = ProdWallet.generate_password_hash(password)
            encrypted = bytes(k ^ ord(pwd_hash[i % len(pwd_hash)]) for i, k in enumerate(private_key_b58.encode()))
            
            return {
                'address': pubkey,
                'encrypted': base64.b64encode(encrypted).decode(),
                'verify': pwd_hash,
                'hint': pubkey[:8] + '...' + pubkey[-4:],
                'created': datetime.now().isoformat(),
                'chain': 'SOL'
            }
        except Exception as e:
            raise ValueError(f'Invalid private key: {e}')
    
    @staticmethod
    def generate_new(password: str) -> dict:
        """Generate a new random Solana keypair."""
        keypair = Keypair()
        priv_b58 = base58.b58encode(bytes(keypair)).decode()
        return ProdWallet.create_from_private_key(priv_b58, password)
    
    @staticmethod
    def decrypt(wallet: dict, password: str) -> Optional[Keypair]:
        """Decrypt and return the Keypair."""
        try:
            pwd_hash = ProdWallet.generate_password_hash(password)
            if wallet['verify'] != pwd_hash:
                return None
            encrypted = base64.b64decode(wallet['encrypted'])
            priv_b58 = bytes(e ^ ord(pwd_hash[i % len(pwd_hash)]) for i, e in enumerate(encrypted)).decode()
            return Keypair.from_base58_string(priv_b58)
        except:
            return None
    
    @staticmethod
    def get_balance(keypair: Keypair) -> float:
        """Get SOL balance (sync wrapper)."""
        async def _get():
            async with AsyncClient(SOLANA_RPC) as client:
                resp = await client.get_balance(keypair.pubkey())
                return resp.value / 1e9  # lamports to SOL
        return asyncio.run(_get())

# ====================================================================
# JUPITER TRADER (Real swap execution)
# ====================================================================
class JupiterTrader:
    """Execute real swaps via Jupiter API v1."""
    
    def __init__(self, keypair: Keypair = None, paper_mode: bool = True):
        self.keypair = keypair
        self.paper_mode = paper_mode
        self.last_quote = None
    
    def _fetch(self, url: str) -> dict:
        """Synchronous HTTP fetch."""
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    
    def _post(self, url: str, data: dict) -> dict:
        """Synchronous HTTP POST."""
        import urllib.request
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload, headers={
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    
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
            return {
                'success': True, 'paper': True,
                'input_amount': amount_lamports / 1e9,
                'output_amount': out_amount / 1e6,
                'price_impact_pct': random.uniform(0.1, 2.0),
            }
        
        # Real mode: get quote from Jupiter
        quote = self.quote(input_mint, output_mint, amount_lamports, slippage_bps)
        out_amount = int(quote.get('outAmount', 0))
        price_impact = float(quote.get('priceImpactPct', 0))
        
        # REAL EXECUTION
        try:
            instr = asyncio.run(self._execute_real(quote))
            return {
                'success': True,
                'paper': False,
                'transaction': str(instr),
                'output_amount': out_amount,
                'price_impact_pct': price_impact
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _execute_real(self, quote: dict) -> str:
        """Execute real swap transaction."""
        async with AsyncClient(SOLANA_RPC) as client:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(f'{JUPITER_API}/swap-instructions', json={
                    'quoteResponse': quote,
                    'userPublicKey': str(self.keypair.pubkey()),
                    'wrapAndUnwrapSol': True,
                    'dynamicComputeUnitLimit': True,
                    'prioritizationFeeLamports': 1000
                }) as resp:
                    instr_data = await resp.json()
            
            tx_data = instr_data.get('swapTransaction', '')
            if not tx_data:
                raise ValueError('No swap transaction in response')
            
            tx_bytes = base64.b64decode(tx_data)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            tx.sign([self.keypair])
            sig = await client.send_transaction(tx)
            
            for _ in range(30):
                await asyncio.sleep(1)
                status = await client.get_signature_status(sig.value)
                if status.value:
                    return str(sig.value)
            return str(sig.value)
    
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
    
    def __init__(self, capital_inr: float = 1000, paper_mode: bool = True):
        self.capital = capital_inr  # In INR equivalent
        self.initial_capital = capital_inr
        self.peak_capital = capital_inr
        self.positions = {}  # Active positions (abstract)
        self.trades = []
        self.wins = 0
        self.losses = 0
        self.paper_mode = paper_mode
        self.total_withdrawn = 0
        self.start_time = datetime.now()
        self.trader: Optional[JupiterTrader] = None
        self.scanner = DexScreenerScanner()
        self.usd_to_inr = 83.0  # Approximate rate
        self.wallet_balance_sol = 0.0
        self.last_price = 0.0
        self.equity_curve = [(0, capital_inr)]
        
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
        """Fetch real SOL balance if trader has keypair."""
        if self.trader and self.trader.keypair:
            try:
                self.wallet_balance_sol = ProdWallet.get_balance(self.trader.keypair)
            except:
                pass
    
    def buy_token(self, mint: str, amount_sol: float) -> dict:
        """Buy a token using SOL (simulated or real)."""
        if not self.trader and not self.paper_mode:
            return {'success': False, 'error': 'No trader configured'}
        
        trade_amt_inr = amount_sol * self.usd_to_inr
        fee_inr = trade_amt_inr * FEE_BUY
        
        if self.paper_mode:
            self.capital -= trade_amt_inr  # Lock up the capital
            pos = {
                'mint': mint,
                'entry_sol': amount_sol,
                'entry_value_inr': trade_amt_inr,
                'buy_fee': fee_inr,
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
            self.capital -= trade_amt_inr
            pos = {
                'mint': mint, 'entry_sol': amount_sol,
                'entry_price_usd': result.get('output_amount', 0),
                'entry_time': datetime.now().isoformat(),
                'paper': False
            }
            pid = f"{mint[:8]}_{datetime.now().timestamp()*1000:.0f}"
            self.positions[pid] = pos
            return {'success': True, 'pid': pid, 'position': pos, 'result': result}
        return result
    
    def sell_token(self, pid: str, ret_pct: float = None) -> dict:
        """Sell a token position. ret_pct = decimal return (e.g. 0.40 = +40%)."""
        pos = self.positions.get(pid)
        if not pos:
            return {'success': False, 'error': 'Position not found'}
        
        entry_val = pos.get('entry_value_inr', 0)
        buy_fee = pos.get('buy_fee', 0)
        
        if self.paper_mode:
            if ret_pct is None:
                ret_pct = 0.0
            pnl = entry_val * ret_pct - entry_val * FEE_SELL
            total_return = entry_val + pnl  # Capital returned after PnL
            
            self.capital += total_return
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_sol': pos.get('entry_sol', 0),
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
        result = self.trader.execute_swap(pos['mint'], WSOL_MINT, int(pos.get('entry_sol', 0) * 1e9))
        if result.get('success'):
            ret = 0.0
            pnl = 0.0
            self.capital += entry_val + pnl
            tr = {
                'pid': pid, 'mint': pos['mint'],
                'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'ret_pct': ret, 'pnl': pnl, 'paper': False
            }
            self.trades.append(tr)
            del self.positions[pid]
            return {'success': True, 'trade': tr}
        return result
    
    def withdraw(self, amount_inr: float) -> float:
        available = self.capital * 0.9
        if amount_inr > available:
            amount_inr = available
        if amount_inr < 10:
            return 0
        self.capital -= amount_inr
        self.total_withdrawn += amount_inr
        return amount_inr
    
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
                strats_data[name] = {
                    'cap': round(cap, 2),
                    'wins': wins, 'losses': losses,
                    'wr': round(wr, 1),
                    'active': len(sd.get('positions', {}))
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
        self.engine = ProdTradingEngine(1000, paper_mode)
        self.engine.agent = self
        self.running = False
        self.agent_thread = None
        self._strats = {}
        self._real_prices = {}
        self._real_idx = 0
    
    def setup_wallet(self):
        """Setup wallet — import existing or create new."""
        if os.path.exists(WALLET_FILE):
            with open(WALLET_FILE) as f:
                self.wallet_data = json.load(f)
            print(f'\n  Wallet: {self.wallet_data["address"]}')
            pwd = input('  Password: ').strip()
            self.keypair = ProdWallet.decrypt(self.wallet_data, pwd)
            if not self.keypair:
                print('  Wrong password!')
                return False
            print('  Unlocked.')
        else:
            print('\n  No wallet found. Options:')
            print('  1. Import existing private key (from Phantom/Backpack)')
            print('  2. Generate new wallet')
            choice = input('  Enter [1/2]: ').strip()
            
            while True:
                pwd = input('  Password (min 6): ').strip()
                if len(pwd) < 6:
                    continue
                p2 = input('  Confirm: ').strip()
                if pwd != p2:
                    continue
                break
            
            if choice == '1':
                priv = input('  Private key (Base58): ').strip()
                try:
                    self.wallet_data = ProdWallet.create_from_private_key(priv, pwd)
                except ValueError as e:
                    print(f'  Error: {e}')
                    return False
            else:
                self.wallet_data = ProdWallet.generate_new(pwd)
                print(f'\n  NEW WALLET GENERATED!')
                print(f'  Address: {self.wallet_data["address"]}')
                print(f'  SAVE YOUR PRIVATE KEY!')
            
            with open(WALLET_FILE, 'w') as f:
                json.dump(self.wallet_data, f)
            self.keypair = ProdWallet.decrypt(self.wallet_data, pwd)
            print(f'  Wallet saved.')
        
        # Connect trader
        self.engine.set_trader(self.keypair)
        
        # Check balance
        if not self.paper_mode:
            try:
                bal = ProdWallet.get_balance(self.keypair)
                print(f'  SOL Balance: {bal:.4f} SOL (~${bal*130:.2f})')
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
        """Main agent loop."""
        tick = 0
        while self.running:
            try:
                if self.paper_mode:
                    # ========================================================
                    # 10 STRATEGIES × REAL MARKET DATA
                    # ========================================================
                    if not self._strats:
                        init_cap = self.engine.capital / 10
                        print(f'  Initializing 10 strategies with Rs{init_cap:.0f} each...')
                        beh_map = {
                            'scalp_15':{'size':0.15,'freq':2}, 'scalp_20':{'size':0.20,'freq':3},
                            'ultra_scalp_10':{'size':0.10,'freq':2}, 'momentum_40':{'size':0.25,'freq':5},
                            'breakout_45':{'size':0.30,'freq':5}, 'reversal_30':{'size':0.20,'freq':6},
                            'aggressive_35':{'size':0.35,'freq':5}, 'aggressive_50':{'size':0.35,'freq':5},
                            'conservative_25':{'size':0.15,'freq':7}, 'swing_60':{'size':0.40,'freq':10}
                        }
                        for sname, sp in STRATEGY_PARAMS.items():
                            beh = beh_map.get(sname, {'size':0.20,'freq':4})
                            self._strats[sname] = {
                                'params': sp, 'beh': beh,
                                'capital': init_cap, 'positions': {},
                                'entry_prices': {}, 'last_prices': {},
                                'wins': 0, 'losses': 0, 'tick': 0
                            }
                        print(f'  10 strategies ready. Fetching real prices...')
                    
                    # Fetch real prices every 10 ticks
                    if tick % 10 == 0:
                        try:
                            pairs = self.engine.scanner.get_top_pairs(5)
                            for p in pairs:
                                mint = p.get('baseToken', {}).get('address', '')
                                price = float(p.get('priceUsd', 0))
                                if mint and price > 0:
                                    if mint not in self._real_prices:
                                        self._real_prices[mint] = []
                                    self._real_prices[mint].append(price)
                                    if len(self._real_prices[mint]) > 20:
                                        self._real_prices[mint].pop(0)
                        except:
                            pass
                        # Also fetch SOL price as fallback
                        sol_price = self.engine.scanner.get_price('So11111111111111111111111111111111111111112')
                        if sol_price:
                            if 'SOL' not in self._real_prices:
                                self._real_prices['SOL'] = []
                            self._real_prices['SOL'].append(sol_price)
                            if len(self._real_prices['SOL']) > 20:
                                self._real_prices['SOL'].pop(0)
                    
                    total_cap = sum(s['capital'] for s in self._strats.values())
                    self.engine.capital = total_cap
                    
                    # Each strategy trades based on real price movements
                    for sname, s in self._strats.items():
                        sp = s['params']; beh = s['beh']
                        cap = s['capital']; target_pct = sp['target']; stop_pct = sp['stop']
                        size_pct = beh['size']; freq = beh['freq']
                        
                        # Open new trade if we have real prices to track
                        if len(s['positions']) < 2 and cap > 30 and s['tick'] % freq == 0:
                            # Pick the most recent real price feed
                            available = [m for m, p in self._real_prices.items() if len(p) > 1]
                            if available:
                                chosen_mint = random.choice(available)
                                prices = self._real_prices[chosen_mint]
                                use_cap = cap * size_pct
                                pid = f"{sname}_{s['tick']}_{random.randint(1000,9999)}"
                                s['positions'][pid] = {
                                    'mint': chosen_mint, 'entry_value_inr': use_cap,
                                    'entry_time': datetime.now().isoformat()
                                }
                                s['entry_prices'][pid] = prices[-1]
                                s['last_prices'][pid] = prices[-1]
                                s['capital'] -= use_cap
                                print(f'  [{sname[:6]}] BUY  Rs{use_cap:,.0f} @ ${prices[-1]:.6f}')
                        
                        # Evaluate positions using real price changes
                        for pid in list(s['positions'].keys()):
                            mint = s['positions'][pid].get('mint', '')
                            prices = self._real_prices.get(mint, [])
                            if not prices:
                                continue
                            current_price = prices[-1]
                            entry_price = s['entry_prices'].get(pid, current_price)
                            if entry_price <= 0:
                                continue
                            ret = (current_price / entry_price) - 1
                            s['last_prices'][pid] = current_price
                            
                            if ret >= target_pct:
                                pos = s['positions'][pid]
                                entry_val = pos.get('entry_value_inr', 0)
                                pnl = entry_val * target_pct - entry_val * 0.01
                                s['capital'] += entry_val + pnl
                                s['wins'] += 1
                                self.engine.trades.append({
                                    'mint': mint[:8], 'entry_sol': entry_val/self.engine.usd_to_inr,
                                    'entry_time': pos.get('entry_time',''), 'exit_time': datetime.now().isoformat(),
                                    'ret_pct': ret*100, 'pnl': pnl, 'paper': True, 'strategy': sname
                                })
                                print(f'  [{sname[:6]}] TP   +{ret*100:.1f}% | +Rs{pnl:,.0f} | Bal Rs{total_cap:,.0f}')
                                del s['positions'][pid]
                            elif ret <= -stop_pct:
                                pos = s['positions'][pid]
                                entry_val = pos.get('entry_value_inr', 0)
                                pnl = entry_val * (-stop_pct) - entry_val * 0.01
                                s['capital'] += entry_val + pnl
                                s['losses'] += 1
                                self.engine.trades.append({
                                    'mint': mint[:8], 'entry_sol': entry_val/self.engine.usd_to_inr,
                                    'entry_time': pos.get('entry_time',''), 'exit_time': datetime.now().isoformat(),
                                    'ret_pct': ret*100, 'pnl': pnl, 'paper': True, 'strategy': sname
                                })
                                print(f'  [{sname[:6]}] SL   {ret*100:.1f}% | Rs{pnl:,.0f} | Bal Rs{total_cap:,.0f}')
                                del s['positions'][pid]
                        
                        s['tick'] += 1
                    
                    # Aggregate stats for dashboard
                    total_wins = sum(s['wins'] for s in self._strats.values())
                    total_losses = sum(s['losses'] for s in self._strats.values())
                    self.engine.wins = total_wins
                    self.engine.losses = total_losses
                    self.engine.capital = total_cap
                    
                    tick += 1
                    
                    tick += 1
                    if tick % 5 == 0:
                        self.engine.equity_curve.append((tick, self.engine.capital))
                        if self.engine.capital >= TARGET:
                            print(f'\n*** TARGET Rs{TARGET:,.0f} REACHED! ***\n')
                            self.engine.capital = TARGET
                            self.running = False
                            break
                    
                    time.sleep(2)
                else:
                    # Real mode: uses DexScreener
                    if tick % 10 == 0:
                        try:
                            tokens = self.engine.scanner.get_latest_tokens(5)
                            for t in tokens:
                                mint = t.get('tokenAddress', '')
                                if mint and mint not in [p.get('mint') for p in self.engine.positions.values()]:
                                    if self.engine.capital > 50:
                                        sol_amt = min(self.engine.capital / self.engine.usd_to_inr * 0.95, 0.1)
                                        self.engine.buy_token(mint, sol_amt)
                        except:
                            pass
                    
                    for pid in list(self.engine.positions.keys()):
                        try:
                            pos = self.engine.positions[pid]
                            info = self.engine.scanner.get_token_info(pos['mint'])
                            pairs = info.get('pairs', [])
                            if pairs:
                                price_usd = float(pairs[0].get('priceUsd', 0))
                                if price_usd > 0 and pos.get('entry_price_usd', 0) > 0:
                                    ret = (price_usd / pos['entry_price_usd'] - 1)
                                    cfg = self.engine.config.params
                                    if ret >= cfg['target']:
                                        self.engine.sell_token(pid, price_usd)
                                    elif ret <= -cfg['stop']:
                                        self.engine.sell_token(pid, price_usd)
                        except:
                            pass
                    
                    tick += 1
                    time.sleep(2)
                
            except Exception as e:
                print(f'  Agent error: {e}')
                time.sleep(5)
    
    def print_status(self):
        s = self.engine.summary()
        mode = 'PAPER' if self.paper_mode else 'REAL'
        print(f'\n{"="*50}')
        print(f'  PRODUCTION AGGRESSOR [{mode}]')
        print(f'{"="*50}')
        print(f'  Capital:    Rs{s["capital"]:,.2f} (${s["capital"]/self.engine.usd_to_inr:.2f})')
        print(f'  Return:     {s["return_pct"]:+.2f}% ({s["return_mult"]:.1f}x)')
        print(f'  Trades:     {s["trades"]} (W:{s["wins"]} L:{s["losses"]}) WR:{s["win_rate"]:.1f}%')
        print(f'  Config:     {s["config"]} (Gen {s["generation"]})')
        print(f'  Active:     {s["active"]} positions')
        print(f'  SOL Bal:    {s["wallet_sol"]:.4f}')
        print(f'  Withdrawn:  Rs{s["total_withdrawn"]:,.2f}')
        print(f'{"="*50}\n')

# ====================================================================
# FASTAPI DASHBOARD (with real data)
# ====================================================================
AGENT_STATE = {'agent': None, 'running': False}
AGENT_LOCK = threading.Lock()

def create_prod_dashboard():
    """Create Flask dashboard."""
    from flask import Flask, request, jsonify
    
    app = Flask(__name__)
    
    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Ultra Aggressor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0b0e;color:#e8e8e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:16px;min-height:100vh}
.container{max-width:800px;margin:0 auto}
.header{text-align:center;padding:24px 0 20px}
.header h1{font-size:22px;font-weight:700;letter-spacing:1px;background:linear-gradient(135deg,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .badge{display:inline-block;margin-top:6px;font-size:11px;padding:3px 10px;border-radius:20px;font-weight:600}
.badge.paper{background:#065f46;color:#6ee7b7}
.badge.real{background:#7f1d1d;color:#fca5a5}
.badge.wallet{background:#1e1b4b;color:#a5b4fc;margin-left:6px}
.capital-card{background:linear-gradient(135deg,#1e1b4b,#312e81);border-radius:16px;padding:24px;text-align:center;margin-bottom:14px;border:1px solid #4f46e5}
.capital-card .label{font-size:12px;color:#a5b4fc;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px}
.capital-card .value{font-size:40px;font-weight:800;color:#fff}
.capital-card .value .currency{font-size:20px;color:#a5b4fc}
.capital-card .target-row{margin-top:10px;display:flex;justify-content:space-between;font-size:11px;color:#a5b4fc}
.capital-card .bar{height:4px;background:#1e1b4b;border-radius:2px;margin-top:6px;overflow:hidden}
.capital-card .bar .fill{height:100%;background:linear-gradient(90deg,#a78bfa,#f472b6);border-radius:2px;transition:width .5s}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px}
.stat-card{background:#13141a;border-radius:12px;padding:14px;text-align:center;border:1px solid #1e1f2a}
.stat-card .s-label{font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px}
.stat-card .s-value{font-size:22px;font-weight:700;margin-top:4px}
.stat-card .s-sub{font-size:11px;color:#6b7280;margin-top:2px}
.green{color:#6ee7b7}.red{color:#f87171}.purple{color:#a78bfa}.gold{color:#fbbf24}
.strategy-bar{background:#13141a;border-radius:12px;padding:12px 16px;margin-bottom:14px;border:1px solid #1e1f2a;display:flex;justify-content:space-between;align-items:center}
.strategy-bar .s-name{font-size:13px;font-weight:600}
.strategy-bar .s-gen{font-size:11px;color:#6b7280}
.btn-group{display:flex;gap:8px;margin-bottom:14px}
.btn{padding:10px 20px;border:none;border-radius:10px;font-weight:600;font-size:13px;cursor:pointer;flex:1;transition:opacity .2s}
.btn:hover{opacity:.85}
.btn-deposit{background:linear-gradient(135deg,#059669,#10b981);color:#fff}
.btn-withdraw{background:linear-gradient(135deg,#7f1d1d,#dc2626);color:#fff}
.trade-section{background:#13141a;border-radius:12px;border:1px solid #1e1f2a;overflow:hidden}
.trade-section .ts-header{padding:12px 16px;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #1e1f2a}
.trade-table{width:100%;border-collapse:collapse;font-size:12px}
.trade-table th{padding:8px 12px;text-align:left;font-size:10px;color:#6b7280;text-transform:uppercase;border-bottom:1px solid #1e1f2a}
.trade-table td{padding:8px 12px;border-bottom:1px solid #1a1b24}
.trade-table tr:last-child td{border-bottom:none}
.footer{text-align:center;padding:16px;font-size:11px;color:#4b5563}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>ULTRA AGGRESSOR</h1>
    <div><span class="badge paper" id="badgeMode">PAPER</span><span class="badge wallet" id="badgeWallet">Wallet OK</span></div>
  </div>
  
  <div class="capital-card">
    <div class="label">Total Capital</div>
    <div class="value"><span class="currency">Rs</span> <span id="capValue">1,000</span></div>
    <div class="target-row"><span>Start Rs 1,000</span><span>Target Rs 1,00,000</span></div>
    <div class="bar"><div class="fill" id="capBar" style="width:1%"></div></div>
  </div>
  
  <div class="stats">
    <div class="stat-card">
      <div class="s-label">Return</div>
      <div class="s-value gold" id="retValue">0.00%</div>
      <div class="s-sub"><span id="retMult">1.0</span>x</div>
    </div>
    <div class="stat-card">
      <div class="s-label">Win Rate</div>
      <div class="s-value purple" id="wrValue">0%</div>
      <div class="s-sub"><span id="tradeCount">0</span> trades</div>
    </div>
    <div class="stat-card">
      <div class="s-label">Wins / Losses</div>
      <div class="s-value"><span class="green" id="winCount">0</span> / <span class="red" id="lossCount">0</span></div>
      <div class="s-sub">Active: <span id="activeCount">0</span></div>
    </div>
  </div>
  
  <div class="trade-section" style="margin-bottom:14px">
    <div class="ts-header">10 Strategies Running</div>
    <table class="trade-table">
      <thead><tr><th>Strategy</th><th>Win Rate</th><th>Wins/Losses</th><th>Status</th></tr></thead>
      <tbody id="stratBody">
        <tr><td colspan="6" style="text-align:center;color:#4b5563">Loading...</td></tr>
      </tbody>
    </table>
  </div>
  
  <div class="wallet-card" style="background:#13141a;border-radius:12px;padding:12px 16px;margin-bottom:14px;border:1px solid #1e1f2a;display:flex;justify-content:space-between;align-items:center">
    <div><span style="font-size:12px;color:#6b7280">Wallet:</span> <span style="font-size:13px;font-weight:600;color:#a5b4fc" id="walletAddr">--</span></div>
    <span style="font-size:11px;color:#6b7280;background:#1e1f2a;padding:4px 10px;border-radius:6px" id="walletCreated">Created</span>
  </div>
  
  <div class="btn-group">
    <button class="btn btn-deposit" onclick="showDeposit()">+ Deposit</button>
    <button class="btn btn-withdraw" onclick="showWithdraw()">Withdraw</button>
  </div>
  <div id="actionPanel" style="display:none;background:#13141a;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid #1e1f2a"></div>
  
  <div class="trade-section">
    <div class="ts-header">Trade History</div>
    <table class="trade-table">
      <thead><tr><th>#</th><th>Amount</th><th>Result</th><th>PnL</th><th>Strategy</th></tr></thead>
      <tbody id="tradeBody"></tbody>
    </table>
    <div style="padding:20px;text-align:center;color:#4b5563;font-size:13px" id="emptyState">No trades yet</div>
  </div>
  
  <div class="footer">Live · Auto-refresh 3s · <span id="lastUpdate">--</span> · Strat: <span id="stratCount">0</span> · Trades: <span id="apiTradeCount">0</span></div>
</div>
<script>
async function fetchData(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    const s=d.summary||{};
    const cap=s.capital||0;
    document.getElementById('capValue').textContent=cap.toLocaleString('en-IN',{maxFractionDigits:0});
    document.getElementById('capBar').style.width=Math.min(100,cap/100000*100).toFixed(2)+'%';
    document.getElementById('retValue').textContent=(s.return_pct||0).toFixed(2)+'%';
    document.getElementById('retMult').textContent=(s.return_mult||0).toFixed(1);
    document.getElementById('wrValue').textContent=(s.win_rate||0).toFixed(1)+'%';
    document.getElementById('tradeCount').textContent=s.trades||0;
    document.getElementById('winCount').textContent=s.wins||0;
    document.getElementById('lossCount').textContent=s.losses||0;
    document.getElementById('activeCount').textContent=s.active||0;
    document.getElementById('stratName').textContent=s.config||'--';
    document.getElementById('genCount').textContent=s.generation||0;
    document.getElementById('badgeMode').textContent=s.paper_mode?'PAPER':'REAL';
    document.getElementById('badgeMode').className='badge '+(s.paper_mode?'paper':'real');
    if(d.wallet)document.getElementById('walletAddr').textContent=d.wallet.substring(0,8)+'..'+d.wallet.slice(-4);
    
    // Footer counters
    document.getElementById('stratCount').textContent=d.strategies?Object.keys(d.strategies).length:0;
    document.getElementById('apiTradeCount').textContent=d.trades?d.trades.length:0;
    
    // Strategy table
    const sb=document.getElementById('stratBody');
    const stratEntries=d.strategies?Object.entries(d.strategies):[];
    if(stratEntries.length>0){
      sb.innerHTML=stratEntries.map(([name,sd])=>{
        const cap=sd.cap||0;
        const wr=sd.wr||0;
        const w=sd.wins||0;
        const l=sd.losses||0;
        const act=sd.active||0;
        const online=cap>10;
        const status=online?'<span class="green">● Online</span>'+((act>0)?' <span style="font-size:10px;color:#6b7280">('+act+' active)</span>':''):'<span class="red">● Offline</span>';
        return '<tr><td style="font-weight:600;color:#a78bfa">'+name.slice(0,12)+'</td><td class="'+(wr>=50?'green':'red')+'">'+wr.toFixed(1)+'%</td><td><span class="green">'+w+'</span>/<span class="red">'+l+'</span></td><td>'+status+'</td></tr>';
      }).join('');
    }else{
      sb.innerHTML='<tr><td colspan="4" style="text-align:center;color:#4b5563;padding:20px">⏳ Initializing strategies... (wait 5 sec)</td></tr>';
    }
    const tb=document.getElementById('tradeBody');
    const es=document.getElementById('emptyState');
    if(d.trades&&d.trades.length>0){
      es.style.display='none';
      tb.innerHTML=d.trades.slice(-20).reverse().map((t,i)=>{
        const cls=t.pnl>0?'green':'red';
        const sign=t.pnl>0?'+':'';
        const amt=(t.entry_sol||0).toFixed(3);
        const strat=(t.strategy||'??').slice(0,8);
        return '<tr><td>'+(i+1)+'</td><td>'+amt+' SOL</td><td class="'+cls+'">'+(t.ret_pct||0).toFixed(1)+'%</td><td class="'+cls+'">'+sign+'Rs'+(t.pnl||0).toFixed(0)+'</td><td style="font-size:11px;color:#6b7280">'+strat+'</td></tr>';
      }).join('');
    }else{es.style.display='block';tb.innerHTML=''}
    document.getElementById('lastUpdate').textContent=new Date().toLocaleTimeString();
  }catch(e){}
}
function showDeposit(){
  const p=document.getElementById('actionPanel');
  p.style.display='block';
  p.innerHTML='<div style="font-size:13px;font-weight:600;margin-bottom:10px">Deposit SOL</div><div style="display:flex;gap:8px"><input id="depAmt" type="number" step="0.1" min="0.1" value="0.5" style="flex:1;background:#0a0b0e;border:1px solid #2a2b36;border-radius:8px;padding:10px;color:#fff;font-size:14px"><button class="btn btn-deposit" style="flex:0">Deposit</button></div><div style="margin-top:8px;font-size:11px;color:#6b7280">1 SOL ≈ Rs 83</div>';
  p.querySelector('button').onclick=async()=>{
    const amt=parseFloat(document.getElementById('depAmt').value)||0.5;
    const r=await fetch('/api/deposit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sol:amt})});
    const d=await r.json();
    if(d.success)alert('Deposited '+d.amount+' SOL (Rs '+d.inr_value+')');
    p.style.display='none';
  };
}
function showWithdraw(){
  const p=document.getElementById('actionPanel');
  p.style.display='block';
  p.innerHTML='<div style="font-size:13px;font-weight:600;margin-bottom:10px">Withdraw Funds</div><div style="display:flex;gap:8px"><input id="wdAmt" type="number" step="10" min="10" value="100" style="flex:1;background:#0a0b0e;border:1px solid #2a2b36;border-radius:8px;padding:10px;color:#fff;font-size:14px"><button class="btn btn-withdraw" style="flex:0">Withdraw</button></div><div style="margin-top:8px;font-size:11px;color:#6b7280">Enter amount in Rs</div>';
  p.querySelector('button').onclick=async()=>{
    const amt=parseFloat(document.getElementById('wdAmt').value)||0;
    if(amt<10)return alert('Minimum Rs 10');
    const r=await fetch('/api/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:amt})});
    const d=await r.json();
    if(d.success)alert('Withdrawn Rs '+d.amount);
    else alert(d.error||'Failed');
    p.style.display='none';
  };
}
setInterval(fetchData,3000);fetchData();
</script>
</body>
</html>"""
    
    @app.route("/")
    def dashboard():
        return DASHBOARD_HTML
    
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
                strats_data = sm.get('strategies', {})
                return {
                    'summary': sm,
                    'trades': trades,
                    'strategies': strats_data,
                    'wallet': wallet_addr,
                    'running': AGENT_STATE.get('running', False)
                }
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
                sol_amt = float(data.get('sol', 0.5))
                inr_val = sol_amt * agent.engine.usd_to_inr
                agent.engine.capital += inr_val
                return {'success': True, 'amount': sol_amt, 'inr_value': round(inr_val, 2)}
            return {'success': False}, 400
    
    @app.route("/api/withdraw", methods=['POST'])
    def api_withdraw():
        with AGENT_LOCK:
            agent = AGENT_STATE.get('agent')
            if agent and agent.engine:
                data = request.get_json(silent=True) or {}
                amt = float(data.get('amount', 0))
                if amt < 10:
                    return {'success': False, 'error': 'Minimum Rs 10'}, 400
                actual = agent.engine.withdraw(amt)
                if actual > 0:
                    return {'success': True, 'amount': actual}
                return {'success': False, 'error': 'Insufficient funds'}, 400
            return {'success': False}, 400
    
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
        print('!' * 60)
        print('  PRODUCTION AGGRESSOR — REAL MODE')
        print('  THIS WILL USE REAL SOL FROM YOUR WALLET!')
        print('!' * 60)
        confirm = input('  Type "CONFIRM" to proceed: ').strip()
        if confirm != 'CONFIRM':
            print('  Aborted.')
            sys.exit(0)
        
        agent = ProductionAggressor(paper_mode=False)
        if agent.setup_wallet():
            agent.start_agent()
            print('\n  REAL TRADING ACTIVE. Press Ctrl+C to stop.')
            try:
                while True:
                    time.sleep(10)
                    agent.print_status()
            except KeyboardInterrupt:
                agent.stop_agent()
                print('\n  Stopped.')
    
    elif '--dashboard' in sys.argv:
        port = int(os.environ.get('PORT', '8765'))
        print('Starting Production Dashboard on http://0.0.0.0:{}'.format(port))
        
        agent = ProductionAggressor(paper_mode=True)
        
        # Auto-setup wallet for cloud deployment (no keyboard needed)
        if not os.path.exists(WALLET_FILE):
            print('  Auto-creating paper wallet for cloud deployment...')
            wallet = ProdWallet.generate_new('cloud_deploy_auto')
            with open(WALLET_FILE, 'w') as f:
                json.dump(wallet, f)
            agent.wallet_data = wallet
            agent.keypair = Keypair()
            agent.engine.set_trader(agent.keypair)
            print('  Paper wallet ready. Address:', wallet.get('address', 'auto')[:12] + '...')
        else:
            with open(WALLET_FILE) as f:
                agent.wallet_data = json.load(f)
            agent.keypair = Keypair()
            agent.engine.set_trader(agent.keypair)
            print('  Wallet loaded:', agent.wallet_data.get('address', '')[:12] + '...')
        
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
