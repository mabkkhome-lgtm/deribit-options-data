
import requests
from datetime import datetime, timezone, timedelta
import os

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"
OUTPUT_FILE = "data/btc_levels_minute.csv"

# Current "Correct" Deribit Levels (Hardcoded or fetched?)
# Ideally fetch fresh, but let's use the last known good ones or fetch fresh.
# Let's fetch fresh Deribit levels inside the script to ensure alignment.

def get_deribit_levels():
    # We must implement the exact logic from deribit_fetcher.py here to get the Target
    # For brevity, I will import/copy the logic or run the script?
    # Better to run the actual logic.
    from deribit_fetcher import main as fetch_deribit
    # But main() writes to CSV. We want the return value.
    # deribit_fetcher.py main() doesn't return.
    # I will modify deribit_fetcher.py to be importable or just reuse code.
    pass

# Copying core logic for self-containment
def get_deribit_oi():
    try:
        url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
        resp = requests.get(url, timeout=10)
        return resp.json()['result']
    except: return []

def get_underlying_price():
    try:
        url = 'https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd'
        resp = requests.get(url, timeout=10)
        return resp.json()['result']['index_price']
    except: return 88000

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        premium_usd = p['premium']
        val = (intrinsic - premium_usd) if is_buyer else (premium_usd - intrinsic)
        total += val * p['size']
    return total

def find_levels(positions):
    if not positions: return None
    longs = positions; shorts = positions
    all_strikes = [p['strike'] for p in longs]
    min_strike = min(all_strikes); max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90); price_max = int(max_strike * 1.10)
    step = 50 # Faster for backfill
    crossings = []
    prev_diff = None
    for price in range(price_min, price_max, step):
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - step) + t * step)
        prev_diff = diff
    if not crossings: return None
    s = round(crossings[0]); r = round(crossings[-1])
    calls = sorted([p for p in positions if p['type']=='call'], key=lambda x:x['strike'])
    total_calls = sum(p['size'] for p in calls)
    bg = (r+s)//2
    if total_calls>0:
        cs=0
        for p in calls: 
            cs+=p['size']
            if cs>=total_calls/2: bg=p['strike']; break
    puts = sorted([p for p in positions if p['type']=='put'], key=lambda x:x['strike'])
    total_puts = sum(p['size'] for p in puts)
    sg = (r+s)//2
    if total_puts>0:
        cs=0
        for p in puts: 
            cs+=p['size']
            if cs>=total_puts/2: sg=p['strike']; break
    if bg < sg: bg, sg = sg, bg
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def get_current_deribit_target():
    print("Fetching Target Deribit Levels...")
    btc_price = get_underlying_price()
    data = get_deribit_oi()
    if not data: return None
    
    # Expiry 24DEC25
    target_exp = "24DEC25"
    cleaned = []
    for item in data:
        inst = item['instrument_name']
        parts = inst.split('-')
        if len(parts)>=3 and parts[1] == target_exp:
            cleaned.append({
                'strike': float(parts[2]),
                'type': 'call' if parts[3] == 'C' else 'put',
                'size': item['open_interest'],
                'premium': item['mark_price'] * btc_price
            })
    return find_levels(cleaned)

def parse_thales_line(line, target_expiry_code=20446):
    parts = line.split(',')
    if len(parts) >= 7 and int(parts[1]) == target_expiry_code:
        try:
             return {
                'type': 'call' if int(parts[0]) == 0 else 'put',
                'strike': float(parts[2]),
                'size': float(parts[5]),
                'premium': float(parts[6])
            }
        except: pass
    return None

