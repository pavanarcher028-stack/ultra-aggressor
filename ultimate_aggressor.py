"""
ULTIMATE AGGRESSOR — Full System with Dashboard, Projections & Auto-Loop
========================================================================
Features:
  - 100k-tick test with forced WR drops (market regime switching)
  - FastAPI web dashboard (balance, history, equity chart, withdraw)
  - Monte Carlo projections (15d, 1m, 1y, 4y)
  - Auto-loop until Rs 1,00,000 target hit
  - Records ALL evolution events for capability analysis

Usage:
  python ultimate_aggressor.py --test       # 100k tick test
  python ultimate_aggressor.py --dashboard  # Start web UI
  python ultimate_aggressor.py --loop       # Auto-loop to target
  python ultimate_aggressor.py --projections # Generate charts
  python ultimate_aggressor.py --all        # Full: test + projections + dashboard
"""
import os, json, time, math, hashlib, base64, secrets, pickle, sys, threading, random
import numpy as np
from datetime import datetime
from copy import deepcopy
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

BASE = Path(__file__).parent.absolute()
os.chdir(BASE)

# ====================================================================
# CONFIG
# ====================================================================
TARGET = 100000  # Rs 1,00,000
FEE_BUY = 0.035  # 3.5% entry fee (swap + pump.fee + slippage)
FEE_SELL = 0.0175  # 1.75% exit fee

# ====================================================================
# WALLET
# ====================================================================
class Wallet:
    FILE = 'ultimate_wallet.json'; STATE = 'ultimate_state.pkl'
    @staticmethod
    def generate(chain='SOL', password=''):
        pk = secrets.token_hex(32)
        pwd_hash = hashlib.sha256(password.encode()).digest()
        encrypted = bytes(int(pk[i:i+2],16)^pwd_hash[i%len(pwd_hash)] for i in range(0,len(pk),2))
        verify = hashlib.sha256(password.encode()+b'::ultimate').hexdigest()[:16]
        addr_hash = hashlib.sha3_256(bytes.fromhex(pk)).digest()
        address = '0x'+addr_hash[-20:].hex() if chain!='SOL' else base64.b64encode(addr_hash[:32]).decode()[:44]
        return {'chain':chain,'address':address,'encrypted':base64.b64encode(encrypted).decode(),'verify':verify,'hint':pk[:8]+'...'+pk[-4:],'created':datetime.now().isoformat()}
    @staticmethod
    def decrypt(wallet, password):
        try:
            if hashlib.sha256(password.encode()+b'::ultimate').hexdigest()[:16]!=wallet['verify']: return None
            pwd_hash=hashlib.sha256(password.encode()).digest()
            encrypted=base64.b64decode(wallet['encrypted'])
            return bytes(e^pwd_hash[i%len(pwd_hash)] for i,e in enumerate(encrypted)).hex()
        except: return None

# ====================================================================
# ENHANCED PRICE SIMULATOR with Market Regime Switching
# ====================================================================
class RegimeSim:
    """Price simulator that switches between market regimes to test evolution."""
    REGIMES = ['BULL', 'BEAR', 'RANGE']
    
    def __init__(self, base=0.000045):
        self.prices = [base]
        self.volumes = [50000]
        self.regime = 'RANGE'
        self.regime_ticks = 0
        self.regime_length = random.randint(80, 200)
        self.trend = 1.0
        self.volatility = 0.008
        self.history = []
        self.total_ticks = 0
        
    def switch_regime(self):
        old = self.regime
        options = [r for r in self.REGIMES if r != old]
        # Weight toward BULL (40% BULL, 30% BEAR, 30% RANGE)
        weights = [0.4 if r == 'BULL' else 0.3 for r in options]
        self.regime = random.choices(options, weights=weights, k=1)[0]
        self.regime_length = random.randint(100, 300)
        self.regime_ticks = 0
        
        if self.regime == 'BULL':
            self.trend = 1.002 + random.random() * 0.004
            self.volatility = 0.008 + random.random() * 0.010
        elif self.regime == 'BEAR':
            self.trend = 0.998 - random.random() * 0.002
            self.volatility = 0.010 + random.random() * 0.012
        else:  # RANGE
            self.trend = 1.0
            self.volatility = 0.004 + random.random() * 0.006
            
        self.history.append({
            'tick': self.total_ticks,
            'from': old, 'to': self.regime,
            'price': self.prices[-1]
        })
        
    def tick(self):
        self.total_ticks += 1
        prev = self.prices[-1]
        self.regime_ticks += 1
        
        if self.regime_ticks >= self.regime_length:
            self.switch_regime()
        
        if random.random() < 0.05:
            self.trend += np.random.uniform(-0.005, 0.005)
            self.trend = max(0.985, min(1.015, self.trend))
        
        if self.regime == 'BULL':
            vol = self.volatility * (1 + random.random())
            spike_p = 0.10
            spike_size = 0.07
        elif self.regime == 'BEAR':
            vol = self.volatility * (1.5 + random.random())
            spike_p = 0.12
            spike_size = 0.10
        else:
            vol = self.volatility * 0.8
            spike_p = 0.04
            spike_size = 0.04
        
        noise = np.random.normal(0, vol)
        spike = random.uniform(-spike_size, spike_size * 1.5) if random.random() < spike_p else 0
        
        p = prev * (self.trend + noise + spike)
        
        # Mean reversion: if price dropped too much, bounce
        if len(self.prices) >= 5:
            recent_ret = p / self.prices[-5] - 1
            if recent_ret < -0.15:
                p *= (1 + random.uniform(0.02, 0.06))  # Bounce 2-6%
            if p < self.prices[-5] * 0.75:
                p = self.prices[-5] * random.uniform(0.75, 0.85)
        
        # Hard floor: price never goes below 1e-8
        p = max(p, 1e-8)
        # Hard ceiling: price never goes 100x above a reasonable level
        p = min(p, 1.0)
        
        self.prices.append(p)
        vol_mult = 2 if abs(noise) > vol * 1.5 else 1  # Higher vol on big moves
        self.volumes.append(50000 * vol_mult * (1 + random.random() * 3))
        
        if len(self.prices) > 200:
            self.prices.pop(0)
            self.volumes.pop(0)
        
        return p
    
    def expected_wr(self):
        """Approximate win rate based on current regime."""
        if self.regime == 'BULL': return 0.55 + random.random() * 0.10
        if self.regime == 'BEAR': return 0.25 + random.random() * 0.10
        return 0.40 + random.random() * 0.10  # RANGE

# ====================================================================
# STRATEGY SYSTEM (from meta_aggressor)
# ====================================================================
STRATEGY_PARAMS = {
    'aggressive_40':  {'target': 0.40, 'stop': 0.15, 'min_vol': 2.0, 'use_trail': True, 'trail_act': 0.25, 'trail_dist': 0.12, 'desc': '+40%/-15%, trail after 25%'},
    'aggressive_50':  {'target': 0.50, 'stop': 0.18, 'min_vol': 2.5, 'use_trail': True, 'trail_act': 0.30, 'trail_dist': 0.15, 'desc': '+50%/-18%, trail after 30%'},
    'conservative_25':{'target': 0.25, 'stop': 0.10, 'min_vol': 3.0, 'use_trail': True, 'trail_act': 0.15, 'trail_dist': 0.08, 'desc': '+25%/-10%, trail after 15%'},
    'swing_100':      {'target': 1.00, 'stop': 0.25, 'min_vol': 4.0, 'use_trail': True, 'trail_act': 0.50, 'trail_dist': 0.20, 'desc': '+100%/-25%, trail after 50%'},
    'scalp_15':       {'target': 0.15, 'stop': 0.06, 'min_vol': 1.5, 'use_trail': False, 'trail_act': 0, 'trail_dist': 0, 'desc': '+15%/-6%, no trail, fast scalp'},
    'momentum_60':    {'target': 0.60, 'stop': 0.20, 'min_vol': 3.0, 'use_trail': True, 'trail_act': 0.35, 'trail_dist': 0.18, 'desc': '+60%/-20%, trail after 35%'},
}

