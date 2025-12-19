#!/usr/bin/env python3
"""
Thales OSS Data Fetcher
=======================
Fetches BTC options data from Thales OSS API and calculates:
- Top Range (Resistance): Right intersection of buyer/seller PnL curves
- Bottom Range (Support): Left intersection of buyer/seller PnL curves

The convergence points represent where buyers and sellers agree on price.

Output: CSV file compatible with TradingView Options Levels Tracker indicator
"""

import requests
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

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
    return int(start_of_day.timestamp() * 1000)  # Thales uses milliseconds


def get_tomorrow_expiry_code():
    """Get the expiry date code for tomorrow (days since epoch)."""
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    # Thales uses days since Unix epoch for expiry codes
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    days_since_epoch = (tomorrow - epoch).days
    return days_since_epoch, tomorrow.strftime("%d/%m/%Y")


def fetch_options_data():
    """Fetch options data from Thales OSS API."""
    from_timestamp = get_start_of_today_utc()
    to_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    url = f"{THALES_API_URL}/FetchOptions"
    params = {
        "source": 1,  # Deribit
        "fromDate": from_timestamp,
        "toDate": to_timestamp
    }
    
    print(f"📊 Fetching data from {datetime.fromtimestamp(from_timestamp/1000, tz=timezone.utc)}")
    print(f"   to {datetime.fromtimestamp(to_timestamp/1000, tz=timezone.utc)}")
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data: {response.status_code} - {response.text}")
    
    return response.text


def parse_options_csv(csv_data, target_expiry_code):
    """
    Parse Thales CSV data and filter for tomorrow's expiry.
    
    CSV Format (inferred):
    - Column 0: Type (0=Call, 1=Put)
    - Column 1: Expiry Date Code (days since epoch)
    - Column 2: Strike Price
    - Column 3: Trade ID/Timestamp
    - Column 4: Side (0=Long/Buyer, 1=Short/Seller)
    - Column 5: Size
    - Column 6: Entry Price
    """
    longs = []  # Buyer positions
    shorts = []  # Seller positions
    
    lines = csv_data.strip().split('\n')
    
    for line in lines:
        if not line.strip():
            continue
            
        parts = line.split(',')
        if len(parts) < 7:
            continue
        
        try:
            option_type = int(parts[0])  # 0=Call, 1=Put
            expiry_code = int(parts[1])
            strike = float(parts[2])
            side = int(parts[4])  # 0=Long, 1=Short
            size = float(parts[5])
            entry_price = float(parts[6])
            
            # Filter for tomorrow's expiry only
            if expiry_code != target_expiry_code:
                continue
            
            position = {
                'type': 'call' if option_type == 0 else 'put',
                'strike': strike,
                'size': size,
                'entry_price': entry_price
            }
            
            if side == 0:  # Long/Buyer
                longs.append(position)
            else:  # Short/Seller
                shorts.append(position)
                
        except (ValueError, IndexError) as e:
            continue
    
    return longs, shorts


def calculate_pnl_at_price(positions, underlying_price):
    """
    Calculate total PnL at expiry for a group of positions at a given underlying price.
    
    For CALLS at expiry:
        PnL = Size * (max(S - K, 0) - EntryPrice) * 100
        
    For PUTS at expiry:
        PnL = Size * (max(K - S, 0) - EntryPrice) * 100
        
    Where S = underlying price, K = strike, EntryPrice = premium paid
    """
    total_pnl = 0
    
    for pos in positions:
        strike = pos['strike']
        size = pos['size']
        entry = pos['entry_price']
        
        if pos['type'] == 'call':
            # Call payoff at expiry
            intrinsic = max(underlying_price - strike, 0)
            pnl = size * (intrinsic - entry) * 100
        else:
            # Put payoff at expiry
            intrinsic = max(strike - underlying_price, 0)
            pnl = size * (intrinsic - entry) * 100
        
        total_pnl += pnl
    
    return total_pnl


def find_convergence_points(longs, shorts, price_range=(50000, 150000), step=100):
    """
    Find where buyer (long) and seller (short) PnL curves intersect.
    
    Returns:
        (left_convergence, right_convergence) - the two price points where curves meet
        left = bottom range (support), right = top range (resistance)
    """
    intersections = []
    prev_diff = None
    
    for price in range(price_range[0], price_range[1], step):
        long_pnl = calculate_pnl_at_price(longs, price)
        short_pnl = calculate_pnl_at_price(shorts, price)
        
        diff = long_pnl - short_pnl
        
        if prev_diff is not None:
            # Check for sign change (crossing)
            if prev_diff * diff < 0:
                # Intersection found - refine it
                refined_price = refine_intersection(longs, shorts, price - step, price)
                intersections.append(refined_price)
        
        prev_diff = diff
    
    if len(intersections) >= 2:
        return int(intersections[0]), int(intersections[-1])
    elif len(intersections) == 1:
        return int(intersections[0]), int(intersections[0])
    else:
        # No clear intersection - return the price range center
        center = (price_range[0] + price_range[1]) // 2
        return center, center


