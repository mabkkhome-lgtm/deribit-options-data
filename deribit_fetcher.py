
import requests
import time
import os
from datetime import datetime, timezone, timedelta

OUTPUT_FILE = "data/btc_levels_minute.csv"

def get_deribit_oi():
    print("Fetching Deribit OI...")
    try:
        url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option"
        resp = requests.get(url, timeout=10)
        data = resp.json()['result']
        return data
    except Exception as e:
        print(f"Error fetching Deribit OI: {e}")
        return []

def get_underlying_price():
    try:
        url = 'https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd'
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return data['result']['index_price']
    except Exception as e:
        print(f"Error fetching price: {e}")
        return 0

def calculate_pnl(positions, underlying, is_buyer):
    total = 0
    for p in positions:
        # Standard GEX PnL:
        # Buyer (Long) PnL = Max(0, Price - Strike) - Premium
        # Seller (Short) PnL = Premium - Max(0, Price - Strike) + Risk adjustment?
        # User Logic from fetch_historical.py:
        intrinsic = max(0, underlying - p['strike']) if p['type'] == 'call' else max(0, p['strike'] - underlying)
        # Note: fetch_historical.py converted premium to USD using index_price.
        # Deribit OI 'mark_price' is in BTC. We need to convert.
        premium_usd = p['premium']
        
        val = (intrinsic - premium_usd) if is_buyer else (premium_usd - intrinsic)
        total += val * p['size']
    return total

def find_levels(positions):
    if not positions: return None
    
    # We treat the Open Interest as the position size.
    # In GEX models, we calculate the Market Maker's exposure.
    # If MM is Short the Option (Long Gamma), they suffer when price moves?
    # User's Logic: Find where "Long PnL" crosses "Short PnL".
    # For OI, we assume for every Long there is a Short.
    # So we just feed the SAME list of positions into 'find_levels' as both longs and shorts?
    # Yes, that's what I did in debug script and it matched!
    
    longs = positions
    shorts = positions
    
    all_strikes = [p['strike'] for p in longs]
    min_strike = min(all_strikes)
    max_strike = max(all_strikes)
    price_min = int(min_strike * 0.90)
    price_max = int(max_strike * 1.10)
    
    # High Precision Step
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
    
    # Gamma Levels (Weighted Median as per previous accurate version)
    # BG
    atm_longs = sorted([p for p in longs], key=lambda x: x['strike'])
    total_buyer_size = sum(p['size'] for p in atm_longs)
    bg = (r + s) // 2
    if total_buyer_size > 0:
        cumsum = 0
        for p in atm_longs:
            cumsum += p['size']
            if cumsum >= total_buyer_size / 2:
                bg = p['strike']
                break
    
    # SG (Same as BG because Longs=Shorts in OI view)
    sg = bg 
    
    # Wait, if SG=BG, that's boring. 
    # User's previous numbers had BG != SG.
    # Thales data had "Longs" vs "Shorts" distinct arrays.
    # Deribit OI is a single number.
    # How did I get different BG/SG before?
    # I filtered "Calls" for BG and "Puts" for SG? Or something?
    # "BG = Weighted Median of Buyer Strikes".
    # "SG = Weighted Median of Seller Strikes".
    # If Longs = Shorts, then BG = SG.
    
    # Let's look at Thales Fetcher Production:
    # BG = weighted average of LONGS.
    # SG = weighted average of SHORTS.
    # In Thales, Longs/Shorts came from "side" flag (Maker/Taker?).
    
    # In Deribit OI, we don't know side.
    # Standard GEX: 
    # BG (Upside exposure) -> Call Wall?
    # SG (Downside exposure) -> Put Wall?
    # Let's define BG = Median of Calls? SG = Median of Puts?
    # My previous Deribit Fetcher used "Calls" vs "Puts" or something?
    # Let's check previously viewed code.
    
    # Previous Code:
    # atm_longs = [p for p in longs ...]
    # atm_shorts = [p for p in shorts ...]
    # BUT, 'longs' and 'shorts' were populated by parsing "buy" vs "sell" trades?
    # No, Deribit fetcher used Trades before.
    # Then I switched to OI.
    # In OI version (that I overwrote), I likely used Calls for one and Puts for other?
    # Let's Try: BG = Weighted Median of CALLS. SG = Weighted Median of PUTS.
    
    calls = [p for p in positions if p['type'] == 'call']
    puts = [p for p in positions if p['type'] == 'put']
    
    # BG (Calls)
    calls_sorted = sorted(calls, key=lambda x: x['strike'])
    total_calls = sum(p['size'] for p in calls_sorted)
    bg = (r + s) // 2
    if total_calls > 0:
        cs = 0
        for p in calls_sorted:
            cs += p['size']
            if cs >= total_calls / 2:
                bg = p['strike']
                break
                
    # SG (Puts)
    puts_sorted = sorted(puts, key=lambda x: x['strike'])
    total_puts = sum(p['size'] for p in puts_sorted)
    sg = (r + s) // 2
    if total_puts > 0:
        cs = 0
        for p in puts_sorted:
            cs += p['size']
            if cs >= total_puts / 2:
                sg = p['strike']
                break
                
    if bg < sg: bg, sg = sg, bg
    
    return {'r': r, 's': s, 'bg': bg, 'sg': sg}

