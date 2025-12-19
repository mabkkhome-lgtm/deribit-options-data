#!/usr/bin/env python3
"""
Deribit Options Data Fetcher
============================
Fetches BTC options data from Deribit API and calculates:
- High (Resistance): Strike with highest Call OI (Call Wall)
- Low (Support): Strike with highest Put OI (Put Wall)  
- Buyer Gamma: Strike with max positive GEX
- Seller Gamma: Strike with max negative GEX

Output: CSV file compatible with TradingView Options Levels Tracker indicator
"""

import requests
import json
import math
from datetime import datetime, timezone
from pathlib import Path

# Deribit API Configuration
DERIBIT_API_URL = "https://www.deribit.com/api/v2"
CURRENCY = "BTC"

# Output Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "btc_levels.csv"
MAX_HISTORY_DAYS = 90


def get_index_price():
    """Get current BTC index price from Deribit."""
    url = f"{DERIBIT_API_URL}/public/get_index_price"
    params = {"index_name": f"{CURRENCY.lower()}_usd"}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if "result" in data:
        return data["result"]["index_price"]
    raise Exception(f"Failed to get index price: {data}")


def get_active_options():
    """Get all active BTC options from Deribit."""
    url = f"{DERIBIT_API_URL}/public/get_instruments"
    params = {
        "currency": CURRENCY,
        "kind": "option",
        "expired": False
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if "result" in data:
        return data["result"]
    raise Exception(f"Failed to get instruments: {data}")


def get_book_summary():
    """Get book summary (OI, Greeks) for all BTC options."""
    url = f"{DERIBIT_API_URL}/public/get_book_summary_by_currency"
    params = {
        "currency": CURRENCY,
        "kind": "option"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if "result" in data:
        return data["result"]
    raise Exception(f"Failed to get book summary: {data}")


def calculate_gamma(spot, strike, time_to_expiry, iv, option_type="call"):
    """
    Calculate option gamma using Black-Scholes approximation.
    
    Args:
        spot: Current price
        strike: Strike price
        time_to_expiry: Time to expiry in years
        iv: Implied volatility (as decimal, e.g., 0.5 for 50%)
        option_type: 'call' or 'put' (gamma is same for both)
    
    Returns:
        Gamma value
    """
    if time_to_expiry <= 0 or iv <= 0:
        return 0
    
    # Standard normal PDF
    def norm_pdf(x):
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    
    try:
        d1 = (math.log(spot / strike) + (0.5 * iv * iv) * time_to_expiry) / (iv * math.sqrt(time_to_expiry))
        gamma = norm_pdf(d1) / (spot * iv * math.sqrt(time_to_expiry))
        return gamma
    except (ValueError, ZeroDivisionError):
        return 0


def calculate_levels(book_summary, spot_price):
    """
    Calculate key options levels from book summary.
    
    Returns:
        dict with high, low, buyerGamma, sellerGamma
    """
    # Organize data by strike
    strikes_data = {}
    current_time = datetime.now(timezone.utc)
    
    for option in book_summary:
        instrument = option.get("instrument_name", "")
        
        # Parse instrument name (e.g., "BTC-27DEC24-100000-C")
        parts = instrument.split("-")
        if len(parts) < 4:
            continue
        
        try:
            strike = int(parts[2])
            option_type = "call" if parts[3] == "C" else "put"
        except (ValueError, IndexError):
            continue
        
        # Get data
        oi = option.get("open_interest", 0) or 0
        iv = option.get("mark_iv", 0) or 0
        iv_decimal = iv / 100  # Convert from percentage
        
        # Parse expiry date
        try:
            expiry_str = parts[1]
            expiry = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=timezone.utc)
            time_to_expiry = (expiry - current_time).total_seconds() / (365.25 * 24 * 3600)
        except ValueError:
            time_to_expiry = 0.01  # Default to very short term
        
        # Calculate gamma
        gamma = calculate_gamma(spot_price, strike, time_to_expiry, iv_decimal, option_type)
        
        # Calculate GEX (Gamma Exposure)
        # For calls: positive GEX (dealers are short gamma when selling calls)
        # For puts: negative GEX (dealers are long gamma when selling puts)
        contract_size = 1  # BTC options are 1 BTC per contract on Deribit
        gex = oi * gamma * 100 * spot_price * contract_size
        
        if option_type == "put":
            gex = -gex  # Puts contribute negative gamma exposure
        
        # Aggregate by strike
        if strike not in strikes_data:
            strikes_data[strike] = {
                "call_oi": 0,
                "put_oi": 0,
                "total_gex": 0
            }
        
        if option_type == "call":
            strikes_data[strike]["call_oi"] += oi
        else:
            strikes_data[strike]["put_oi"] += oi
        
        strikes_data[strike]["total_gex"] += gex
    
    # Find key levels
    max_call_oi = 0
    max_call_strike = spot_price
    max_put_oi = 0
    max_put_strike = spot_price
    max_positive_gex = 0
    max_positive_gex_strike = spot_price
    max_negative_gex = 0
    max_negative_gex_strike = spot_price
    
    for strike, data in strikes_data.items():
        # Call Wall (Resistance) - highest Call OI
        if data["call_oi"] > max_call_oi:
            max_call_oi = data["call_oi"]
            max_call_strike = strike
        
        # Put Wall (Support) - highest Put OI
        if data["put_oi"] > max_put_oi:
            max_put_oi = data["put_oi"]
            max_put_strike = strike
        
        # Buyer Gamma - max positive GEX
        if data["total_gex"] > max_positive_gex:
            max_positive_gex = data["total_gex"]
            max_positive_gex_strike = strike
        
        # Seller Gamma - max negative GEX
        if data["total_gex"] < max_negative_gex:
            max_negative_gex = data["total_gex"]
            max_negative_gex_strike = strike
    
    return {
        "high": max_call_strike,          # Resistance (Call Wall)
        "low": max_put_strike,             # Support (Put Wall)
        "buyerGamma": max_positive_gex_strike,
        "sellerGamma": max_negative_gex_strike,
        "spot": spot_price,
        "call_wall_oi": max_call_oi,
        "put_wall_oi": max_put_oi
    }


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
    
    # Check if today's data already exists
    today = datetime.now().strftime("%d/%m/%Y")
    updated_lines = []
    today_found = False
    
    for line in existing_lines:
        if line.startswith(today):
            # Update today's entry
            updated_lines.append(new_line)
            today_found = True
        else:
            updated_lines.append(line)
    
    if not today_found:
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
    """Main function to fetch and process Deribit data."""
    print("=" * 60)
    print("Deribit Options Data Fetcher")
    print("=" * 60)
    
    try:
        # Step 1: Get current spot price
        print("\n📊 Fetching BTC index price...")
        spot_price = get_index_price()
        print(f"   Current BTC: ${spot_price:,.2f}")
        
        # Step 2: Get book summary for all options
        print("\n📈 Fetching options book summary...")
        book_summary = get_book_summary()
        print(f"   Found {len(book_summary)} active options")
        
        # Step 3: Calculate key levels
        print("\n🎯 Calculating key levels...")
        levels = calculate_levels(book_summary, spot_price)
        
        print(f"""
   Results:
   ─────────────────────────────────
   High (Resistance/Call Wall): ${levels['high']:,}
   Low (Support/Put Wall):      ${levels['low']:,}
   Buyer Gamma Strike:          ${levels['buyerGamma']:,}
   Seller Gamma Strike:         ${levels['sellerGamma']:,}
   ─────────────────────────────────
   Call Wall OI: {levels['call_wall_oi']:,.2f} BTC
   Put Wall OI:  {levels['put_wall_oi']:,.2f} BTC
""")
        
        # Step 4: Format and save data
        today = datetime.now().strftime("%d/%m/%Y")
        new_line = f"{today},{levels['high']},{levels['low']},{levels['buyerGamma']},{levels['sellerGamma']}"
        
        print(f"📝 CSV Line: {new_line}")
        
        # Load existing data and save
        existing_lines = load_existing_data()
        save_data(existing_lines, new_line)
        
        print("\n✅ Done!")
        
        return levels
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
