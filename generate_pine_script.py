#!/usr/bin/env python3
"""
Pine Script Generator
=====================
Generates a Pine Script indicator with 90 days of historical data
embedded directly in the code as arrays.

The generated indicator needs NO external data input - 
everything is built-in and ready to use.

Output: A complete Pine Script file that can be copied to TradingView
"""

import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Thales OSS API Configuration
THALES_API_URL = "https://oss.thales-mfi.com/api/MarketScreener"

# Output Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_PINE = OUTPUT_DIR / "options_levels_indicator.pine"
OUTPUT_CSV = OUTPUT_DIR / "btc_levels.csv"
HISTORY_DAYS = 90


def get_timestamp_for_days_ago(days):
    """Get timestamp for N days ago at 00:00 UTC."""
    target_date = datetime.now(timezone.utc) - timedelta(days=days)
    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start_of_day.timestamp() * 1000)


def get_expiry_code_for_date(target_date):
    """Get expiry code (days since epoch) for a given date."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (target_date - epoch).days


def fetch_options_data(from_timestamp, to_timestamp):
    """Fetch options data from Thales OSS API."""
    url = f"{THALES_API_URL}/FetchOptions"
    params = {
        "source": 1,
        "fromDate": from_timestamp,
        "toDate": to_timestamp
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        return ""
    
    return response.text


def parse_and_calculate_for_expiry(csv_data, expiry_code):
    """Parse data and calculate convergence points for a specific expiry."""
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
            line_expiry = int(parts[1])
            strike = float(parts[2])
            side = int(parts[4])
            size = float(parts[5])
            premium = float(parts[6])
            
            if line_expiry != expiry_code:
                continue
            
            pos = {
                'type': 'call' if option_type == 0 else 'put',
                'strike': strike,
                'size': size,
                'premium': premium
            }
            
            if side == 0:
                longs.append(pos)
            else:
                shorts.append(pos)
                
        except (ValueError, IndexError):
            continue
    
    if len(longs) == 0 or len(shorts) == 0:
        return None, None
    
    # Calculate convergence points
    all_strikes = [p['strike'] for p in longs + shorts]
    price_min = int(min(all_strikes) * 0.90)
    price_max = int(max(all_strikes) * 1.10)
    
    intersections = []
    prev_diff = None
    
    for price in range(price_min, price_max, 10):
        long_pnl = sum(
            (max(price - p['strike'], 0) if p['type'] == 'call' else max(p['strike'] - price, 0)) - p['premium']
            for p in longs
        ) * sum(p['size'] for p in longs)
        
        short_pnl = sum(
            p['premium'] - (max(price - p['strike'], 0) if p['type'] == 'call' else max(p['strike'] - price, 0))
            for p in shorts
        ) * sum(p['size'] for p in shorts)
        
        diff = long_pnl - short_pnl
        
        if prev_diff is not None and prev_diff * diff < 0:
            intersections.append(price)
        
        prev_diff = diff
    
    if len(intersections) >= 2:
        return intersections[0], intersections[-1]
    elif len(intersections) == 1:
        return intersections[0], intersections[0]
    
    return None, None


def load_existing_csv():
    """Load existing CSV data."""
    if not OUTPUT_CSV.exists():
        return {}
    
    data = {}
    with open(OUTPUT_CSV, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('date'):
                parts = line.split(',')
                if len(parts) >= 3:
                    data[parts[0]] = (int(parts[1]), int(parts[2]))
    return data


def save_csv(data):
    """Save data to CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_CSV, 'w') as f:
        f.write("date,high,low,buyerGamma,sellerGamma\n")
        for date in sorted(data.keys(), key=lambda x: datetime.strptime(x, "%d/%m/%Y")):
            high, low = data[date]
            f.write(f"{date},{high},{low},{high},{low}\n")


