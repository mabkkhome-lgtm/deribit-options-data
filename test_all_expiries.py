#!/usr/bin/env python3
"""
Test ALL expiries to find which matches user's values
Target: R=90,255, S=85,997
"""
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

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
    
    return {'r': r, 's': s}

# Fetch current data
now = datetime.now(timezone.utc)
start = now.replace(hour=0, minute=0, second=0, microsecond=0)

from_ts = int(start.timestamp() * 1000)
to_ts = int(now.timestamp() * 1000)

url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
resp = requests.get(url, timeout=30)
lines = resp.text.strip().split('\n')

print(f"Testing all expiries against target: R=90,255, S=85,997")
print("=" * 70)

# Group by expiry
expiries_data = defaultdict(lambda: {'longs': [], 'shorts': []})
expiry_counts = defaultdict(int)
epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

for line in lines:
    parts = line.split(',')
    if len(parts) >= 7:
        try:
            expiry_code = int(parts[1])
            size = float(parts[5])
            expiry_counts[expiry_code] += size
            
            pos = {
                'type': 'call' if int(parts[0]) == 0 else 'put',
                'strike': float(parts[2]),
                'size': size,
                'premium': float(parts[6])
            }
            
            if int(parts[4]) == 0:
                expiries_data[expiry_code]['longs'].append(pos)
            else:
                expiries_data[expiry_code]['shorts'].append(pos)
        except: pass

target_r, target_s = 90255, 85997
best_diff = 999999
best_expiry = None

for code in sorted(expiry_counts.keys()):
    exp_date = epoch + timedelta(days=code)
    longs = expiries_data[code]['longs']
    shorts = expiries_data[code]['shorts']
    
    if not longs or not shorts:
        continue
    
    result = find_levels(longs, shorts)
    if result:
        diff_r = abs(result['r'] - target_r)
        diff_s = abs(result['s'] - target_s)
        total_diff = diff_r + diff_s
        
        print(f"{exp_date.strftime('%d%b%y')}: R={result['r']:,} (Δ{diff_r:4d})  S={result['s']:,} (Δ{diff_s:4d})  Total Δ={total_diff:5d}")
        
        if total_diff < best_diff:
            best_diff = total_diff
            best_expiry = exp_date.strftime('%d%b%y')

print("\n" + "=" * 70)
print(f"✅ CLOSEST MATCH: {best_expiry} (Total difference: {best_diff})")
