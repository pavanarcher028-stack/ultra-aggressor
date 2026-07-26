"""
MEME AGENT — 24/7 Autonomous Meme Coin Trading Agent
=====================================================
For real money. Runs 24/7. Scans, filters, enters, exits automatically.
All costs (fees, gas, slippage, tax) deducted BEFORE profit calculation.
State saved to disk — survives restarts/crashes.
"""
import numpy as np, pandas as pd, json, os, time, math, pickle
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple
import warnings; warnings.filterwarnings('ignore')

# ====================================================================
# COST MODELS — Realistic fees per chain
# ====================================================================
@dataclass
class ChainCosts:
    name: str
    swap_fee_pct: float       # DEX swap fee (e.g., 0.3% = 0.003)
    gas_fixed_usd: float      # Fixed gas per tx in USD
    pump_fee_pct: float       # Pump.fun style platform fee
    slippage_pct: float       # Expected slippage for meme coin
    tax_buy_pct: float        # Token buy tax (if any)
    tax_sell_pct: float       # Token sell tax (if any)
    
    def round_trip_cost_pct(self, trade_size_usd: float) -> float:
        """Total cost of a round-trip trade as % of trade size."""
        buy_cost = self.swap_fee_pct + self.pump_fee_pct + self.tax_buy_pct + self.slippage_pct
        sell_cost = self.swap_fee_pct + self.pump_fee_pct + self.tax_sell_pct + self.slippage_pct
        gas_pct = (self.gas_fixed_usd * 2) / max(trade_size_usd, 1) if trade_size_usd > 0 else 0
        return buy_cost + sell_cost + gas_pct
    
    def break_even_gain_pct(self, trade_size_usd: float) -> float:
        """Minimum % gain needed to break even after ALL costs."""
        return self.round_trip_cost_pct(trade_size_usd) * 100

# Chain configurations (realistic estimates)
CHAINS = {
    'SOL': ChainCosts('Solana', 0.0025, 0.002, 0.01, 0.02, 0.0, 0.0),      # Raydium + pump.fun
    'ETH': ChainCosts('Ethereum', 0.003, 25.0, 0.0, 0.02, 0.0, 0.0),       # Uniswap
    'BASE': ChainCosts('Base', 0.003, 0.05, 0.0, 0.015, 0.0, 0.0),         # Aerodrome
    'BSC': ChainCosts('BSC', 0.0025, 0.10, 0.0, 0.02, 0.0, 0.0),          # PancakeSwap
}

# ====================================================================
# STATE MANAGEMENT — Survives restarts
# ====================================================================
class AgentState:
    """Persistent state for the agent. Saves/loads from disk."""
    
    STATE_FILE = 'meme_agent_state.pkl'
    
    def __init__(self, initial_capital_inr=1000):
        self.initial_capital = initial_capital_inr
        self.capital_inr = initial_capital_inr      # Available INR
        self.capital_usd = initial_capital_inr / 85  # Convert at ~85 INR/USD
        self.positions: Dict[str, dict] = {}          # Active positions
        self.trade_history: List[dict] = []
        self.total_fees_paid_inr = 0.0
        self.total_fees_paid_usd = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.blacklisted_coins: set = set()
        self.last_scan_time = None
        self.kill_switch_active = False
        self.kill_switch_reason = ''
        self.start_time = datetime.now()
        self.seen_coins: set = set()                  # Avoid re-entering same coin
        self.daily_start_capital = initial_capital_inr
        self.daily_loss_pct = 0.0
        
    def save(self):
        data = {k: v for k, v in self.__dict__.items()}
        data['blacklisted_coins'] = list(self.blacklisted_coins)
        data['seen_coins'] = list(self.seen_coins)
        with open(self.STATE_FILE, 'wb') as f:
            pickle.dump(data, f)
    
    def load(self):
        if not os.path.exists(self.STATE_FILE):
            return False
        with open(self.STATE_FILE, 'rb') as f:
            data = pickle.load(f)
        data['blacklisted_coins'] = set(data.get('blacklisted_coins', []))
        data['seen_coins'] = set(data.get('seen_coins', []))
        for k, v in data.items():
            setattr(self, k, v)
        return True
    
    @property
    def total_value_inr(self) -> float:
        pos_value = 0
        for pos in self.positions.values():
            pos_value += pos['quantity'] * pos['current_price_usd'] * 85
        return self.capital_inr + pos_value
    
    @property
    def total_return_pct(self) -> float:
        return (self.total_value_inr / self.initial_capital - 1) * 100
    
    @property
    def win_rate(self) -> float:
        return self.winning_trades / max(self.total_trades, 1) * 100

