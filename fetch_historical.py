#!/usr/bin/env python3
"""
Historical Level Backfill Script v2
Fetches historical options data and calculates R, S, BG, SG at intervals.
Auto-detects the nearest expiry with trades for each date.
"""

import requests
from datetime import datetime, timezone, timedelta
import time
import os
from collections import defaultdict

# Configuration
THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"
OUTPUT_FILE = "data/btc_levels_hourly.csv"
DAYS_TO_FETCH = 90
HOUR_STEP = 4  # Calculate every 4 hours (0, 4, 8, 12, 16, 20)

def calculate_pnl(positions, underlying, is_buyer):
    """Calculate PnL at a given underlying price"""
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        total += (intrinsic - p['premium'] if is_buyer else p['premium'] - intrinsic) * p['size']
    return total

def find_levels(longs, shorts):
    """Calculate R, S, BG, SG using proper formulas"""
    if not longs or not shorts:
        return None
    
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # Find crossings where buyer PnL = seller PnL
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, 1):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - 1) + t)
        prev_diff = diff
    
    if len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif len(crossings) == 1:
        s = r = round(crossings[0])
    else:
        s = round(min_strike)
        r = round(max_strike)
    
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def fetch_data_for_date(date, hour):
    """Fetch data and auto-detect the best expiry to use"""
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = date.replace(hour=hour, minute=59, second=59, microsecond=0)
    
    from_ts = int(start.timestamp() * 1000)
    to_ts = int(end.timestamp() * 1000)
    
    url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
    
    try:
        resp = requests.get(url, timeout=30)
        if not resp.text.strip():
            return None
        
        lines = resp.text.strip().split('\n')
        
        # Count trades per expiry to find the best one
        expiry_counts = defaultdict(int)
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7:
                try:
                    expiry = int(parts[1])
                    size = float(parts[5])
                    expiry_counts[expiry] += size
                except:
                    pass
        
        if not expiry_counts:
            return None
        
        # Use the expiry with most volume that's within 7 days of the date
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        current_code = (date - epoch).days
        
        # Filter to expiries within next 7 days
        valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}
        
        if not valid_expiries:
            # Fallback: use any near expiry
            valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code}
        
        if not valid_expiries:
            return None
        
        # Pick the expiry with most trades
        best_expiry = max(valid_expiries.items(), key=lambda x: x[1])[0]
        
        # Now parse positions for this expiry
        longs = []
        shorts = []
        
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7:
                try:
                    option_type = int(parts[0])
                    expiry = int(parts[1])
                    strike = float(parts[2])
                    side = int(parts[4])
                    size = float(parts[5])
                    premium = float(parts[6])
                    
                    if expiry != best_expiry:
                        continue
                    
                    pos = {
                        'type': 'call' if option_type == 0 else 'put',
                        'strike': strike,
                        'size': size,
                        'premium': premium
                    }
                    
                    if side == 0:
                        longs.append(pos)
                    else:
                        shorts.append(pos)
                except:
                    continue
        
        if longs and shorts:
            return find_levels(longs, shorts)
    except Exception as e:
        print(f"    Error: {e}")
    
    return None

def main():
    print("=" * 60)
    print("Historical Level Backfill Script v2")
    print("=" * 60)
    print(f"\nFetching {DAYS_TO_FETCH} days of data, every {HOUR_STEP} hours")
    print("Auto-detecting best expiry for each date...")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write("datetime,R,S,BG,SG\n")
    
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=DAYS_TO_FETCH)
    
    results = []
    
    for day_offset in range(DAYS_TO_FETCH + 1):
        current_date = start_date + timedelta(days=day_offset)
        
        if current_date.date() > now.date():
            break
        
        print(f"\n📅 {current_date.strftime('%Y-%m-%d')}", end="")
        
        day_results = []
        for hour in range(0, 24, HOUR_STEP):
            if current_date.date() == now.date() and hour > now.hour:
                break
            
            levels = fetch_data_for_date(current_date, hour)
            
            if levels:
                timestamp = current_date.replace(hour=hour, minute=0, second=0)
                iso_time = timestamp.strftime('%Y-%m-%dT%H:%M')
                row = f"{iso_time},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}"
                results.append(row)
                day_results.append(f"R={levels['r']:,}")
            
            time.sleep(0.3)
        
        if day_results:
            print(f" -> {len(day_results)} points ({day_results[-1]})")
        else:
            print(" -> No data")
    
    # Write all results
    with open(OUTPUT_FILE, 'a') as f:
        for row in results:
            f.write(row + '\n')
    
    print(f"\n✅ Done! Saved {len(results)} data points to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()

