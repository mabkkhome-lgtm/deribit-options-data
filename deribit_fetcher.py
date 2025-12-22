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
OUTPUT_FILE = "data/btc_levels_minute.csv"

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
    
    # Require at least 2 crossings for valid levels
    if len(crossings) < 2:
        print("  Warning: Less than 2 crossings found, skipping")
        return None
    
    # S = left crossing, R = right crossing
    s = round(crossings[0])
    r = round(crossings[-1])
    
    # Sanity check - S must be below R
    if s >= r:
        print(f"  Warning: Invalid S >= R ({s} >= {r}), skipping")
        return None
    
    # BG = weighted median of BUYER strikes near the money (ATM ±5%)
    atm_longs = [p for p in longs if underlying_price * 0.95 <= p['strike'] <= underlying_price * 1.05]
    if not atm_longs:
        atm_longs = longs  # Fallback to all if no ATM
    
    # Sort by strike and find weighted median
    atm_longs_sorted = sorted(atm_longs, key=lambda x: x['strike'])
    total_buyer = sum(p['size'] for p in atm_longs_sorted)
    cumsum = 0
    bg = atm_longs_sorted[-1]['strike']  # Default to highest
    for p in atm_longs_sorted:
        cumsum += p['size']
        if cumsum >= total_buyer / 2:
            bg = p['strike']
            break
    
    # SG = weighted median of SELLER strikes near the money (ATM ±5%)
    atm_shorts = [p for p in shorts if underlying_price * 0.95 <= p['strike'] <= underlying_price * 1.05]
    if not atm_shorts:
        atm_shorts = shorts  # Fallback to all if no ATM
    
    atm_shorts_sorted = sorted(atm_shorts, key=lambda x: x['strike'])
    total_seller = sum(p['size'] for p in atm_shorts_sorted)
    cumsum = 0
    sg = atm_shorts_sorted[0]['strike']  # Default to lowest
    for p in atm_shorts_sorted:
        cumsum += p['size']
        if cumsum >= total_seller / 2:
            sg = p['strike']
            break
    
    # BG should be >= SG (swap if needed)
    if bg < sg:
        bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}


def fetch_open_interest():
    """Fetch active Open Interest for all BTC options"""
    print(f"Fetching Open Interest data from Deribit...")
    try:
        url = f"{DERIBIT_API}/public/get_book_summary_by_currency"
        params = {'currency': 'BTC', 'kind': 'option'}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json().get('result', [])
        print(f"Fetched {len(data)} active instruments")
        return data
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

def process_oi_data(data):
    """Process OI data into longs and shorts for PnL calculation"""
    longs = []
    shorts = []
    
    # In the OI model, for every contract open, there is a Buyer (Long) and Seller (Short).
    # We calculate the PnL for the Entire Market.
    # Longs = Holders of the option
    # Shorts = Writers of the option
    
    for item in data:
        # Skip if no OI
        if item.get('open_interest', 0) <= 0:
            continue
            
        parsed = parse_instrument(item['instrument_name'])
        if not parsed:
            continue
            
        # Use Mark Price as the current premium/value approximation
        premium = item.get('mark_price')
        if premium is None:
            premium = item.get('mid_price')
        
        # Get underlying index price
        index_price = item.get('underlying_price')
        
        if premium is None or index_price is None:
            continue

        pos = {
            'strike': parsed['strike'],
            'type': parsed['type'],
            'size': item['open_interest'],
            'premium': premium,       # Current market value (BTC)
            'index_price': index_price,
            'expiry': parsed['expiry']
        }
        
        # Add to both sides - reflecting the total market state
        longs.append(pos)
        shorts.append(pos)
        
    return longs, shorts

    return longs, shorts

def get_underlying_price():
    """Get current BTC price from Deribit"""
    url = f"{DERIBIT_API}/public/get_index_price"
    params = {'index_name': 'btc_usd'}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        return data.get('result', {}).get('index_price', 88000)
    except:
        return 88000

def main():

    print("=" * 60)
    print("Deribit Options Chain Data (Open Interest Method)")
    print("=" * 60)
    
    # Get current price
    underlying = get_underlying_price()
    print(f"\nCurrent BTC: ${underlying:,.2f}")
    
    # Fetch all OI data
    oi_data = fetch_open_interest()
    
    if not oi_data:
        print("No data found!")
        return
    
    # Get tomorrow's expiry
    target_expiry = get_tomorrow_expiry()
    print(f"Target expiry: {target_expiry}")
    
    # Filter to target expiry first
    target_data = [x for x in oi_data if parse_instrument(x['instrument_name'])['expiry'] == target_expiry]
    print(f"Contracts for {target_expiry}: {len(target_data)}")
    
    # Fallback logic if target has low volume/OI
    if len(target_data) < 10:
        # Find expiry with most OI
        expiry_oi = {}
        for x in oi_data:
            p = parse_instrument(x['instrument_name'])
            if p:
                expiry_oi[p['expiry']] = expiry_oi.get(p['expiry'], 0) + x['open_interest']
        
        if expiry_oi:
            target_expiry = max(expiry_oi.items(), key=lambda x: x[1])[0]
            print(f"Using liquid expiry: {target_expiry} (OI: {expiry_oi[target_expiry]:.0f})")
            target_data = [x for x in oi_data if parse_instrument(x['instrument_name'])['expiry'] == target_expiry]

    # Process into positions
    longs, shorts = process_oi_data(target_data)
    print(f"Processed Positions: {len(longs)} Strikes with Open Interest")
    
    # Calculate levels
    levels = find_levels(longs, shorts, underlying)
    
    if levels:
        print(f"\n📊 LEVELS (OI Based):")
        print(f"   R (Resistance): ${levels['r']:,}")
        print(f"   S (Support):    ${levels['s']:,}")
        print(f"   BG (Buyer Gamma): ${levels['bg']:,}")
        print(f"   SG (Seller Gamma): ${levels['sg']:,}")
        
        # Save to CSV
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        now = datetime.now(timezone.utc)
        iso_time = now.strftime('%Y-%m-%dT%H:%M')
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
