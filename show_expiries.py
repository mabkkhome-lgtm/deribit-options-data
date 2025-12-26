#!/usr/bin/env python3
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

THALES_API = "https://oss.thales-mfi.com/api/MarketScreener/FetchOptions"

now = datetime.now(timezone.utc)
start = now.replace(hour=0, minute=0, second=0, microsecond=0)
end = now

from_ts = int(start.timestamp() * 1000)
to_ts = int(end.timestamp() * 1000)

url = f"{THALES_API}?source=1&fromDate={from_ts}&toDate={to_ts}"
resp = requests.get(url, timeout=30)
lines = resp.text.strip().split('\n')

print(f"Current time: {now}")
print(f"Data window: {start} to {end}")
print(f"Lines fetched: {len(lines)}\n")

# Count volume per expiry
expiry_counts = defaultdict(int)
for line in lines:
    parts = line.split(',')
    if len(parts) >= 7:
        try:
            expiry_code = int(parts[1])
            size = float(parts[5])
            expiry_counts[expiry_code] += size
        except: pass

epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
current_code = (now - epoch).days

print("All available expiries:")
print("-" * 60)
for code in sorted(expiry_counts.keys()):
    exp_date = epoch + timedelta(days=code)
    days_away = code - current_code
    volume = expiry_counts[code]
    print(f"{exp_date.strftime('%d%b%y')} (code {code}): {volume:,.1f} volume, {days_away} days away")

# Show selection logic
valid_expiries = {k: v for k, v in expiry_counts.items() if k > current_code and k <= current_code + 7}
if valid_expiries:
    best = max(valid_expiries.items(), key=lambda x: x[1])[0]
    best_date = epoch + timedelta(days=best)
    print(f"\n✅ Auto-selected: {best_date.strftime('%d%b%y')} (highest volume within 7 days)")
else:
    print("\n⚠️ No expiries within 7 days")
