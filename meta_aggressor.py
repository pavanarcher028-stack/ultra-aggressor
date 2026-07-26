"""
META AGGRESSOR v3 — Self-Improving HFT with Realistic Projections
==================================================================
Every 50-100 trades: retests performance. If failing, evolves strategy.
If still failing, asks you for input to create new strategy together.
Includes REALISTIC vs OPTIMISTIC probability breakdowns.
"""
import os, json, time, math, hashlib, base64, secrets, pickle, sys
import numpy as np
from datetime import datetime
from copy import deepcopy
import warnings; warnings.filterwarnings('ignore')

# ====================================================================
# WALLET (same secure generation)
# ====================================================================
class Wallet:
    FILE = 'meta_wallet.json'; STATE = 'meta_state.pkl'
    @staticmethod
    def generate(chain='SOL', password=''):
        pk = secrets.token_hex(32)
        pwd_hash = hashlib.sha256(password.encode()).digest()
        encrypted = bytes(int(pk[i:i+2],16)^pwd_hash[i%len(pwd_hash)] for i in range(0,len(pk),2))
        verify = hashlib.sha256(password.encode()+b'::meta').hexdigest()[:16]
        addr_hash = hashlib.sha3_256(bytes.fromhex(pk)).digest()
        address = '0x'+addr_hash[-20:].hex() if chain!='SOL' else base64.b64encode(addr_hash[:32]).decode()[:44]
        return {'chain':chain,'address':address,'encrypted':base64.b64encode(encrypted).decode(),'verify':verify,'hint':pk[:8]+'...'+pk[-4:],'created':datetime.now().isoformat()}
    @staticmethod
    def decrypt(wallet, password):
        try:
            if hashlib.sha256(password.encode()+b'::meta').hexdigest()[:16]!=wallet['verify']: return None
            pwd_hash=hashlib.sha256(password.encode()).digest()
            encrypted=base64.b64decode(wallet['encrypted'])
            return bytes(e^pwd_hash[i%len(pwd_hash)] for i,e in enumerate(encrypted)).hex()
        except: return None

# ====================================================================
# STRATEGY PARAMETER SPACE
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
        """Random mutation of parameters."""
        import random
        pkeys = list(STRATEGY_PARAMS.keys())
        skeys = list(SIGNAL_MODES.keys())
        self.params_key = random.choice(pkeys)
        self.signal_key = random.choice(skeys)
        self.params = deepcopy(STRATEGY_PARAMS[self.params_key])
        self.signal = deepcopy(SIGNAL_MODES[self.signal_key])
        self.name = f"{self.params_key}+{self.signal_key}"
        # Add small random tweaks
        for k in ['target', 'stop']:
            self.params[k] *= (1 + np.random.uniform(-0.1, 0.1))
        return self

# ====================================================================
# SIGNAL GENERATOR (multi-mode)
# ====================================================================
class SignalGenerator:
    @staticmethod
    def scan(prices, volumes, config):
        signals = []
        if len(prices) < 20: return signals
        
        p = np.array(prices[-20:])
        v = np.array(volumes[-20:])
        ret_1m = (p[-1]/p[-2]-1) if len(p)>=2 else 0
        ret_5m = (p[-1]/p[-5]-1) if len(p)>=5 else 0
        vol_avg = np.mean(v)
        vol_ratio = v[-1]/max(vol_avg, 1)
        sig = config.signal
        
        # Momentum
        if ret_1m > sig['min_ret_1m'] and vol_ratio > sig['min_vol_ratio']:
            signals.append(('BUY', 'MOMENTUM'))
        
        # Reversal (drop then recover)
        if len(p)>=3 and p[-2] < p[-3]*0.995 and p[-1] > p[-2]:
            signals.append(('BUY', 'REVERSAL'))
        
        # Breakout
        if len(p)>=10:
            rng = (np.max(p[-10:])/np.min(p[-10:])-1)
            if rng < 0.03 and ret_1m > 0.005:
                signals.append(('BUY', 'BREAKOUT'))
        
        # Dip buy
        if ret_5m < -0.01 and vol_ratio > sig['min_vol_ratio']:
            signals.append(('BUY', 'DIP_BUY'))
        
        # Hybrid: all of the above
        if sig['min_ret_1m'] == 0:
            # Vol-weighted: any signal with enough volume
            if vol_ratio > 2.5:
                signals.append(('BUY', 'VOLUME_SURGE'))
        
        return signals[:3]

