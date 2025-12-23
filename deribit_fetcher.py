
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import os
import time

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"
OUTPUT_FILE = "data/btc_levels_minute.csv"

def get_underlying_price():
    try:
        url = 'https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd'
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return data['result']['index_price']
    except Exception as e:
        print(f"Error fetching underlying price: {e}")
        return 0

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
    
    # Step 10 for speed initially, then refine? Or just use step 100 like previous script
    # fetch_historical used step 1. That's slow for large range.
    # Let's use step 50.
    step = 50
    for price in range(price_min, price_max, step):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            # Linear interpolation
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - step) + t * step)
        prev_diff = diff
    
    if len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif len(crossings) == 1:
        s = r = round(crossings[0])
    else:
        s = round(min_strike)
        r = round(max_strike)
    
    # Gamma Calculation (Weighted Average as per fetch_historical.py)
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def main():
    print("=" * 60)
    print("Thales Options Data Fetcher (Live)")
    print("=" * 60)
    
    now = datetime.now(timezone.utc)
    # Fetch last 24 hours of data
    start = now - timedelta(hours=24)
    from_ts = int(start.timestamp() * 1000)
    to_ts = int(now.timestamp() * 1000)
    
    url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
    print(f"Fetching from {url}...")
    
    try:
        resp = requests.get(url, timeout=30)
        lines = resp.text.strip().split('\n')
        
        # Priority: Expiry 20446 (Dec 24) for now, but really we should auto-detect "Tomorrow"
        # 20446 is Dec 24. 
        # Logic: Find expiry closest to (Now + 1 day)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        today_code = (now - epoch).days
        target_code = today_code + 1 
        
        # Check if target_code exists in data
        expiry_counts = defaultdict(int)
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7:
                try:
                    expiry = int(parts[1])
                    size = float(parts[5])
                    expiry_counts[expiry] += size
                except: pass
        
        best_expiry = None
        if target_code in expiry_counts:
            best_expiry = target_code
            print(f"Targeting Tomorrow's Expiry: {best_expiry}")
        elif (target_code + 1) in expiry_counts:
            best_expiry = target_code + 1
            print(f"Targeting Day After Tomorrow: {best_expiry}")
        elif expiry_counts:
             # Fallback to volume
             valid_expiries = {k: v for k, v in expiry_counts.items() if k > today_code and k <= today_code + 7}
             if valid_expiries:
                 best_expiry = max(valid_expiries.items(), key=lambda x: x[1])[0]
                 print(f"Fallback to Volume Expiry: {best_expiry}")
        
        if best_expiry is None:
            print("No valid expiry found")
            return

        print(f"Using Expiry Code: {best_expiry}")
        
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
        
        levels = find_levels(longs, shorts)
        
        if levels:
            # Save to CSV
            timestamp = now.strftime('%Y-%m-%dT%H:%M')
            row = f"{timestamp},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}"
            
            # Create file if not exists
            if not os.path.exists(OUTPUT_FILE):
                with open(OUTPUT_FILE, 'w') as f:
                    f.write("datetime,R,S,BG,SG\n")
            
            # Append
            with open(OUTPUT_FILE, 'a') as f:
                f.write(row + '\n')
            
            print(f"\n✅ Saved: {row}")
            
            # Also print debug info
            btc_price = get_underlying_price()
            print(f"BTC Price: {btc_price}")
            print(f"Calculated: R={levels['r']}, S={levels['s']}, BG={levels['bg']}, SG={levels['sg']}")
        else:
            print("No levels calculated")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