# ====================================================================
# COST-AWARE TRADE EXECUTOR
# ====================================================================
class CostAwareExecutor:
    """Executes trades with all costs deducted before profit calculation."""
    
    def __init__(self, state: AgentState):
        self.state = state
    
    def get_chain(self, coin: dict) -> ChainCosts:
        return CHAINS.get(coin.get('chain', 'SOL'), CHAINS['SOL'])
    
    def can_enter(self, coin: dict, entry_amt_inr: float) -> Tuple[bool, str, float]:
        """Check if entry is viable after costs. Returns (can_enter, reason, effective_cost_pct)."""
        chain = self.get_chain(coin)
        entry_usd = entry_amt_inr / 85
        
        # Check minimum gas buffer
        if entry_usd < chain.gas_fixed_usd * 10:
            return False, f'Entry too small for gas (${entry_usd:.2f} vs ${chain.gas_fixed_usd*10:.2f} min)', 0
        
        # Calculate total cost
        cost_pct = chain.round_trip_cost_pct(entry_usd)
        cost_inr = entry_amt_inr * cost_pct
        
        # Check if capital can cover costs
        if cost_inr > self.state.capital_inr * 0.1:
            return False, f'Costs too high vs capital ({cost_pct*100:.1f}% = Rs{cost_inr:.0f})', cost_pct
        
        # Effective buy price after costs
        buy_cost = chain.swap_fee_pct + chain.pump_fee_pct + chain.tax_buy_pct + chain.slippage_pct
        effective_cost = cost_pct  # round trip
        break_even = chain.break_even_gain_pct(entry_usd)
        
        return True, f'Cost {cost_pct*100:.1f}% (breakeven at +{break_even:.1f}%)', cost_pct
    
    def execute_buy(self, coin: dict, entry_price_usd: float, allocation_pct: float = 0.50) -> Optional[dict]:
        """Execute a buy with all costs factored in."""
        chain = self.get_chain(coin)
        entry_inr = self.state.capital_inr * allocation_pct
        entry_usd = entry_inr / 85
        cost_pct = chain.round_trip_cost_pct(entry_usd)
        
        # Deduct entry costs
        buy_cost_pct = chain.swap_fee_pct + chain.pump_fee_pct + chain.tax_buy_pct + chain.slippage_pct
        gas_cost_usd = chain.gas_fixed_usd
        gas_cost_inr = gas_cost_usd * 85
        
        # Amount after costs
        amount_after_cost = entry_usd * (1 - buy_cost_pct)
        quantity = amount_after_cost / entry_price_usd
        
        # Record fees
        total_fee_usd = entry_usd * buy_cost_pct + gas_cost_usd
        total_fee_inr = total_fee_usd * 85
        
        position = {
            'coin_name': coin['name'],
            'ticker': coin['ticker'],
            'chain': chain.name,
            'entry_price_usd': entry_price_usd,
            'entry_time': datetime.now().isoformat(),
            'quantity': quantity,
            'allocation_inr': entry_inr,
            'allocation_usd': entry_usd,
            'fees_paid_buy_inr': total_fee_inr,
            'fees_paid_buy_usd': total_fee_usd,
            'current_price_usd': entry_price_usd,
            'peak_price_usd': entry_price_usd,
            'peak_gain_pct': 0,
            'sold_half': False,
            'sold_rest': False,
            'volume_drop_pct': 0,
            'whale_dumped': False,
        }
        
        self.state.capital_inr -= entry_inr
        self.state.capital_usd -= entry_usd
        self.state.total_fees_paid_inr += total_fee_inr
        self.state.total_fees_paid_usd += total_fee_usd
        
        return position
    
    def execute_sell(self, ticker: str, current_price_usd: float, sell_pct: float = 1.0, reason: str = '') -> Optional[dict]:
        """Execute a sell with all costs deducted. Returns net proceeds."""
        if ticker not in self.state.positions:
            return None
        
        pos = self.state.positions[ticker]
        chain = CHAINS.get(pos['chain'], CHAINS['SOL'])
        pos['current_price_usd'] = current_price_usd
        
        sell_qty = pos['quantity'] * sell_pct
        gross_proceeds_usd = sell_qty * current_price_usd
        
        # Sell costs
        sell_cost_pct = chain.swap_fee_pct + chain.pump_fee_pct + chain.tax_sell_pct + chain.slippage_pct
        gas_cost_usd = chain.gas_fixed_usd
        net_proceeds_usd = gross_proceeds_usd * (1 - sell_cost_pct) - gas_cost_usd
        net_proceeds_inr = net_proceeds_usd * 85
        
        fee_usd = gross_proceeds_usd - net_proceeds_usd
        fee_inr = fee_usd * 85
        
        # Calculate net gain/loss (already after costs)
        entry_cost = pos['allocation_usd']
        net_gain_usd = net_proceeds_usd - (entry_cost * sell_pct)
        net_gain_pct = (net_gain_usd / (entry_cost * sell_pct)) * 100 if entry_cost > 0 else 0
        
        # Update position
        pos['quantity'] -= sell_qty
        self.state.capital_inr += net_proceeds_inr
        self.state.capital_usd += net_proceeds_usd
        self.state.total_fees_paid_inr += fee_inr
        self.state.total_fees_paid_usd += fee_usd
        self.state.total_trades += 1
        
        if net_gain_usd > 0:
            self.state.winning_trades += 1
        
        trade_record = {
            'time': datetime.now().isoformat(),
            'action': 'SELL',
            'coin': pos['ticker'],
            'entry_price': pos['entry_price_usd'],
            'exit_price': current_price_usd,
            'sell_pct': sell_pct,
            'gross_proceeds_usd': gross_proceeds_usd,
            'fees_usd': fee_usd,
            'net_proceeds_usd': net_proceeds_usd,
            'net_gain_pct': net_gain_pct,
            'net_gain_usd': net_gain_usd,
            'reason': reason,
        }
        self.state.trade_history.append(trade_record)
        
        # Remove if fully sold
        if pos['quantity'] <= 0.0000001:
            del self.state.positions[ticker]
        
        return trade_record