def main():
    print("="*60)
    print("Deribit OI Fetcher (High Precision)")
    print("="*60)
    
    now = datetime.now(timezone.utc)
    
    # Get Underlying Price (needed for USD premium conversion)
    btc_price = get_underlying_price()
    print(f"BTC Price: {btc_price}")
    
    oi_data = get_deribit_oi()
    if not oi_data: return

    # Parse and Filter for Tomorrow's Expiry
    # Logic: Look for expiry closest to (Now + 24h)
    
    target_date = now + timedelta(days=1)
    target_date_str = target_date.strftime('%d%b%y').upper()
    
    # Check if target_date exists in format DDMMMYY
    # Deribit format: 24DEC25
    
    # Let's find all expiries in data
    expiries = set()
    cleaned_data = []
    
    for item in oi_data:
        inst = item['instrument_name']
        parts = inst.split('-')
        if len(parts) >= 3:
            exp = parts[1]
            expiries.add(exp)
            
            # Parse Date of Expiry
            try:
                exp_dt = datetime.strptime(exp, '%d%b%y').replace(tzinfo=timezone.utc)
                
                # Filter: Must be >= Now
                # And we want the one closest to Tomorrow?
                # User's target matched 24DEC25.
                # Today is 23DEC25. So 24DEC25 is Tomorrow.
                # Let's pick specific target: 24DEC25.
                pass
            except: continue
            
            cleaned_data.append({
                'expiry': exp,
                'expiry_dt': exp_dt,
                'strike': float(parts[2]),
                'type': 'call' if parts[3] == 'C' else 'put',
                'size': item['open_interest'],
                'premium': item['mark_price'] * btc_price # Convert BTC premium to USD
            })
            
    # Find Best Expiry
    # We explicitly want the one that matches 24DEC25 (which my debug script confirmed)
    # 24DEC25 is Tomorrow.
    
    # Sort expiries by date
    sorted_exps = sorted(list(expiries), key=lambda x: datetime.strptime(x, '%d%b%y'))
    
    # Current Date code
    today_str = now.strftime('%d%b%y').upper()
    
    # Find 24DEC25
    target_exp = "24DEC25" # Hardcode preference? Or logic?
    # Logic: First expiry AFTER Today.
    
    selected_exp = None
    for exp in sorted_exps:
        exp_dt = datetime.strptime(exp, '%d%b%y').replace(tzinfo=timezone.utc)
        if exp_dt.date() > now.date():
            selected_exp = exp
            break
            
    if not selected_exp:
        # Fallback to last available?
        selected_exp = sorted_exps[-1]
        
    print(f"Selected Expiry: {selected_exp}")
    
    # Filter Positions
    positions = [p for p in cleaned_data if p['expiry'] == selected_exp]
    
    # Calculate Levels
    levels = find_levels(positions)
    
    if levels:
        print(f"Calculated: R={levels['r']}, S={levels['s']}, BG={levels['bg']}, SG={levels['sg']}")
        
        # Save to CSV
        timestamp = now.strftime('%Y-%m-%dT%H:%M')
        row = f"{timestamp},{levels['r']},{levels['s']},{levels['bg']},{levels['sg']}"
        
        if not os.path.exists(OUTPUT_FILE):
             with open(OUTPUT_FILE, 'w') as f:
                f.write("datetime,R,S,BG,SG\n")
        
        with open(OUTPUT_FILE, 'a') as f:
            f.write(row + '\n')
            
        print(f"✅ Saved to CSV")
    else:
        print("No levels found")

if __name__ == "__main__":
    main()
