
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import time

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"

def get_deribit_oi():
    print("Fetching Deribit OI...")
    try:
        url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
        resp = requests.get(url, timeout=10)
        data = resp.json()['result']
        return data
    except Exception as e:
        print(f"Deribit Error: {e}")
        return []

def get_thales_data(source_id=1):
    print(f"Fetching Thales Data (Source {source_id})...")
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    from_ts = int(start.timestamp() * 1000)
    to_ts = int(now.timestamp() * 1000)
    url = f"{THALES_API}?source={source_id}&fromDate={from_ts}&toDate={to_ts}"
    try:
        resp = requests.get(url, timeout=10)
        return resp.text.strip().split('\n')
    except Exception as e:
        print(f"Thales Error: {e}")
        return []

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        total += (intrinsic - p['premium'] if is_buyer else p['premium'] - intrinsic) * p['size']
    return total

def find_levels(longs, shorts):
    if not longs or not shorts: return None
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    if not all_strikes: return None
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # Use step 10 for decent precision
    step = 10
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
    s = round(crossings[0])
    r = round(crossings[-1])
    return r, s

def parse_deribit(data):
    # Group by expiry
    expiries = defaultdict(list)
    for item in data:
        inst = item['instrument_name']
        parts = inst.split('-')
        if len(parts) >= 3:
            expiry_str = parts[1]
            strike = float(parts[2])
            type_ = 'call' if parts[3] == 'C' else 'put'
            size = item['open_interest']
            mark_price = item['mark_price']
            
            if size > 0:
                pos = {'strike': strike, 'type': type_, 'size': size, 'premium': mark_price * 90000} # Approx price
                expiries[expiry_str].append(pos)
    return expiries

def parse_thales(lines):
    expiries = defaultdict(lambda: {'longs': [], 'shorts': []})
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    
    for line in lines:
        parts = line.split(',')
        if len(parts) >= 7:
            try:
                code = int(parts[1])
                exp_date = (epoch + timedelta(days=code)).strftime('%d%b%y').upper()
                pos = {
                    'type': 'call' if int(parts[0]) == 0 else 'put',
                    'strike': float(parts[2]),
                    'size': float(parts[5]),
                    'premium': float(parts[6])
                }
                if int(parts[4]) == 0: expiries[exp_date]['longs'].append(pos)
                else: expiries[exp_date]['shorts'].append(pos)
            except: continue
    return expiries

def main():
    target_r = 89579
    target_s = 85875
    print(f"TARGET FROM USER (CURRENT REAL): R={target_r}, S={target_s}")
    print(f"Dashboard shows: R=89824, S=86159")
    print(f"Difference: R_diff={89824-target_r}, S_diff={86159-target_s}")
    print("="*60)
    
    
    # 1. Test Deribit OI
    deribit_data = get_deribit_oi()
    deribit_exps = parse_deribit(deribit_data)
    
    print("\n--- DERIBIT OI CHECK ---")
    best_diff = 999999
    best_source = None
    best_exp = None
    
    for exp, positions in deribit_exps.items():
        res = find_levels(positions, positions) # Longs=Shorts for OI
        if res:
            r, s = res
            diff_r = abs(r - target_r)
            diff_s = abs(s - target_s)
            print(f"Deribit {exp}: R={r}, S={s} (Diff: R={diff_r}, S={diff_s})")
            if diff_r + diff_s < best_diff:
                best_diff = diff_r + diff_s
                best_source = "Deribit"
                best_exp = exp
    
    # 2. Test Thales Data Sources
    print("\n--- THALES DATA VARIATIONS ---")
    for source in [0, 1, 2, 3, 4]:
        lines = get_thales_data(source)
        if not lines: continue
        
        parsed = parse_thales(lines)
        if not parsed:
            print(f"Source {source}: No parseable data")
            continue
            
        for exp, data in parsed.items():
            longs = data['longs']
            shorts = data['shorts']
            
            res = find_levels(longs, shorts)
            if res:
                r, s = res
                diff_r = abs(r - target_r)
                diff_s = abs(s - target_s)
                print(f"Thales Src={source} Exp={exp}: R={r}, S={s} (Diff: R={diff_r}, S={diff_s})")
                if diff_r + diff_s < best_diff:
                    best_diff = diff_r + diff_s
                    best_source = f"Thales Src={source}"
                    best_exp = exp
    
    print(f"\n✅ BEST MATCH: {best_source} {best_exp} (Total Diff: {best_diff})")

if __name__ == "__main__":
    main()