def generate_pine_script(historical_data):
    """Generate complete Pine Script with embedded data."""
    
    # Sort data by date
    sorted_dates = sorted(historical_data.keys(), key=lambda x: datetime.strptime(x, "%d/%m/%Y"))
    
    # Create arrays for Pine Script
    dates_array = ', '.join(f'"{d}"' for d in sorted_dates)
    highs_array = ', '.join(str(historical_data[d][0]) for d in sorted_dates)
    lows_array = ', '.join(str(historical_data[d][1]) for d in sorted_dates)
    
    # Get the latest data
    latest_date = sorted_dates[-1] if sorted_dates else "01/01/2025"
    latest_high = historical_data[latest_date][0] if sorted_dates else 100000
    latest_low = historical_data[latest_date][1] if sorted_dates else 85000
    
    pine_script = f'''// Options Levels Tracker - Auto-Generated with {len(sorted_dates)} days of historical data
// Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}
// To get the latest version: https://github.com/mabkkhome-lgtm/deribit-options-data/blob/main/data/options_levels_indicator.pine

//@version=5
indicator("Options Levels Tracker", overlay=true, max_lines_count=500, max_labels_count=50, max_boxes_count=50)

// ═══════════════════════════════════════════════════════════════════════════════
// EMBEDDED HISTORICAL DATA ({len(sorted_dates)} days)
// ═══════════════════════════════════════════════════════════════════════════════

var array<string> DATA_DATES = array.from({dates_array})
var array<float> DATA_HIGHS = array.from({highs_array})
var array<float> DATA_LOWS = array.from({lows_array})

// ═══════════════════════════════════════════════════════════════════════════════
// OPTIONAL: Override today's data (for real-time updates)
// ═══════════════════════════════════════════════════════════════════════════════

bool useOverride = input.bool(false, "Use Manual Override for Today", group="📊 Manual Override")
float overrideHigh = input.float({latest_high}, "Today's Resistance", group="📊 Manual Override")
float overrideLow = input.float({latest_low}, "Today's Support", group="📊 Manual Override")
string overrideDate = input.string("{latest_date}", "Today's Date (dd/mm/yyyy)", group="📊 Manual Override")

// ═══════════════════════════════════════════════════════════════════════════════
// ANALYSIS PERIODS
// ═══════════════════════════════════════════════════════════════════════════════

int shortPeriod = input.int(7, "Short Period (days)", minval=1, maxval=30, group="📈 Analysis Periods")
int longPeriod = input.int(30, "Long Period (days)", minval=7, maxval=90, group="📈 Analysis Periods")

// ═══════════════════════════════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════════════════════════════

string showOn = input.string("BTCUSDT", "Chart Symbol", group="⚙️ Settings")

// Visual Styles
color topColor = input.color(#00ff00, "Resistance", inline="c1", group="⚙️ Settings")
color lowColor = input.color(#ff0000, "Support", inline="c2", group="⚙️ Settings")
color zoneColor = input.color(color.new(#2962ff, 90), "Zone Fill", inline="c2", group="⚙️ Settings")

int lineThickness = input.int(2, "Line Width", minval=1, maxval=5, group="⚙️ Settings")
string lineStyle = input.string("Solid", "Line Style", options=["Solid", "Dashed", "Dotted"], group="⚙️ Settings")

// Features
bool showLabels = input.bool(true, "Show Labels (Latest Only)", group="⚙️ Settings")
bool showPrices = input.bool(true, "Show Prices", group="⚙️ Settings")
bool showZones = input.bool(true, "Support/Resistance Zones", group="⚙️ Settings")
bool showStats = input.bool(true, "Statistics Panel", group="⚙️ Settings")

// Table Options
string tablePosition = input.string("Bottom Right", "Table Position", options=["Top Right", "Top Left", "Bottom Right", "Bottom Left"], group="📊 Table Settings")
string tableTextSize = input.string("Small", "Table Font Size", options=["Tiny", "Small", "Normal", "Large"], group="📊 Table Settings")

// ═══════════════════════════════════════════════════════════════════════════════
// CORE LOGIC
// ═══════════════════════════════════════════════════════════════════════════════

bool show = syminfo.ticker == showOn
string pineLineStyle = lineStyle == "Dashed" ? line.style_dashed : lineStyle == "Dotted" ? line.style_dotted : line.style_solid

// Parse date string to timestamp
parseDate(dateStr) =>
    array<string> parts = str.split(dateStr, "/")
    if array.size(parts) == 3
        int dd = int(str.tonumber(array.get(parts, 0)))
        int mm = int(str.tonumber(array.get(parts, 1)))
        int yy = int(str.tonumber(array.get(parts, 2)))
        if yy < 100
            yy := yy + 2000
        timestamp(yy, mm, dd, 0, 0, 0)
    else
        na

// Get data for drawing
getData() =>
    int dataSize = array.size(DATA_DATES)
    array<string> dates = array.copy(DATA_DATES)
    array<float> highs = array.copy(DATA_HIGHS)
    array<float> lows = array.copy(DATA_LOWS)
    
    // Add override if enabled
    if useOverride
        array.push(dates, overrideDate)
        array.push(highs, overrideHigh)
        array.push(lows, overrideLow)
    
    [dates, highs, lows]

// Statistics variables
var float todayRange = na
var float lastTop = na
var float lastLow = na

// Draw levels
if barstate.islast and show
    [dates, highs, lows] = getData()
    int dataSize = array.size(dates)
    
    if dataSize > 0
        var float prevTop = na
        var float prevLow = na
        var int prevTs = na
        
        string labelSize = tableTextSize == "Tiny" ? size.tiny : tableTextSize == "Small" ? size.small : tableTextSize == "Large" ? size.large : size.normal
        
        for i = 0 to dataSize - 1
            string dateStr = array.get(dates, i)
            float topVal = array.get(highs, i)
            float lowVal = array.get(lows, i)
            int anchorTs = parseDate(dateStr)
            
            if not na(anchorTs) and not na(topVal) and not na(lowVal)
                int boxStart = anchorTs - (24 * 60 * 60 * 1000)
                
                // Draw zone
                if showZones
                    box.new(boxStart, topVal, anchorTs, lowVal, xloc=xloc.bar_time, border_color=color.new(zoneColor, 100), bgcolor=zoneColor)
                
                // Draw connecting lines
                if not na(prevTs)
                    line.new(prevTs, prevTop, anchorTs, topVal, xloc=xloc.bar_time, color=topColor, width=lineThickness, style=pineLineStyle)
                    line.new(prevTs, prevLow, anchorTs, lowVal, xloc=xloc.bar_time, color=lowColor, width=lineThickness, style=pineLineStyle)
                
                // Labels on last point only
                if i == dataSize - 1 and showLabels
                    string topText = showPrices ? "R: " + str.tostring(topVal) : "R"
                    string lowText = showPrices ? "S: " + str.tostring(lowVal) : "S"
                    label.new(anchorTs, topVal, topText, xloc=xloc.bar_time, color=topColor, textcolor=color.white, style=label.style_label_left, size=labelSize == size.tiny ? size.tiny : labelSize == size.small ? size.small : labelSize == size.large ? size.large : size.normal)
                    label.new(anchorTs, lowVal, lowText, xloc=xloc.bar_time, color=lowColor, textcolor=color.white, style=label.style_label_left, size=labelSize == size.tiny ? size.tiny : labelSize == size.small ? size.small : labelSize == size.large ? size.large : size.normal)
                    
                    lastTop := topVal
                    lastLow := lowVal
                    todayRange := topVal - lowVal
                
                prevTop := topVal
                prevLow := lowVal
                prevTs := anchorTs

// ═══════════════════════════════════════════════════════════════════════════════
// STATISTICS PANEL
// ═══════════════════════════════════════════════════════════════════════════════

if showStats and barstate.islast and show
    var positionSetting = tablePosition == "Top Right" ? position.top_right : tablePosition == "Top Left" ? position.top_left : tablePosition == "Bottom Left" ? position.bottom_left : position.bottom_right
    var tableSize = tableTextSize == "Tiny" ? size.tiny : tableTextSize == "Normal" ? size.normal : tableTextSize == "Large" ? size.large : size.small
    
    var table statsTable = table.new(positionSetting, 2, 6, bgcolor=color.new(#1a1a1a, 5), border_width=2, border_color=color.new(#333333, 0))
    
    table.cell(statsTable, 0, 0, "📊 Options Levels", text_color=color.new(#ffffff, 0), text_size=tableSize, bgcolor=color.new(#2962ff, 20))
    table.merge_cells(statsTable, 0, 0, 1, 0)
    
    if not na(lastTop)
        table.cell(statsTable, 0, 1, "Resistance", text_color=color.new(#cccccc, 0), text_size=tableSize, text_halign=text.align_left)
        table.cell(statsTable, 1, 1, str.tostring(math.round(lastTop, 0)), text_color=color.new(#4caf50, 0), text_size=tableSize, text_halign=text.align_right)
    
    if not na(lastLow)
        table.cell(statsTable, 0, 2, "Support", text_color=color.new(#cccccc, 0), text_size=tableSize, text_halign=text.align_left)
        table.cell(statsTable, 1, 2, str.tostring(math.round(lastLow, 0)), text_color=color.new(#f44336, 0), text_size=tableSize, text_halign=text.align_right)
    
    if not na(todayRange)
        table.cell(statsTable, 0, 3, "Range", text_color=color.new(#cccccc, 0), text_size=tableSize, text_halign=text.align_left)
        table.cell(statsTable, 1, 3, str.tostring(math.round(todayRange, 0)), text_color=color.new(#ffeb3b, 0), text_size=tableSize, text_halign=text.align_right)
    
    if not na(lastTop) and not na(lastLow)
        float pricePos = (close - lastLow) / (lastTop - lastLow) * 100
        string posText = pricePos > 66 ? "🔴 Near R" : pricePos < 33 ? "🟢 Near S" : "⚪ Mid"
        table.cell(statsTable, 0, 4, "Position", text_color=color.new(#cccccc, 0), text_size=tableSize, text_halign=text.align_left)
        table.cell(statsTable, 1, 4, posText + " " + str.tostring(math.round(pricePos, 1)) + "%", text_color=color.new(#ffeb3b, 0), text_size=tableSize, text_halign=text.align_right)
    
    table.cell(statsTable, 0, 5, "Data: " + str.tostring(array.size(DATA_DATES)) + " days", text_color=color.new(#4caf50, 0), text_size=tableSize, text_halign=text.align_center, bgcolor=color.new(#1b5e20, 30))
    table.merge_cells(statsTable, 0, 5, 1, 5)
'''
    
    return pine_script


