"""
Venom Skateboards — Container Forecast Stock Refresh
=====================================================
Pulls live stock levels from Linnworks for all 78 Venom SKUs,
then rewrites index.html with the updated data.

Run locally:   python refresh_stock.py
Run via CI:    set env vars LINNWORKS_APP_ID, LINNWORKS_APP_SECRET, LINNWORKS_TOKEN

Linnworks credentials:
  - Go to https://developer.linnworks.com
  - Your app's Application ID and Application Secret are under Edit Application → General
  - The Token is the static token you received when you installed the app on your account
"""

import os, re, json, time, datetime, requests

# ── Credentials (from environment variables / GitHub Secrets) ──────────────
APP_ID     = os.environ["LINNWORKS_APP_ID"]
APP_SECRET = os.environ["LINNWORKS_APP_SECRET"]
TOKEN      = os.environ["LINNWORKS_TOKEN"]

DEFAULT_LOC_ID = "00000000-0000-0000-0000-000000000000"

SKUS = [
    "ven-20-black-raw-core-complete-8.0",
    "ven-20-natural-raw-core-complete-8.5",
    "ven-20-natural-raw-core-complete-7.75",
    "vnm-mid-galaxy",
    "vnm-catnip-MID",
    "vnm-skullspots-teal-MID",
    "vnm-sun-moon-black-MID",
    "vnm-cat-pink-JNR",
    "vnm-dragon-blue-MFS",
    "vnm-jnr-desert-viper",
    "vnm-jnr-ice-fab",
    "vnm-jnr-melons",
    "vnm-jnr-unicorn",
    "vnm-kittypaw-purple-JNR",
    "vnm-kittyswipe-blue-JNR",
    "vnm-robodino-red-MFS",
    "vnm-skull-black-JNR",
    "vnm-unicorn-flip-JNR",
    "vnm-unicorn-night-JNR",
    "vnm-deck-gold",
    "vnm-deck-mattblack",
    "vnm-deck-mattwhite",
    'vnm_blank_black-8.0"',
    'vnm_blank_black-8.25"',
    'vnm_blank_black-8.5"',
    'vnm_blank_nat-8.0"',
    'vnm_blank_nat-8.25"',
    'vnm_blank_nat-8.5"',
    "swh_abec11",
    "swh_abec9",
    "blackgrip-9x33",
    "vnm-gt-clear",
    "venom-skate-lube",
    "ven-grip-cleaner",
    "ven_hardware",
    "venom-ttool-black",
    "vnm-premiumgiftpack",
    "vnm-premiumXLgiftpack",
    "vnm-ultimategiftpack",
    "venom-helmet-Small",
    "venom-helmet-Medium",
    "venom-helmet-Large",
    "vnm-helmet-pink-small",
    "vnm-helmet-pink-medium",
    "vnm-helmet-red-small",
    "vnm-helmet-red-medium",
    "venom-triplepads-adult",
    "vnm-triplepads-blueblack-jnr",
    "vnm-triplepads-pinkwhite-jnr",
    "vnm-triplepads-redblack-jnr",
    "vnm_uc_BLT-raw-5.0",
    "vnm_uc_BLT-raw-5.25",
    "ven-20-black-raw-core-complete-7.75",
    "ven-20-black-raw-core-complete-8.25",
    "ven-20-natural-raw-core-complete-8.0",
    "ven-20-natural-raw-core-complete-8.25",
    "vnm-jnr-abominable",
    "vnm-jnr-funghoul",
    "vnm-jnr-party-parrot",
    "vnm-jnr-patchwork",
    "vnm-jnr-pizza",
    "vnm-jnr-rainbow-uni",
    "vnm-mid-astro",
    "vnm-mid-cloudkicker",
    "vnm-mid-houndstooth",
    "vnm-mid-riptide",
    "vnm-mid-robo-kitty",
    "vnm-mid-seagull",
    "vnm-mid-slime",
    "vnm-mid-street-dreams",
    "vnm-mid-wildcat",
    "vnm-mfs-astro",
    "vnm-mfs-pizza",
    "vnm-mfs-street-dreams",
    "vnm-mfs-wildcat",
    "vnm-skull-jnr",
    "vnm-skull-mid",
    "vnm-skull-mfs",
    "vnm-skull-ppro",
]


