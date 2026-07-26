"""
MEME HFT AGGRESSOR — Maximum Aggression HFT for 1k INR
=======================================================
No baby risk management. This is for turning Rs1,000 into lacs.
- 100% capital per trade (you have nothing to diversify)
- 15-20% stop, 30-100% target
- No position limits, no daily loss limit
- Full compounding every trade
- Only kill: 90% total loss (you're already wiped)
"""
import os, json, time, math, hashlib, base64, secrets, pickle, sys
import numpy as np
from datetime import datetime
import warnings; warnings.filterwarnings('ignore')

# ====================================================================
# AGGRESSIVE CONFIG — No safety nets
# ====================================================================
CONFIG = {
    'capital_per_trade': 1.0,      # 100% of capital every trade
    'stop_loss': 0.15,              # 15% stop
    'take_profit': 0.40,            # 40% target
    'trail_activate': 0.30,         # Trail after 30% gain
    'trail_dist': 0.15,             # 15% trailing
    'min_win_rate': 0.30,           # 30% WR is fine (3:1 R:R)
    'cost_model': 'aggressive',     # Include all fees
    'kill_switch_at': 0.90,         # Only stop at 90% loss
    'max_trades_per_day': 50,       # No limit really
}

# ====================================================================
# WALLET (same as before — secure key generation)
# ====================================================================
class Wallet:
    """Minimal wallet — generate, save, load, decrypt."""
    FILE = 'agg_wallet.json'
    STATE = 'agg_state.pkl'
    
    @staticmethod
    def generate(chain='SOL', password=''):
        pk = secrets.token_hex(32)
        # Simple XOR encryption with verify hash
        pwd_hash = hashlib.sha256(password.encode()).digest()
        encrypted = bytes(int(pk[i:i+2], 16) ^ pwd_hash[i % len(pwd_hash)] for i in range(0, len(pk), 2))
        verify = hashlib.sha256(password.encode() + b'::agg').hexdigest()[:16]
        # Derive a fake address (in production use actual chain derivation)
        addr_hash = hashlib.sha3_256(bytes.fromhex(pk)).digest()
        address = '0x' + addr_hash[-20:].hex() if chain != 'SOL' else base64.b64encode(addr_hash[:32]).decode()[:44]
        return {'chain': chain, 'address': address, 'encrypted': base64.b64encode(encrypted).decode(), 'verify': verify, 'hint': pk[:8]+'...'+pk[-4:], 'created': datetime.now().isoformat()}
    
    @staticmethod
    def decrypt(wallet, password):
        try:
            if hashlib.sha256(password.encode() + b'::agg').hexdigest()[:16] != wallet['verify']: return None
            pwd_hash = hashlib.sha256(password.encode()).digest()
            encrypted = base64.b64decode(wallet['encrypted'])
            pk_bytes = bytes(e ^ pwd_hash[i % len(pwd_hash)] for i, e in enumerate(encrypted))
            return pk_bytes.hex()
        except: return None