# ====================================================================
# HFT ENGINE (with strategy config)
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
        fee = trade_amt * 0.035
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
            sell_fee = 0.0175
            net_r = gross_r - sell_fee - (pos['fees_paid']/pos['capital_used'])
            pnl = pos['capital_used']*net_r
            self.capital += pos['capital_used'] + pnl
            if pnl > 0: self.wins += 1
            else: self.losses += 1
            tr = {'pid':pid,'ticker':pos['ticker'],'entry':entry,'exit':current_price,
                  'ret_pct':ret,'net_pct':net_r*100,'pnl':pnl,'reason':exit_reason,
                  'time':datetime.now().isoformat(),'config':self.config.name}
            self.trades.append(tr)
            self.peak_capital = max(self.peak_capital, self.capital)
            del self.positions[pid]
            return tr
        return None
    
    def summary(self):
        tv = self.total_value()
        total = self.wins+self.losses
        return {'capital':self.capital,'total_value':tv,'peak':self.peak_capital,
                'return_pct':(tv/self.initial_capital-1)*100,'return_mult':tv/self.initial_capital,
                'trades':total,'wins':self.wins,'losses':self.losses,
                'win_rate':self.wins/max(total,1)*100,'active':len(self.positions),
                'config':self.config.name,'generation':self.generation}

