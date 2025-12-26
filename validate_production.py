#!/usr/bin/env python3
"""
PRODUCTION VALIDATION TEST
Compares deribit_fetcher.py output with your trusted fetch_historical.py
"""
import subprocess
import sys

print("="*70)
print("PRODUCTION VALIDATION TEST")
print("="*70)
print("\nRunning BOTH scripts and comparing outputs...\n")

# Run deribit_fetcher.py (production)
print("1. Running deribit_fetcher.py (PRODUCTION)...")
result1 = subprocess.run(
    ["python3", "deribit_fetcher.py"],
    capture_output=True,
    text=True
)

if "✅" in result1.stdout:
    prod_line = [l for l in result1.stdout.split('\n') if '✅' in l][0]
    prod_r = int(prod_line.split('R=')[1].split(',')[0])
    prod_s = int(prod_line.split('S=')[1].split('\n')[0])
    print(f"   Result: R={prod_r:,}, S={prod_s:,}")
else:
    print("   ERROR: Production script failed")
    print(result1.stdout)
    sys.exit(1)

# Run calculate_now.py (fetch_historical.py logic test)
print("\n2. Running calculate_now.py (fetch_historical.py logic)...")
result2 = subprocess.run(
    ["python3", "calculate_now.py"],
    capture_output=True,
    text=True
)

if "R=" in result2.stdout:
    lines = result2.stdout.split('\n')
    for line in lines:
        if 'R=' in line and 'S=' in line:
            test_r = int(line.split('R=')[1].split(',')[0])
            test_s = int(line.split('S=')[1].split(',')[0])
            print(f"   Result: R={test_r:,}, S={test_s:,}")
            break
else:
    print("   ERROR: Test script failed")
    print(result2.stdout)
    sys.exit(1)

# Compare
print("\n" + "="*70)
print("COMPARISON")
print("="*70)

diff_r = abs(prod_r - test_r)
diff_s = abs(prod_s - test_s)
percent_r = (diff_r / prod_r) * 100
percent_s = (diff_s / prod_s) * 100

print(f"R Difference: {diff_r:,} points ({percent_r:.3f}%)")
print(f"S Difference: {diff_s:,} points ({percent_s:.3f}%)")

if diff_r < 100 and diff_s < 100:
    print("\n✅ PASS: Production script matches trusted logic (<100pt variance)")
    print("   The system is PRODUCTION READY")
    sys.exit(0)
elif diff_r < 500 and diff_s < 500:
    print("\n⚠️  ACCEPTABLE: Minor variance (<500pt), likely due to timing")
    print("   The system is acceptable for production")
    sys.exit(0)
else:
    print("\n❌ FAIL: Large variance detected")
    print("   The calculations do NOT match - DO NOT USE IN PRODUCTION")
    sys.exit(1)
