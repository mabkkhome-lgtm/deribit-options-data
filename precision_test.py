
import requests
from datetime import datetime, timezone

def get_deribit_oi():
    url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
    resp = requests.get(url, timeout=10)
    return resp.json()['result']

def get_underlying_price():
    url = 'https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd'
    resp = requests.get(url, timeout=10)
    return resp.json()['result']['index_price']

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        val = (intrinsic - p['premium']) if is_buyer else (p['premium'] - intrinsic)
        total += val * p['size']
    return total

def find_levels_with_step(positions, step_size):
    if not positions: return None
    
    all_strikes = [p['strike'] for p in positions]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, step_size):
        buyer_pnl = calculate_pnl(positions, price, True)
        seller_pnl = calculate_pnl(positions, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - step_size) + t * step_size)
        prev_diff = diff
    
    if not crossings: return None
    return round(crossings[-1]), round(crossings[0])

print("="*60)
print("PRECISION TEST - Testing different step sizes")
print("="*60)

btc_price = get_underlying_price()
print(f"BTC Index Price: ${btc_price:,.2f}")

# Get Deribit Data
data = get_deribit_oi()
positions = []

for item in data:
    inst = item['instrument_name']
    parts = inst.split('-')
    if len(parts) >= 3 and parts[1] == '24DEC25':
        positions.append({
            'strike': float(parts[2]),
            'type': 'call' if parts[3] == 'C' else 'put',
            'size': item['open_interest'],
            'premium': item['mark_price'] * btc_price
        })

print(f"\nPositions loaded: {len(positions)}")
print("\nTesting different step sizes:")
print("-" * 60)

target_r = 89579
target_s = 85875

for step in [50, 20, 10, 5, 1]:
    result = find_levels_with_step(positions, step)
    if result:
        r, s = result
        diff_r = abs(r - target_r)
        diff_s = abs(s - target_s)
        print(f"Step={step:2d}: R={r:,} (Δ{diff_r:3d}) | S={s:,} (Δ{diff_s:3d}) | Total Δ={diff_r+diff_s}")