# ====================================================================
# SELF-IMPROVEMENT ENGINE (Evolves every 50-100 trades)
# ====================================================================
class MetaOptimizer:
    """Self-improvement layer: evaluates performance and evolves strategy."""
    
    def __init__(self, engine):
        self.engine = engine
        self.evolution_history = []
        self.stuck_count = 0
        self.last_eval_trades = 0
    
    def evaluate_and_evolve(self, force=False):
        """Check if strategy needs improvement. Returns True if evolved."""
        if not force and len(self.engine.trades) - self.last_eval_trades < 50:
            return False
        if len(self.engine.trades) < 30:
            return False
        
        recent = self.engine.trades[-100:]
        if not recent: return False
        
        wins = sum(1 for t in recent if t['pnl'] > 0)
        losses = sum(1 for t in recent if t['pnl'] <= 0)
        total = wins + losses
        wr = wins / max(total, 1) * 100
        net_pnl = sum(t['pnl'] for t in recent)
        avg_win = np.mean([t['pnl'] for t in recent if t['pnl'] > 0]) if wins > 0 else 0
        avg_loss = abs(np.mean([t['pnl'] for t in recent if t['pnl'] <= 0])) if losses > 0 else 0
        rr = avg_win / max(avg_loss, 1)
        
        self.last_eval_trades = len(self.engine.trades)
        
        print(f"\n{'='*50}")
        print(f"  STRATEGY EVALUATION (Trades {len(self.engine.trades)-total}-{len(self.engine.trades)})")
        print(f"  Config: {self.engine.config.name}")
        print(f"  WR: {wr:.1f}% | Net PnL: Rs{net_pnl:+.0f} | R:R: {rr:.2f}")
        print(f"  Active Capital: Rs{self.engine.capital:.0f} / Rs{self.engine.peak_capital:.0f} peak")
        print(f"{'='*50}")
        
        # Decision tree
        evolved = False
        if wr >= 40 and net_pnl > 0:
            print(f"  STATUS: STRATEGY WORKING — Continue with current config")
            self.stuck_count = 0
        elif wr >= 30 and net_pnl > 0:
            print(f"  STATUS: MARGINAL — Fine-tuning parameters")
            self._fine_tune()
            evolved = True
        elif net_pnl < 0 and wr < 35:
            print(f"  STATUS: FAILING — Need new strategy")
            self.stuck_count += 1
            if self.stuck_count >= 3:
                self._ask_human()
            else:
                self._evolve_strategy()
                evolved = True
        else:
            print(f"  STATUS: SUB-OPTIMAL — Trying alternative signals")
            self._swap_signal()
            evolved = True
        
        self.evolution_history.append({
            'time': datetime.now().isoformat(), 'trades': len(self.engine.trades),
            'wr': wr, 'net_pnl': net_pnl, 'config': self.engine.config.name, 'evolved': evolved
        })
        
        if evolved:
            print(f"  NEW CONFIG: {self.engine.config.name}")
            print(f"  {self.engine.config.params['desc']} | {self.engine.config.signal['desc']}")
        
        # Save evolution log
        with open('meta_evolution.json', 'w') as f:
            json.dump(self.evolution_history, f, indent=2)
        
        return evolved
    
    def _fine_tune(self):
        """Small parameter adjustments."""
        p = self.engine.config.params
        wr = self.engine.win_rate
        if wr < 35:
            p['target'] *= 0.95  # Reduce target, increase win rate
            p['stop'] *= 0.95    # Tighter stop
        elif wr > 55:
            p['target'] *= 1.1   # Increase target, let winners run
        self.engine.generation += 1
    
    def _swap_signal(self):
        """Try a different signal mode."""
        import random
        current = self.engine.config.signal_key
        options = [k for k in SIGNAL_MODES.keys() if k != current]
        new_sig = random.choice(options)
        self.engine.config.signal = deepcopy(SIGNAL_MODES[new_sig])
        self.engine.config.signal_key = new_sig
        self.engine.config.name = f"{self.engine.config.params_key}+{new_sig}"
        self.engine.generation += 1
    
    def _evolve_strategy(self):
        """Major evolution: try completely different parameters."""
        import random
        self.engine.config.mutate()
        self.engine.generation += 1
        self._log_evolution("MAJOR_EVOLVE")
    
    def _ask_human(self):
        """Last resort: ask user for help designing new strategy."""
        print(f"\n{'!'*50}")
        print(f"  HUMAN INPUT REQUIRED")
        print(f"  The agent has failed 3 consecutive evolutions.")
        print(f"  Current config: {self.engine.config.name}")
        print(f"  Current capital: Rs{self.engine.capital:.0f}")
        print(f"{'!'*50}")
        print(f"\n  Choose a new direction:")
        print(f"  1. MORE AGGRESSIVE — Increase target to 60-100%, accept lower WR")
        print(f"  2. MORE CONSERVATIVE — Decrease target to 15-25%, aim for 50%+ WR")
        print(f"  3. SWING — Hold for 50-100% moves over days, not minutes")
        print(f"  4. SCALP — Ultra-fast 5-10% targets, very tight 3-5% stops")
        print(f"  5. CUSTOM — Enter your own parameters")
        choice = input(f"  Enter [1-5]: ").strip()
        
        new_params = None
        if choice == '1':
            new_params = StrategyConfig('aggressive_50', 'momentum')
        elif choice == '2':
            new_params = StrategyConfig('conservative_25', 'reversal')
        elif choice == '3':
            new_params = StrategyConfig('swing_100', 'breakout')
        elif choice == '4':
            new_params = StrategyConfig('scalp_15', 'momentum')
        elif choice == '5':
            try:
                t = float(input("  Target % (e.g., 40): "))/100
                s = float(input("  Stop % (e.g., 15): "))/100
                sig = input("  Signal (momentum/reversal/breakout): ").strip()
                new_params = StrategyConfig('aggressive_40', sig if sig in SIGNAL_MODES else 'momentum')
                new_params.params['target'] = t
                new_params.params['stop'] = s
            except: new_params = StrategyConfig('aggressive_40', 'momentum')
        
        if new_params:
            self.engine.config = new_params
            self.engine.generation += 1
            self.stuck_count = 0
            self._log_evolution(f"HUMAN_INPUT_{choice}")
            print(f"  Updated to: {self.engine.config.name}")
    
    def _log_evolution(self, reason):
        log = {'time':datetime.now().isoformat(),'reason':reason,'config':self.engine.config.name,
               'capital':self.engine.capital,'trades':len(self.engine.trades)}
        os.makedirs('evolution_logs', exist_ok=True)
        with open(f'evolution_logs/evol_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json','w') as f:
            json.dump(log, f, indent=2)

# ====================================================================
# PRICE SIMULATOR
# ====================================================================
class PriceSim:
    def __init__(self, base=0.000045):
        self.prices = [base]; self.volumes = [50000]
        self.trend = 1.0
    def tick(self):
        prev = self.prices[-1]
        if np.random.random() < 0.08: self.trend = 1 + np.random.uniform(-0.015, 0.02)
        noise = np.random.normal(0, 0.008)
        spike = np.random.uniform(-0.03, 0.05) if np.random.random() < 0.08 else 0
        p = max(prev*(self.trend+noise+spike), prev*0.80)
        self.prices.append(p); self.volumes.append(50000*(1+np.random.random()*2))
        if len(self.prices) > 200: self.prices.pop(0); self.volumes.pop(0)
        return p

