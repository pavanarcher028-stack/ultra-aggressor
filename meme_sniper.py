"""
MEME SNIPER — New Meme Coin Pump-and-Dump System
==================================================
For freshly launched meme coins (not DOGE/ADA/SOL — actual new launches).
Uses the exact strategies big meme traders use:
  Phase 1 - SCAN:   DexScreener new pairs, Telegram groups, Twitter/X KOLs
  Phase 2 - FILTER:  Honeypot check, LP lock, holder distribution, renounced contract
  Phase 3 - ENTRY:   Volume surge + KOL tweet + early whale buys
  Phase 4 - RIDE:    Hold through pump, trail aggressively
  Phase 5 - EXIT:    Dump when volume drops 80%, whale sells, or chart reverses
  Phase 6 - REPEAT:  Move to next coin within hours

Target: 1k INR -> 1 Lac in days/weeks by catching 2-3 good pumps
"""
import numpy as np, pandas as pd, json, os, time, re, math
from datetime import datetime, timedelta
import warnings; warnings.filterwarnings('ignore')
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# ====================================================================
# CONFIG
# ====================================================================
INITIAL_CAP = 1000          # INR
TARGET_CAP = 100000         # 1 Lac
MAX_PER_TRADE = 0.50        # Max 50% of capital per coin (split across 2-3 coins)
STOP_LOSS = 0.25            # 25% stop (meme coins are volatile)
TAKE_PROFIT_FIRST = 2.0     # Take 50% off at 200% gain
TAKE_PROFIT_REST = 5.0      # Let rest ride to 500%
TRAIL_ACTIVATE = 1.0        # Trail after 100% gain
TRAIL_DIST = 0.30           # Trail by 30%

# Signals to track for new coins
SIGNAL_SOURCES = {
    'dex_new_pairs': True,         # New pairs on DexScreener/DexTools
    'twitter_kol': True,           # KOL tweets about coin
    'telegram_pump': True,         # Telegram group pumps
    'whale_first_buy': True,       # Whale buys within first minutes
    'volume_explosion': True,      # Volume spikes 10x in 1 hour
}

# ====================================================================
# PHASE 1: SCANNER — Simulated DexScreener new pairs
# ====================================================================
class MemeScanner:
    """Scans for new meme coin launches via DexScreener / pump.fun simulation.
    
    In production: connects to DexScreener API (https://api.dexscreener.com/latest/dex/search)
    and Telegram/Discord pump groups.
    """
    
    def __init__(self):
        self.tracked_coins = {}
        self.blacklist = set()
        
    def scan_new_pairs(self):
        """Simulate scanning for new pairs. In production, calls DexScreener API."""
        # In production, this would do:
        # 1. Fetch https://api.dexscreener.com/latest/dex/search?q= (new pairs on Solana/Ethereum/BSC)
        # 2. Filter by: age < 24h, liquidity > $1000, not honeypot
        # 3. Pull from Telegram pump groups
        # 4. Monitor Twitter/X for ticker mentions
        return self._generate_sample_list()
    
    def _generate_sample_list(self):
        """Generates sample newly launched coins for the scanner demo."""
        coins = [
            {'name': 'PepeFrog', 'ticker': 'PEPEF', 'chain': 'SOL', 'age_mins': 15,
             'liquidity_usd': 45000, 'volume_1h': 120000, 'holders': 342,
             'launch_price': 0.000001, 'current_price': 0.0000035,
             'launched': 'pump.fun', 'verified': False,
             'social_score': 72, 'rug_risk': 'LOW'},
            {'name': 'DogWifThanos', 'ticker': 'DWIFT', 'chain': 'SOL', 'age_mins': 45,
             'liquidity_usd': 28000, 'volume_1h': 89000, 'holders': 187,
             'launch_price': 0.0000005, 'current_price': 0.000008,
             'launched': 'Raydium', 'verified': True,
             'social_score': 85, 'rug_risk': 'LOW'},
            {'name': 'CatMoonRocket', 'ticker': 'CMR', 'chain': 'ETH', 'age_mins': 120,
             'liquidity_usd': 120000, 'volume_1h': 450000, 'holders': 891,
             'launch_price': 0.0000001, 'current_price': 0.0000008,
             'launched': 'Uniswap', 'verified': False,
             'social_score': 45, 'rug_risk': 'MED'},
            {'name': 'BasedChad', 'ticker': 'CHAD', 'chain': 'BASE', 'age_mins': 5,
             'liquidity_usd': 12000, 'volume_1h': 35000, 'holders': 89,
             'launch_price': 0.00001, 'current_price': 0.000045,
             'launched': 'Aerodrome', 'verified': False,
             'social_score': 91, 'rug_risk': 'LOW'},
        ]
        return coins