def authenticate():
    """Authenticate with Linnworks and return (session_token, server_url)."""
    print("Authenticating with Linnworks...")
    resp = requests.post(
        "https://api.linnworks.net/api/Auth/AuthorizeByApplication",
        data={
            "applicationId":     APP_ID,
            "applicationSecret": APP_SECRET,
            "token":             TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token  = data["Token"]
    server = data["Server"]
    print(f"  Authenticated. Server: {server}")
    return token, server


def get_inventory_item_id(server, token, sku):
    """Return the Linnworks inventory item GUID for a given SKU, or None."""
    resp = requests.post(
        f"{server}/api/Inventory/GetInventoryItemBysku",
        headers={"Authorization": token},
        data={"sku": sku},
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    # Response is an object with StockItemId field
    return data.get("StockItemId") or data.get("Id")


def get_default_stock(server, token, item_id):
    """Return Default-location stock level for the given inventory item GUID."""
    resp = requests.post(
        f"{server}/api/Stock/GetStockLevel",
        headers={"Authorization": token},
        data={"inventoryItemId": item_id},
        timeout=20,
    )
    if resp.status_code != 200:
        return 0
    locations = resp.json()
    if not isinstance(locations, list):
        locations = locations.get("Locations", [])
    for loc in locations:
        loc_id = (
            loc.get("Location", {}).get("StockLocationId")
            or loc.get("StockLocationId")
            or loc.get("LocationId", "")
        )
        if loc_id == DEFAULT_LOC_ID:
            return max(0, int(loc.get("StockLevel", 0) or loc.get("Available", 0) or 0))
    return 0


def fetch_all_stock():
    """Return dict of {sku: stock_level} for all SKUs."""
    token, server = authenticate()
    results = {}
    errors  = []

    for i, sku in enumerate(SKUS):
        print(f"  [{i+1}/{len(SKUS)}] {sku}", end=" ... ")
        try:
            item_id = get_inventory_item_id(server, token, sku)
            if item_id:
                stock = get_default_stock(server, token, item_id)
                results[sku] = stock
                print(f"{stock}")
            else:
                results[sku] = 0
                print("not found (0)")
                errors.append(sku)
        except Exception as e:
            results[sku] = 0
            print(f"ERROR: {e}")
            errors.append(sku)
        # Respect rate limit: 150 calls/min = ~0.4s between pairs of calls
        time.sleep(0.5)

    return results, errors


def update_html(stock_data):
    """Read index.html, update the RAW JSON stock values, write back."""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    m = re.search(r"RAW = (\{.*?\});", html, re.DOTALL)
    if not m:
        raise RuntimeError("Could not find RAW JSON in index.html")

    raw = json.loads(m.group(1))

    for sku_obj in raw["skus"]:
        sku = sku_obj["sku"]
        if sku in stock_data:
            new_stock = stock_data[sku]
            sku_obj["stock"] = new_stock
            # Recalculate downstream
            demand     = sku_obj.get("demand", 0)
            carton_qty = sku_obj.get("carton_qty", 1) or 1
            cbm_carton = sku_obj.get("cbm_carton", 0)
            cost_usd   = sku_obj.get("cost_usd", 0)
            net        = max(0, demand - new_stock)
            cartons    = round(net / carton_qty)
            sku_obj["net_order"]  = net
            sku_obj["cartons"]    = cartons
            sku_obj["order_cbm"]  = round(cartons * cbm_carton, 4)
            sku_obj["order_cost"] = round(cartons * carton_qty * cost_usd, 2)

    # Update last-refreshed timestamp in header
    now_str = datetime.datetime.utcnow().strftime("%-d %b %Y")
    html = re.sub(
        r'id="data-date">[^<]*<',
        f'id="data-date">{now_str}<',
        html,
    )

    new_raw = json.dumps(raw, separators=(",", ":"))
    html = re.sub(r"RAW = \{.*?\};", f"RAW = {new_raw};", html, flags=re.DOTALL)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return raw


def print_summary(raw, errors):
    skus = raw["skus"]
    need = [s for s in skus if s["net_order"] > 0]
    total_cbm  = sum(s["order_cbm"]  for s in need)
    total_cost = sum(s["order_cost"] for s in need)
    print("\n" + "=" * 50)
    print("REFRESH COMPLETE")
    print(f"  SKUs updated:       {len(skus)}")
    print(f"  SKUs needing order: {len(need)}")
    print(f"  Total CBM:          {total_cbm:.1f}")
    print(f"  Total order cost:   ${total_cost:,.0f}")
    if errors:
        print(f"  Errors ({len(errors)}): {', '.join(errors)}")
    print("=" * 50)


if __name__ == "__main__":
    stock_data, errors = fetch_all_stock()
    raw = update_html(stock_data)
    print_summary(raw, errors)