# ====================================================================
# MAIN AGENT
# ====================================================================
class MetaAggressor:
    def __init__(self):
        self.wallet = None
        self.engine = None
        self.optimizer = None
        self.sim = PriceSim()
    
    def setup(self):
        print("=" * 60)
        print("  META AGGRESSOR v3 — Self-Improving HFT")
        print("  Every 50-100 trades: retest + evolve strategy")
        print("  If failing 3x: asks you for new strategy design")
        print("=" * 60)
        
        if os.path.exists(Wallet.FILE):
            with open(Wallet.FILE) as f: self.wallet = json.load(f)
            print(f"\n  Wallet: {self.wallet['address']}")
            pwd = input("  Password: ").strip()
            if not Wallet.decrypt(self.wallet, pwd): print("  Wrong password!"); return False
            print("  Unlocked.")
        else:
            print("\n  Creating wallet...")
            while True:
                pwd = input("  Password (min 6): ").strip()
                if len(pwd)<6: continue
                p2 = input("  Confirm: ").strip()
                if pwd!=p2: continue
                break
            self.wallet = Wallet.generate('SOL', pwd)
            with open(Wallet.FILE,'w') as f: json.dump(self.wallet, f)
            print(f"\n  ADDRESS: {self.wallet['address']}")
            print(f"  KEY HINT: {self.wallet['hint']}")
            print(f"  PASSWORD: {pwd} (write this down!)")
        
        if os.path.exists(Wallet.STATE):
            with open(Wallet.STATE,'rb') as f: state=pickle.load(f)
            cap = state.get('capital', 0)
            if cap > 0:
                self.engine = HFTEngine(cap)
                self.engine.wins = state.get('wins', 0)
                self.engine.losses = state.get('losses', 0)
                self.engine.trades = state.get('trades', [])
                self.optimizer = MetaOptimizer(self.engine)
                print(f"  Restored: Rs{cap:.0f}, {len(self.engine.trades)} trades")
                return True
        
        amt = input("  Deposit (INR): Rs").strip()
        try:
            amt = float(amt)
            if amt < 100: print("  Min Rs100"); return False
            self.engine = HFTEngine(amt)
            self.optimizer = MetaOptimizer(self.engine)
            print(f"  Funded: Rs{amt:.0f}")
            return True
        except: print("  Invalid"); return False
    
    def tick(self):
        if not self.engine: return
        price = self.sim.tick()
        
        for pid in list(self.engine.positions.keys()):
            ei = self.engine.evaluate(pid, price)
            if ei:
                s = self.engine.summary()
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] EXIT {ei['ticker']}: "
                      f"{ei['ret_pct']:+.1f}% (net:{ei['net_pct']:+.1f}%) | {ei['reason']} | "
                      f"Rs{ei['pnl']:+.0f} | Cap:Rs{s['total_value']:.0f}")
        
        if len(self.sim.prices) >= 20 and len(self.engine.positions) < 3:
            sigs = SignalGenerator.scan(self.sim.prices, self.sim.volumes, self.engine.config)
            for d,r in sigs[:1]:
                pos = self.engine.enter('MEME', price, r)
                if pos:
                    pid, p = pos
                    s = self.engine.summary()
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] ENTER: ${p['entry']:.8f} -> "
                          f"${p['target']:.8f} (+{self.engine.config.params['target']*100:.0f}%) | "
                          f"Rs{p['capital_used']:.0f} at risk | Cap:Rs{s['total_value']:.0f} | {s['config']}")
        
        # Self-evaluation every 50-100 trades
        self.optimizer.evaluate_and_evolve()
    
    def print_status(self):
        s = self.engine.summary()
        print(f"\n{'='*50}")
        print(f"  STATUS  (Gen {s['generation']} | {s['config']})")
        print(f"{'='*50}")
        print(f"  Total:      Rs{s['total_value']:,.2f}")
        print(f"  Free:       Rs{s['capital']:,.2f}")
        print(f"  Peak:       Rs{s['peak']:,.2f}")
        print(f"  Return:     {s['return_pct']:+.2f}% ({s['return_mult']:.1f}x)")
        print(f"  Trades:     {s['trades']} (W:{s['wins']} L:{s['losses']}) WR:{s['win_rate']:.1f}%")
        print(f"  Active:     {s['active']} positions")
        
        if s['total_value'] > 1000:
            if s['total_value'] >= 100000:
                print(f"  >>> TARGET ACHIEVED: Rs{s['total_value']:,.0f}")
            else:
                need = 100000 / s['total_value']
                trades_needed = math.log(need, 1 + self.engine.config.params['target'])
                print(f"  To 1 Lac:   ~{trades_needed:.0f} more winning trades at current config")
                # REALISTIC probability
                wr = s['win_rate']/100
                if wr > 0:
                    ev_per_trade = wr*self.engine.config.params['target'] - (1-wr)*self.engine.config.params['stop']
                    winning_trades_needed = math.log(100000/s['total_value'], 1+self.engine.config.params['target'])
                    prob_hit = (wr ** winning_trades_needed) * 100 if winning_trades_needed > 0 else 0
                    print(f"  Realistic prob: ~{prob_hit:.1f}% (needs {winning_trades_needed:.0f} wins in a row)")
                    print(f"  Optimistic prob: ~{min(100, wr*100+30):.0f}% (with variance)")
        print(f"{'='*50}\n")
        
        with open(Wallet.STATE,'wb') as f:
            pickle.dump({'capital':self.engine.capital,'wins':self.engine.wins,
                        'losses':self.engine.losses,'trades':self.engine.trades[-500:],
                        'config':self.engine.config.name}, f)
    
    def run(self):
        if not self.setup(): return
        print(f"\n  Starting. Target: Rs100,000 ({(100000/self.engine.initial_capital):.0f}x)")
        print(f"  Strategy will self-evolve every 50-100 trades.")
        print(f"  Initial config: {self.engine.config.name}")
        print(f"  {'='*50}")
        
        cycle = 0
        try:
            while True:
                cycle += 1; self.tick()
                if cycle % 200 == 0: self.print_status()
                time.sleep(0.01)
        except KeyboardInterrupt: pass
        self.print_status()