# ====================================================================
# EXIT STRATEGY — Cost-aware, volume-aware, trailing
# ====================================================================
class ExitEngine:
    """Decides when to exit a position based on price, volume, and costs."""
    
    def __init__(self, state: AgentState, executor: CostAwareExecutor):
        self.state = state
        self.executor = executor
        
    def evaluate(self, ticker: str, current_price_usd: float, 
                 volume_24h: float = 0, peak_volume: float = 1,
                 whale_dump: bool = False) -> List[dict]:
        """Evaluate exit conditions. Returns list of sell actions to execute."""
        pos = self.state.positions.get(ticker)
        if not pos:
            return []
        
        pos['current_price_usd'] = current_price_usd
        gain_pct = (current_price_usd / pos['entry_price_usd'] - 1) * 100
        pos['peak_price_usd'] = max(pos['peak_price_usd'], current_price_usd)
        pos['peak_gain_pct'] = max(pos['peak_gain_pct'], gain_pct)
        
        chain = CHAINS.get(pos['chain'], CHAINS['SOL'])
        breakeven = chain.break_even_gain_pct(pos['allocation_usd'])
        actions = []
        
        # 1. Volume decay check (volume dropped 80%+ from peak)
        vol_drop_pct = 100 * (1 - volume_24h / max(peak_volume, 1))
        pos['volume_drop_pct'] = max(pos['volume_drop_pct'], vol_drop_pct)
        if vol_drop_pct > 80 and gain_pct > breakeven:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 1.0, f'VOLUME_DECAY_{vol_drop_pct:.0f}%'))
            return actions
        
        # 2. Whale dump
        if whale_dump:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 1.0, 'WHALE_DUMP'))
            return actions
        
        # 3. Take profit: sell half at 2x (after costs)
        if not pos['sold_half'] and gain_pct >= 100:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 0.5, f'TP_2X_GAIN_{gain_pct:.0f}%'))
            pos['sold_half'] = True
        
        # 4. Take profit: sell rest at 5x (after costs)
        if pos['sold_half'] and not pos['sold_rest'] and gain_pct >= 300:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 1.0, f'TP_5X_GAIN_{gain_pct:.0f}%'))
            pos['sold_rest'] = True
        
        # 5. Trailing stop (activate after 100% gain)
        if gain_pct > 100:
            trail_from = pos['peak_price_usd']
            trail_dist = 0.30  # 30% trailing
            trail_price = trail_from * (1 - trail_dist)
            if current_price_usd < trail_price and gain_pct > breakeven:
                actions.append(self.executor.execute_sell(
                    ticker, current_price_usd, 1.0, f'TRAIL_HIT_{trail_dist*100:.0f}%_FROM_PEAK'))
                return actions
        
        # 6. Stop loss (after costs already incurred — cut at -25% from entry)
        if not pos['sold_half'] and gain_pct < -25:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 1.0, f'STOP_LOSS_{gain_pct:.0f}%'))
            return actions
        
        # 7. Time stop: if held > 72 hours and not profitable after costs
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        if hours_held > 72 and gain_pct < breakeven:
            actions.append(self.executor.execute_sell(
                ticker, current_price_usd, 1.0, f'TIME_STOP_{hours_held:.0f}h_BREAKEVEN_{breakeven:.1f}%'))
            return actions
        
        return actions

