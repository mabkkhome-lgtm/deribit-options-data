#!/usr/bin/env python3
"""
PRODUCTION Fetcher - Uses EXACT fetch_historical.py logic
"""
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import os

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"
OUTPUT_FILE = "data/btc_levels_minute.csv"

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
    
    # Optimized: coarse scan then refine
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

def main():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=now.hour, minute=59, second=59, microsecond=0)
    
    from_ts, to_ts = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
    
    try:
        resp = requests.get(url, timeout=30)
        if not resp.text.strip(): return
        
        lines = resp.text.strip().split('\n')
        
        expiry_counts = defaultdict(int)
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7:
                try:
                    expiry_counts[int(parts[1])] += float(parts[5])
                except: pass
        
        if not expiry_counts: return
        
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        current_code = (now - epoch).days
        
        valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}
        if not valid_expiries:
            valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code}
        if not valid_expiries: return
        
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
        if not result: return
        
        timestamp = now.strftime('%Y-%m-%dT%H:%M')
        row = f"{timestamp},{result['r']},{result['s']},{result['bg']},{result['sg']}"
        
        if not os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, 'w') as f:
                f.write("datetime,R,S,BG,SG\n")
        
        with open(OUTPUT_FILE, 'a') as f:
            f.write(row + '\n')
        
        print(f"✅ R={result['r']}, S={result['s']}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