# ====================================================================
# AGGRESSIVE HFT ENGINE
# ====================================================================
class AggressiveHFT:
    """No limits. Full capital. 40% target. 15% stop."""
    
    def __init__(self, capital_inr=1000):
        self.capital = capital_inr
        self.initial_capital = capital_inr
        self.peak_capital = capital_inr
        self.positions = {}
        self.trades = []
        self.daily_trades = 0
        self.wins = 0
        self.losses = 0
        self.consecutive_losses = 0
        self.start_time = datetime.now()
        self.last_reset_date = datetime.now().date()
    
    def reset_daily(self):
        now = datetime.now()
        if now.date() > self.last_reset_date:
            self.daily_trades = 0
            self.last_reset_date = now.date()
    
    def can_trade(self):
        self.reset_daily()
        if self.capital < 10: return False, "Capital depleted"
        loss_pct = (self.peak_capital - self.capital) / self.peak_capital
        if loss_pct >= CONFIG['kill_switch_at']: return False, f"90%+ drawdown"
        return True, "OK"
    
    def enter(self, ticker, price, reason='SIGNAL'):
        ok, msg = self.can_trade()
        if not ok: return None
        
        # 100% capital deployment (minus a tiny buffer for fees)
        trade_amt = self.capital * 0.95
        if trade_amt < 10: return None
        
        # Fee deduction
        fee = trade_amt * 0.035  # ~3.5% round trip on SOL
        trade_amt_after = trade_amt - fee
        quantity = trade_amt_after / price
        
        pos = {
            'ticker': ticker, 'entry': price, 'qty': quantity,
            'target': price * (1 + CONFIG['take_profit']),
            'stop': price * (1 - CONFIG['stop_loss']),
            'peak': price, 'entry_time': datetime.now().isoformat(),
            'reason': reason, 'capital_used': trade_amt,
            'fees_paid': fee,
        }
        
        pos_id = f"{ticker}_{datetime.now().timestamp()*1000:.0f}_{secrets.token_hex(4)}"
        self.positions[pos_id] = pos
        self.capital -= trade_amt
        self.daily_trades += 1
        
        return pos_id, pos
    
    def evaluate(self, pos_id, current_price, volume_ratio=1.0):
        pos = self.positions.get(pos_id)
        if not pos: return None
        
        entry = pos['entry']; direction = 1  # Only long for meme coins
        ret = (current_price / entry - 1) * 100
        
        # Update peak
        if current_price > pos['peak']:
            pos['peak'] = current_price
        
        exit_reason = None
        
        # Take profit
        if current_price >= pos['target']:
            exit_reason = 'TAKE_PROFIT'
        # Stop loss
        elif current_price <= pos['stop']:
            exit_reason = 'STOP_LOSS'
        # Trailing stop (activate after 30% gain)
        else:
            peak_gain = (pos['peak'] / entry - 1)
            if peak_gain > CONFIG['trail_activate']:
                trail_price = pos['peak'] * (1 - CONFIG['trail_dist'])
                if current_price <= trail_price:
                    exit_reason = f'TRAIL_{CONFIG["trail_dist"]*100:.0f}%'
        
        if exit_reason:
            # Calculate net PnL (after sell fees)
            gross_return = ret / 100
            sell_fee = 0.0175  # ~1.75% sell costs
            net_return = gross_return - sell_fee - (pos['fees_paid'] / pos['capital_used'])
            pnl = pos['capital_used'] * net_return
            
            self.capital += pos['capital_used'] + pnl
            if pnl > 0: self.wins += 1
            else: self.losses += 1
            
            trade_record = {
                'pos_id': pos_id, 'ticker': pos['ticker'], 'entry': entry,
                'exit': current_price, 'ret_pct': ret, 'net_pct': net_return * 100,
                'pnl': pnl, 'reason': exit_reason, 'time': datetime.now().isoformat()
            }
            self.trades.append(trade_record)
            
            self.peak_capital = max(self.peak_capital, self.capital)
            del self.positions[pos_id]
            return trade_record
        
        return None
    
    def total_value(self):
        pos_val = sum(p['qty'] * p['entry'] for p in self.positions.values())
        return self.capital + pos_val
    
    def summary(self):
        total = self.wins + self.losses
        wr = self.wins / max(total, 1) * 100
        tv = self.total_value()
        return {
            'capital': self.capital, 'peak': self.peak_capital, 'total_value': tv,
            'return_pct': (tv / self.initial_capital - 1) * 100,
            'trades': total, 'wins': self.wins, 'losses': self.losses,
            'win_rate': wr, 'active_pos': len(self.positions),
            'consecutive_losses': self.consecutive_losses,
        }

# ====================================================================
# SIGNAL GENERATOR — Simple, fast, aggressive
# ====================================================================
class AggressiveSignals:
    """Generates aggressive entry signals on 1-min data."""
    
    @staticmethod
    def scan(prices, volumes, n=20):
        """Generate signals from recent price action."""
        signals = []
        if len(prices) < n: return signals
        
        p = np.array(prices[-n:])
        v = np.array(volumes[-n:])
        ret_1m = (p[-1] / p[-2] - 1) * 100 if len(p) >= 2 else 0
        ret_5m = (p[-1] / p[-5] - 1) * 100 if len(p) >= 5 else 0
        vol_avg = np.mean(v)
        vol_ratio = v[-1] / max(vol_avg, 1)
        
        # Price is at recent low (potential bounce)
        if p[-1] <= np.min(p[-5:]) * 1.001 and ret_1m > 0:
            signals.append(('BUY', 'SUPPORT_BOUNCE'))
        
        # Volume spike + price up
        if vol_ratio > 3 and ret_1m > 0.5:
            signals.append(('BUY', 'VOLUME_SURGE'))
        
        # Breakout from tight range
        if len(p) >= 10:
            recent_range = (np.max(p[-10:]) / np.min(p[-10:]) - 1) * 100
            if recent_range < 2 and ret_1m > 0.3:
                signals.append(('BUY', 'RANGE_BREAKOUT'))
        
        # Momentum continuation
        if ret_5m > 2 and ret_1m > 0:
            signals.append(('BUY', 'MOMENTUM'))
        
        # Green candle after red (reversal)
        if len(p) >= 3:
            if p[-2] < p[-3] and p[-1] > p[-2]:
                signals.append(('BUY', 'REVERSAL'))
        
        return signals