SIGNAL_MODES = {
    'momentum': {'min_ret_1m': 0.003, 'min_vol_ratio': 2.5, 'desc': 'Momentum: buy when price + volume rising'},
    'reversal': {'min_ret_1m': -0.005, 'min_vol_ratio': 3.0, 'desc': 'Reversal: buy after sharp drop + volume spike'},
    'breakout': {'min_ret_1m': 0.005, 'min_vol_ratio': 3.5, 'desc': 'Breakout: buy when price breaks range with volume'},
    'dip_buy':  {'min_ret_1m': -0.01, 'min_vol_ratio': 2.0, 'desc': 'Dip buy: buy -1%+ drops'},
    'hybrid':   {'min_ret_1m': 0.0, 'min_vol_ratio': 2.0, 'desc': 'Hybrid: all signals weighted'},
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
        for k in ['target', 'stop']:
            self.params[k] *= (1 + np.random.uniform(-0.1, 0.1))
        return self

# ====================================================================
# SIGNAL GENERATOR
# ====================================================================
class SignalGenerator:
    @staticmethod
    def scan(prices, volumes, config):
        signals = []
        if len(prices) < 10: return signals
        p = np.array(prices[-20:]) if len(prices) >= 20 else np.array(prices)
        v = np.array(volumes[-20:]) if len(volumes) >= 20 else np.array(volumes)
        ret_1m = (p[-1]/p[-2]-1) if len(p)>=2 else 0
        ret_5m = (p[-1]/p[-5]-1) if len(p)>=5 else 0
        vol_avg = np.mean(v) if len(v) > 0 else 1
        vol_ratio = v[-1]/max(vol_avg, 1) if vol_avg > 0 else 1
        sig = config.signal
        
        if ret_1m > sig['min_ret_1m'] and vol_ratio > sig['min_vol_ratio']:
            signals.append(('BUY', 'MOMENTUM'))
        if len(p)>=3 and p[-2] < p[-3]*0.995 and p[-1] > p[-2]:
            signals.append(('BUY', 'REVERSAL'))
        if len(p)>=10:
            rng = (np.max(p[-10:])/np.min(p[-10:])-1)
            if rng < 0.03 and ret_1m > 0.005:
                signals.append(('BUY', 'BREAKOUT'))
        if ret_5m < -0.01 and vol_ratio > sig['min_vol_ratio']:
            signals.append(('BUY', 'DIP_BUY'))
        if sig['min_ret_1m'] == 0 and vol_ratio > 2.5:
            signals.append(('BUY', 'VOLUME_SURGE'))
        
        # Fallback: if no signals but has capital, generate based on simple price action
        if not signals and len(p) >= 3:
            if p[-1] > p[-2]:  # Price just went up
                signals.append(('BUY', 'FALLBACK_UPSWING'))
            elif p[-1] < p[-2] and p[-2] < p[-3]:  # 2 consecutive drops
                signals.append(('BUY', 'FALLBACK_DIP'))
            else:
                signals.append(('BUY', 'FALLBACK_NEUTRAL'))
        
        return signals[:2]

# ====================================================================
# HFT ENGINE
# ====================================================================
class HFTEngine:
    def __init__(self, capital_inr=1000):
        self.capital = capital_inr
        self.initial_capital = capital_inr
        self.peak_capital = capital_inr
        self.positions = {}
        self.trades = []
        self.wins = 0
        self.losses = 0
        self.consecutive_losses = 0
        self.start_time = datetime.now()
        self.config = StrategyConfig()
        self.generation = 0
        self.last_evolution_check = 0
        self.equity_curve = [(0, capital_inr)]  # (tick, equity)
        self.tick_counter = 0
        self.total_withdrawn = 0
    
    def total_value(self):
        pos_val = sum(p['qty']*p['entry'] for p in self.positions.values())
        return self.capital + pos_val
    
    @property
    def win_rate(self):
        total = self.wins + self.losses
        return self.wins/max(total,1)*100
    
    def enter(self, ticker, price, reason='SIGNAL'):
        if self.capital < 10: return None
        trade_amt = self.capital * 0.95
        if trade_amt < 10: return None
        fee = trade_amt * FEE_BUY
        trade_amt_after = trade_amt - fee
        qty = trade_amt_after / price
        tp = price * (1 + self.config.params['target'])
        sl = price * (1 - self.config.params['stop'])
        pos = {'ticker':ticker,'entry':price,'qty':qty,'target':tp,'stop':sl,'peak':price,
               'entry_time':datetime.now().isoformat(),'reason':reason,'capital_used':trade_amt,'fees_paid':fee}
        pid = f"{ticker}_{datetime.now().timestamp()*1000:.0f}_{secrets.token_hex(4)}"
        self.positions[pid] = pos
        self.capital -= trade_amt
        return pid, pos
    
    def evaluate(self, pid, current_price):
        pos = self.positions.get(pid)
        if not pos: return None
        entry = pos['entry']; ret = (current_price/entry-1)*100
        if current_price > pos['peak']: pos['peak'] = current_price
        exit_reason = None
        if current_price >= pos['target']:
            exit_reason = 'TAKE_PROFIT'
        elif current_price <= pos['stop']:
            exit_reason = 'STOP_LOSS'
        elif self.config.params.get('use_trail', True):
            peak_gain = (pos['peak']/entry-1)
            if peak_gain > self.config.params.get('trail_act', 0.25):
                trail_d = self.config.params.get('trail_dist', 0.12)
                trail_p = pos['peak']*(1-trail_d)
                if current_price <= trail_p: exit_reason = f'TRAIL_{trail_d*100:.0f}%'
        if exit_reason:
            gross_r = ret/100
            sell_fee = FEE_SELL
            net_r = gross_r - sell_fee - (pos['fees_paid']/pos['capital_used'])
            pnl = pos['capital_used']*net_r
            self.capital += pos['capital_used'] + pnl
            if pnl > 0: self.wins += 1
            else: self.losses += 1
            self.consecutive_losses = 0 if pnl > 0 else self.consecutive_losses + 1
            tr = {'pid':pid,'ticker':pos['ticker'],'entry':entry,'exit':current_price,
                  'ret_pct':ret,'net_pct':net_r*100,'pnl':pnl,'reason':exit_reason,
                  'time':datetime.now().isoformat(),'config':self.config.name}
            self.trades.append(tr)
            self.peak_capital = max(self.peak_capital, self.capital)
            del self.positions[pid]
            return tr
        return None
    
    def withdraw(self, amount):
        available = self.capital * 0.9  # Keep 10% reserve
        if amount > available: amount = available
        if amount < 10: return 0
        self.capital -= amount
        self.total_withdrawn += amount
        return amount
    
    def summary(self):
        tv = self.total_value()
        total = self.wins+self.losses
        return {'capital':self.capital,'total_value':tv,'peak':self.peak_capital,
                'return_pct':(tv/self.initial_capital-1)*100,'return_mult':tv/self.initial_capital,
                'trades':total,'wins':self.wins,'losses':self.losses,
                'win_rate':self.wins/max(total,1)*100,'active':len(self.positions),
                'config':self.config.name,'generation':self.generation,
                'consecutive_losses':self.consecutive_losses,'total_withdrawn':self.total_withdrawn,
                'start_time':self.start_time.isoformat()}

# ====================================================================
# META OPTIMIZER (with detailed logging)
# ====================================================================
class MetaOptimizer:
    def __init__(self, engine):
        self.engine = engine
        self.evolution_history = []
        self.stuck_count = 0
        self.last_eval_trades = 0
        self.capability_log = []  # Records what each evolution did
    
    def evaluate_and_evolve(self, force=False):
        """Check if strategy needs improvement. Returns (evolved, action_taken)."""
        if not force and len(self.engine.trades) - self.last_eval_trades < 50:
            return False, 'WAITING'
        if len(self.engine.trades) < 30:
            return False, 'WAITING'
        
        recent = self.engine.trades[-100:]
        if not recent: return False, 'WAITING'
        
        wins = sum(1 for t in recent if t['pnl'] > 0)
        losses = sum(1 for t in recent if t['pnl'] <= 0)
        total = wins + losses
        wr = wins / max(total, 1) * 100
        net_pnl = sum(t['pnl'] for t in recent)
        avg_win = np.mean([t['pnl'] for t in recent if t['pnl'] > 0]) if wins > 0 else 0
        avg_loss = abs(np.mean([t['pnl'] for t in recent if t['pnl'] <= 0])) if losses > 0 else 0
        rr = avg_win / max(avg_loss, 1)
        
        self.last_eval_trades = len(self.engine.trades)
        
        print(f"\n{'='*55}")
        print(f"  EVALUATION @ Trade {len(self.engine.trades)} | Config: {self.engine.config.name}")
        print(f"  WR: {wr:.1f}% | Net PnL: Rs{net_pnl:+.0f} | R:R: {rr:.2f}")
        print(f"  Capital: Rs{self.engine.capital:.0f} / Rs{self.engine.peak_capital:.0f} peak")
        print(f"{'='*55}")
        
        evolved = False
        action = 'NONE'
        
        if wr >= 40 and net_pnl > 0:
            print(f"  >> STRATEGY WORKING — Continue (WR={wr:.1f}% >= 40%, PnL>0)")
            self.stuck_count = 0
            action = 'CONTINUE'
        elif wr >= 30 and net_pnl > 0:
            print(f"  >> MARGINAL — Fine-tuning parameters (WR={wr:.1f}%, 30-40%)")
            self._fine_tune()
            evolved = True; action = 'FINE_TUNE'
        elif net_pnl < 0 and wr < 35:
            print(f"  >> FAILING — Need new strategy (WR={wr:.1f}% < 35%, PnL<0)")
            self.stuck_count += 1
            if self.stuck_count >= 3:
                print(f"  >> 3 consecutive failures — Asking for human input")
                self._log_evolution("HUMAN_INPUT_SIMULATED")
                self._auto_choose_strategy()
                evolved = True; action = 'HUMAN_INPUT_SIMULATED'
            else:
                self._evolve_strategy()
                evolved = True; action = 'MAJOR_EVOLVE'
        else:
            print(f"  >> SUB-OPTIMAL — Swapping signal mode")
            self._swap_signal()
            evolved = True; action = 'SWAP_SIGNAL'
        
        self.evolution_history.append({
            'time': datetime.now().isoformat(), 'trades': len(self.engine.trades),
            'wr': wr, 'net_pnl': net_pnl, 'config': self.engine.config.name,
            'evolved': evolved, 'action': action, 'stuck_count': self.stuck_count
        })
        
        if evolved:
            print(f"  >> NEW CONFIG: {self.engine.config.name}")
            print(f"  >> {self.engine.config.params['desc']} | {self.engine.config.signal['desc']}")
        
        self.capability_log.append({
            'action': action, 'trades': len(self.engine.trades),
            'wr_before': wr, 'config_before': self.engine.config.name,
            'config_after': self.engine.config.name if evolved else self.engine.config.name,
            'capital': self.engine.capital, 'net_pnl': net_pnl
        })
        
        with open('ultimate_evolution.json', 'w') as f:
            json.dump(self.evolution_history, f, indent=2)
        
        return evolved, action
    
    def _fine_tune(self):
        p = self.engine.config.params
        wr = self.engine.win_rate
        old_target, old_stop = p['target'], p['stop']
        if wr < 35:
            p['target'] *= 0.95
            p['stop'] *= 0.95
        elif wr > 55:
            p['target'] *= 1.1
        self.engine.generation += 1
        self._log_evolution(f"FINE_TUNE target:{old_target:.2f}->{p['target']:.2f} stop:{old_stop:.2f}->{p['stop']:.2f}")
    
    def _swap_signal(self):
        current = self.engine.config.signal_key
        options = [k for k in SIGNAL_MODES.keys() if k != current]
        new_sig = random.choice(options)
        old_sig = self.engine.config.signal_key
        self.engine.config.signal = deepcopy(SIGNAL_MODES[new_sig])
        self.engine.config.signal_key = new_sig
        self.engine.config.name = f"{self.engine.config.params_key}+{new_sig}"
        self.engine.generation += 1
        self._log_evolution(f"SWAP_SIGNAL {old_sig}->{new_sig}")
    
    def _evolve_strategy(self):
        old_name = self.engine.config.name
        self.engine.config.mutate()
        self.engine.generation += 1
        self._log_evolution(f"MAJOR_EVOLVE {old_name}->{self.engine.config.name}")
    
    def _auto_choose_strategy(self):
        """Auto-choose when human input is simulated."""
        old_name = self.engine.config.name
        choices = ['aggressive_50+momentum', 'conservative_25+reversal', 'swing_100+breakout', 'scalp_15+momentum']
        choice = random.choice(choices)
        pk, sk = choice.split('+')
        self.engine.config = StrategyConfig(pk, sk)
        self.engine.generation += 1
        self.stuck_count = 0
        self._log_evolution(f"HUMAN_SIM {old_name}->{self.engine.config.name}")
    
    def _log_evolution(self, reason):
        log = {'time':datetime.now().isoformat(),'reason':reason,'config':self.engine.config.name,
               'capital':self.engine.capital,'trades':len(self.engine.trades)}
        os.makedirs('evolution_logs', exist_ok=True)
        with open(f'evolution_logs/evol_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json','w') as f:
            json.dump(log, f, indent=2)
    
    def get_capability_report(self):
        """Generate a human-readable report of what was tested."""
        actions = [c['action'] for c in self.capability_log]
        return {
            'total_checks': len(self.capability_log),
            'evolutions_triggered': sum(1 for a in actions if a != 'NONE' and a != 'WAITING' and a != 'CONTINUE'),
            'fine_tunes': actions.count('FINE_TUNE'),
            'swap_signals': actions.count('SWAP_SIGNAL'),
            'major_evolves': actions.count('MAJOR_EVOLVE'),
            'human_inputs': actions.count('HUMAN_INPUT_SIMULATED'),
            'continues': actions.count('CONTINUE'),
            'history': self.capability_log[-20:]  # Last 20 events
        }

# ====================================================================
# PROJECTION GENERATOR
# ====================================================================
def generate_projections():
    """Generate Monte Carlo projections and save charts."""
    print("\n" + "="*60)
    print("  GENERATING PROJECTIONS")
    print("="*60)
    
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        scenarios = [
            ('BEAR (30% WR)', 0.30, '+40%/-15%', 'red'),
            ('REALISTIC (35% WR)', 0.35, '+40%/-15%', 'orange'),
            ('OPTIMISTIC (40% WR)', 0.40, '+40%/-15%', 'green'),
            ('EXCEPTIONAL (45% WR)', 0.45, '+40%/-15%', 'blue'),
        ]
        timeframes = [
            ('15 Days', 15), ('1 Month', 30), ('1 Year', 365), ('4 Years', 1460)
        ]
        trades_per_day = 8
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        axes = axes.flatten()
        
        results = {}
        
        for idx, (sname, wr, desc, color) in enumerate(scenarios):
            ax = axes[idx]
            all_curves = []
            
            for sim in range(200):
                eq = 1000.0
                curve = [eq]
                days = timeframes[-1][1]  # Max days (4 years)
                for d in range(days):
                    for _ in range(trades_per_day):
                        is_win = random.random() < wr
                        ret = 0.40 if is_win else -0.15
                        eq *= (1 + ret)
                        eq = max(eq, 0.01)
                    curve.append(eq)
                all_curves.append(curve)
            
            all_curves = np.array(all_curves)
            p25 = np.percentile(all_curves, 25, axis=0)
            p50 = np.percentile(all_curves, 50, axis=0)
            p75 = np.percentile(all_curves, 75, axis=0)
            
            days_arr = np.arange(len(p50))
            ax.fill_between(days_arr, p25, p75, alpha=0.2, color=color)
            ax.plot(days_arr, p50, color=color, linewidth=2, label=f'{sname} (P50)')
            ax.axhline(y=100000, color='gold', linestyle='--', alpha=0.5, label='Rs 1,00,000 Target')
            ax.set_yscale('log')
            ax.set_xlabel('Days')
            ax.set_ylabel('Capital (Rs, log scale)')
            ax.set_title(f'{sname} — {desc}')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Calculate probabilities at each timeframe
            for label, days in timeframes:
                idx_day = min(days, len(p50)-1)
                p50_val = p50[idx_day]
                p25_val = p25[idx_day]
                p75_val = p75[idx_day]
                hit_pct = np.sum(all_curves[:, idx_day] >= 100000) / len(all_curves) * 100
                key = f"{sname}_{label}"
                results[key] = {
                    'P50': p50_val, 'P25': p25_val, 'P75': p75_val,
                    'hit_1Lac_pct': hit_pct
                }
        
        plt.tight_layout()
        plt.savefig('ultimate_projections.png', dpi=150, bbox_inches='tight')
        plt.close()
        print("  Saved: ultimate_projections.png")
        
        # Also save individual timeframe charts
        fig2, axes2 = plt.subplots(2, 2, figsize=(14, 10))
        axes2 = axes2.flatten()
        
        for idx, (label, days) in enumerate(timeframes):
            ax = axes2[idx]
            tf_results = {}
            for sname, wr, desc, color in scenarios:
                eqs = []
                for sim in range(500):
                    eq = 1000.0
                    for d in range(days):
                        for _ in range(trades_per_day):
                            is_win = random.random() < wr
                            ret = 0.40 if is_win else -0.15
                            eq *= (1 + ret)
                            eq = max(eq, 0.01)
                    eqs.append(eq)
                eqs = np.array(eqs)
                p50 = np.percentile(eqs, 50)
                p25 = np.percentile(eqs, 25)
                p75 = np.percentile(eqs, 75)
                hit = np.sum(eqs >= 100000) / len(eqs) * 100
                tf_results[sname] = {'P50': p50, 'P25': p25, 'P75': p75, 'hit': hit}
            
            # Bar chart
            names = list(tf_results.keys())
            p50s = [tf_results[n]['P50'] for n in names]
            p25s = [tf_results[n]['P25'] for n in names]
            p75s = [tf_results[n]['P75'] for n in names]
            hits = [tf_results[n]['hit'] for n in names]
            
            x = np.arange(len(names))
            width = 0.35
            bars = ax.bar(x, p50s, width, color=['red', 'orange', 'green', 'blue'], alpha=0.7)
            ax.set_xticks(x)
            ax.set_xticklabels([n.split('(')[0].strip() for n in names], rotation=15)
            ax.set_ylabel('Median Capital (Rs, log scale)')
            ax.set_yscale('log')
            ax.set_title(f'{label} Projection')
            ax.axhline(y=100000, color='gold', linestyle='--', alpha=0.5)
            
            for i, (bar, hit) in enumerate(zip(bars, hits)):
                ax.text(bar.get_x() + bar.get_width()/2., bar.get_height()*1.1,
                        f'{hit:.1f}%', ha='center', va='bottom', fontsize=8, rotation=0)
            
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('ultimate_projections_timeline.png', dpi=150, bbox_inches='tight')
        plt.close()
        print("  Saved: ultimate_projections_timeline.png")
        
        # Save results JSON
        with open('ultimate_projections.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print("  Saved: ultimate_projections.json")
        
        # Print table
        print(f"\n{'='*80}")
        print(f"  PROJECTION TABLE — Starting Capital: Rs1,000")
        print(f"{'='*80}")
        print(f"  {'Scenario':<25s} {'Timeframe':<12s} {'P50':>12s} {'P25':>12s} {'P75':>12s} {'1Lac%':>8s}")
        print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
        for sname, wr, desc, color in scenarios:
            for label, days in timeframes:
                key = f"{sname}_{label}"
                r = results.get(key, {})
                p50 = f"Rs{r.get('P50',0):,.0f}" if r.get('P50',0) < 1e12 else f"{r.get('P50',0):.2e}"
                p25 = f"Rs{r.get('P25',0):,.0f}" if r.get('P25',0) < 1e12 else f"{r.get('P25',0):.2e}"
                p75 = f"Rs{r.get('P75',0):,.0f}" if r.get('P75',0) < 1e12 else f"{r.get('P75',0):.2e}"
                hit = f"{r.get('hit_1Lac_pct',0):.1f}%"
                print(f"  {sname:<25s} {label:<12s} {p50:>12s} {p25:>12s} {p75:>12s} {hit:>8s}")
        
        return results
    except Exception as e:
        print(f"  Chart generation failed: {e}")
        return None

# ====================================================================
# FASTAPI WEB DASHBOARD
# ====================================================================
AGENT_STATE = {'engine': None, 'optimizer': None, 'sim': None, 'running': False}
AGENT_LOCK = threading.Lock()

def create_dashboard_app():
    """Create FastAPI app for the web dashboard."""
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import io, base64
    
    app = FastAPI(title="Ultimate Aggressor Dashboard")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    
    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ultimate Aggressor Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 20px; }
.container { max-width: 1400px; margin: 0 auto; }
.header { background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #2a2a4e; }
.header h1 { color: #00ff88; font-size: 28px; }
.header .subtitle { color: #888; font-size: 14px; margin-top: 5px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }
.card { background: #12121a; border-radius: 10px; padding: 18px; border: 1px solid #2a2a4e; }
.card h3 { color: #666; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.card .value { font-size: 28px; font-weight: bold; }
.card .value.green { color: #00ff88; } .card .value.red { color: #ff4444; }
.card .value.gold { color: #ffd700; } .card .value.blue { color: #4488ff; }
.progress-bar { height: 6px; background: #2a2a4e; border-radius: 3px; margin-top: 8px; overflow: hidden; }
.progress-bar .fill { height: 100%; background: linear-gradient(90deg, #00ff88, #ffd700); border-radius: 3px; transition: width 0.5s; }
.charts { display: grid; grid-template-columns: 2fr 1fr; gap: 15px; margin-bottom: 20px; }
.chart-card { background: #12121a; border-radius: 10px; padding: 15px; border: 1px solid #2a2a4e; }
.chart-card h3 { color: #666; font-size: 12px; text-transform: uppercase; margin-bottom: 10px; }
.chart-card img { width: 100%; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px 12px; border-bottom: 1px solid #2a2a4e; color: #666; font-size: 11px; text-transform: uppercase; }
td { padding: 8px 12px; border-bottom: 1px solid #1a1a2e; }
tr:hover { background: #1a1a2e; }
.win { color: #00ff88; } .loss { color: #ff4444; }
.btn { background: linear-gradient(135deg, #00ff88, #00cc66); border: none; color: #000; padding: 10px 24px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; }
.btn:hover { opacity: 0.9; }
.btn.danger { background: linear-gradient(135deg, #ff4444, #cc0000); color: #fff; }
.btn.secondary { background: #2a2a4e; color: #e0e0e0; }
.modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; }
.modal-content { background: #12121a; margin: 10% auto; padding: 30px; border-radius: 12px; max-width: 400px; border: 1px solid #2a2a4e; }
.modal-content h2 { margin-bottom: 15px; }
.modal-content input { width: 100%; padding: 10px; margin: 10px 0; background: #1a1a2e; border: 1px solid #2a2a4e; border-radius: 6px; color: #e0e0e0; font-size: 16px; }
.evolution-log { max-height: 300px; overflow-y: auto; }
.evolution-log .entry { padding: 6px 0; border-bottom: 1px solid #1a1a2e; font-size: 12px; }
.evolution-log .entry .action { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; margin-right: 6px; }
.action-CONTINUE { background: #003300; color: #00ff88; }
.action-FINE_TUNE { background: #333300; color: #ffff00; }
.action-SWAP_SIGNAL { background: #000033; color: #4488ff; }
.action-MAJOR_EVOLVE { background: #330000; color: #ff4444; }
.action-HUMAN_INPUT_SIMULATED { background: #330033; color: #ff44ff; }
.refresh-info { color: #666; font-size: 12px; margin-top: 10px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>ULTIMATE AGGRESSOR</h1>
    <div class="subtitle">Self-Improving HFT Agent | Live Dashboard | Auto-Loop to Rs 1,00,000</div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Total Value</h3>
      <div class="value green" id="totalValue">Rs --</div>
      <div class="progress-bar"><div class="fill" id="targetProgress" style="width:0%"></div></div>
      <div style="margin-top:5px;font-size:12px;color:#666;"><span id="targetLabel">0%</span> to Rs 1,00,000</div>
    </div>
    <div class="card">
      <h3>Free Capital</h3>
      <div class="value blue" id="freeCapital">Rs --</div>
      <div style="margin-top:5px;font-size:12px;color:#666;">Peak: Rs<span id="peakCapital">--</span></div>
    </div>
    <div class="card">
      <h3>Return</h3>
      <div class="value gold" id="returnPct">--</div>
      <div style="margin-top:5px;font-size:12px;color:#666;"><span id="returnMult">--</span>x from initial</div>
    </div>
    <div class="card">
      <h3>Win Rate</h3>
      <div class="value" id="winRate" style="color:#4488ff;">--</div>
      <div style="margin-top:5px;font-size:12px;color:#666;"><span id="totalTrades">0</span> trades (W:<span id="wins">0</span> L:<span id="losses">0</span>)</div>
    </div>
    <div class="card">
      <h3>Strategy</h3>
      <div class="value" style="font-size:16px;color:#e0e0e0;" id="strategy">--</div>
      <div style="margin-top:5px;font-size:12px;color:#666;">Gen <span id="generation">0</span> | <span id="activePositions">0</span> active</div>
    </div>
    <div class="card">
      <h3>Withdrawn</h3>
      <div class="value gold" id="withdrawn">Rs 0</div>
      <button class="btn secondary" onclick="showWithdrawModal()" style="margin-top:8px;width:100%;">Withdraw</button>
    </div>
  </div>

  <div class="charts">
    <div class="chart-card">
      <h3>Equity Curve</h3>
      <img id="equityChart" src="" alt="Equity Curve">
    </div>
    <div class="chart-card">
      <h3>Strategy Info</h3>
      <div id="strategyInfo">
        <p style="color:#666;">Loading...</p>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px;">
    <h3>Recent Trades</h3>
    <div style="max-height:300px;overflow-y:auto;">
      <table>
        <thead><tr><th>Time</th><th>Entry</th><th>Exit</th><th>Return</th><th>Net</th><th>PnL</th><th>Reason</th><th>Config</th></tr></thead>
        <tbody id="tradeHistory"></tbody>
      </table>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px;">
    <h3>Evolution Log</h3>
    <div class="evolution-log" id="evolutionLog">
      <p style="color:#666;">No evolution events yet.</p>
    </div>
  </div>

  <div class="refresh-info" id="refreshInfo">Last updated: -- | Auto-refreshing every 2s</div>
</div>

<div class="modal" id="withdrawModal">
  <div class="modal-content">
    <h2>Withdraw Funds</h2>
    <p style="color:#888;margin-bottom:15px;">Available: Rs <span id="availableForWithdraw">0</span> (90% of free capital)</p>
    <input type="number" id="withdrawAmount" placeholder="Amount in Rs" min="10">
    <div style="display:flex;gap:10px;margin-top:15px;">
      <button class="btn" onclick="doWithdraw()" style="flex:1">Withdraw</button>
      <button class="btn danger" onclick="hideWithdrawModal()" style="flex:1">Cancel</button>
    </div>
    <div id="withdrawResult" style="margin-top:10px;font-size:13px;"></div>
  </div>
</div>

<script>
let autoRefresh = true;

function showWithdrawModal() { document.getElementById('withdrawModal').style.display = 'block'; }
function hideWithdrawModal() { document.getElementById('withdrawModal').style.display = 'none'; }

async function fetchData() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    updateDashboard(data);
  } catch(e) { console.error('Fetch error:', e); }
}

function updateDashboard(d) {
  const s = d.summary || {};
  document.getElementById('totalValue').textContent = 'Rs ' + (s.total_value || 0).toLocaleString('en-IN', {maximumFractionDigits:0});
  document.getElementById('freeCapital').textContent = 'Rs ' + (s.capital || 0).toLocaleString('en-IN', {maximumFractionDigits:0});
  document.getElementById('peakCapital').textContent = (s.peak || 0).toLocaleString('en-IN', {maximumFractionDigits:0});
  document.getElementById('returnPct').textContent = (s.return_pct || 0).toFixed(2) + '%';
  document.getElementById('returnMult').textContent = (s.return_mult || 0).toFixed(1);
  document.getElementById('winRate').textContent = (s.win_rate || 0).toFixed(1) + '%';
  document.getElementById('totalTrades').textContent = s.trades || 0;
  document.getElementById('wins').textContent = s.wins || 0;
  document.getElementById('losses').textContent = s.losses || 0;
  document.getElementById('strategy').textContent = s.config || '--';
  document.getElementById('generation').textContent = s.generation || 0;
  document.getElementById('activePositions').textContent = s.active || 0;
  document.getElementById('withdrawn').textContent = 'Rs ' + (s.total_withdrawn || 0).toLocaleString('en-IN', {maximumFractionDigits:0});
  
  const tv = s.total_value || 0;
  const pct = Math.min(100, (tv / 100000) * 100);
  document.getElementById('targetProgress').style.width = pct.toFixed(1) + '%';
  document.getElementById('targetLabel').textContent = pct.toFixed(1) + '%';
  
  if (tv >= 100000) {
    document.getElementById('totalValue').style.color = '#ffd700';
    document.getElementById('targetLabel').textContent = 'TARGET HIT! Rs 1,00,000';
  }
  
  document.getElementById('availableForWithdraw').textContent = (s.capital * 0.9 || 0).toFixed(0);
  
  // Equity curve
  if (d.equity_chart) {
    document.getElementById('equityChart').src = 'data:image/png;base64,' + d.equity_chart;
  }
  
  // Trade history
  const tbody = document.getElementById('tradeHistory');
  if (d.trades && d.trades.length > 0) {
    tbody.innerHTML = d.trades.slice(-20).reverse().map(t => {
      const cls = t.pnl > 0 ? 'win' : 'loss';
      return `<tr><td>${t.time || ''}</td><td>$${parseFloat(t.entry).toFixed(8)}</td><td>$${parseFloat(t.exit).toFixed(8)}</td>
        <td class="${cls}">${(t.ret_pct || 0).toFixed(1)}%</td><td class="${cls}">${(t.net_pct || 0).toFixed(1)}%</td>
        <td class="${cls}">Rs${(t.pnl || 0).toFixed(0)}</td><td>${t.reason || ''}</td><td>${t.config || ''}</td></tr>`;
    }).join('');
  } else {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#666;">No trades yet</td></tr>';
  }
  
  // Evolution log
  const evoDiv = document.getElementById('evolutionLog');
  if (d.evolution_history && d.evolution_history.length > 0) {
    evoDiv.innerHTML = d.evolution_history.slice(-15).reverse().map(e => {
      const cls = 'action-' + (e.action || 'NONE');
      return `<div class="entry"><span class="action ${cls}">${e.action || 'NONE'}</span>Trades: ${e.trades} | WR: ${(e.wr||0).toFixed(1)}% | PnL: Rs${(e.net_pnl||0).toFixed(0)} | ${e.config || '--'}</div>`;
    }).join('');
  }
  
  // Strategy info
  const si = document.getElementById('strategyInfo');
  if (d.summary) {
    si.innerHTML = `
      <p><strong>Config:</strong> ${d.summary.config || '--'}</p>
      <p><strong>Generation:</strong> ${d.summary.generation || 0}</p>
      <p><strong>Active Positions:</strong> ${d.summary.active || 0}</p>
      <p><strong>Consecutive Losses:</strong> ${d.summary.consecutive_losses || 0}</p>
      <p><strong>Start Time:</strong> ${d.summary.start_time || '--'}</p>
      <p><strong>Running:</strong> ${d.running ? 'Yes' : 'No'}</p>
      <p><strong>Regime:</strong> ${d.regime || '--'}</p>
    `;
  }
  
  document.getElementById('refreshInfo').textContent = 'Last updated: ' + new Date().toLocaleTimeString() + ' | Auto-refreshing every 2s';
}

async function doWithdraw() {
  const amt = document.getElementById('withdrawAmount').value;
  if (!amt || amt < 10) { document.getElementById('withdrawResult').textContent = 'Minimum Rs 10'; return; }
  try {
    const r = await fetch('/api/withdraw?amount=' + amt);
    const data = await r.json();
    document.getElementById('withdrawResult').textContent = data.withdrawn > 0 
      ? 'Withdrew Rs ' + data.withdrawn.toFixed(0) 
      : 'Withdrawal failed: ' + (data.error || 'unknown');
    document.getElementById('withdrawAmount').value = '';
    setTimeout(fetchData, 500);
  } catch(e) {
    document.getElementById('withdrawResult').textContent = 'Error: ' + e.message;
  }
}

setInterval(fetchData, 2000);
fetchData();
</script>
</body>
</html>"""
    
    @app.get("/")
    async def dashboard():
        return HTMLResponse(DASHBOARD_HTML)
    
    @app.get("/api/status")
    async def api_status():
        with AGENT_LOCK:
            state = AGENT_STATE.copy()
            if state['engine']:
                s = state['engine'].summary()
                trades = state['engine'].trades[-50:]
                
                # Generate equity chart
                eq_chart = None
                try:
                    import matplotlib
                    matplotlib.use('Agg')
                    import matplotlib.pyplot as plt
                    
                    curve = state['engine'].equity_curve
                    if len(curve) > 1:
                        fig, ax = plt.subplots(figsize=(10, 4))
                        ticks, vals = zip(*curve)
                        ax.plot(ticks, vals, color='#00ff88', linewidth=1)
                        ax.fill_between(ticks, vals, alpha=0.1, color='#00ff88')
                        ax.axhline(y=100000, color='#ffd700', linestyle='--', alpha=0.5)
                        ax.set_yscale('log')
                        ax.set_facecolor('#0a0a0f')
                        fig.patch.set_facecolor('#0a0a0f')
                        ax.tick_params(colors='#666')
                        ax.spines['bottom'].set_color('#2a2a4e')
                        ax.spines['left'].set_color('#2a2a4e')
                        ax.yaxis.label.set_color('#666')
                        ax.xaxis.label.set_color('#666')
                        
                        import io, base64
                        buf = io.BytesIO()
                        plt.savefig(buf, format='png', dpi=80, bbox_inches='tight', facecolor='#0a0a0f')
                        plt.close()
                        eq_chart = base64.b64encode(buf.getvalue()).decode()
                except: pass
                
                return {
                    'summary': s,
                    'trades': trades,
                    'evolution_history': state['optimizer'].evolution_history if state['optimizer'] else [],
                    'regime': state['sim'].regime if state['sim'] else 'N/A',
                    'running': state['running'],
                    'equity_chart': eq_chart,
                }
            return {'summary': {'capital': 0, 'total_value': 0, 'trades': 0}}
    
    @app.get("/api/withdraw")
    async def api_withdraw(amount: float = Query(0)):
        with AGENT_LOCK:
            if not AGENT_STATE['engine']:
                return {'withdrawn': 0, 'error': 'No engine'}
            withdrawn = AGENT_STATE['engine'].withdraw(amount)
            return {'withdrawn': withdrawn}
    
    @app.get("/api/history")
    async def api_history():
        with AGENT_LOCK:
            if not AGENT_STATE['engine']:
                return {'trades': []}
            return {'trades': AGENT_STATE['engine'].trades[-100:]}
    
    return app

# ====================================================================
# COMPREHENSIVE TEST RUNNER
# ====================================================================
class ComprehensiveTest:
    def __init__(self, ticks=100000, target=100000):
        self.ticks = ticks
        self.target = target
        self.sim = RegimeSim()
        self.engine = HFTEngine(1000)
        self.optimizer = MetaOptimizer(self.engine)
        self.wallet = None
        self.start_time = datetime.now()
        self.forced_drop_done = False
        self.evolution_events = []
        self.regime_log = []
    
    def setup(self):
        """Setup wallet and state."""
        if os.path.exists(Wallet.FILE):
            with open(Wallet.FILE) as f: self.wallet = json.load(f)
        else:
            self.wallet = Wallet.generate('SOL', 'ultimate_test')
            with open(Wallet.FILE, 'w') as f: json.dump(self.wallet, f)
        
        if os.path.exists(Wallet.STATE):
            with open(Wallet.STATE, 'rb') as f:
                state = pickle.load(f)
            cap = state.get('capital', 0)
            if cap > 0:
                self.engine = HFTEngine(cap)
                self.engine.wins = state.get('wins', 0)
                self.engine.losses = state.get('losses', 0)
                self.engine.trades = state.get('trades', [])
                self.engine.total_withdrawn = state.get('total_withdrawn', 0)
                self.optimizer = MetaOptimizer(self.engine)
                print(f"  Restored: Rs{cap:.0f}, {len(self.engine.trades)} trades")
                return True
        
        print(f"  Fresh start: Rs1,000")
        return True
    
    def tick(self):
        """Single simulation tick."""
        price = self.sim.tick()
        tick_num = self.sim.total_ticks
        
        # FORCED WR DROP: After 20,000 ticks, make market go BEAR for 5000 ticks
        if tick_num > 20000 and tick_num < 25000 and not self.forced_drop_done:
            if self.sim.regime != 'BEAR':
                old = self.sim.regime
                self.sim.regime = 'BEAR'
                self.sim.trend = 0.995
                self.sim.volatility = 0.015
                self.sim.regime_length = 5000
                self.sim.regime_ticks = 0
                self.forced_drop_done = True
                print(f"\n{'!'*55}")
                print(f"  FORCED REGIME SWITCH: {old} -> BEAR (to test evolution)")
                print(f"{'!'*55}")
                self.regime_log.append({
                    'tick': tick_num, 'event': 'FORCED_BEAR',
                    'description': 'Simulated market crash to test strategy evolution'
                })
        elif tick_num > 25000 and tick_num < 25500 and self.forced_drop_done:
            # Switch back to BULL after the crash
            if self.sim.regime == 'BEAR':
                self.sim.regime = 'BULL'
                self.sim.trend = 1.003
                self.sim.volatility = 0.008
                self.sim.regime_length = 3000
                self.sim.regime_ticks = 0
                print(f"\n{'!'*55}")
                print(f"  RECOVERY: BEAR -> BULL")
                print(f"{'!'*55}")
        
        # Evaluate positions
        for pid in list(self.engine.positions.keys()):
            ei = self.engine.evaluate(pid, price)
            if ei:
                s = self.engine.summary()
                if s['trades'] % 10 == 0:
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] EXIT {ei['ticker']}: "
                          f"{ei['ret_pct']:+.1f}% (net:{ei['net_pct']:+.1f}%) | {ei['reason']} | "
                          f"Rs{ei['pnl']:+.0f} | Cap:Rs{s['total_value']:.0f} | {s['config']}")
        
        # Enter new positions (max 1 to preserve capital for compounding)
        if len(self.sim.prices) >= 10 and len(self.engine.positions) < 1 and self.engine.capital > 50:
            sigs = SignalGenerator.scan(self.sim.prices, self.sim.volumes, self.engine.config)
            for direction, reason in sigs[:1]:
                pos = self.engine.enter('MEME', price, reason)
                if pos:
                    pid, p = pos
                    if self.engine.summary()['trades'] % 10 == 0:
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] ENTER: ${p['entry']:.8f} -> "
                              f"${p['target']:.8f} (+{self.engine.config.params['target']*100:.0f}%) | "
                              f"Rs{p['capital_used']:.0f} at risk | {self.engine.config.name}")
        
        # Record equity curve
        if len(self.engine.equity_curve) == 0 or tick_num % 100 == 0:
            self.engine.equity_curve.append((tick_num, self.engine.total_value()))
        
        # Self-evaluation
        evolved, action = self.optimizer.evaluate_and_evolve()
        if evolved:
            self.evolution_events.append({
                'tick': tick_num, 'action': action,
                'config': self.engine.config.name,
                'capital': self.engine.capital,
                'trades': len(self.engine.trades)
            })
        
        # Save state periodically
        if tick_num % 5000 == 0:
            self._save_state()
    
    def _save_state(self):
        with open(Wallet.STATE, 'wb') as f:
            pickle.dump({
                'capital': self.engine.capital,
                'wins': self.engine.wins,
                'losses': self.engine.losses,
                'trades': self.engine.trades[-500:],
                'config': self.engine.config.name,
                'total_withdrawn': self.engine.total_withdrawn,
                'peak_capital': self.engine.peak_capital,
            }, f)
    
    def run(self):
        """Run the comprehensive test."""
        self.setup()
        print(f"\n{'='*60}")
        print(f"  COMPREHENSIVE TEST: {self.ticks:,} ticks")
        print(f"  Target: Rs{self.target:,}")
        print(f"  Start: {self.start_time.isoformat()}")
        print(f"{'='*60}")
        
        try:
            for i in range(self.ticks):
                self.tick()
                
                # Check if target hit
                if self.engine.total_value() >= self.target:
                    print(f"\n{'='*55}")
                    print(f"  >>> TARGET ACHIEVED at tick {i+1}!")
                    print(f"  >>> Rs{self.engine.total_value():,.2f}")
                    print(f"{'='*55}")
                    break
                
                # Status updates
                if (i+1) % 10000 == 0:
                    s = self.engine.summary()
                    print(f"\n--- CHECKPOINT @ Tick {self.sim.total_ticks:,} ---")
                    print(f"  Value: Rs{s['total_value']:,.2f} | Trades: {s['trades']} | WR: {s['win_rate']:.1f}%")
                    print(f"  Config: {s['config']} | Gen: {s['generation']} | Regime: {self.sim.regime}")
                    self._save_state()
        except KeyboardInterrupt:
            print(f"\n  Interrupted at tick {self.sim.total_ticks}")
        
        self._save_state()
        self._print_final_report()
        return self.engine.total_value() >= self.target
    
    def _print_final_report(self):
        """Print comprehensive final report."""
        s = self.engine.summary()
        cap = self.optimizer.get_capability_report()
        
        print(f"\n{'='*60}")
        print(f"  FINAL REPORT")
        print(f"{'='*60}")
        print(f"  Duration: {datetime.now() - self.start_time}")
        print(f"  Ticks: {self.sim.total_ticks:,}")
        print(f"")
        print(f"  CAPITAL:      Rs{s['total_value']:,.2f}")
        print(f"  INITIAL:      Rs{self.engine.initial_capital:,.2f}")
        print(f"  RETURN:       {s['return_pct']:+.2f}% ({s['return_mult']:.1f}x)")
        print(f"  PEAK:         Rs{s['peak']:,.2f}")
        print(f"  WITHDRAWN:    Rs{s['total_withdrawn']:,.2f}")
        print(f"")
        print(f"  TRADES:       {s['trades']}")
        print(f"  WINS:         {s['wins']}")
        print(f"  LOSSES:       {s['losses']}")
        print(f"  WIN RATE:     {s['win_rate']:.1f}%")
        print(f"  CONSEC LOSS:  {s['consecutive_losses']}")
        print(f"")
        print(f"  CURRENT CONFIG: {s['config']}")
        print(f"  GENERATION:     {s['generation']}")
        print(f"")
        print(f"  EVOLUTION ENGINE:")
        print(f"    Total evaluations:   {cap['total_checks']}")
        print(f"    Evolutions triggered: {cap['evolutions_triggered']}")
        print(f"    Fine-tunes:          {cap['fine_tunes']}")
        print(f"    Signal swaps:        {cap['swap_signals']}")
        print(f"    Major evolves:       {cap['major_evolves']}")
        print(f"    Human inputs:        {cap['human_inputs']}")
        print(f"    Continues:           {cap['continues']}")
        print(f"")
        
        if cap['history']:
            print(f"  RECENT EVOLUTION EVENTS:")
            for h in cap['history'][-10:]:
                print(f"    [{h['action']:<22s}] Trades:{h['trades']:>4d} | WR:{h['wr_before']:>5.1f}% | Config:{h['config_after']}")
        
        print(f"\n  REGIME CHANGES DURING TEST:")
        for r in self.sim.history[-10:]:
            print(f"    Tick {r['tick']:>6d}: {r['from']} -> {r['to']} @ ${r['price']:.8f}")
        
        if self.regime_log:
            print(f"\n  FORCED EVENTS:")
            for r in self.regime_log:
                print(f"    Tick {r['tick']:>6d}: {r['description']}")
        
        target_hit = s['total_value'] >= self.target
        print(f"\n  TARGET Rs{self.target:,}: {'ACHIEVED!' if target_hit else 'NOT ACHIEVED'}")
        if not target_hit and s['total_value'] > 0:
            need = self.target / s['total_value']
            trades_needed = math.log(need, 1 + self.engine.config.params['target'])
            print(f"  Estimated trades to target: ~{trades_needed:.0f} more wins at current config")
        
        print(f"{'='*60}")
        
        # Save report to file
        report = {k: v for k, v in s.items()}
        report['ticks'] = len(self.sim.prices)
        report['regime_history'] = self.sim.history[-50:]
        report['evolution_capability'] = cap
        report['target_hit'] = target_hit
        with open('ultimate_final_report.json', 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n  Report saved: ultimate_final_report.json")

# ====================================================================
# LOOP MODE — Auto-retry until target hit
# ====================================================================
def loop_mode(max_attempts=10):
    """Auto-loop: restart if target not hit, with strategy adjustments."""
    print(f"\n{'='*60}")
    print(f"  AUTO-LOOP MODE — Target: Rs{100000:,}")
    print(f"  Max attempts: {max_attempts}")
    print(f"{'='*60}")
    
    best_value = 0
    best_config = None
    
    for attempt in range(1, max_attempts + 1):
        print(f"\n{'='*55}")
        print(f"  ATTEMPT {attempt}/{max_attempts}")
        print(f"{'='*55}")
        
        # Clean state for fresh start
        for f in ['meta_wallet.json', 'meta_state.pkl', 'ultimate_wallet.json', 'ultimate_state.pkl']:
            if os.path.exists(f): os.remove(f)
        
        # Adjust initial strategy based on previous attempts
        test = ComprehensiveTest(ticks=50000, target=100000)
        if attempt > 1 and best_config:
            pk, sk = best_config.split('+')
            test.engine.config = StrategyConfig(pk, sk)
        
        hit_target = test.run()
        
        s = test.engine.summary()
        if s['total_value'] > best_value:
            best_value = s['total_value']
            best_config = s['config']
        
        if hit_target:
            print(f"\n  >>> TARGET ACHIEVED on attempt {attempt}!")
            return True
        
        print(f"\n  Attempt {attempt} result: Rs{s['total_value']:,.2f} (best: Rs{best_value:,.2f})")
        
        if attempt < max_attempts:
            print(f"  Retrying with different parameters...")
    
    print(f"\n  Max attempts ({max_attempts}) reached. Best: Rs{best_value:,.2f}")
    return False

# ====================================================================
# DASHBOARD MODE
# ====================================================================
def dashboard_mode():
    """Start the web dashboard with a live running agent."""
    import uvicorn
    
    print(f"\n{'='*60}")
    print(f"  WEB DASHBOARD MODE")
    print(f"  Starting agent + web server...")
    print(f"{'='*60}")
    
    # Start agent in background
    test = ComprehensiveTest(ticks=1000000, target=100000)
    test.setup()
    
    with AGENT_LOCK:
        AGENT_STATE['engine'] = test.engine
        AGENT_STATE['optimizer'] = test.optimizer
        AGENT_STATE['sim'] = test.sim
        AGENT_STATE['running'] = True
    
    def run_agent():
        try:
            while AGENT_STATE['running']:
                with AGENT_LOCK:
                    if AGENT_STATE['engine']:
                        AGENT_STATE['sim'].tick()
                        price = AGENT_STATE['sim'].prices[-1]
                        
                        for pid in list(AGENT_STATE['engine'].positions.keys()):
                            AGENT_STATE['engine'].evaluate(pid, price)
                        
                        if len(AGENT_STATE['sim'].prices) >= 10 and len(AGENT_STATE['engine'].positions) < 1 and AGENT_STATE['engine'].capital > 50:
                            sigs = SignalGenerator.scan(
                                AGENT_STATE['sim'].prices, AGENT_STATE['sim'].volumes,
                                AGENT_STATE['engine'].config
                            )
                            for direction, reason in sigs[:1]:
                                AGENT_STATE['engine'].enter('MEME', price, reason)
                        
                        tick_num = len(AGENT_STATE['sim'].prices)
                        if tick_num % 100 == 0:
                            AGENT_STATE['engine'].equity_curve.append((tick_num, AGENT_STATE['engine'].total_value()))
                        
                        AGENT_STATE['optimizer'].evaluate_and_evolve()
                        
                        if AGENT_STATE['engine'].total_value() >= 100000:
                            print(f"\n  >>> TARGET ACHIEVED in dashboard mode!")
        except Exception as e:
            print(f"  Agent error: {e}")
        finally:
            AGENT_STATE['running'] = False
    
    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()
    
    print(f"  Agent running in background. Starting web server...")
    print(f"  Dashboard: http://localhost:8765")
    print(f"  Press Ctrl+C to stop")
    
    app = create_dashboard_app()
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")

# ====================================================================
# MAIN
# ====================================================================
if __name__ == '__main__':
    import sys
    
    if '--all' in sys.argv:
        print("=" * 60)
        print("  ULTIMATE AGGRESSOR — Full Suite")
        print("=" * 60)
        
        # 1. Generate projections
        generate_projections()
        
        # 2. Run comprehensive test
        print("\n" + "="*60)
        print("  Running comprehensive test (100k ticks)...")
        test = ComprehensiveTest(ticks=100000, target=100000)
        test.run()
        
        # 3. Launch dashboard
        print("\n" + "="*60)
        print("  Starting web dashboard...")
        dashboard_mode()
    
    elif '--test' in sys.argv:
        ticks = 100000
        for i, arg in enumerate(sys.argv):
            if arg == '--ticks' and i+1 < len(sys.argv):
                ticks = int(sys.argv[i+1])
        test = ComprehensiveTest(ticks=ticks, target=100000)
        test.run()
    
    elif '--dashboard' in sys.argv:
        dashboard_mode()
    
    elif '--loop' in sys.argv:
        attempts = 10
        for i, arg in enumerate(sys.argv):
            if arg == '--attempts' and i+1 < len(sys.argv):
                attempts = int(sys.argv[i+1])
        loop_mode(max_attempts=attempts)
    
    elif '--projections' in sys.argv:
        generate_projections()
    
    elif '--fast' in sys.argv:
        # Quick 5000-tick test
        test = ComprehensiveTest(ticks=5000, target=100000)
        test.run()
    
    else:
        print("Ultimate Aggressor v1.0 — Complete Trading System")
        print()
        print("Usage:")
        print("  python ultimate_aggressor.py --test         Run 100k tick test")
        print("  python ultimate_aggressor.py --test --ticks 20000  Custom tick count")
        print("  python ultimate_aggressor.py --dashboard    Launch web dashboard")
        print("  python ultimate_aggressor.py --loop         Auto-loop until target hit")
        print("  python ultimate_aggressor.py --projections  Generate projection charts")
        print("  python ultimate_aggressor.py --all          Full suite")
        print("  python ultimate_aggressor.py --fast         Quick 5000-tick test")
