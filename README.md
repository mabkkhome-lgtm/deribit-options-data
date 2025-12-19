# Deribit Options Data Automation

Automatically fetches BTC options data from Deribit and prepares it for the TradingView Options Levels Tracker indicator.

## Quick Start

### 1. Test Locally

```bash
cd /Users/mat/Desktop/indicator/Thales/automation
pip install requests
python fetch_deribit.py
```

This will create `data/btc_levels.csv` with today's levels.

### 2. Set Up GitHub Repository

1. Create a new **public** GitHub repository (e.g., `deribit-options-data`)

2. Copy these files to your repo:
   ```
   deribit-options-data/
   ├── fetch_deribit.py
   ├── data/
   │   └── btc_levels.csv
   └── .github/
       └── workflows/
           └── update_data.yml
   ```

3. Push to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/deribit-options-data.git
   git push -u origin main
   ```

4. Enable GitHub Actions (Settings → Actions → General → Allow all actions)

### 3. Update TradingView Indicator

Add this code to your Pine Script indicator to fetch data automatically:

```pine
// Fetch from GitHub (replace YOUR_USERNAME with your GitHub username)
[date, high, low, bg, sg] = request.seed("YOUR_USERNAME", "deribit-options-data", "btc_levels", input.string("BTC"))
```

## Data Format

The script outputs CSV in this format:

```csv
date,high,low,buyerGamma,sellerGamma
18/12/2024,98500,95200,99000,94500
19/12/2024,99200,95800,99800,95000
```

| Column | Description |
|--------|-------------|
| `date` | Date in DD/MM/YYYY format |
| `high` | Resistance level (Call Wall - strike with highest Call OI) |
| `low` | Support level (Put Wall - strike with highest Put OI) |
| `buyerGamma` | Strike with maximum positive GEX (gamma exposure) |
| `sellerGamma` | Strike with maximum negative GEX |

## How It Works

1. **Deribit API** - Fetches all active BTC options (public, no auth needed)
2. **Call Wall** - Finds strike with highest Call open interest → Resistance
3. **Put Wall** - Finds strike with highest Put open interest → Support
4. **Gamma Exposure** - Calculates GEX for each strike to find gamma walls
5. **Output** - Saves to CSV compatible with TradingView indicator

## Schedule

GitHub Actions runs every 4 hours:
- 00:00 UTC
- 04:00 UTC
- 08:00 UTC
- 12:00 UTC
- 16:00 UTC
- 20:00 UTC

You can also trigger manually from the Actions tab.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No data appearing | Check GitHub Actions logs for errors |
| Old data | Manually trigger workflow from Actions tab |
| Wrong levels | Verify Deribit API is accessible |
| TradingView not updating | `request.seed()` refreshes every 5-15 mins |

## Files

| File | Purpose |
|------|---------|
| `fetch_deribit.py` | Main Python script |
| `data/btc_levels.csv` | Output data file |
| `.github/workflows/update_data.yml` | Automation schedule |