# ====================================================================
# SCANNER — Pairs with DexScreener-style data
# ====================================================================
class DexScanner:
    """Scans for new meme coin pairs. Production: uses DexScreener API."""
    
    def __init__(self, state: AgentState):
        self.state = state
    
    def scan(self) -> List[dict]:
        """Scan for new tradable coins. Returns filtered candidates.
        
        In production, this would:
        1. Call https://api.dexscreener.com/latest/dex/search?q= (new pairs)
        2. Call https://api.dexscreener.com/token-profiles/latest/v1 (new tokens)
        3. Check Telegram/Discord pump groups
        4. Monitor Twitter/X for ticker mentions
        5. Check pump.fun for new launches
        
        For demo: generates sample coins.
        """
        return self._demo_scan()
    
    def _demo_scan(self) -> List[dict]:
        """Demo: generates sample newly launched coins."""
        import random
        templates = [
            {'name': 'PepeFrog', 'ticker': 'PEPEF', 'chain': 'SOL', 'age_mins': 10,
             'liquidity_usd': 45000, 'vol_24h': 120000, 'holders': 342,
             'price_usd': 0.0000035, 'launch_price': 0.000001,
             'social_score': 72, 'rug_risk': 'LOW', 'verified': False,
             'whale_buys_1h': 4, 'kol_tweeted': True},
            {'name': 'DogWifThanos', 'ticker': 'DWIFT', 'chain': 'SOL', 'age_mins': 30,
             'liquidity_usd': 28000, 'vol_24h': 89000, 'holders': 187,
             'price_usd': 0.000008, 'launch_price': 0.0000005,
             'social_score': 85, 'rug_risk': 'LOW', 'verified': True,
             'whale_buys_1h': 2, 'kol_tweeted': False},
            {'name': 'CatMoonRocket', 'ticker': 'CMR', 'chain': 'ETH', 'age_mins': 60,
             'liquidity_usd': 120000, 'vol_24h': 450000, 'holders': 891,
             'price_usd': 0.0000008, 'launch_price': 0.0000001,
             'social_score': 45, 'rug_risk': 'MED', 'verified': False,
             'whale_buys_1h': 1, 'kol_tweeted': False},
            {'name': 'BasedChad', 'ticker': 'CHAD', 'chain': 'BASE', 'age_mins': 5,
             'liquidity_usd': 12000, 'vol_24h': 35000, 'holders': 89,
             'price_usd': 0.000045, 'launch_price': 0.00001,
             'social_score': 91, 'rug_risk': 'LOW', 'verified': False,
             'whale_buys_1h': 5, 'kol_tweeted': True},
        ]
        # Only return coins we haven't seen yet
        new_coins = [c for c in templates if c['ticker'] not in self.state.seen_coins]
        for c in new_coins:
            self.state.seen_coins.add(c['ticker'])
        return new_coins