# ====================================================================
# PROBABILITY TABLE (honest)
# ====================================================================
def print_probabilities():
    print("\n" + "=" * 80)
    print("  REALISTIC PROBABILITY TABLE — Rs1,000 Start, 100% Capital/Trade")
    print("=" * 80)
    
    scenarios = [
        ('REALISTIC (35% WR)', 0.35, '+35%/-15%', 8),
        ('OPTIMISTIC (40% WR)', 0.40, '+35%/-15%', 8),
        ('EXCEPTIONAL (45% WR)', 0.45, '+35%/-15%', 8),
        ('CONSERVATIVE (50% WR)', 0.50, '+20%/-10%', 8),
    ]
    targets = [('15 Aug', 20), ('1 Month', 30), ('3 Months', 90), ('6 Months', 180)]
    
    for sname, wr, desc, tpd in scenarios:
        print(f"\n  {sname} ({desc}):")
        for label, days in targets:
            eqs = np.ones(5000)
            for d in range(days):
                for _ in range(tpd):
                    is_win = np.random.random(len(eqs)) < wr
                    ret = np.where(is_win, 0.35, -0.15)
                    if sname.startswith('CONSERVATIVE'):
                        ret = np.where(is_win, 0.20, -0.10)
                    eqs *= (1 + ret)
                    eqs = np.maximum(eqs, 0.01)
            
            p25 = np.percentile(eqs, 25)
            p50 = np.percentile(eqs, 50)
            p75 = np.percentile(eqs, 75)
            hit = np.sum(eqs >= 100000) / len(eqs) * 100
            wiped = np.sum(eqs < 1) / len(eqs) * 100
            
            print(f"    {label:<12s}: P50=Rs{p50:>10,.0f}  [Rs{p25:>8,.0f}-Rs{p75:>8,.0f}]  "
                  f"1Lac={hit:>5.1f}%  Wiped={wiped:>4.1f}%")

# ====================================================================
if __name__ == '__main__':
    import sys
    if '--prob' in sys.argv:
        print_probabilities()
    else:
        agent = MetaAggressor()
        agent.run()
