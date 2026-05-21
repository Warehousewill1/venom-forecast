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

DEFAULT_LOC_ID    = "00000000-0000-0000-0000-000000000000"
VENOM_SUPPLIER_ID = "9a2026ab-8e68-49a2-a3e0-2cc36a41501c"  # Skatewarehouse Ltd

# These 78 SKUs exactly match the dashboard (derived from index.html RAW JSON)
SKUS = [
    "ven-20-black-raw-core-complete-8.0",
    "ven-20-natural-raw-core-complete-8.5",
    "ven-20-natural-raw-core-complete-7.75",
    "vnm-mid-galaxy",
    "vnm-catnip-MID",
    "vnm-skullspots-teal-MID",
    "vnm-sun-moon-black-MID",
    "vnm-cat-pink-JNR",
    "vnm-kittypaw-purple-JNR",
    "vnm-kittyswipe-blue-JNR",
    "vnm-skull-teal-JNR",
    "vnm-skull-black-JNR",
    "vnm-mid-doughnuts",
    "vnm-mid-fadeoutlines",
    "vnm-unicorn-flip-JNR",
    "vnm-jnr-desert-viper",
    "vnm-jnr-ice-fab",
    "vnm-jnr-melons",
    "vnm-jnr-unicorn",
    "vnm-unicorn-night-JNR",
    "vnm_uc_BLT-raw-5.5",
    "vnm_uc_BLT-raw-5.25",
    "vnm_uc_BLT-raw-5.0",
    "vnm-deck-silver",
    "vnm-deck-gold",
    "vnm-dragon-blue-MFS",
    "vnm-football-blues-MFS",
    "vnm-robodino-red-MFS",
    "vnm-football-reds-MFS",
    "vnm-deck-mattblack",
    "vnm-deck-mattwhite",
    'vnm_blank_black-8.25"',
    'vnm_blank_black-8.5"',
    'vnm_blank_black-8.0"',
    'vnm_blank_nat-8.25"',
    'vnm_blank_nat-8.5"',
    'vnm_blank_nat-7.5"',
    'vnm_blank_nat-7.75"',
    'vnm_blank_nat-8.0"',
    "vnm-premiumXLgiftpack",
    "venom-helmet-Small",
    "venom-helmet-Medium",
    "venom-helmet-Large",
    "vnm-helmet-blue-small",
    "vnm-helmet-blue-medium",
    "vnm-helmet-pink-small",
    "vnm-helmet-pink-medium",
    "vnm-helmet-red-small",
    "vnm-helmet-red-medium",
    "venom-triplepads-junior",
    "venom-triplepads-adult",
    "vnm-triplepads-blueblack-jnr",
    "vnm-triplepads-blueblack-adt",
    "vnm-triplepads-pinkwhite-jnr",
    "vnm-triplepads-pinkwhite-adt",
    "vnm-triplepads-redblack-jnr",
    "vnm-triplepads-redblack-adt",
    "vnm-premiumgiftpack",
    "vnm_bearings_gold",
    "vnm_artdeck_8.0",
    "swh_abec11",
    "venom_abec11",
    "swh_abec9",
    "venom_abec9",
    "vnm_tc_wheels_54mm",
    "vnm_tc_wheels_56mm",
    "vnm_tc_wheels_58mm",
    "vnm_tc_wheels_60mm",
    "vnm_tc_wheels_52mm",
    "vnm-ultimategiftpack",
    "vnm_logo_wheel-52mm",
    "venom-ttool-black",
    "ven_ttool",
    "blackgrip-9x33",
    "vnm-gt-clear",
    "venom-skate-lube",
    "ven-grip-cleaner",
    "ven_hardware",
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
        data={"SKU": sku},   # Linnworks requires uppercase SKU
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    return (
        data.get("StockItemId")
        or data.get("pkStockItemId")
        or data.get("Id")
        or data.get("id")
    )


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


def fetch_all_stock(server, token):
    """Return dict of {sku: stock_level} for all SKUs."""
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


def fetch_open_pos(server, token):
    """Return {sku: outstanding_qty} from open Venom (Skatewarehouse Ltd) POs."""
    po_qty = {}
    print("\nFetching open Venom purchase orders...")
    try:
        # Get all open POs
        resp = requests.get(
            f"{server}/api/PurchaseOrder/GetAllPurchaseOrders",
            headers={"Authorization": token},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  ⚠️  PO list HTTP {resp.status_code} — skipping PO data")
            return po_qty

        result = resp.json()
        all_pos = result if isinstance(result, list) else result.get("Data", result.get("PurchaseOrders", []))

        # Filter to Skatewarehouse Ltd open POs only
        venom_pos = [
            po for po in all_pos
            if (po.get("fkSupplierId") or po.get("SupplierId", "")) == VENOM_SUPPLIER_ID
            and (po.get("Status") or po.get("StatusCode", "")).upper() in ("OPEN", "PENDING", "PARTIAL", "2", "1", "3")
        ]
        print(f"  Found {len(venom_pos)} open Venom PO(s)")

        for po in venom_pos:
            po_id = po.get("pkPurchaseId") or po.get("Id", "")
            ref   = po.get("ExternalInvoiceNumber") or po.get("Reference", str(po_id))
            if not po_id:
                continue

            detail_resp = requests.get(
                f"{server}/api/PurchaseOrder/GetPurchaseOrderById",
                headers={"Authorization": token},
                params={"id": po_id},
                timeout=20,
            )
            if detail_resp.status_code != 200:
                print(f"  ⚠️  PO detail {ref} HTTP {detail_resp.status_code} — skipping")
                continue

            detail = detail_resp.json()
            items  = detail.get("Items", detail.get("PurchaseItems", []))
            count  = 0
            for item in items:
                sku         = item.get("SKU") or item.get("sku") or item.get("ItemNumber", "")
                qty         = float(item.get("dQuantity") or item.get("Quantity") or 0)
                delivered   = float(item.get("dDelivered") or item.get("Delivered") or 0)
                outstanding = max(0, int(qty - delivered))
                if sku and outstanding > 0:
                    po_qty[sku] = po_qty.get(sku, 0) + outstanding
                    count += 1
            print(f"  {ref}: {count} SKUs with outstanding qty")

    except Exception as e:
        print(f"  ⚠️  Error fetching POs: {e} — continuing without PO data")

    return po_qty


def update_html(stock_data, po_data=None):
    """Read index.html, update stock + PO quantities in the RAW JSON, write back."""
    if po_data is None:
        po_data = {}

    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    m = re.search(r"RAW = (\{.*?\});", html, re.DOTALL)
    if not m:
        raise RuntimeError("Could not find RAW JSON in index.html")

    raw = json.loads(m.group(1))

    for sku_obj in raw["skus"]:
        sku = sku_obj["sku"]

        live_stock  = stock_data.get(sku, sku_obj.get("stock", 0))
        outstanding = po_data.get(sku, 0)
        total_stock = live_stock + outstanding

        # Update PO fields (always overwrite so removals are reflected)
        sku_obj["po_qty"] = outstanding
        sku_obj["has_po"] = outstanding > 0

        # Update stock = live + PO incoming; recalculate downstream
        sku_obj["stock"] = total_stock
        demand     = sku_obj.get("demand", 0)
        carton_qty = sku_obj.get("carton_qty", 1) or 1
        cbm_carton = sku_obj.get("cbm_carton", 0)
        cost_usd   = sku_obj.get("cost_usd", 0)
        net        = max(0, demand - total_stock)
        cartons    = round(net / carton_qty) if net > 0 else 0
        sku_obj["net_order"]  = net
        sku_obj["cartons"]    = cartons
        sku_obj["order_cbm"]  = round(cartons * cbm_carton, 4)
        sku_obj["order_cost"] = round(cartons * carton_qty * cost_usd, 2)
        if total_stock == 0:
            sku_obj["status"] = "OUT"
        elif total_stock < demand:
            sku_obj["status"] = "LOW"
        else:
            sku_obj["status"] = "OK"

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
    token, server  = authenticate()
    stock_data, errors = fetch_all_stock(server, token)
    po_data        = fetch_open_pos(server, token)
    raw            = update_html(stock_data, po_data)
    print_summary(raw, errors)
