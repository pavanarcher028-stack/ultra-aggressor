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
    """Scan for newly launched tokens on Solana."""
    
    def get_latest_tokens(self, limit: int = 30) -> list:
        """Get latest token profiles from DexScreener."""
        import urllib.request
        req = urllib.request.Request(
            f'{DEXSCREENER_API}/token-profiles/latest/v1',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data[:limit]
    
    def get_token_info(self, mint: str) -> dict:
        """Get detailed token info from DexScreener."""
        import urllib.request
        req = urllib.request.Request(
            f'{DEXSCREENER_API}/latest/dex/tokens/{mint}',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    
    def search(self, query: str) -> list:
        """Search for tokens."""
        import urllib.request
        req = urllib.request.Request(
            f'{DEXSCREENER_API}/latest/dex/search?q={query}',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get('pairs', [])

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
        if not self.trader:
            return {'success': False, 'error': 'No trader configured'}
        
        amount_lamports = int(amount_sol * 1e9)
        result = self.trader.execute_swap(WSOL_MINT, mint, amount_lamports)
        
        if result.get('success'):
            trade_amt_inr = amount_sol * self.usd_to_inr
            fee = trade_amt_inr * FEE_BUY
            self.capital -= trade_amt_inr
            
            pos = {
                'mint': mint,
                'entry_sol': amount_sol,
                'entry_price_usd': result.get('output_amount', 0),
                'entry_time': datetime.now().isoformat(),
                'paper': self.paper_mode
            }
            pid = f"{mint[:8]}_{datetime.now().timestamp()*1000:.0f}"
            self.positions[pid] = pos
            return {'success': True, 'pid': pid, 'position': pos, 'result': result}
        
        return result
    
    def sell_token(self, pid: str, price: float) -> dict:
        """Sell a token position (simulated or real)."""
        pos = self.positions.get(pid)
        if not pos:
            return {'success': False, 'error': 'Position not found'}
        
        if not self.trader:
            return {'success': False, 'error': 'No trader configured'}
        
        result = self.trader.execute_swap(pos['mint'], WSOL_MINT, int(pos['entry_sol'] * 1e9))
        
        if result.get('success'):
            ret = (price / pos.get('entry_price_usd', price) - 1) * 100 if pos.get('entry_price_usd') else 0
            pnl = pos['entry_sol'] * self.usd_to_inr * (ret / 100) - pos['entry_sol'] * self.usd_to_inr * FEE_SELL
            
            self.capital += pos['entry_sol'] * self.usd_to_inr + pnl
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            
            tr = {
                'pid': pid, 'mint': pos['mint'], 'entry_time': pos['entry_time'],
                'exit_time': datetime.now().isoformat(), 'ret_pct': ret, 'pnl': pnl,
                'paper': self.paper_mode
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
            'start_time': self.start_time.isoformat()
        }

# ====================================================================
# STRATEGY SYSTEM (from meta_aggressor)
# ====================================================================
STRATEGY_PARAMS = {
    'aggressive_40':  {'target': 0.40, 'stop': 0.15, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.25, 'trail_dist': 0.12, 'desc': '+40%/-15%, trail after 25%'},
    'aggressive_50':  {'target': 0.50, 'stop': 0.18, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.30, 'trail_dist': 0.15, 'desc': '+50%/-18%, trail after 30%'},
    'conservative_25':{'target': 0.25, 'stop': 0.10, 'min_vol': 3.0, 'use_trail': True, 'trail_act': 0.15, 'trail_dist': 0.08, 'desc': '+25%/-10%, trail after 15%'},
    'scalp_15':       {'target': 0.15, 'stop': 0.06, 'min_vol': 1.5, 'use_trail': False, 'trail_act': 0, 'trail_dist': 0, 'desc': '+15%/-6%, no trail, fast scalp'},
}

SIGNAL_MODES = {
    'momentum': {'desc': 'Buy when price + volume rising'},
    'reversal': {'desc': 'Buy after sharp drop + volume spike'},
    'breakout': {'desc': 'Buy when price breaks range with volume'},
}

class StrategyConfig:
    def __init__(self, params_key='aggressive_40', signal_key='momentum'):
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
        self.running = False
        self.agent_thread = None
    
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
        fake_mints = ['So11111111111111111111111111111111111111111']
        self._next_mint_idx = 1
        
        def fake_price(last_price: float) -> float:
            change = random.gauss(self.engine.config.params.get('drift', 0.005), 0.06)
            return last_price * (1 + change)
        
        while self.running:
            try:
                if self.paper_mode:
                    # Paper mode: fully simulated
                    # 1. Open new position periodically
                    if len(self.engine.positions) < 3 and self.engine.capital > 100 and tick % 15 == 0:
                        mint = fake_mints[0] + hashlib.md5(str(tick).encode()).hexdigest()[:16]
                        sol_amt = min(self.engine.capital / self.engine.usd_to_inr * 0.95, 0.08)
                        entry_price = 0.0001 + random.random() * 0.01
                        result = self.engine.buy_token(mint, sol_amt)
                        if result.get('success'):
                            pos = self.engine.positions.get(result['pid'])
                            if pos:
                                pos['entry_price_usd'] = entry_price
                            print(f'  Paper buy: {sol_amt:.4f} SOL | entry=${entry_price:.6f}')
                    
                    # 2. Simulate price moves and check TP/SL
                    for pid in list(self.engine.positions.keys()):
                        pos = self.engine.positions[pid]
                        old_price = pos.get('entry_price_usd', 0.0001)
                        if not hasattr(self, '_sim_prices'):
                            self._sim_prices = {}
                        sim_price = self._sim_prices.get(pid, old_price)
                        sim_price = fake_price(sim_price)
                        self._sim_prices[pid] = sim_price
                        
                        ret = (sim_price / old_price - 1) if old_price > 0 else 0
                        cfg = self.engine.config.params
                        if ret >= cfg['target']:
                            result = self.engine.sell_token(pid, sim_price)
                            if result.get('success'):
                                print(f'  TP HIT +{ret*100:.1f}% | PnL: Rs{result.get("pnl",0):.0f}')
                        elif ret <= -cfg['stop']:
                            result = self.engine.sell_token(pid, sim_price)
                            if result.get('success'):
                                print(f'  SL HIT {ret*100:.1f}% | PnL: Rs{result.get("pnl",0):.0f}')
                    
                    # 3. Strategy evolution every 50 trades
                    if (self.engine.wins + self.engine.losses) > 0 and \
                       (self.engine.wins + self.engine.losses) % 50 == 0:
                        self._evolve_strategy()
                    
                    tick += 1
                    if tick % 5 == 0:
                        self.engine.equity_curve.append((tick, self.engine.total_value))
                        # Check if target reached
                        if self.engine.capital >= TARGET:
                            print(f'\n*** TARGET Rs{TARGET:,.0f} REACHED! ***\n')
                            self.engine.capital = TARGET
                            self.running = False
                            break
                    
                    time.sleep(3)
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
    """Create Flask dashboard for production agent."""
    from flask import Flask
    
    app = Flask(__name__)
    
    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Production Aggressor</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif; background:#0a0a0f; color:#e0e0e0; padding:20px; }
.container { max-width:1200px; margin:0 auto; }
.header { background:linear-gradient(135deg,#1a0033,#330066); padding:20px; border-radius:12px; margin-bottom:20px; border:1px solid #6633cc; }
.header h1 { color:#cc66ff; font-size:26px; }
.header .subtitle { color:#888; font-size:13px; margin-top:3px; }
.header .mode-tag { display:inline-block; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:bold; margin-left:10px; }
.mode-paper { background:#003300; color:#00ff88; }
.mode-real { background:#330000; color:#ff4444; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; margin-bottom:20px; }
.card { background:#12121a; border-radius:10px; padding:15px; border:1px solid #2a2a4e; }
.card h3 { color:#666; font-size:11px; text-transform:uppercase; margin-bottom:8px; }
.card .value { font-size:24px; font-weight:bold; }
.card .value.green { color:#00ff88; }
.card .value.red { color:#ff4444; }
.card .value.purple { color:#cc66ff; }
.card .value.gold { color:#ffd700; }
.progress-bar { height:6px; background:#2a2a4e; border-radius:3px; margin-top:8px; overflow:hidden; }
.progress-bar .fill { height:100%; background:linear-gradient(90deg,#cc66ff,#ffd700); border-radius:3px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; padding:8px 12px; border-bottom:1px solid #2a2a4e; color:#666; font-size:11px; text-transform:uppercase; }
td { padding:8px 12px; border-bottom:1px solid #1a1a2e; }
.win { color:#00ff88; } .loss { color:#ff4444; }
.btn { background:linear-gradient(135deg,#cc66ff,#9933ff); border:none; color:#fff; padding:8px 20px; border-radius:6px; cursor:pointer; font-weight:bold; }
.btn:hover { opacity:0.9; }
.btn.danger { background:linear-gradient(135deg,#ff4444,#cc0000); }
.refresh { color:#666; font-size:12px; margin-top:10px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>PRODUCTION AGGRESSOR <span class="mode-tag mode-paper" id="modeTag">PAPER</span></h1>
    <div class="subtitle">Real Solana Trading via Jupiter API | DexScreener Scanner | Self-Improving</div>
  </div>
  
  <div class="grid">
    <div class="card">
      <h3>Total Capital</h3>
      <div class="value green" id="totalValue">Rs --</div>
      <div class="progress-bar"><div class="fill" id="targetProgress" style="width:0%"></div></div>
    </div>
    <div class="card">
      <h3>Return</h3>
      <div class="value gold" id="returnPct">--</div>
      <div style="font-size:12px;color:#666;"><span id="returnMult">--</span>x</div>
    </div>
    <div class="card">
      <h3>Win Rate</h3>
      <div class="value purple" id="winRate">--</div>
      <div style="font-size:12px;color:#666;"><span id="totalTrades">0</span> trades</div>
    </div>
    <div class="card">
      <h3>Strategy</h3>
      <div class="value" style="font-size:14px;color:#e0e0e0;" id="strategy">--</div>
      <div style="font-size:12px;color:#666;">Gen <span id="generation">0</span></div>
    </div>
    <div class="card">
      <h3>SOL Balance</h3>
      <div class="value gold" id="solBalance">--</div>
      <div style="font-size:12px;color:#666;">Wallet: <span id="walletAddr">--</span></div>
    </div>
    <div class="card">
      <h3>Withdrawn</h3>
      <div class="value gold" id="withdrawn">Rs 0</div>
      <button class="btn" onclick="alert('Paper mode: no real withdraw')">Withdraw</button>
    </div>
  </div>
  
  <div class="card" style="margin-bottom:20px;">
    <h3>Trade History</h3>
    <div style="max-height:250px;overflow-y:auto;">
      <table>
        <thead><tr><th>Mint</th><th>Entry</th><th>Exit</th><th>Return</th><th>PnL</th><th>Paper</th></tr></thead>
        <tbody id="tradeHistory"></tbody>
      </table>
    </div>
  </div>
  
  <div class="refresh" id="refreshInfo">Last updated: -- | Auto-refresh 3s</div>
</div>
<script>
async function fetchData() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const s = d.summary || {};
    document.getElementById('totalValue').textContent = 'Rs ' + (s.capital || 0).toLocaleString('en-IN',{maxFractionDigits:0});
    document.getElementById('returnPct').textContent = (s.return_pct || 0).toFixed(2) + '%';
    document.getElementById('returnMult').textContent = (s.return_mult || 0).toFixed(1);
    document.getElementById('winRate').textContent = (s.win_rate || 0).toFixed(1) + '%';
    document.getElementById('totalTrades').textContent = s.trades || 0;
    document.getElementById('strategy').textContent = s.config || '--';
    document.getElementById('generation').textContent = s.generation || 0;
    document.getElementById('solBalance').textContent = (s.wallet_sol || 0).toFixed(4) + ' SOL';
    document.getElementById('walletAddr').textContent = (d.address || '--').substring(0,12) + '...';
    document.getElementById('withdrawn').textContent = 'Rs ' + (s.total_withdrawn || 0).toLocaleString();
    document.getElementById('modeTag').textContent = s.paper_mode ? 'PAPER' : 'REAL';
    document.getElementById('modeTag').className = 'mode-tag ' + (s.paper_mode ? 'mode-paper' : 'mode-real');
    
    const pct = Math.min(100, ((s.capital || 0) / 100000) * 100);
    document.getElementById('targetProgress').style.width = pct.toFixed(1) + '%';
    
    const tbody = document.getElementById('tradeHistory');
    if (d.trades && d.trades.length > 0) {
      tbody.innerHTML = d.trades.slice(-15).reverse().map(t => {
        const cls = (t.pnl || 0) > 0 ? 'win' : 'loss';
        return '<tr><td>' + (t.mint || '').substring(0,10) + '..</td><td>' + (t.entry_time || '').substring(11,19) + '</td><td>' + (t.exit_time || '').substring(11,19) + '</td><td class="' + cls + '">' + (t.ret_pct || 0).toFixed(1) + '%</td><td class="' + cls + '">Rs' + (t.pnl || 0).toFixed(0) + '</td><td>' + (t.paper ? 'Y' : 'N') + '</td></tr>';
      }).join('');
    }
    document.getElementById('refreshInfo').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  } catch(e) { console.error(e); }
}
setInterval(fetchData, 3000);
fetchData();
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
                return {
                    'summary': agent.engine.summary(),
                    'trades': agent.engine.trades[-30:],
                    'address': agent.wallet_data.get('address', '') if agent.wallet_data else '',
                    'running': AGENT_STATE.get('running', False)
                }
            return {'summary': {'capital': 0, 'trades': 0}}
    
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
