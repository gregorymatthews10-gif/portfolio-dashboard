"""
update_prices.py
Refreshes last_price for every holding in holdings.json using live quotes
from Yahoo Finance, then stamps as_of with today's date.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

HOLDINGS_FILE = Path("holdings.json")


def get_price(ticker: str):
    """Return a live price for ticker, or None if Yahoo has no quote."""
    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.get("last_price") or fi.get("lastPrice")
        if price and price > 0:
            return round(float(price), 4)
    except Exception as e:
        print(f"  ! {ticker}: lookup failed ({e})")
    return None


def main():
    data = json.loads(HOLDINGS_FILE.read_text())

    updated, skipped = 0, []
    for h in data["holdings"]:
        ticker = h["ticker"]
        price = get_price(ticker)
        if price is None:
            skipped.append(ticker)
            print(f"  - {ticker}: kept {h['last_price']} (no quote)")
            continue
        h["last_price"] = price
        updated += 1
        print(f"  + {ticker}: {price}")

    data["as_of"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    HOLDINGS_FILE.write_text(json.dumps(data, indent=2) + "\n")

    print(f"\nUpdated {updated} prices, kept {len(skipped)} "
          f"({', '.join(skipped) or 'none'}). as_of = {data['as_of']}")


if __name__ == "__main__":
    main()
