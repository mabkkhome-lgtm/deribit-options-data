#!/usr/bin/env python3
"""
Minute-Level Historical Backfill from Deribit
Fetches last N days of options trades and calculates R,S,BG,SG every minute.
"""

import requests
from datetime import datetime, timezone, timedelta
import time
import os
from collections import defaultdict

# Configuration
DERIBIT_API = "https://www.deribit.com/api/v2/public"
OUTPUT_FILE = "data/btc_levels_minute.csv"
DAYS_TO_FETCH = 10
MINUTE_STEP = 5  # Calculate every 5 minutes (2880 points for 10 days)

def parse_instrument(name):
    """Parse instrument name like 'BTC-22DEC25-90000-C'"""
    parts = name.split('-')
    if len(parts) >= 4:
        return {
            'expiry': parts[1],
            'strike': int(parts[2]),
            'type': 'call' if parts[3] == 'C' else 'put'
        }
    return None

def fetch_trades_for_period(start_ts, end_ts):
    """Fetch trades for a specific time period"""
    all_trades = []
    current_end = end_ts
    
    while True:
        url = f"{DERIBIT_API}/get_last_trades_by_currency_and_time"
        params = {
            'currency': 'BTC',
            'kind': 'option',
            'start_timestamp': start_ts,
            'end_timestamp': current_end,
            'count': 1000
        }
        
        try:
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
            
            if 'result' not in data or 'trades' not in data['result']:
                break
            
            trades = data['result']['trades']
            if not trades:
                break
            
            all_trades.extend(trades)
            
            has_more = data['result'].get('has_more', False)
            if not has_more or len(trades) < 1000:
                break
            
            current_end = min(t['timestamp'] for t in trades) - 1
            time.sleep(0.1)  # Rate limiting
            
        except Exception as e:
            print(f"    Error: {e}")
            break
    
    return all_trades

def calculate_pnl(positions, underlying, is_buyer):
    """Calculate PnL at a given underlying price"""
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        premium_usd = p['premium'] * p.get('index_price', underlying)
        total += (intrinsic - premium_usd if is_buyer else premium_usd - intrinsic) * p['size']
    return total

def find_levels(longs, shorts, underlying_price):
    """Calculate R, S, BG, SG"""
    if not longs or not shorts:
        return None
    
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    
    price_min = int(min(min_strike, underlying_price * 0.85))
    price_max = int(max(max_strike, underlying_price * 1.15))
    
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, 100):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - 100) + t * 100)
        prev_diff = diff
    
    if len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif len(crossings) == 1:
        crossing = round(crossings[0])
        if crossing < underlying_price:
            s = crossing
            r = int(underlying_price * 1.05)
        else:
            r = crossing
            s = int(underlying_price * 0.95)
    else:
        s = int(underlying_price * 0.95)
        r = int(underlying_price * 1.05)
    
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def process_trades(trades, target_expiry):
    """Process trades into longs and shorts"""
    longs = []
    shorts = []
    
    for t in trades:
        parsed = parse_instrument(t['instrument_name'])
        if not parsed or parsed['expiry'] != target_expiry:
            continue
        
        pos = {
            'strike': parsed['strike'],
            'type': parsed['type'],
            'size': t['amount'],
            'premium': t['price'],
            'index_price': t.get('index_price', 90000)
        }
        
        if t['direction'] == 'buy':
            longs.append(pos)
        else:
            shorts.append(pos)
    
    return longs, shorts

def find_best_expiry(trades):
    """Find the expiry with most trades"""
    expiry_counts = defaultdict(int)
    for t in trades:
        parsed = parse_instrument(t['instrument_name'])
        if parsed:
            expiry_counts[parsed['expiry']] += t['amount']
    
    if not expiry_counts:
        return None
    
    return max(expiry_counts.items(), key=lambda x: x[1])[0]

def main():
    print("=" * 60)
    print("Minute-Level Deribit Backfill")
    print(f"Fetching {DAYS_TO_FETCH} days, every {MINUTE_STEP} minutes")
    print("=" * 60)
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Start fresh
    with open(OUTPUT_FILE, 'w') as f:
        f.write("datetime,R,S,BG,SG\n")
    
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=DAYS_TO_FETCH)
    
    results = []
    total_minutes = DAYS_TO_FETCH * 24 * 60 // MINUTE_STEP
    processed = 0
    
    current_time = start_date
    
    while current_time < now:
        # Fetch trades from the previous hour up to current_time
        period_start = current_time - timedelta(hours=4)  # Look back 4 hours for accumulated trades
        period_end = current_time
        
        # Progress
        processed += 1
        if processed % 10 == 0:
            pct = processed / total_minutes * 100
            print(f"\n[{pct:.1f}%] {current_time.strftime('%Y-%m-%d %H:%M')}")
        
        start_ts = int(period_start.timestamp() * 1000)
        end_ts = int(period_end.timestamp() * 1000)
        
        trades = fetch_trades_for_period(start_ts, end_ts)
        
        if trades:
            # Find best expiry for this time period
            best_expiry = find_best_expiry(trades)
            
            if best_expiry:
                longs, shorts = process_trades(trades, best_expiry)
                
                # Get average index price from trades
                avg_price = sum(t.get('index_price', 90000) for t in trades) / len(trades) if trades else 90000
                
                if longs and shorts:
                    levels = find_levels(longs, shorts, avg_price)
                    
                    if levels:
                        iso_time = current_time.strftime('%Y-%m-%dT%H:%M')
                        row = f"{iso_time},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}"
                        results.append(row)
                        
                        # Write immediately to file (in case of interruption)
                        with open(OUTPUT_FILE, 'a') as f:
                            f.write(row + '\n')
                        
                        if processed % 50 == 0:
                            print(f"  R={levels['r']:,} S={levels['s']:,}")
        
        # Move to next time period
        current_time += timedelta(minutes=MINUTE_STEP)
        time.sleep(0.15)  # Rate limiting
    
    print(f"\n✅ Done! Saved {len(results)} data points to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
