#!/usr/bin/env python3
"""
Thales OSS Data Fetcher - v3
============================
Fetches BTC options data from Thales OSS API and calculates:
- Top Range (Resistance): Right intersection of buyer/seller PnL curves
- Bottom Range (Support): Left intersection of buyer/seller PnL curves

Entry prices in Thales data are in USD.

Output: CSV file compatible with TradingView Options Levels Tracker indicator
"""

import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Thales OSS API Configuration
THALES_API_URL = "https://oss.thales-mfi.com/api/MarketScreener"

# Output Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "btc_levels.csv"
MAX_HISTORY_DAYS = 90


def get_start_of_today_utc():
    """Get timestamp for 00:00 UTC today."""
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start_of_day.timestamp() * 1000)


def get_tomorrow_expiry_code():
    """Get the expiry date code for tomorrow (days since epoch)."""
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    days_since_epoch = (tomorrow - epoch).days
    return days_since_epoch, tomorrow.strftime("%d/%m/%Y")


def fetch_options_data():
    """Fetch options data from Thales OSS API."""
    from_timestamp = get_start_of_today_utc()
    to_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    url = f"{THALES_API_URL}/FetchOptions"
    params = {
        "source": 1,
        "fromDate": from_timestamp,
        "toDate": to_timestamp
    }
    
    print(f"📊 Fetching from {datetime.fromtimestamp(from_timestamp/1000, tz=timezone.utc)}")
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch: {response.status_code}")
    
    return response.text


def parse_options_csv(csv_data, target_expiry_code):
    """
    Parse Thales CSV data.
    
    CSV Format:
    - Column 0: Type (0=Call, 1=Put)
    - Column 1: Expiry Date Code
    - Column 2: Strike Price (USD)
    - Column 3: Trade ID/Timestamp
    - Column 4: Side (0=Long/Buyer, 1=Short/Seller)
    - Column 5: Size (BTC contracts)
    - Column 6: Entry Price (USD per contract)
    """
    longs = []
    shorts = []
    
    for line in csv_data.strip().split('\n'):
        if not line.strip():
            continue
            
        parts = line.split(',')
        if len(parts) < 7:
            continue
        
        try:
            option_type = int(parts[0])
            expiry_code = int(parts[1])
            strike = float(parts[2])
            side = int(parts[4])
            size = float(parts[5])
            entry_price_usd = float(parts[6])  # Already in USD!
            
            if expiry_code != target_expiry_code:
                continue
            
            position = {
                'type': 'call' if option_type == 0 else 'put',
                'strike': strike,
                'size': size,
                'premium_usd': entry_price_usd  # Premium in USD
            }
            
            if side == 0:
                longs.append(position)
            else:
                shorts.append(position)
                
        except (ValueError, IndexError):
            continue
    
    return longs, shorts


def calculate_pnl_at_expiry(positions, underlying_price, is_buyer=True):
    """
    Calculate total PnL at expiry (in USD).
    
    For BUYER (Long):
        Call: max(S - K, 0) - Premium
        Put:  max(K - S, 0) - Premium
        
    For SELLER (Short):
        Call: Premium - max(S - K, 0)
        Put:  Premium - max(K - S, 0)
        
    All values in USD. Size multiplies the per-contract PnL.
    """
    total_pnl = 0
    
    for pos in positions:
        strike = pos['strike']
        size = pos['size']
        premium = pos['premium_usd']
        
        if pos['type'] == 'call':
            intrinsic = max(underlying_price - strike, 0)
        else:  # put
            intrinsic = max(strike - underlying_price, 0)
        
        if is_buyer:
            # Buyer paid premium, receives intrinsic value
            pnl = (intrinsic - premium) * size
        else:
            # Seller received premium, pays out intrinsic value
            pnl = (premium - intrinsic) * size
        
        total_pnl += pnl
    
    return total_pnl


def find_convergence_points(longs, shorts):
    """
    Find where buyer (long) and seller (short) PnL curves intersect.
    """
    # Get all strikes for range estimation
    all_strikes = [p['strike'] for p in longs + shorts]
    if not all_strikes:
        return 85000, 100000
    
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    
    # Search range
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # Calculate PnL at many price points (10 USD steps for precision)
    step = 10
    prices = list(range(price_min, price_max, step))
    
    # Track crossings
    intersections = []
    prev_long_pnl = None
    prev_short_pnl = None
    
    for price in prices:
        long_pnl = calculate_pnl_at_expiry(longs, price, is_buyer=True)
        short_pnl = calculate_pnl_at_expiry(shorts, price, is_buyer=False)
        
        if prev_long_pnl is not None:
            prev_diff = prev_long_pnl - prev_short_pnl
            curr_diff = long_pnl - short_pnl
            
            # Check for sign change (crossing)
            if prev_diff * curr_diff < 0:
                # Linear interpolation
                t = abs(prev_diff) / (abs(prev_diff) + abs(curr_diff))
                crossing_price = (price - step) + t * step
                intersections.append(int(crossing_price))
        
        prev_long_pnl = long_pnl
        prev_short_pnl = short_pnl
    
    print(f"   Found {len(intersections)} intersection points: {intersections}")
    
    if len(intersections) >= 2:
        return intersections[0], intersections[-1]
    elif len(intersections) == 1:
        return intersections[0], intersections[0]
    else:
        # Fallback: weighted average of strikes
        print("   ⚠️ No intersections found, using weighted average")
        mean_strike = sum(all_strikes) / len(all_strikes)
        return int(mean_strike * 0.95), int(mean_strike * 1.05)