def fetch_thales_history(target_deribit):
    print("Fetching Thales History...")
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    from_ts = int(start.timestamp() * 1000)
    to_ts = int(now.timestamp() * 1000)
    url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
    resp = requests.get(url)
    lines = resp.text.strip().split('\n')
    
    # Reconstruct history using sliding window?
    # Or just calculate ONE Thales level for the whole period to find offset?
    # Thales trades accumulate. The "History" of levels changes as trades happen.
    # To get proper curve, we need sliding window.
    
    # 1. Calculate Current Thales Level (using all data)
    lines_all = [parse_thales_line(l) for l in lines]
    lines_all = [l for l in lines_all if l]
    
    # Thales API returns TRADES.
    # To mimic OI, we just sum them up?
    # fetch_historical.py logic: Accumulates trades.
    # So "Current" Thales Level = All trades in window.
    
    thales_current = find_levels(lines_all) # Using same finds_level logic (treats list as positions)
    # Note: Thales 'find_levels' was slightly different (Longs vs Shorts lists), 
    # but here I treat them same as Deribit for consistency of curve behavior.
    
    if not thales_current: 
        print("No Thales data")
        return []
        
    print(f"Thales Current: {thales_current}")
    print(f"Deribit Target: {target_deribit}")
    
    offsets = {
        'r': target_deribit['r'] - thales_current['r'],
        's': target_deribit['s'] - thales_current['s'],
        'bg': target_deribit['bg'] - thales_current['bg'],
        'sg': target_deribit['sg'] - thales_current['sg']
    }
    print(f"Offsets: {offsets}")
    
    # 2. Generate History (Sliding Window of accumulated trades?)
    # No, usually "History" means "What was the level at time T?"
    # At time T, the level was calculated based on (Window ending at T).
    # Since we only have last 24h trades, we can simulate "Growth" of open interest?
    # Or just assume the "Trades" represent the full book at that time?
    # No, "FetchOptions" returns TRADES.
    
    # Alternative:
    # Generative Curve.
    # Use Thales 15min interval slices to generate *variations*.
    # Slice the 24h into 96 buckets.
    # For each bucket, calculate level based on Cumulative Trades up to that point?
    # Yes.
    
    results = []
    bucket_size = timedelta(minutes=15)
    current_time = start
    cumulative_positions = []
    
    # Parse all lines with timestamps?
    # Thales csv doesn't have timestamps per line easily parseable?
    # Wait, fetch_historical.py uses `parts` but I don't see timestamp in typical lines?
    # Ah, Thales API results are just CSV: type, expiry, strike, ?, side, size, premium...
    # Where is the timestamp?
    # Thales API might strictly filter by time window.
    
    # If I can't split by time within the result, I can't regenerate history accurately.
    # I have to FETCH multiple times for sliding window.
    pass

def main():
    target = get_current_deribit_target()
    if not target:
        print("Failed to get target")
        return

    # To backfill, we will run fetches for 15 min intervals
    # This takes time (96 requests).
    # Faster: 1 step per hour (24 requests).
    
    results = []
    now = datetime.now(timezone.utc)
    
    # First, calculate "Base" thales level for current time (to find offset)
    # fetch 24h data
    latest_thales_lines = requests.get(f"{THALES_API}?source=1&fromDate={int((now-timedelta(hours=24)).timestamp()*1000)}&toDate={int(now.timestamp()*1000)}").text.split('\n')
    latest_pos = [l for l in [parse_thales_line(x) for x in latest_thales_lines] if l]
    thales_now = find_levels(latest_pos)
    
    if not thales_now:
        print("No Thales base")
        return
        
    offsets = {k: target[k] - thales_now[k] for k in target}
    print(f"Calibrated Offsets: {offsets}")
    
    # Now loop backwards for 48 hours at 15 min intervals
    # Total points: 48 * 4 = 192 points
    
    intervals = 48 * 4
    
    for i in range(intervals):
        t_end = now - timedelta(minutes=15*i)
        t_start = t_end - timedelta(hours=24) # Floating window of 24h
        
        url = f"{THALES_API}?source=1&fromDate={int(t_start.timestamp()*1000)}&toDate={int(t_end.timestamp()*1000)}"
        try:
            lines = requests.get(url, timeout=5).text.split('\n')
            pos = [l for l in [parse_thales_line(x) for x in lines] if l]
            lvl = find_levels(pos)
            
            if lvl:
                # Apply Offset
                adj_r = int(lvl['r'] + offsets['r'])
                adj_s = int(lvl['s'] + offsets['s'])
                adj_bg = int(lvl['bg'] + offsets['bg'])
                adj_sg = int(lvl['sg'] + offsets['sg'])
                
                ts_str = t_end.strftime('%Y-%m-%dT%H:%M')
                results.append(f"{ts_str},{adj_r},{adj_s},{adj_bg},{adj_sg}")
                print(f"Generated {ts_str} | R:{adj_r} S:{adj_s}")
            else:
                print(f"No levels for {t_end}")
        except Exception as e: 
            print(f"Error {e}")
            pass
        
    results.reverse()
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write("datetime,R,S,BG,SG\n")
        for r in results:
            f.write(r + '\n')
            
    # Finally append the REAL current target as the last point
    ts_now = now.strftime('%Y-%m-%dT%H:%M')
    with open(OUTPUT_FILE, 'a') as f:
        # Round the target values too just in case
        f.write(f"{ts_now},{int(target['r'])},{int(target['s'])},{int(target['bg'])},{int(target['sg'])}\n")
    print(f"✅ Final Point (Real): {ts_now} | R:{int(target['r'])} S:{int(target['s'])}")


if __name__ == "__main__":
    main()
