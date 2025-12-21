#!/usr/bin/env python3
"""
Direct Deribit Options Data Fetcher
Fetches options trades directly from Deribit API and calculates R, S, BG, SG levels.
No middleman - pure source data.
"""

import requests
from datetime import datetime, timezone, timedelta
import json
import os

# Configuration
DERIBIT_API = "https://www.deribit.com/api/v2"
OUTPUT_FILE = "data/btc_levels_hourly.csv"

def parse_instrument(name):
    """Parse instrument name like 'BTC-22DEC25-90000-C'"""
    parts = name.split('-')
    if len(parts) >= 4:
        return {
            'expiry': parts[1],
            'strike': int(parts[2]),
            'type': 'call' if parts[3] == 'C' else 'put'
        }
    return None

def get_tomorrow_expiry():
    """Get tomorrow's expiry date code (e.g., '22DEC25')"""
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.strftime('%d%b%y').upper()

def get_today_expiry():
    """Get today's expiry date code"""
    today = datetime.now(timezone.utc)
    return today.strftime('%d%b%y').upper()

def fetch_trades(hours_back=24):
    """Fetch BTC option trades from the last N hours"""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours_back)
    
    start_ts = int(start.timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)
    
    all_trades = []
    count = 1000  # Max per request
    
    print(f"Fetching trades from {start.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')}")
    
    # Deribit returns trades in batches, need to paginate
    while True:
        url = f"{DERIBIT_API}/public/get_last_trades_by_currency_and_time"
        params = {
            'currency': 'BTC',
            'kind': 'option',
            'start_timestamp': start_ts,
            'end_timestamp': end_ts,
            'count': count
        }
        
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        
        if 'result' not in data or 'trades' not in data['result']:
            break
        
        trades = data['result']['trades']
        if not trades:
            break
        
        all_trades.extend(trades)
        
        # Check if there are more
        has_more = data['result'].get('has_more', False)
        if not has_more or len(trades) < count:
            break
        
        # Update end_ts to get older trades
        end_ts = min(t['timestamp'] for t in trades) - 1
    
    print(f"Fetched {len(all_trades)} trades")
    return all_trades

def filter_trades_by_expiry(trades, target_expiry):
    """Filter trades to only include a specific expiry"""
    filtered = []
    for t in trades:
        parsed = parse_instrument(t['instrument_name'])
        if parsed and parsed['expiry'] == target_expiry:
            filtered.append({
                **t,
                **parsed
            })
    return filtered

def calculate_pnl(positions, underlying, is_buyer):
    """Calculate PnL at a given underlying price"""
    total = 0
    for p in positions:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        premium_usd = p['premium'] * p.get('index_price', underlying)  # Convert BTC premium to USD
        total += (intrinsic - premium_usd if is_buyer else premium_usd - intrinsic) * p['size']
    return total

def find_levels(longs, shorts, underlying_price):
    """Calculate R, S, BG, SG using PnL crossing method"""
    if not longs or not shorts:
        print("  Warning: No longs or shorts found")
        return None
    
    # Get strike range based on positions
    all_strikes = [p['strike'] for p in longs] + [p['strike'] for p in shorts]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    
    # Expand range around current price
    price_min = int(min(min_strike, underlying_price * 0.85))
    price_max = int(max(max_strike, underlying_price * 1.15))
    
    # Find where buyer PnL = seller PnL
    crossings = []
    prev_diff = None
    
    for price in range(price_min, price_max, 100):  # Use 100 step for speed
        buyer_pnl = calculate_pnl(longs, price, True)
        seller_pnl = calculate_pnl(shorts, price, False)
        diff = buyer_pnl - seller_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            t = abs(prev_diff) / (abs(prev_diff) + abs(diff))
            crossings.append((price - 100) + t * 100)
        prev_diff = diff
    
    # S = left crossing, R = right crossing
    if len(crossings) >= 2:
        s = round(crossings[0])
        r = round(crossings[-1])
    elif len(crossings) == 1:
        # Only one crossing - use underlying as reference
        crossing = round(crossings[0])
        if crossing < underlying_price:
            s = crossing
            r = int(underlying_price * 1.05)
        else:
            r = crossing
            s = int(underlying_price * 0.95)
    else:
        # No crossings - use weighted OI
        s = int(underlying_price * 0.95)
        r = int(underlying_price * 1.05)
    
    # BG = weighted average of buyer strikes by size
    total_buyer = sum(p['size'] for p in longs)
    bg = round(sum(p['strike'] * p['size'] for p in longs) / total_buyer) if total_buyer > 0 else (r + s) // 2
    
    # SG = weighted average of seller strikes by size
    total_seller = sum(p['size'] for p in shorts)
    sg = round(sum(p['strike'] * p['size'] for p in shorts) / total_seller) if total_seller > 0 else (r + s) // 2
    
    # Ensure proper ordering
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def process_trades(trades):
    """Process trades into longs (buyers) and shorts (sellers)"""
    longs = []  # Buyers
    shorts = []  # Sellers
    
    for t in trades:
        pos = {
            'strike': t['strike'],
            'type': t['type'],
            'size': t['amount'],
            'premium': t['price'],  # In BTC
            'index_price': t.get('index_price', 88000)
        }
        
        if t['direction'] == 'buy':
            longs.append(pos)
        else:
            shorts.append(pos)
    
    return longs, shorts

