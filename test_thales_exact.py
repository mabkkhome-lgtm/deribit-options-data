#!/usr/bin/env python3
"""
Test script matching fetch_historical.py logic exactly
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
    """EXACT logic from fetch_historical.py"""
    if not longs or not shorts:
        return None
    
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # Find crossings (step=1 for exact match)
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
    
    # Weighted AVERAGE (not median)
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

# Fetch current Thales data
now = datetime.now(timezone.utc)
start = now - timedelta(hours=24)
from_ts = int(start.timestamp() * 1000)
to_ts = int(now.timestamp() * 1000)

url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
resp = requests.get(url, timeout=30)
lines = resp.text.strip().split('\n')

print("="*70)
print("THALES API TEST (fetch_historical.py exact logic)")
print("="*70)
print(f"Target: R=89,579 | S=85,875\n")

# Parse by expiry
expiries = defaultdict(lambda: {'longs': [], 'shorts': []})
expiry_trades = defaultdict(float)
epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

for line in lines:
    parts = line.split(',')
    if len(parts) >= 7:
        try:
            opt_type = int(parts[0])  # 0=call, 1=put
            expiry_code = int(parts[1])
            strike = float(parts[2])
            side = int(parts[4])  # 0=long (buyer), 1=short (seller)
            size = float(parts[5])
            premium = float(parts[6])
            
            exp_date = (epoch + timedelta(days=expiry_code)).strftime('%d%b%y').upper()
            
            pos = {
                'type': 'call' if opt_type == 0 else 'put',
                'strike': strike,
                'size': size,
                'premium': premium
            }
            
            if side == 0:
                expiries[exp_date]['longs'].append(pos)
            else:
                expiries[exp_date]['shorts'].append(pos)
                
            expiry_trades[exp_date] += size
        except:
            pass

# Test each expiry
print(f"Found {len(expiries)} expiries\n")

target_r, target_s = 89579, 85875
best_diff = 999999
best_exp = None

for exp in sorted(expiries.keys(), key=lambda x: expiry_trades[x], reverse=True)[:5]:  # Top 5 by volume
    longs = expiries[exp]['longs']
    shorts = expiries[exp]['shorts']
    
    if not longs or not shorts:
        continue
        
    result = find_levels(longs, shorts)
    if result:
        r, s, bg, sg = result['r'], result['s'], result['bg'], result['sg']
        diff_r = abs(r - target_r)
        diff_s = abs(s - target_s)
        total_diff = diff_r + diff_s
        
        print(f"{exp}: R={r:,} (Δ{diff_r:3d}) | S={s:,} (Δ{diff_s:3d}) | Volume={expiry_trades[exp]:.1f}")
        
        if total_diff < best_diff:
            best_diff = total_diff
            best_exp = exp
            best_result = result

print(f"\n✅ Best Match: {best_exp} (Total Diff: {best_diff})")
if best_diff < 300:
    print(f"   VERY CLOSE! R={best_result['r']}, S={best_result['s']}")