# ====================================================================
# MAIN LOOP
# ====================================================================
class AggressiveAgent:
    """Full agent: wallet -> fund -> aggressive HFT loop."""
    
    def __init__(self):
        self.wallet = None
        self.password = ''
        self.engine = None
        self.sim_prices = [0.000045]
        self.sim_volumes = [50000]
    
    def setup(self):
        print("=" * 60)
        print("  MEME HFT AGGRESSOR v2.0")
        print("  100% capital per trade | 40% target | 15% stop")
        print("  No risk management for babies")
        print("=" * 60)
        
        # Load or create wallet
        if os.path.exists(Wallet.FILE):
            with open(Wallet.FILE) as f:
                self.wallet = json.load(f)
            print(f"\n  Wallet found: {self.wallet['address']}")
            pwd = input("  Password: ").strip()
            pk = Wallet.decrypt(self.wallet, pwd)
            if not pk: print("  Wrong password!"); return False
            self.password = pwd
            print("  Wallet unlocked.")
        else:
            print("\n  No wallet found. Creating...")
            chain = 'SOL'
            while True:
                pwd = input("  Set password (min 6): ").strip()
                if len(pwd) < 6: print("  Too short!"); continue
                pwd2 = input("  Confirm: ").strip()
                if pwd != pwd2: print("  No match!"); continue
                break
            self.wallet = Wallet.generate(chain, pwd)
            self.password = pwd
            with open(Wallet.FILE, 'w') as f:
                json.dump(self.wallet, f)
            print(f"\n  WALLET CREATED!")
            print(f"  Address: {self.wallet['address']}")
            print(f"  Key:     {self.wallet['hint']}")
            print(f"  PASSWORD: {pwd} (write this down!)")
            print(f"\n  Send SOL to the address above to fund.")
        
        # Fund check
        if os.path.exists(Wallet.STATE):
            with open(Wallet.STATE, 'rb') as f:
                state = pickle.load(f)
            capital = state.get('capital', 0)
            if capital > 0:
                print(f"\n  Restored capital: Rs{capital:.0f}")
                self.engine = AggressiveHFT(capital)
                return True
        
        # Ask for deposit
        print(f"\n  How much are you depositing? (INR)")
        amt = input(f"  Amount (min 100): Rs").strip()
        try:
            amt = float(amt)
            if amt < 100: print("  Minimum Rs100"); return False
            self.engine = AggressiveHFT(amt)
            print(f"  Funded with Rs{amt:.0f}. Starting aggressive HFT...")
            return True
        except:
            print("  Invalid amount"); return False
    
    def tick(self):
        """One HFT tick."""
        if not self.engine: return
        
        # More aggressive price moves (meme coin style)
        prev = self.sim_prices[-1]
        if not hasattr(self, 'trend') or self.trend is None: self.trend = 1.0
        if np.random.random() < 0.08: self.trend = 1 + np.random.uniform(-0.01, 0.015)
        noise = np.random.normal(0, 0.008)
        spike = np.random.uniform(-0.03, 0.05) if np.random.random() < 0.08 else 0
        new_price = max(prev * (self.trend + noise + spike), prev * 0.80)
        self.sim_prices.append(new_price)
        self.sim_volumes.append(50000 * (1 + np.random.random() * 2))
        
        if len(self.sim_prices) > 200:
            self.sim_prices.pop(0)
            self.sim_volumes.pop(0)
        
        # Manage positions
        for pid in list(self.engine.positions.keys()):
            vol_ratio = self.sim_volumes[-1] / np.mean(self.sim_volumes[-20:]) if len(self.sim_volumes) >= 20 else 1
            exit_info = self.engine.evaluate(pid, new_price, vol_ratio)
            if exit_info:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] EXIT: "
                      f"{exit_info['ret_pct']:+.1f}% (net: {exit_info['net_pct']:+.1f}%) | "
                      f"{exit_info['reason']} | Rs{exit_info['pnl']:+.0f}")
        
        # Generate signals every 10 ticks
        if len(self.sim_prices) >= 20 and int(datetime.now().timestamp() * 10) % 10 == 0:
            sigs = AggressiveSignals.scan(self.sim_prices, self.sim_volumes)
            for direction, reason in sigs[:2]:  # Max 2 signals per tick
                pos = self.engine.enter('MEME', new_price, reason)
                if pos:
                    pid, p = pos
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] ENTER: ${p['entry']:.8f} -> "
                          f"${p['target']:.8f} (+{CONFIG['take_profit']*100:.0f}%) | "
                          f"Stop: ${p['stop']:.8f} (-{CONFIG['stop_loss']*100:.0f}%) | "
                          f"Rs{p['capital_used']:.0f} at risk | {reason}")
    
    def print_status(self):
        if not self.engine: return
        s = self.engine.summary()
        print(f"\n{'='*50}")
        print(f"  STATUS")
        print(f"{'='*50}")
        print(f"  Total:      Rs{s['total_value']:,.2f}")
        print(f"  Free:       Rs{s['capital']:,.2f}")
        print(f"  Peak:       Rs{s['peak']:,.2f}")
        print(f"  Return:     {s['return_pct']:+.2f}%")
        print(f"  Trades:     {s['trades']} (W:{s['wins']} L:{s['losses']})")
        print(f"  Win Rate:   {s['win_rate']:.1f}%")
        print(f"  Active:     {s['active_pos']}")
        
        if s['capital'] > 1000:
            mult = s['capital'] / 1000
            print(f"  Multiple:   {mult:.1f}x")
            if s['capital'] >= 100000:
                print(f"  >>> TARGET HIT! Rs{s['capital']:,.0f}")
            else:
                target = 100000
                need = target / s['capital']
                trades_needed = math.log(need, 1 + CONFIG['take_profit'])
                print(f"  To 1 Lac:   ~{trades_needed:.0f} more winning trades")
        print(f"{'='*50}\n")
        
        # Save state
        with open(Wallet.STATE, 'wb') as f:
            pickle.dump({'capital': self.engine.capital, 'peak': self.engine.peak_capital,
                        'trades': s['trades'], 'wins': s['wins'], 'timestamp': datetime.now().isoformat()}, f)
    
    def run(self):
        if not self.setup():
            return
        
        print(f"\n{'='*60}")
        print(f"  AGGRESSIVE HFT RUNNING")
        print(f"  Capital: Rs{self.engine.capital:.0f}")
        print(f"  Target:  Rs100,000 ({(100000/self.engine.capital):.0f}x)")
        print(f"  Per trade: {CONFIG['capital_per_trade']*100:.0f}% capital, "
              f"+{CONFIG['take_profit']*100:.0f}% target, -{CONFIG['stop_loss']*100:.0f}% stop")
        print(f"  Only kill: 90% total loss")
        print(f"{'='*60}")
        
        cycle = 0
        try:
            while True:
                cycle += 1
                self.tick()
                
                if cycle % 100 == 0:
                    self.print_status()
                    
                    # Check if target hit
                    if self.engine.capital >= 100000:
                        print(f"\n{'!'*60}")
                        print(f"  TARGET ACHIEVED: Rs{self.engine.capital:,.0f}!")
                        print(f"  Started with Rs{self.engine.initial_capital if hasattr(self.engine, 'initial_capital') else 'unknown'}")
                        print(f"{'!'*60}")
                        break
                    
                    # Check kill switch
                    s = self.engine.summary()
                    if s['capital'] < 10:
                        print(f"\n  Capital depleted. Stopping.")
                        break
                
                time.sleep(0.01)  # 10ms = HFT latency
                
        except KeyboardInterrupt:
            pass
        
        self.print_status()
        print(f"\n  State saved. Restart: python meme_hft_aggressor.py")

if __name__ == '__main__':
    agent = AggressiveAgent()
    agent.run()
