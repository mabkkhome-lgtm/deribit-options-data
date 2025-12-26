#!/usr/bin/env python3
"""
Fill missing days Dec 22-25 with correct data
"""
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import os

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        total += (intrinsic - p['premium'] if is_buyer else p['premium'] - intrinsic) * p['size']
    return total

def find_levels(longs, shorts):
    if not longs or not shorts:
        return None
    
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike, max_strike = min(all_strikes), max(all_strikes)
    price_min, price_max = int(min_strike * 0.90), int(max_strike * 1.10)
    
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, 50):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            for p in range(max(price_min, price - 50), min(price_max, price + 1)):
                buyer_pnl2 = calculate_pnl(longs, p, True)
                seller_pnl2 = calculate_pnl(shorts, p, False)
                diff2 = buyer_pnl2 - seller_pnl2
                if prev_diff * diff2 < 0:
                    t = abs(prev_diff) / (abs(prev_diff) + abs(diff2))
                    crossings.append((p - 1) + t)
                    break
        prev_diff = diff
    
    if len(crossings) >= 2:
        s, r = round(crossings[0]), round(crossings[-1])
    elif len(crossings) == 1:
        s = r = round(crossings[0])
    else:
        s, r = round(min_strike), round(max_strike)
    
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg: bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def fetch_for_date(target_date):
    """Fetch for a specific date"""
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Try different hours of the day
    results = []
    for hour in [4, 8, 12, 16, 20]:
        end = target_date.replace(hour=hour, minute=59, second=59, microsecond=0)
        
        from_ts = int(start.timestamp() * 1000)
        to_ts = int(end.timestamp() * 1000)
        
        url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
        
        try:
            resp = requests.get(url, timeout=30)
            if not resp.text.strip():
                continue
            
            lines = resp.text.strip().split('\n')
            
            expiry_counts = defaultdict(int)
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 7:
                    try:
                        expiry_counts[int(parts[1])] += float(parts[5])
                    except: pass
            
            if not expiry_counts:
                continue
            
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            current_code = (target_date - epoch).days
            
            valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}
            if not valid_expiries:
                valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code}
            if not valid_expiries:
                continue
            
            best_expiry = max(valid_expiries.items(), key=lambda x: x[1])[0]
            
            longs, shorts = [], []
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 7:
                    try:
                        if int(parts[1]) != best_expiry: continue
                        pos = {
                            'type': 'call' if int(parts[0]) == 0 else 'put',
                            'strike': float(parts[2]),
                            'size': float(parts[5]),
                            'premium': float(parts[6])
                        }
                        (longs if int(parts[4]) == 0 else shorts).append(pos)
                    except: pass
            
            result = find_levels(longs, shorts)
            if result:
                ts = end.strftime('%Y-%m-%dT%H:%M')
                results.append(f"{ts},{result['r']},{result['s']},{result['bg']},{result['sg']}")
                print(f"{ts}: R={result['r']}, S={result['s']}")
        except Exception as e:
            print(f"Error at {end}: {e}")
            continue
    
    return results

# Fill Dec 22, 23, 24, 25
print("Filling missing days...")

all_results = []

for day_offset in [4, 3, 2, 1, 0]:  # Dec 21, 22, 23, 24, 25
    target_date = datetime.now(timezone.utc) - timedelta(days=day_offset)
    print(f"\nProcessing {target_date.strftime('%Y-%m-%d')}...")
    results = fetch_for_date(target_date)
    all_results.extend(results)

# Read existing data
with open('data/btc_levels_minute.csv', 'r') as f:
    existing = f.read().strip().split('\n')

# Append new data
with open('data/btc_levels_minute.csv', 'w') as f:
    f.write(existing[0] + '\n')  # Header
    for line in existing[1:]:
        f.write(line + '\n')
    for line in all_results:
        f.write(line + '\n')

print(f"\n✅ Added {len(all_results)} new points")
