
import requests
from datetime import datetime, timezone, timedelta
import time
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
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    crossings = []
    prev_diff = None
    
    # Speed up by stepping 100 first, then refining? 
    # fetch_historical.py uses step 1. Let's use 10 for speed in test.
    for price in range(price_min, price_max, 10):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - 10) + t * 10)
        prev_diff = diff
    
    if len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif len(crossings) == 1:
        s = r = round(crossings[0])
    else:
        return None
    
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def fetch_data():
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24) # Last 24h
    
    from_ts = int(start.timestamp() * 1000)
    to_ts = int(now.timestamp() * 1000)
    
    url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
    print(f"Fetching from {url}...")
    
    try:
        resp = requests.get(url, timeout=30)
        lines = resp.text.strip().split('\n')
        
        # Auto-detect best expiry
        expiry_counts = defaultdict(int)
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7:
                try:
                    expiry = int(parts[1])
                    size = float(parts[5])
                    expiry_counts[expiry] += size
                except: pass
                
        if not expiry_counts:
            print("No data found")
            return

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        current_code = (now - epoch).days
        valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}
        if not valid_expiries: 
            valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code}
            
        best_expiry = max(valid_expiries.items(), key=lambda x: x[1])[0]
        print(f"Best Expiry Code: {best_expiry}")
        
        longs = []
        shorts = []
        
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
                    
                    if int(parts[4]) == 0: longs.append(pos)
                    else: shorts.append(pos)
                except: continue
                
        print(f"Processed {len(longs)} longs, {len(shorts)} shorts")
        levels = find_levels(longs, shorts)
        print("Calculated Levels (Thales Source):", levels)
        
    except Exception as e:
        print(e)

if __name__ == "__main__":
    fetch_data()
