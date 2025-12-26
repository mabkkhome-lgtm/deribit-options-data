
import requests

def get_deribit_oi():
    url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
    resp = requests.get(url, timeout=10)
    return resp.json()['result']

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        val = (intrinsic - p['premium']) if is_buyer else (p['premium'] - intrinsic)
        total += val * p['size']
    return total

def find_levels(positions):
    if not positions: return None
    
    all_strikes = [p['strike'] for p in positions]
    min_strike, max_strike = min(all_strikes), max(all_strikes)
    price_min, price_max = int(min_strike * 0.90), int(max_strike * 1.10)
    
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, 1):  # step=1 for max precision
        buyer_pnl = calculate_pnl(positions, price, True)
        seller_pnl = calculate_pnl(positions, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - 1) + t)
        prev_diff = diff
    
    if not crossings: return None
    return round(crossings[-1]), round(crossings[0])

print("="*70)
print("BTC PRICE SENSITIVITY TEST")
print("="*70)
print(f"Target: R=89,579 | S=85,875\n")

# Get Deribit raw data
data = get_deribit_oi()
raw_positions = []

for item in data:
    inst = item['instrument_name']
    parts = inst.split('-')
    if len(parts) >= 3 and parts[1] == '24DEC25':
        raw_positions.append({
            'strike': float(parts[2]),
            'type': 'call' if parts[3] == 'C' else 'put',
            'size': item['open_interest'],
            'mark_btc': item['mark_price']  # In BTC
        })

print(f"Loaded {len(raw_positions)} positions for 24DEC25\n")
print("Testing different BTC prices for premium conversion:")
print("-"*70)

target_r, target_s = 89579, 85875
best_diff = 999999
best_price = None

# Test range of BTC prices
for btc_price in range(86000, 92000, 100):
    positions = [{
        'strike': p['strike'],
        'type': p['type'],
        'size': p['size'],
        'premium': p['mark_btc'] * btc_price
    } for p in raw_positions]
    
    result = find_levels(positions)
    if result:
        r, s = result
        diff_r = abs(r - target_r)
        diff_s = abs(s - target_s)
        total_diff = diff_r + diff_s
        
        if total_diff < best_diff:
            best_diff = total_diff
            best_price = btc_price
            if total_diff < 50:  # Print if very close
                print(f"BTC=${btc_price:,}: R={r:,} (Δ{diff_r:3d}) | S={s:,} (Δ{diff_s:3d}) | Total Δ={total_diff}")

print(f"\n✅ Best Match: BTC=${best_price:,} (Total Diff: {best_diff})")