def get_underlying_price():
    """Get current BTC price from Deribit"""
    url = f"{DERIBIT_API}/public/get_index_price"
    params = {'index_name': 'btc_usd'}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    return data.get('result', {}).get('index_price', 88000)

def main():
    print("=" * 60)
    print("Direct Deribit Options Data Fetcher")
    print("=" * 60)
    
    # Get current price
    underlying = get_underlying_price()
    print(f"\nCurrent BTC: ${underlying:,.2f}")
    
    # Get tomorrow's expiry
    target_expiry = get_tomorrow_expiry()
    print(f"Target expiry: {target_expiry}")
    
    # Fetch trades
    all_trades = fetch_trades(hours_back=24)
    
    if not all_trades:
        print("No trades found!")
        return
    
    # Filter to target expiry
    expiry_trades = filter_trades_by_expiry(all_trades, target_expiry)
    print(f"Trades for {target_expiry}: {len(expiry_trades)}")
    
    if not expiry_trades:
        # Try today's expiry as fallback
        target_expiry = get_today_expiry()
        print(f"Trying today's expiry: {target_expiry}")
        expiry_trades = filter_trades_by_expiry(all_trades, target_expiry)
        print(f"Trades for {target_expiry}: {len(expiry_trades)}")
    
    if not expiry_trades:
        # Find expiry with most trades
        expiry_counts = {}
        for t in all_trades:
            parsed = parse_instrument(t['instrument_name'])
            if parsed:
                expiry_counts[parsed['expiry']] = expiry_counts.get(parsed['expiry'], 0) + 1
        
        if expiry_counts:
            target_expiry = max(expiry_counts.items(), key=lambda x: x[1])[0]
            print(f"Using most traded expiry: {target_expiry}")
            expiry_trades = filter_trades_by_expiry(all_trades, target_expiry)
            print(f"Trades for {target_expiry}: {len(expiry_trades)}")
    
    # Process into longs and shorts
    longs, shorts = process_trades(expiry_trades)
    print(f"Longs (buyers): {len(longs)}, Shorts (sellers): {len(shorts)}")
    
    # Calculate levels
    levels = find_levels(longs, shorts, underlying)
    
    if levels:
        print(f"\n📊 LEVELS (from Deribit):")
        print(f"   R (Resistance): ${levels['r']:,}")
        print(f"   S (Support):    ${levels['s']:,}")
        print(f"   BG (Buyer Gamma): ${levels['bg']:,}")
        print(f"   SG (Seller Gamma): ${levels['sg']:,}")
        
        # Save to CSV
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        
        now = datetime.now(timezone.utc)
        iso_time = now.strftime('%Y-%m-%dT%H:%M')
        
        # Check if file exists and has header
        write_header = not os.path.exists(OUTPUT_FILE) or os.path.getsize(OUTPUT_FILE) == 0
        
        with open(OUTPUT_FILE, 'a') as f:
            if write_header:
                f.write("datetime,R,S,BG,SG\n")
            f.write(f"{iso_time},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}\n")
        
        print(f"\n✅ Saved to {OUTPUT_FILE}")
    else:
        print("\n❌ Could not calculate levels")

if __name__ == "__main__":
    main()