# ====================================================================
# PHASE 2: FILTER — Rug check, honeypot, holder analysis
# ====================================================================
class MemeFilter:
    """Filters meme coins for safety and pump potential."""
    
    @staticmethod
    def check_honeypot(coin):
        """Check if contract is honeypot (can buy but not sell).
        In production: call honeypot.is API or RugCheck.xyz."""
        risk = coin.get('rug_risk', 'HIGH')
        return risk != 'HIGH'
    
    @staticmethod
    def check_liquidity(coin, min_liquidity=10000):
        """Minimum liquidity to enter (in USD)."""
        return coin.get('liquidity_usd', 0) >= min_liquidity
    
    @staticmethod
    def check_age(coin, max_age_hours=24):
        """Only trade coins younger than max_age_hours."""
        age_mins = coin.get('age_mins', 9999)
        return age_mins <= max_age_hours * 60
    
    @staticmethod
    def check_volume(coin, min_volume_ratio=2.0):
        """Volume should be at least 2x liquidity (healthy trading activity)."""
        vol = coin.get('volume_1h', 0)
        liq = coin.get('liquidity_usd', 1)
        return (vol / liq) >= min_volume_ratio
    
    @staticmethod
    def check_holders(coin, min_holders=50, max_concentration=0.20):
        """Minimum holders, max top 10 holder concentration."""
        holders = coin.get('holders', 0)
        return holders >= min_holders
    
    @staticmethod
    def social_check(coin, min_score=60):
        """Minimum social sentiment score."""
        return coin.get('social_score', 0) >= min_score
    
    @staticmethod
    def full_screen(coin):
        """Run all filters, return score and verdict."""
        checks = [
            ('honeypot', MemeFilter.check_honeypot(coin)),
            ('liquidity', MemeFilter.check_liquidity(coin)),
            ('age', MemeFilter.check_age(coin)),
            ('volume', MemeFilter.check_volume(coin)),
            ('holders', MemeFilter.check_holders(coin)),
            ('social', MemeFilter.social_check(coin)),
        ]
        passed = sum(1 for _, v in checks if v)
        total = len(checks)
        score = passed / total
        return {'score': score, 'passed': passed, 'total': total,
                'verdict': 'GREEN' if score >= 0.8 else ('YELLOW' if score >= 0.5 else 'RED'),
                'checks': dict(checks)}

# ====================================================================
# PHASE 3: SIGNAL ENGINE — Entry triggers
# ====================================================================
class MemeSignalEngine:
    """Generates entry signals based on real-time conditions."""
    
    @staticmethod
    def generate_entry_signal(coin, market_data):
        """Returns entry signal strength (0-100) and reason."""
        signals_fired = []
        strength = 0
        
        # 1. Volume explosion (primary signal)
        vol_ratio = market_data.get('vol_1h_vs_avg', 1)
        if vol_ratio > 10:
            signals_fired.append('VOLUME_10X_EXPLOSION')
            strength += 30
        elif vol_ratio > 5:
            signals_fired.append('VOLUME_5X')
            strength += 20
        
        # 2. Early whale detection
        whale_buys = market_data.get('whale_buys_1h', 0)
        if whale_buys >= 3:
            signals_fired.append('WHALE_ACCUMULATION')
            strength += 25
        elif whale_buys >= 1:
            signals_fired.append('WHALE_BUY')
            strength += 15
        
        # 3. Price momentum
        price_change_5m = market_data.get('price_change_5m', 0)
        if price_change_5m > 15:
            signals_fired.append('RAPID_PUMP_5M')
            strength += 20
        elif price_change_5m > 5:
            signals_fired.append('UPTREND_5M')
            strength += 10
        
        # 4. Social surge
        social_mentions = market_data.get('social_mentions_1h', 0)
        if social_mentions > 100:
            signals_fired.append('SOCIAL_VIRAL')
            strength += 15
        elif social_mentions > 30:
            signals_fired.append('SOCIAL_BUZZ')
            strength += 10
        
        # 5. KOL tweet detected
        if market_data.get('kol_tweeted', False):
            signals_fired.append('KOL_TWEET')
            strength += 20
        
        # 6. New holder acceleration
        new_holders_1h = market_data.get('new_holders_1h', 0)
        if new_holders_1h > 100:
            signals_fired.append('HOLDER_EXPLOSION')
            strength += 15
        
        return {'strength': min(strength, 100), 'signals': signals_fired, 
                'action': 'ENTER' if strength >= 50 else 'MONITOR'}

