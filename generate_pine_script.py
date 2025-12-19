#!/usr/bin/env python3
"""
Pine Script Generator - Fixed Version
======================================
Generates a Pine Script indicator with historical data embedded.
"""

import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Output Configuration
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_PINE = OUTPUT_DIR / "options_levels_indicator.pine"
OUTPUT_CSV = OUTPUT_DIR / "btc_levels.csv"


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
                    data[parts[0]] = (int(float(parts[1])), int(float(parts[2])))
    return data


def generate_pine_script(historical_data):
    """Generate complete Pine Script with embedded data."""
    
    # Sort data by date
    sorted_dates = sorted(historical_data.keys(), key=lambda x: datetime.strptime(x, "%d/%m/%Y"))
    
    # Keep last 90 days to avoid script being too large
    if len(sorted_dates) > 90:
        sorted_dates = sorted_dates[-90:]
    
    # Get the latest data
    latest_date = sorted_dates[-1] if sorted_dates else "01/01/2025"
    latest_high = historical_data[latest_date][0] if sorted_dates else 100000
    latest_low = historical_data[latest_date][1] if sorted_dates else 85000
    
    # Generate the data initialization code - split into multiple lines to avoid line length issues
    dates_init = ""
    highs_init = ""
    lows_init = ""
    
    for i, d in enumerate(sorted_dates):
        high, low = historical_data[d]
        if i == 0:
            dates_init += f'array.push(dates, "{d}")\n'
            highs_init += f'array.push(highs, {high}.0)\n'
            lows_init += f'array.push(lows, {low}.0)\n'
        else:
            dates_init += f'    array.push(dates, "{d}")\n'
            highs_init += f'    array.push(highs, {high}.0)\n'
            lows_init += f'    array.push(lows, {low}.0)\n'
    
    pine_script = f'''//@version=5
indicator("Options Levels Tracker", overlay=true, max_lines_count=500, max_labels_count=50, max_boxes_count=50)

// ═══════════════════════════════════════════════════════════════════════════════
// OPTIONS LEVELS TRACKER
// Auto-Generated with {len(sorted_dates)} days of historical data
// Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}
// https://github.com/mabkkhome-lgtm/deribit-options-data
// ═══════════════════════════════════════════════════════════════════════════════

// Settings
string showOn = input.string("BTCUSDT", "Chart Symbol", group="⚙️ Settings")
color topColor = input.color(#00ff00, "Resistance Color", group="⚙️ Settings")
color lowColor = input.color(#ff0000, "Support Color", group="⚙️ Settings")
color zoneColor = input.color(color.new(#2962ff, 90), "Zone Fill", group="⚙️ Settings")
int lineThickness = input.int(2, "Line Width", minval=1, maxval=5, group="⚙️ Settings")
bool showZones = input.bool(true, "Show Zones", group="⚙️ Settings")
bool showLabels = input.bool(true, "Show Labels", group="⚙️ Settings")
bool showStats = input.bool(true, "Show Stats Panel", group="⚙️ Settings")
string tablePosition = input.string("Bottom Right", "Table Position", options=["Top Right", "Top Left", "Bottom Right", "Bottom Left"], group="⚙️ Settings")

// Manual Override (for real-time updates)
bool useOverride = input.bool(false, "Use Manual Override", group="📊 Manual Override")
float overrideHigh = input.float({latest_high}, "Today's Resistance", group="📊 Manual Override")
float overrideLow = input.float({latest_low}, "Today's Support", group="📊 Manual Override")

// ═══════════════════════════════════════════════════════════════════════════════
// EMBEDDED DATA - {len(sorted_dates)} days
// ═══════════════════════════════════════════════════════════════════════════════

var array<string> dates = array.new_string()
var array<float> highs = array.new_float()
var array<float> lows = array.new_float()
var bool dataLoaded = false

if not dataLoaded
    {dates_init.rstrip()}
    {highs_init.rstrip()}
    {lows_init.rstrip()}
    dataLoaded := true

// ═══════════════════════════════════════════════════════════════════════════════
// DRAWING
// ═══════════════════════════════════════════════════════════════════════════════

bool show = syminfo.ticker == showOn

parseDate(string dateStr) =>
    result = int(na)
    parts = str.split(dateStr, "/")
    if array.size(parts) == 3
        dd = int(str.tonumber(array.get(parts, 0)))
        mm = int(str.tonumber(array.get(parts, 1)))
        yy = int(str.tonumber(array.get(parts, 2)))
        if yy < 100
            yy := yy + 2000
        result := timestamp(yy, mm, dd, 0, 0, 0)
    result

var float lastTop = na
var float lastLow = na

if barstate.islast and show
    int dataSize = array.size(dates)
    
    // Add override if enabled
    if useOverride
        lastTop := overrideHigh
        lastLow := overrideLow
    
    if dataSize > 0
        float prevTop = na
        float prevLow = na
        int prevTs = na
        
        for i = 0 to dataSize - 1
            string dateStr = array.get(dates, i)
            float topVal = array.get(highs, i)
            float lowVal = array.get(lows, i)
            int anchorTs = parseDate(dateStr)
            
            if not na(anchorTs) and not na(topVal) and not na(lowVal)
                int boxStart = anchorTs - 86400000  // 24 hours in ms
                
                // Draw zone
                if showZones
                    box.new(boxStart, topVal, anchorTs, lowVal, xloc=xloc.bar_time, border_color=color.new(zoneColor, 100), bgcolor=zoneColor)
                
                // Draw connecting lines
                if not na(prevTs)
                    line.new(prevTs, prevTop, anchorTs, topVal, xloc=xloc.bar_time, color=topColor, width=lineThickness)
                    line.new(prevTs, prevLow, anchorTs, lowVal, xloc=xloc.bar_time, color=lowColor, width=lineThickness)
                
                // Labels on last point only
                if i == dataSize - 1 and showLabels
                    label.new(anchorTs, topVal, "R: " + str.tostring(topVal, "#"), xloc=xloc.bar_time, color=topColor, textcolor=color.white, style=label.style_label_left, size=size.small)
                    label.new(anchorTs, lowVal, "S: " + str.tostring(lowVal, "#"), xloc=xloc.bar_time, color=lowColor, textcolor=color.white, style=label.style_label_left, size=size.small)
                    lastTop := topVal
                    lastLow := lowVal
                
                prevTop := topVal
                prevLow := lowVal
                prevTs := anchorTs

// ═══════════════════════════════════════════════════════════════════════════════
// STATS PANEL
// ═══════════════════════════════════════════════════════════════════════════════

if showStats and barstate.islast and show
    positionSetting = tablePosition == "Top Right" ? position.top_right : tablePosition == "Top Left" ? position.top_left : tablePosition == "Bottom Left" ? position.bottom_left : position.bottom_right
    
    var table statsTable = table.new(positionSetting, 2, 5, bgcolor=color.new(#1a1a1a, 5), border_width=1, border_color=color.new(#333333, 0))
    
    table.cell(statsTable, 0, 0, "📊 Options Levels", text_color=#ffffff, text_size=size.small, bgcolor=color.new(#2962ff, 20))
    table.merge_cells(statsTable, 0, 0, 1, 0)
    
    if not na(lastTop)
        table.cell(statsTable, 0, 1, "Resistance", text_color=#cccccc, text_size=size.small, text_halign=text.align_left)
        table.cell(statsTable, 1, 1, str.tostring(lastTop, "#"), text_color=#4caf50, text_size=size.small, text_halign=text.align_right)
    
    if not na(lastLow)
        table.cell(statsTable, 0, 2, "Support", text_color=#cccccc, text_size=size.small, text_halign=text.align_left)
        table.cell(statsTable, 1, 2, str.tostring(lastLow, "#"), text_color=#f44336, text_size=size.small, text_halign=text.align_right)
    
    if not na(lastTop) and not na(lastLow)
        table.cell(statsTable, 0, 3, "Range", text_color=#cccccc, text_size=size.small, text_halign=text.align_left)
        table.cell(statsTable, 1, 3, str.tostring(lastTop - lastLow, "#"), text_color=#ffeb3b, text_size=size.small, text_halign=text.align_right)
        
        pricePos = (close - lastLow) / (lastTop - lastLow) * 100
        posText = pricePos > 66 ? "🔴 Near R" : pricePos < 33 ? "🟢 Near S" : "⚪ Mid"
        table.cell(statsTable, 0, 4, posText, text_color=#ffeb3b, text_size=size.small, text_halign=text.align_center, bgcolor=color.new(#1b5e20, 30))
        table.merge_cells(statsTable, 0, 4, 1, 4)
'''
    
    return pine_script


def main():
    """Main function."""
    print("=" * 60)
    print("Pine Script Generator - Fixed Version")
    print("=" * 60)
    
    # Load existing data
    historical_data = load_existing_csv()
    print(f"\n📂 Loaded {len(historical_data)} data points")
    
    # Generate Pine Script
    print(f"\n📝 Generating Pine Script...")
    pine_script = generate_pine_script(historical_data)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PINE, 'w') as f:
        f.write(pine_script)
    
    print(f"✅ Pine Script saved to {OUTPUT_PINE}")
    print(f"   Lines of code: {len(pine_script.splitlines())}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