def refine_intersection(longs, shorts, low_price, high_price, tolerance=10):
    """Binary search to find precise intersection point."""
    while high_price - low_price > tolerance:
        mid = (low_price + high_price) / 2
        
        long_pnl = calculate_pnl_at_price(longs, mid)
        short_pnl = calculate_pnl_at_price(shorts, mid)
        
        low_long_pnl = calculate_pnl_at_price(longs, low_price)
        low_short_pnl = calculate_pnl_at_price(shorts, low_price)
        
        low_diff = low_long_pnl - low_short_pnl
        mid_diff = long_pnl - short_pnl
        
        if low_diff * mid_diff < 0:
            high_price = mid
        else:
            low_price = mid
    
    return (low_price + high_price) / 2


def get_current_btc_price():
    """Get current BTC price from Thales API for reference."""
    try:
        url = f"{THALES_API_URL}/InstrumentPrices"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Look for BTC price in the response
            if isinstance(data, dict) and 'underlying' in data:
                return data['underlying']
        return None
    except:
        return None


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
    """Save data to CSV, keeping only last MAX_HISTORY_DAYS entries."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Extract date from new line
    new_date = new_line.split(',')[0]
    
    # Filter out any existing entries for the same date
    updated_lines = [line for line in existing_lines if not line.startswith(new_date)]
    updated_lines.append(new_line)
    
    # Keep only last MAX_HISTORY_DAYS entries
    if len(updated_lines) > MAX_HISTORY_DAYS:
        updated_lines = updated_lines[-MAX_HISTORY_DAYS:]
    
    # Write to file
    with open(OUTPUT_FILE, "w") as f:
        f.write("date,high,low,buyerGamma,sellerGamma\n")
        for line in updated_lines:
            f.write(line + "\n")
    
    print(f"✅ Data saved to {OUTPUT_FILE}")


def main():
    """Main function to fetch and process Thales OSS data."""
    print("=" * 60)
    print("Thales OSS Options Data Fetcher")
    print("=" * 60)
    
    try:
        # Step 1: Get target expiry (tomorrow)
        expiry_code, expiry_date = get_tomorrow_expiry_code()
        print(f"\n📅 Target Expiry: {expiry_date} (code: {expiry_code})")
        
        # Step 2: Fetch options data from Thales OSS
        print("\n📈 Fetching options data from Thales OSS...")
        csv_data = fetch_options_data()
        
        total_lines = len(csv_data.strip().split('\n'))
        print(f"   Received {total_lines} trade records")
        
        # Step 3: Parse and filter for tomorrow's expiry
        print("\n🔍 Filtering for tomorrow's expiry...")
        longs, shorts = parse_options_csv(csv_data, expiry_code)
        print(f"   Found {len(longs)} buyer (long) positions")
        print(f"   Found {len(shorts)} seller (short) positions")
        
        if len(longs) == 0 or len(shorts) == 0:
            print("\n⚠️  Warning: Not enough positions for tomorrow's expiry.")
            print("   This might happen early in the day or if there's no trading activity.")
            print("   Using fallback values...")
            
            # Try to get current BTC price as fallback
            btc_price = get_current_btc_price()
            if btc_price:
                bottom_range = int(btc_price * 0.97)  # -3%
                top_range = int(btc_price * 1.03)  # +3%
            else:
                # Absolute fallback
                bottom_range = 85000
                top_range = 100000
        else:
            # Step 4: Find convergence points
            print("\n🎯 Calculating convergence points...")
            
            # Determine price range based on strikes in data
            all_strikes = [p['strike'] for p in longs + shorts]
            min_strike = min(all_strikes)
            max_strike = max(all_strikes)
            price_range = (int(min_strike * 0.9), int(max_strike * 1.1))
            
            bottom_range, top_range = find_convergence_points(longs, shorts, price_range)
        
        print(f"""
   Results:
   ─────────────────────────────────
   Bottom Range (Support):  ${bottom_range:,}
   Top Range (Resistance):  ${top_range:,}
   ─────────────────────────────────
   Expiry Date: {expiry_date}
   Buyer Positions: {len(longs)}
   Seller Positions: {len(shorts)}
""")
        
        # Step 5: Format and save data
        # Note: buyerGamma and sellerGamma are set to same as ranges for now
        # These could be calculated separately if needed
        new_line = f"{expiry_date},{top_range},{bottom_range},{top_range},{bottom_range}"
        
        print(f"📝 CSV Line: {new_line}")
        
        # Load existing data and save
        existing_lines = load_existing_data()
        save_data(existing_lines, new_line)
        
        print("\n✅ Done!")
        
        return {
            'date': expiry_date,
            'top_range': top_range,
            'bottom_range': bottom_range
        }
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