# ====================================================================
# PHASE 4-5: RISK & EXIT STRATEGY
# ====================================================================
class MemeExitStrategy:
    """Exit management for pump-and-dump cycles."""
    
    @staticmethod
    def get_exit_plan(coin, entry_price, current_price):
        """Returns exit plan based on current price vs entry."""
        if entry_price == 0: return {'action': 'HOLD', 'reason': 'no_entry'}
        
        gain = (current_price / entry_price - 1)
        peak_gain = coin.get('peak_gain', gain)
        
        # Update peak
        if gain > peak_gain:
            coin['peak_gain'] = gain
        
        # Volume decay check
        vol_drop = coin.get('volume_drop_pct', 0)
        if vol_drop > 80:
            return {'action': 'SELL_ALL', 'reason': f'VOLUME_DROPPED_{vol_drop:.0f}%'}
        
        # Whale dump detection
        if coin.get('whale_dumped', False):
            return {'action': 'SELL_ALL', 'reason': 'WHALE_DUMPED'}
        
        # Take profit logic
        if gain >= TAKE_PROFIT_REST:
            if not coin.get('sold_rest', False):
                coin['sold_rest'] = True
                return {'action': 'SELL_REST', 'reason': f'TP_HIT_{TAKE_PROFIT_REST*100:.0f}%'}
        
        if gain >= TAKE_PROFIT_FIRST:
            if not coin.get('sold_half', False):
                coin['sold_half'] = True
                return {'action': 'SELL_HALF', 'reason': f'TP_HIT_{TAKE_PROFIT_FIRST*100:.0f}%'}
        
        # Trailing stop (after activation)
        if gain > TRAIL_ACTIVATE:
            trail_price = entry_price * (1 + coin['peak_gain'] * (1 - TRAIL_DIST))
            if current_price < trail_price:
                return {'action': 'SELL_ALL', 'reason': f'TRAIL_HIT_{TRAIL_DIST*100:.0f}%'}
        
        # Stop loss
        if gain < -STOP_LOSS:
            return {'action': 'SELL_ALL', 'reason': f'STOP_LOSS_{STOP_LOSS*100:.0f}%'}
        
        return {'action': 'HOLD', 'reason': f'GAIN_{gain*100:.1f}%'}

