#!/usr/bin/env python3
"""
Calculate current levels using EXACT fetch_historical.py logic
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
    """EXACT copy from fetch_historical.py lines 28-71"""
    if not longs or not shorts:
        return None
    
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # First pass with larger step for speed
    crossings_rough = []
    prev_diff = None
    
    for price in range(price_min, price_max, 100):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            # Found a crossing, refine it
            for p in range(price - 100, price, 1):
                buyer_pnl2 = calculate_pnl(longs, p, True)
                seller_pnl2 = calculate_pnl(shorts, p, False)
                diff2 = buyer_pnl2 - seller_pnl2
                
                if prev_diff * diff2 < 0:
                    t = abs(prev_diff) / (abs(prev_diff) + abs(diff2))
                    crossings_rough.append((p - 1) + t)
                    break
                prev_diff = diff2
        prev_diff = diff
    
    crossings = crossings_rough

    
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

# Fetch with EXACT window logic from fetch_historical.py
now = datetime.now(timezone.utc)
date = now
hour = now.hour

start = date.replace(hour=0, minute=0, second=0, microsecond=0)
end = date.replace(hour=hour, minute=59, second=59, microsecond=0)

from_ts = int(start.timestamp() * 1000)
to_ts = int(end.timestamp() * 1000)

url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"

print(f"Fetching from {start} to {end}")
print(f"URL: {url[:80]}...")

resp = requests.get(url, timeout=30)
lines = resp.text.strip().split('\n')

print(f"Received {len(lines)} lines\n")

# Count trades per expiry (EXACT logic from fetch_historical.py lines 90-100)
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
    print("No data!")
    exit(1)

# Use expiry with most volume within 7 days (lines 105-120)
epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
current_code = (date - epoch).days

valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}

if not valid_expiries:
    valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code}

if not valid_expiries:
    print("No valid expiries!")
    exit(1)

best_expiry = max(valid_expiries.items(), key=lambda x: x[1])[0]
best_exp_date = epoch + timedelta(days=best_expiry)

print(f"Selected expiry: {best_exp_date.strftime('%d%b%y')} (code {best_expiry})")
print(f"Volume: {valid_expiries[best_expiry]:.1f}")
print()

# Parse positions for this expiry (lines 122-148)
longs = []
shorts = []

for line in lines:
    parts = line.split(',')
    if len(parts) >= 7:
        try:
            option_type = int(parts[0])
            expiry_code = int(parts[1])
            strike = float(parts[2])
            side = int(parts[4])
            size = float(parts[5])
            premium = float(parts[6])
            
            if expiry_code != best_expiry:
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
            pass

print(f"Longs: {len(longs)}")
print(f"Shorts: {len(shorts)}")
print()

result = find_levels(longs, shorts)

if result:
    print("="*50)
    print(f"R = {result['r']:,}")
    print(f"S = {result['s']:,}")
    print(f"BG = {result['bg']:,}")
    print(f"SG = {result['sg']:,}")
    print("="*50)
else:
    print("Failed to calculate levels!")