def find_gamma_levels(longs, shorts, support, resistance):
    """
    Find gamma levels (BG and SG) using weighted average of strikes.
    BG = weighted average of BUYER (long) positions by size
    SG = weighted average of SELLER (short) positions by size
    """
    # Calculate weighted average of buyer strikes
    total_buyer_size = sum(p['size'] for p in longs)
    if total_buyer_size > 0:
        bg = sum(p['strike'] * p['size'] for p in longs) / total_buyer_size
    else:
        bg = (support + resistance) / 2
    
    # Calculate weighted average of seller strikes
    total_seller_size = sum(p['size'] for p in shorts)
    if total_seller_size > 0:
        sg = sum(p['strike'] * p['size'] for p in shorts) / total_seller_size
    else:
        sg = (support + resistance) / 2
    
    bg = int(bg)
    sg = int(sg)
    
    # Ensure BG > SG
    if bg < sg:
        bg, sg = sg, bg
    
    print(f"   Gamma: BG={bg} (buyer weighted avg), SG={sg} (seller weighted avg)")
    
    return bg, sg

def load_existing_data():
    """Load existing CSV data if it exists."""
    if not OUTPUT_FILE.exists():
        return []
    
    lines = []
    with open(OUTPUT_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("date"):
                lines.append(line)
    
    return lines


def save_data(existing_lines, new_line):
    """Save data to CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    new_date = new_line.split(',')[0]
    updated_lines = [line for line in existing_lines if not line.startswith(new_date)]
    updated_lines.append(new_line)
    
    if len(updated_lines) > MAX_HISTORY_DAYS:
        updated_lines = updated_lines[-MAX_HISTORY_DAYS:]
    
    with open(OUTPUT_FILE, "w") as f:
        f.write("date,high,low,buyerGamma,sellerGamma\n")
        for line in updated_lines:
            f.write(line + "\n")
    
    print(f"✅ Data saved to {OUTPUT_FILE}")


def main():
    """Main function."""
    print("=" * 60)
    print("Thales OSS Options Data Fetcher v3")
    print("=" * 60)
    
    try:
        expiry_code, expiry_date = get_tomorrow_expiry_code()
        print(f"\n📅 Target Expiry: {expiry_date} (code: {expiry_code})")
        
        print("\n📈 Fetching from Thales OSS...")
        csv_data = fetch_options_data()
        
        total_lines = len(csv_data.strip().split('\n'))
        print(f"   Received {total_lines} trade records")
        
        print("\n🔍 Parsing positions for tomorrow's expiry...")
        longs, shorts = parse_options_csv(csv_data, expiry_code)
        print(f"   Buyers (Long): {len(longs)} positions")
        print(f"   Sellers (Short): {len(shorts)} positions")
        
        if len(longs) == 0 or len(shorts) == 0:
            print("\n⚠️  Not enough data, using defaults")
            bottom_range = 85000
            top_range = 100000
            buyer_gamma = 90000
            seller_gamma = 87000
        else:
            print("\n🎯 Finding convergence points...")
            bottom_range, top_range = find_convergence_points(longs, shorts)
            
            print("\n📊 Finding gamma levels...")
            buyer_gamma, seller_gamma = find_gamma_levels(longs, shorts, bottom_range, top_range)
        
        print(f"""
   Results:
   ─────────────────────────────────
   Resistance (R):   ${top_range:,}
   Support (S):      ${bottom_range:,}
   Buyer Gamma (BG): ${buyer_gamma:,}
   Seller Gamma (SG): ${seller_gamma:,}
   ─────────────────────────────────
""")
        
        new_line = f"{expiry_date},{top_range},{bottom_range},{buyer_gamma},{seller_gamma}"
        print(f"📝 CSV: {new_line}")
        
        existing_lines = load_existing_data()
        save_data(existing_lines, new_line)
        
        print("\n✅ Done!")
        
        return {'date': expiry_date, 'top': top_range, 'bottom': bottom_range}
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