def main():
    """Main function to fetch data and generate Pine Script."""
    print("=" * 60)
    print("Pine Script Generator - Options Levels Indicator")
    print("=" * 60)
    
    # Load existing data
    historical_data = load_existing_csv()
    print(f"\n📂 Loaded {len(historical_data)} existing data points")
    
    # Fetch new data for recent days
    print(f"\n📊 Fetching data for last {HISTORY_DAYS} days...")
    
    new_data_count = 0
    for days_ago in range(HISTORY_DAYS, -1, -1):
        target_date = datetime.now(timezone.utc) + timedelta(days=1) - timedelta(days=days_ago)
        date_str = target_date.strftime("%d/%m/%Y")
        
        # Skip if we already have this date
        if date_str in historical_data:
            continue
        
        # Fetch data for the day before (orders placed on day before for this expiry)
        fetch_date = target_date - timedelta(days=1)
        from_ts = int(fetch_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        to_ts = int(fetch_date.replace(hour=23, minute=59, second=59).timestamp() * 1000)
        
        csv_data = fetch_options_data(from_ts, to_ts)
        
        if csv_data:
            expiry_code = get_expiry_code_for_date(target_date)
            low, high = parse_and_calculate_for_expiry(csv_data, expiry_code)
            
            if high is not None and low is not None:
                historical_data[date_str] = (high, low)
                new_data_count += 1
                print(f"   ✓ {date_str}: {low:,} - {high:,}")
    
    print(f"\n✅ Total data points: {len(historical_data)}")
    print(f"   New data added: {new_data_count}")
    
    # Save CSV
    save_csv(historical_data)
    print(f"\n💾 Saved to {OUTPUT_CSV}")
    
    # Generate Pine Script
    print(f"\n📝 Generating Pine Script...")
    pine_script = generate_pine_script(historical_data)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PINE, 'w') as f:
        f.write(pine_script)
    
    print(f"✅ Pine Script saved to {OUTPUT_PINE}")
    print(f"   Lines of code: {len(pine_script.splitlines())}")
    
    print("\n" + "=" * 60)
    print("Done! Users can now copy the Pine Script from:")
    print(f"  {OUTPUT_PINE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
