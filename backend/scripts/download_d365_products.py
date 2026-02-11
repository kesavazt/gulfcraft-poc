"""
Download Products from D365 Finance & Operations OData API.

Authenticates via OAuth2 client credentials and fetches ProductsV2
with ReleasedProducts expanded. Handles pagination automatically.

Usage:
    python scripts/download_d365_products.py
    python scripts/download_d365_products.py --output Products.json
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR.parent / ".env")

# D365 config from environment
D365_TENANT_ID = os.getenv("D365_TENANT_ID", "")
D365_CLIENT_ID = os.getenv("D365_CLIENT_ID", "")
D365_CLIENT_SECRET = os.getenv("D365_CLIENT_SECRET", "")
D365_BASE_URL = os.getenv(
    "D365_API_URL",
    "https://gcdev06a48d842c8e439bc1devaos.cloudax.uae.dynamics.com"
)

TOKEN_URL = f"https://login.microsoftonline.com/{D365_TENANT_ID}/oauth2/v2.0/token"

PRODUCTS_URL = (
    f"{D365_BASE_URL}/data/ProductsV2"
    f"?cross-company=true"
    f"&$expand=ReleasedProducts($select=UnitCost,ItemNumber)"
    f"&$select=ProductNumber,ProductDescription"
)


def get_access_token() -> str:
    """Get OAuth2 access token using client credentials flow."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": D365_CLIENT_ID,
        "client_secret": D365_CLIENT_SECRET,
        "scope": f"{D365_BASE_URL}/.default",
    }

    resp = requests.post(TOKEN_URL, data=payload, timeout=30)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {resp.json()}")
    return token


def fetch_all_pages(url: str, headers: dict) -> list:
    """Fetch all pages of an OData response following @odata.nextLink."""
    all_records = []
    page = 1

    while url:
        print(f"  Fetching page {page}...")
        resp = requests.get(url, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        records = data.get("value", [])
        all_records.extend(records)
        print(f"  Got {len(records)} records (total: {len(all_records)})")

        url = data.get("@odata.nextLink")
        page += 1

    return all_records


def main():
    parser = argparse.ArgumentParser(description="Download D365 Products")
    parser.add_argument(
        "--output", "-o",
        default=str(BASE_DIR / "scripts" / "Products.json"),
        help="Output JSON file path",
    )
    args = parser.parse_args()

    # Validate credentials
    missing = []
    if not D365_TENANT_ID or D365_TENANT_ID == "your_tenant_id":
        missing.append("D365_TENANT_ID")
    if not D365_CLIENT_ID or D365_CLIENT_ID == "your_d365_client_id":
        missing.append("D365_CLIENT_ID")
    if not D365_CLIENT_SECRET or D365_CLIENT_SECRET == "your_d365_client_secret":
        missing.append("D365_CLIENT_SECRET")

    if missing:
        print(f"ERROR: Missing D365 credentials in .env: {', '.join(missing)}")
        print("Please update your .env file with valid D365 credentials.")
        sys.exit(1)

    print(f"D365 Base URL: {D365_BASE_URL}")
    print("Authenticating...")
    token = get_access_token()
    print("Authenticated successfully.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    print(f"\nFetching products from: {PRODUCTS_URL[:80]}...")
    products = fetch_all_pages(PRODUCTS_URL, headers)
    print(f"\nTotal products downloaded: {len(products)}")

    output_data = {"value": products}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Saved to: {args.output}")


if __name__ == "__main__":
    main()
