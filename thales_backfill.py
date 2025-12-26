
import requests
from datetime import datetime, timezone, timedelta
import time
from collections import defaultdict

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
    if not all_strikes: return None
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    crossings = []
    prev_diff = None
    step = 50
    
    for price in range(price_min, price_max, step):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - step) + t * step)
        prev_diff = diff
    
    if hasattr(crossings, '__len__') and len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif hasattr(crossings, '__len__') and len(crossings) == 1:
        s = r = round(crossings[0])
    else:
        s = round(min_strike)
        r = round(max_strike)
    
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    if bg < sg: bg, sg = sg, bg
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def fetch_period(start_ts, end_ts):
    url = f"{THALES_API}?source=1&fromDate={start_ts}&toDate={end_ts}"
    try:
        resp = requests.get(url, timeout=10)
        lines = resp.text.strip().split('\n')
        
        # Priority: Expiry 20446 (Dec 24)
        target_expiry = 20446 
        
        longs = []
        shorts = []
        
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 7 and int(parts[1]) == target_expiry:
                try:
                    pos = {
                        'type': 'call' if int(parts[0]) == 0 else 'put',
                        'strike': float(parts[2]),
                        'size': float(parts[5]),
                        'premium': float(parts[6])
                    }
                    if int(parts[4]) == 0: longs.append(pos)
                    else: shorts.append(pos)
                except: continue
        
        if not longs: return None
        return find_levels(longs, shorts)
    except:
        return None

def main():
    print("Starting Backfill...")
    results = []
    
    # Generate 5-minute intervals for last 24 hours
    now = datetime.now(timezone.utc)
    now = now.replace(second=0, microsecond=0)
    start_time = now - timedelta(hours=24)
    
    current = start_time
    while current <= now:
        # Window: [Current-24h, Current] ?? 
        # No, 'Live' indicator usually looks at "Trailing 24h" or "Since Midnight".
        # Let's assume Trailing 24h window for each data point
        
        window_end = current
        window_start = window_end - timedelta(hours=24)
        
        from_ts = int(window_start.timestamp() * 1000)
        to_ts = int(window_end.timestamp() * 1000)
        
        levels = fetch_period(from_ts, to_ts)
        
        if levels:
            iso = current.strftime('%Y-%m-%dT%H:%M')
            row = f"{iso},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}"
            results.append(row)
            print(f"{iso}: R={levels['r']} S={levels['s']}")
        
        current += timedelta(minutes=15) # Step 15 mins to save time
        time.sleep(0.1)

    with open(OUTPUT_FILE, 'w') as f:
        f.write("datetime,R,S,BG,SG\n")
        for row in results:
            f.write(row + '\n')
            
    print(f"✅ Backfilled {len(results)} points")

if __name__ == "__main__":
    main()