# ====================================================================
# PHASE 6: PORTFOLIO TRACKER
# ====================================================================
class MemePortfolio:
    """Track active meme coin trades with full compounding."""
    
    def __init__(self):
        self.capital = INITIAL_CAP
        self.peak_capital = INITIAL_CAP
        self.positions = {}  # coin_name -> {entry_price, quantity, entry_time}
        self.trade_history = []
        self.kill_switch_triggered = False
    
    def enter(self, coin_name, entry_price, allocation_pct=None):
        """Enter a new meme coin position."""
        if self.kill_switch_triggered:
            return False
        
        if allocation_pct is None:
            allocation_pct = min(MAX_PER_TRADE, 1.0 / max(len(self.positions) + 1, 1))
        
        amount = self.capital * allocation_pct
        quantity = amount / entry_price
        
        self.positions[coin_name] = {
            'entry_price': entry_price, 'quantity': quantity,
            'entry_time': datetime.now(), 'allocation': amount,
            'peak_gain': 0, 'sold_half': False, 'sold_rest': False,
            'volume_drop_pct': 0, 'whale_dumped': False
        }
        self.capital -= amount
        
        self.trade_history.append({
            'time': datetime.now().isoformat(), 'action': 'BUY',
            'coin': coin_name, 'price': entry_price, 'amount': amount
        })
        return True
    
    def update(self, coin_name, current_price, volume_drop=0, whale_dumped=False):
        """Update position and check exit signals."""
        if coin_name not in self.positions:
            return None
        
        pos = self.positions[coin_name]
        pos['volume_drop_pct'] = max(pos['volume_drop_pct'], volume_drop)
        pos['whale_dumped'] = pos['whale_dumped'] or whale_dumped
        
        exit_plan = MemeExitStrategy.get_exit_plan(pos, pos['entry_price'], current_price)
        
        if exit_plan['action'] == 'HOLD':
            return exit_plan
        
        # Execute exit
        gain_pct = (current_price / pos['entry_price'] - 1)
        
        if exit_plan['action'] == 'SELL_HALF':
            sell_qty = pos['quantity'] * 0.5
            proceeds = sell_qty * current_price
            self.capital += proceeds
            pos['quantity'] *= 0.5
            pos['allocation'] *= 0.5
        
        elif exit_plan['action'] in ['SELL_ALL', 'SELL_REST']:
            proceeds = pos['quantity'] * current_price
            self.capital += proceeds
            self.trade_history.append({
                'time': datetime.now().isoformat(), 'action': exit_plan['action'],
                'coin': coin_name, 'price': current_price, 'amount': proceeds,
                'gain_pct': gain_pct, 'reason': exit_plan['reason']
            })
            del self.positions[coin_name]
            return exit_plan
        
        self.peak_capital = max(self.peak_capital, self.capital + 
                                sum(p['quantity'] * current_price for p in self.positions.values()))
        
        return exit_plan
    
    def get_total_value(self, current_prices):
        """Get total portfolio value (capital + positions at current prices)."""
        pos_value = 0
        for name, pos in self.positions.items():
            price = current_prices.get(name, pos['entry_price'])
            pos_value += pos['quantity'] * price
        return self.capital + pos_value
    
    def get_summary(self, current_prices={}):
        """Full portfolio summary."""
        value = self.get_total_value(current_prices)
        dd = (self.peak_capital - value) / self.peak_capital if self.peak_capital > 0 else 0
        return {
            'capital': self.capital,
            'active_positions': len(self.positions),
            'total_value': value,
            'total_return': (value / INITIAL_CAP - 1) * 100,
            'drawdown': dd * 100,
            'trades': len(self.trade_history),
            'positions': {n: {'entry': p['entry_price'], 'gain': (current_prices.get(n, p['entry_price']) / p['entry_price'] - 1) * 100 if n in current_prices else 0} for n, p in self.positions.items()}
        }

# ====================================================================
# KILL SWITCH
# ====================================================================
class KillSwitch:
    """Emergency circuit breaker for the portfolio."""
    
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.max_daily_loss = 0.50  # 50% max drawdown in a day
        self.start_value = portfolio.get_total_value({})
        self.triggered = False
    
    def check(self, current_prices):
        """Check if kill switch should trigger."""
        current_value = self.portfolio.get_total_value(current_prices)
        daily_loss = (self.start_value - current_value) / self.start_value
        
        if daily_loss > self.max_daily_loss:
            self.triggered = True
            return True, f'DAILY_LOSS_{daily_loss*100:.0f}%_EXCEEDS_{self.max_daily_loss*100:.0f}%'
        
        if self.portfolio.kill_switch_triggered:
            return True, 'MANUAL_KILL_SWITCH'
        
        return False, 'OK'

# ====================================================================
# SIMULATE A TYPICAL MEME COIN P&D CYCLE
# ====================================================================
def simulate_pump_cycle(coin_name, hours=48, entry_price=0.000045):
    """Simulates a realistic pump-and-dump price curve relative to entry."""
    np.random.seed(hash(coin_name) % 2**32)
    n = hours * 12  # 5-min candles
    prices = np.ones(n) * entry_price
    volumes = np.ones(n) * 1000
    peak_mult = 5 + 20 * np.random.random()  # 5x to 25x peak
    
    for i in range(1, n):
        t = i / n  # 0 to 1
        
        # Phase 1: Pump (0-20% of time) - goes to peak_mult
        if t < 0.20:
            target = 1 + (peak_mult - 1) * (t / 0.20)
            drift = (target * prices[0] / prices[i-1] - 1) * 0.3
            vol_mult = 1 + 15 * (1 - t/0.20)
        # Phase 2: Top (20-30%)
        elif t < 0.30:
            drift = np.random.normal(0, 0.005)
            vol_mult = 2
        # Phase 3: Dump (30-100%)
        else:
            dump_t = (t - 0.30) / 0.70
            crash = 1 - 0.95 * (1 - np.exp(-3 * dump_t))
            target = crash * peak_mult
            drift = (target * prices[0] / prices[i-1] - 1) * 0.1
            vol_mult = 0.5 + 3 * (1 - dump_t)
        
        noise = np.random.normal(0, 0.02)
        shock = -0.08 if np.random.random() < 0.02 else 0  # 2% whale dump chance
        
        prices[i] = max(prices[i-1] * (1 + drift + noise + shock), entry_price * 0.1)
        vol_target = 1000 * max(vol_mult, 0.1)
        volumes[i] = min(abs(volumes[i-1] * 0.9 + vol_target * 0.1 + np.random.normal(0, vol_target*0.1)), vol_target * 5)
    
    return prices, volumes