# ====================================================================
# COST-AWARE FILTER
# ====================================================================
class CostAwareFilter:
    """Filters coins with cost awareness."""
    
    def __init__(self, state: AgentState):
        self.state = state
    
    def screen(self, coin: dict) -> dict:
        """Full screening with cost awareness."""
        chain = CHAINS.get(coin.get('chain', 'SOL'), CHAINS['SOL'])
        entry_usd = (self.state.capital_inr * 0.50) / 85
        cost_pct = chain.round_trip_cost_pct(entry_usd)
        breakeven = chain.break_even_gain_pct(entry_usd)
        
        checks = [
            ('chain_supported', coin.get('chain', '') in CHAINS),
            ('honeypot_risk_low', coin.get('rug_risk', 'HIGH') != 'HIGH'),
            ('min_liquidity', coin.get('liquidity_usd', 0) >= 10000),
            ('max_age_24h', coin.get('age_mins', 9999) <= 1440),
            ('volume_active', coin.get('vol_24h', 0) / max(coin.get('liquidity_usd', 1), 1) >= 2.0),
            ('min_holders', coin.get('holders', 0) >= 50),
            ('social_buzz', coin.get('social_score', 0) >= 50),
            ('whale_buys', coin.get('whale_buys_1h', 0) >= 1),
        ]
        
        passed = sum(1 for _, v in checks if v)
        total = len(checks)
        score = passed / total
        
        return {
            'score': score, 'passed': passed, 'total': total,
            'verdict': 'GREEN' if score >= 0.75 else ('YELLOW' if score >= 0.5 else 'RED'),
            'checks': dict(checks),
            'cost_pct': cost_pct * 100,
            'breakeven_pct': breakeven,
            'chain_costs': f'{chain.name}: {chain.round_trip_cost_pct(entry_usd)*100:.1f}% round trip + gas ${chain.gas_fixed_usd*2:.2f}'
        }

# ====================================================================
# KILL SWITCH — Cost-aware
# ====================================================================
class KillSwitch:
    """Protects capital with multiple layers."""
    
    def __init__(self, state: AgentState):
        self.state = state
        self.max_daily_loss_pct = 40  # Stop if 40% down in a day
        self.max_total_loss_pct = 70  # Stop if 70% down total
        self.max_concurrent_positions = 5
        self.daily_check_reset()
    
    def daily_check_reset(self):
        now = datetime.now()
        self.day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.day_start_capital = self.state.total_value_inr
    
    def check(self) -> Tuple[bool, str]:
        """Check all kill switch conditions. Resets if conditions normalize."""
        now = datetime.now()
        daily_pct = (self.day_start_capital - self.state.total_value_inr) / max(self.day_start_capital, 1) * 100
        total_pct = (self.state.initial_capital - self.state.total_value_inr) / max(self.state.initial_capital, 1) * 100
        
        # Auto-reset kill switch if conditions improved
        if self.state.kill_switch_active:
            if len(self.state.positions) < self.max_concurrent_positions and self.state.capital_inr >= 100:
                if 'MAX_POSITIONS' in self.state.kill_switch_reason or 'CAPITAL_TOO_LOW' in self.state.kill_switch_reason:
                    self.state.kill_switch_active = False
                    self.state.kill_switch_reason = ''
                    return False, 'OK'
        
        # Daily loss limit
        if daily_pct > self.max_daily_loss_pct:
            return True, f'DAILY_LOSS_{daily_pct:.0f}%_EXCEEDS_{self.max_daily_loss_pct}%_LIMIT'
        
        # Total loss limit
        if total_pct > self.max_total_loss_pct:
            return True, f'TOTAL_LOSS_{total_pct:.0f}%_EXCEEDS_{self.max_total_loss_pct}%_LIMIT'
        
        # Too many positions (only if we have active capital)
        if len(self.state.positions) >= self.max_concurrent_positions and self.state.capital_inr > 0:
            return True, f'MAX_POSITIONS_{self.max_concurrent_positions}_REACHED'
        
        # Capital too low to trade
        if self.state.capital_inr < 50 and self.state.total_value_inr > 50:
            return True, f'CAPITAL_TOO_LOW_RS{self.state.capital_inr:.0f}'
        
        # Reset daily check if new day
        if now.date() > self.day_start.date():
            self.daily_check_reset()
        
        return False, 'OK'