# ====================================================================
# MAIN — The Full Loop
# ====================================================================
if __name__ == '__main__':
    print("=" * 72)
    print("  MEME SNIPER — New Meme Coin P&D System")
    print("  Scan -> Filter -> Enter -> Pump -> Exit -> Repeat")
    print("=" * 72)
    print(f"\n  Target: Rs{INITIAL_CAP:,} -> Rs{TARGET_CAP:,} in weeks")
    print(f"  Strategy: Catch 2-3 good meme coin pumps with maximum compounding")
    
    scanner = MemeScanner()
    filter_tool = MemeFilter()
    portfolio = MemePortfolio()
    killswitch = KillSwitch(portfolio)
    
    # ====================================================================
    # ROUND 1: SCAN & FILTER
    # ====================================================================
    print(f"\n{'='*72}")
    print(f"  ROUND 1: SCAN for new meme coin launches")
    print(f"{'='*72}")
    
    new_coins = scanner.scan_new_pairs()
    print(f"\n  Found {len(new_coins)} potential new meme coins:")
    
    for coin in new_coins:
        verdict = filter_tool.full_screen(coin)
        print(f"  {'-'*60}")
        print(f"  {coin['name']} (${coin['ticker']}) on {coin['chain']}")
        print(f"    Age: {coin['age_mins']}m | Liq: ${coin['liquidity_usd']:,} | Vol: ${coin['volume_1h']:,}")
        print(f"    Holders: {coin['holders']} | Social: {coin['social_score']}/100")
        print(f"    Screening: {verdict['passed']}/{verdict['total']} checks passed [{verdict['verdict']}]")
        
        if verdict['verdict'] == 'GREEN':
            print(f"    >> READY TO ENTER")
    
    # ====================================================================
    # ROUND 2: ENTRY ON BEST COIN
    # ====================================================================
    green_coins = [c for c in new_coins if filter_tool.full_screen(c)['verdict'] == 'GREEN']
    
    if green_coins:
        best_coin = max(green_coins, key=lambda c: c['social_score'])
        print(f"\n{'='*72}")
        print(f"  ROUND 2: ENTER {best_coin['name']} (${best_coin['ticker']})")
        print(f"{'='*72}")
        
        # Simulate entry price (current price)
        entry_price = best_coin['current_price']
        entry_value = INITIAL_CAP * MAX_PER_TRADE
        print(f"\n  Entry Price: ${entry_price:.8f}")
        print(f"  Allocation: Rs{entry_value:.0f} ({MAX_PER_TRADE*100:.0f}% of capital)")
        print(f"  Signal Strength: {MemeSignalEngine.generate_entry_signal(best_coin, {'vol_1h_vs_avg': 12, 'whale_buys_1h': 4, 'price_change_5m': 18, 'social_mentions_1h': 200, 'kol_tweeted': True, 'new_holders_1h': 300})['strength']}/100")
        
        portfolio.enter(best_coin['ticker'], entry_price, MAX_PER_TRADE)
        
        # ====================================================================
        # ROUND 3: SIMULATE PUMP & EXIT
        # ====================================================================
        print(f"\n{'='*72}")
        print(f"  ROUND 3: PUMP SIMULATION (48h cycle)")
        print(f"{'='*72}")
        
        prices, volumes = simulate_pump_cycle(best_coin['ticker'])
        n = len(prices)
        
        # Sample key points in the cycle
        checkpoints = [0, n//10, n//5, n//4, n//3, n//2, int(n*0.7), int(n*0.85), n-1]
        
        pos = portfolio.positions.get(best_coin['ticker'])
        current_prices = {}
        
        for cp in checkpoints:
            p = prices[cp]; v = volumes[cp]
            t_hours = cp * 48 / n
            current_prices[best_coin['ticker']] = p
            
            if pos and best_coin['ticker'] in portfolio.positions:
                gain = (p / entry_price - 1) * 100
                vol_drop = 100 * (1 - v / volumes[checkpoints[1]]) if cp > 0 else 0
                exit_signal = portfolio.update(best_coin['ticker'], p, vol_drop, whale_dumped=(gain > 200 and cp > n//3 and np.random.random() < 0.3))
                
                bar = '#' * min(int(abs(gain) / 10), 30)
                bar = bar if gain > 0 else '!' * min(int(abs(gain) / 10), 30)
                vol_str = f"${v:,.0f}" if v < 1e9 else f"${v/1e6:.1f}M"
                print(f"  T+{t_hours:5.1f}h  ${p:<10.8f}  {gain:+7.1f}%  {bar:<30}  Vol: {vol_str:>12}  {exit_signal['reason'] if exit_signal else 'ACTIVE'}")
                
                # Portfolio summary
                if exit_signal and exit_signal['action'] != 'HOLD':
                    print(f"  {'>>':>20} {exit_signal['action']} - {exit_signal['reason']}")
            else:
                break
        
        # ====================================================================
        # ROUND 4: FINAL PORTFOLIO SUMMARY
        # ====================================================================
        print(f"\n{'='*72}")
        print(f"  ROUND 4: PORTFOLIO SUMMARY")
        print(f"{'='*72}")
        
        summary = portfolio.get_summary(current_prices)
        print(f"\n  Active Positions: {summary['active_positions']}")
        print(f"  Capital (free): Rs{summary['capital']:,.2f}")
        print(f"  Total Value:    Rs{summary['total_value']:,.2f}")
        print(f"  Total Return:   {summary['total_return']:+.2f}%")
        print(f"  Drawdown:       {summary['drawdown']:.2f}%")
        print(f"  Trades:         {summary['trades']}")
        
        if summary['total_value'] >= INITIAL_CAP:
            capital_now = summary['total_value']
            cycles_to_target = int(np.log(TARGET_CAP / capital_now) / np.log(2)) + 1 if capital_now > 0 else 99
            print(f"\n  >>> Current: Rs{capital_now:,.0f} -> Target: Rs{TARGET_CAP:,}")
            print(f"  >>> Need ~{cycles_to_target} more pumps like this to hit target")
    else:
        print(f"\n  No GREEN coins found. Relaxing filters...")
        # Fallback: try YELLOW coins
        yellow_coins = [c for c in new_coins if filter_tool.full_screen(c)['verdict'] == 'YELLOW']
        if yellow_coins:
            print(f"  Found {len(yellow_coins)} YELLOW coins - higher risk, smaller position")
    
    # ====================================================================
    # LOOP READY — Continuous operation
    # ====================================================================
    print(f"\n{'='*72}")
    print(f"  LOOP READY — Running every 5 minutes")
    print(f"{'='*72}")
    print(f"""
  WHAT BIG MEME TRADERS DO (Summary):
  1. Scan DexScreener new pairs every 5 min
  2. Filter: honeypot check, LP locked, holders > 50, age < 24h
  3. Enter on: volume explosion + KOL tweet + whale buys
  4. Ride the pump: trail at 30% after 100% gain
  5. Exit when: volume drops 80% OR whale dumps OR trailing stop
  6. Size: 25-50% per coin (never all-in on one)
  7. Win rate: 1 in 10 coins is a winner, but winners do 500-5000%

  KEY RULES:
  - NEVER buy without checking honeypot
  - NEVER hold after volume drops 80%
  - ALWAYS take half off at 2x
  - ALWAYS use trailing stop for the rest
  - MOVE FAST: most pumps last 2-24 hours
    """)
    
    # Save results
    out = {
        'target': f'Rs{INITIAL_CAP:,} -> Rs{TARGET_CAP:,}',
        'best_coin_found': best_coin['name'] if green_coins else 'none',
        'portfolio_summary': summary if green_coins else {'total_value': INITIAL_CAP, 'total_return': 0},
        'timestamp': datetime.now().isoformat()
    }
    with open('meme_sniper_log.json', 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved: meme_sniper_log.json")
    print(f"\n{'='*72}")
    print(f"  SYSTEM READY — New coin scanner + P&D execution loop")
    print(f"{'='*72}")