# ====================================================================
# MAIN AGENT — The 24/7 Loop
# ====================================================================
class MemeAgent:
    """Autonomous 24/7 meme coin trading agent with full cost accounting."""
    
    def __init__(self, initial_capital_inr=1000, scan_interval_secs=300):
        self.initial_capital = initial_capital_inr
        self.scan_interval = scan_interval_secs
        self.state = AgentState(initial_capital_inr)
        self.executor = CostAwareExecutor(self.state)
        self.exit_engine = ExitEngine(self.state, self.executor)
        self.scanner = DexScanner(self.state)
        self.filter_tool = CostAwareFilter(self.state)
        self.kill_switch = KillSwitch(self.state)
        self.cycle_count = 0
        
        # Try to restore state
        if self.state.load():
            print(f"[AGENT] State restored: Rs{self.state.total_value_inr:.2f} from "
                  f"{self.state.total_trades} trades, WR {self.state.win_rate:.0f}%")
            # Auto-reset stale kill switch if positions cleared
            if self.state.kill_switch_active and not self.state.positions:
                self.state.kill_switch_active = False
                self.state.kill_switch_reason = ''
                print(f"[AGENT] Stale kill switch auto-cleared (no positions)")
        else:
            print(f"[AGENT] Fresh start with Rs{initial_capital_inr:.0f}")
    
    def log(self, msg: str, level='INFO'):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] [{level}] {msg}", flush=True)
    
    def run_cycle(self):
        """One full scan->filter->enter->manage->exit cycle."""
        self.cycle_count += 1
        
        # 1. Kill switch check
        ks_active, ks_reason = self.kill_switch.check()
        if ks_active:
            self.state.kill_switch_active = True
            self.state.kill_switch_reason = ks_reason
            self.log(f'KILL SWITCH: {ks_reason}', 'CRITICAL')
            
            # Different kill switch types have different responses:
            # MAX_POSITIONS = block new entries only, let existing run
            # LOSS limits = emergency liquidate
            if 'MAX_POSITIONS' in ks_reason or 'CAPITAL_TOO_LOW' in ks_reason:
                self.log('Blocking new entries only — existing positions continue running')
                self.state.save()
                # Still manage exits below
            elif 'LOSS' in ks_reason:
                emergency = True
                if self.state.positions:
                    self.log('EMERGENCY LIQUIDATION of all positions')
                    for ticker in list(self.state.positions.keys()):
                        self.executor.execute_sell(ticker, self.state.positions[ticker]['current_price_usd'], 1.0, 'KILL_SWITCH')
                self.state.save()
                if not self.state.positions:
                    return True
        
        # 2. Manage existing positions (check exits)
        for ticker in list(self.state.positions.keys()):
            pos = self.state.positions[ticker]
            # In production, get real current price from API
            simulated_price_mult = 1 + np.random.normal(0, 0.05)
            current_price = pos['entry_price_usd'] * max(0.5, simulated_price_mult)
            
            actions = self.exit_engine.evaluate(
                ticker, current_price,
                volume_24h=pos.get('allocation_usd', 1000) * 100 * (0.5 + np.random.random()),
                peak_volume=pos.get('allocation_usd', 1000) * 150,
                whale_dump=np.random.random() < 0.02
            )
            for a in actions:
                if a:
                    self.log(f"EXIT {ticker}: {a['reason']} | Net gain: {a['net_gain_pct']:.1f}% | "
                            f"Fees: ${a['fees_usd']:.4f} | Proceeds: ${a['net_proceeds_usd']:.4f}")
        
        # 3. Scan for new coins
        new_coins = self.scanner.scan()
        if not new_coins:
            return True
        
        self.log(f"Scan: {len(new_coins)} new coins found")
        
        # 4. Filter and enter (skip if kill switch blocks new entries)
        if self.state.kill_switch_active and any(x in self.state.kill_switch_reason for x in ['MAX_POSITIONS', 'CAPITAL_TOO_LOW']):
            self.log(f'Kill switch active ({self.state.kill_switch_reason}) — skipping new entries')
        else:
            self._enter_new_positions(new_coins)
        
        # 5. Save state
        self.state.save()
        return True
    
    def _enter_new_positions(self, new_coins):
        """Filter and enter new positions (separated for kill-switch skip)."""
        for coin in new_coins:
            if coin['ticker'] in self.state.blacklisted_coins:
                continue
            
            screen = self.filter_tool.screen(coin)
            
            self.log(f"  {coin['name']} (${coin['ticker']}) on {coin['chain']}: "
                    f"{screen['verdict']} {screen['passed']}/{screen['total']} checks | "
                    f"Cost: {screen['cost_pct']:.1f}% round trip | BE: +{screen['breakeven_pct']:.1f}%")
            
            if screen['verdict'] in ['GREEN', 'YELLOW']:
                allocation = 0.50 if screen['verdict'] == 'GREEN' else 0.25
                
                can_enter, reason, cost_pct = self.executor.can_enter(coin, self.state.capital_inr * allocation)
                if not can_enter:
                    self.log(f"  SKIP {coin['ticker']}: {reason}")
                    continue
                
                entry_price = coin['price_usd']
                position = self.executor.execute_buy(coin, entry_price, allocation)
                
                if position:
                    breakeven_pct = cost_pct * 100
                    self.log(f"  ENTER {coin['ticker']} @ ${entry_price:.8f} | "
                            f"Alloc: Rs{position['allocation_inr']:.0f} | "
                            f"Cost: {cost_pct*100:.1f}% r/t | BE: +{breakeven_pct:.1f}%")
                    self.state.positions[coin['ticker']] = position
    def print_summary(self):
        """Print current portfolio summary."""
        print(f"\n{'='*60}")
        print(f"  MEME AGENT SUMMARY")
        print(f"{'='*60}")
        print(f"  Capital:         Rs{self.state.capital_inr:,.2f}")
        print(f"  Active Positions: {len(self.state.positions)}")
        for ticker, pos in self.state.positions.items():
            gain = (pos['current_price_usd'] / pos['entry_price_usd'] - 1) * 100
            print(f"    {ticker}: ${pos['entry_price_usd']:.8f} -> ${pos['current_price_usd']:.8f} ({gain:+.1f}%)")
        print(f"  Total Value:     Rs{self.state.total_value_inr:,.2f}")
        print(f"  Total Return:    {self.state.total_return_pct:+.2f}%")
        print(f"  Trades:          {self.state.total_trades} (WR: {self.state.win_rate:.1f}%)")
        print(f"  Fees Paid:       Rs{self.state.total_fees_paid_inr:,.2f} (${self.state.total_fees_paid_usd:.4f})")
        
        if self.state.kill_switch_active:
            print(f"  KILL SWITCH:     {self.state.kill_switch_reason}")
        
        cycles_needed = 0
        val = self.state.total_value_inr
        if val > self.initial_capital:
            cycles_needed = max(1, int(math.log(self.initial_capital * 100 / val, 2)) + 1)
            print(f"  Path to Rs{self.initial_capital*100:,}: {cycles_needed} more cycles at current performance")
        print(f"{'='*60}\n")
    
    def run(self, max_cycles=None):
        """Main 24/7 loop."""
        self.log(f"Starting 24/7 agent: Rs{self.initial_capital:,} -> target Rs{self.initial_capital*100:,}")
        self.log(f"Scan interval: {self.scan_interval}s | {self.state.initial_capital} INR initial")
        
        cooldown = 0; cycle = 0
        while True:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                break
            
            try:
                result = self.run_cycle()
                
                if result and cycle % 10 == 0:
                    self.print_summary()
                elif not result and self.state.kill_switch_active:
                    cooldown += 1
                    if cooldown >= 5:
                        self.log("5 cycles without progress — rechecking kill switch conditions")
                        self.kill_switch.check()  # Re-evaluate
                        cooldown = 0
                
                self.state.save()
                
            except KeyboardInterrupt:
                self.log("Agent stopped by user")
                self.print_summary()
                self.state.save()
                break
            except Exception as e:
                self.log(f"Error in cycle {cycle}: {e}", 'ERROR')
                import traceback; traceback.print_exc()
                self.state.save()
            
            time.sleep(self.scan_interval)

if __name__ == '__main__':
    import sys
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)  # line buffered
    
    capital = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300  # 5 min default
    
    print(f"\n{'='*60}", flush=True)
    print(f"  MEME AGENT v1.0 — 24/7 Autonomous Meme Coin Trader", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Capital: Rs{capital:,}", flush=True)
    print(f"  All costs factored: swap fees, gas, slippage, platform fees, token tax", flush=True)
    print(f"  Break-even calculated BEFORE every trade", flush=True)
    print(f"  State saved to: {AgentState.STATE_FILE}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    agent = MemeAgent(initial_capital_inr=capital, scan_interval_secs=interval)
    
    try:
        agent.run(max_cycles=5)  # 5 cycles for demo
    except KeyboardInterrupt:
        pass
    
    agent.print_summary()
    print(f"\nAgent state saved to {AgentState.STATE_FILE}", flush=True)
    print(f"Restart: python meme_agent.py {capital} {interval}", flush=True)
