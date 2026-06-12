# ah_flipper.py
import requests
import time
import os
import json
import re
from statistics import median

AH_DISCORD_WEBHOOK_URL = os.getenv("AH_DISCORD_WEBHOOK_URL")
print("AH webhook loaded:", bool(AH_DISCORD_WEBHOOK_URL), flush=True)

ALERT_FILE = "ah_alerted.json"
HISTORY_FILE = "ah_history.json"

MIN_REAL_PROFIT = 3_000_000
MIN_DISCOUNT_PERCENT = 10
MAX_PRICE = 250_000_000
SCAN_INTERVAL = 300

MIN_LISTINGS = 5
ALERT_COOLDOWN = 1800
AH_TAX_RATE = 0.02

BAD_WORDS = [
    "Skin", "Dye", "Rune", "Furniture", "Cake Soul",
    "New Year Cake", "Century Cake", "Edition",
]

BAD_ITEMS = [
    "Training Weight", "Beating Heart", "Premium Flesh",
]


def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def clean_lore(lore):
    if not lore:
        return ""
    lore = re.sub(r"§.", "", lore)
    return lore


def extract_stars(name, lore):
    text = name + " " + lore
    return text.count("✪") + text.count("➊") + text.count("➋") + text.count("➌") + text.count("➍") + text.count("➎")


def extract_pet_level(name, lore):
    match = re.search(r"\[Lvl (\d+)\]", name)
    if match:
        return int(match.group(1))
    return None


def is_recomb(lore):
    return "RECOMBOBULATED" in lore.upper() or "recombobulated" in lore.lower()


def extract_attributes(lore):
    attrs = []
    for line in lore.split("\n"):
        line_clean = line.strip()
        if "Attribute" in line_clean or re.search(r"\b[A-Z][a-z]+ [IVX]+\b", line_clean):
            attrs.append(line_clean[:40])
    return "|".join(attrs[:4])


def make_item_key(auction):
    name = auction.get("item_name", "")
    lore = clean_lore(auction.get("item_lore", ""))
    tier = auction.get("tier", "")
    category = auction.get("category", "")

    pet_level = extract_pet_level(name, lore)
    stars = extract_stars(name, lore)
    recomb = is_recomb(lore)
    attributes = extract_attributes(lore)

    # Remove pet level from grouping name so lvl gets grouped separately below
    base_name = re.sub(r"\[Lvl \d+\]\s*", "", name)

    return f"{base_name}|tier={tier}|cat={category}|stars={stars}|recomb={recomb}|pet={pet_level}|attrs={attributes}"


def is_bad_item(name):
    if any(word in name for word in BAD_WORDS):
        return True
    if any(item in name for item in BAD_ITEMS):
        return True
    return False


def get_all_auctions():
    first = requests.get(
        "https://api.hypixel.net/v2/skyblock/auctions?page=0",
        timeout=20
    ).json()

    total_pages = first["totalPages"]
    auctions = first["auctions"]

    for page in range(1, total_pages):
        print(f"Fetching AH page {page}/{total_pages - 1}", flush=True)

        data = requests.get(
            f"https://api.hypixel.net/v2/skyblock/auctions?page={page}",
            timeout=20
        ).json()

        auctions.extend(data["auctions"])
        time.sleep(0.15)

    return auctions


def calculate_confidence(listing_count, second_low, median_price, discount, real_profit, repeated_count):
    confidence = 0

    if listing_count >= 12:
        confidence += 1
    if listing_count >= 20:
        confidence += 1
    if second_low >= median_price * 0.90:
        confidence += 2
    if discount >= 25:
        confidence += 2
    if real_profit >= 15_000_000:
        confidence += 2
    if repeated_count >= 2:
        confidence += 1
    if repeated_count >= 3:
        confidence += 1

    return confidence


def send_alert(item_name, price, second_low, median_price, real_profit, discount, uuid, listing_count, confidence, repeated_count):
    if not AH_DISCORD_WEBHOOK_URL:
        print("No Discord webhook set.", flush=True)
        return

    tax = median_price * AH_TAX_RATE

    msg = {
        "content": (
            f"🏷️ **AH Flip Alert**\n"
            f"**Item:** {item_name}\n\n"

            f"**Quantity to Buy:** 1\n"
            f"**Coins Needed:** {price:,.0f}\n\n"

            f"**Lowest BIN:** {price:,.0f}\n"
            f"**Second Lowest BIN:** {second_low:,.0f}\n"
            f"**Estimated Sell Value:** {median_price:,.0f}\n"
            f"**Estimated AH Tax:** {tax:,.0f}\n"
            f"**Estimated Real Profit:** {real_profit:,.0f}\n"
            f"**Discount:** {discount:.2f}%\n\n"

            f"**Listings Found:** {listing_count}\n"
            f"**Confidence:** {confidence}/8\n"
            f"**Seen In Recent Scans:** {repeated_count}\n\n"

            f"✅ Before buying:\n"
            f"1. Check enchants/stars/attributes/pet level.\n"
            f"2. Make sure lowest BIN is still there.\n"
            f"3. Make sure second-lowest did not drop.\n"
            f"4. Do not buy if the item looks weird or dead.\n\n"

            f"UUID: `{uuid}`"
        )
    }

    response = requests.post(AH_DISCORD_WEBHOOK_URL, json=msg, timeout=10)

    if response.status_code in [200, 204]:
        print(f"Discord alert sent: {item_name}", flush=True)
    else:
        print(f"Discord failed: {response.status_code} {response.text}", flush=True)


def scan_ah():
    auctions = get_all_auctions()
    print(f"Loaded {len(auctions):,} auctions", flush=True)

    bins_by_key = {}

    for auction in auctions:
        if not auction.get("bin"):
            continue

        name = auction.get("item_name")
        price = auction.get("starting_bid", 0)

        if not name:
            continue

        if is_bad_item(name):
            continue

        if price <= 0 or price > MAX_PRICE:
            continue

        key = make_item_key(auction)
        bins_by_key.setdefault(key, []).append(auction)

    alerted = load_json(ALERT_FILE)
    history = load_json(HISTORY_FILE)
    now = time.time()

    found = 0

    for key, items in bins_by_key.items():
        if len(items) < MIN_LISTINGS:
            continue

        sorted_items = sorted(items, key=lambda x: x["starting_bid"])
        prices = [a["starting_bid"] for a in sorted_items]

        low = prices[0]
        second_low = prices[1]
        med = median(prices[:10])

        if med <= 0:
            continue

        tax = med * AH_TAX_RATE
        real_profit = med - low - tax
        discount = ((med - low) / med) * 100

        if second_low < med * 0.75:
            continue

        if second_low - low < MIN_REAL_PROFIT * 0.4:
            continue

        if real_profit < MIN_REAL_PROFIT:
            continue

        if discount < MIN_DISCOUNT_PERCENT:
            continue

        cheapest = sorted_items[0]
        uuid = cheapest["uuid"]
        name = cheapest.get("item_name", "Unknown Item")

        history[key] = history.get(key, 0) + 1
        repeated_count = history[key]

        confidence = calculate_confidence(
            len(items),
            second_low,
            med,
            discount,
            real_profit,
            repeated_count
        )

        if confidence < 3:
            print(
                f"Risky skip: {name} | profit={real_profit:,.0f} | "
                f"confidence={confidence}/8 | listings={len(items)}",
                flush=True
            )
            continue

        if now - alerted.get(uuid, 0) < ALERT_COOLDOWN:
            continue

        found += 1

        print(
            f"SAFE AH flip: {name} | "
            f"buy={low:,} | second={second_low:,} | "
            f"value={med:,} | real_profit={real_profit:,.0f} | "
            f"confidence={confidence}/8 | listings={len(items)}",
            flush=True
        )

        send_alert(
            name,
            low,
            second_low,
            med,
            real_profit,
            discount,
            uuid,
            len(items),
            confidence,
            repeated_count
        )

        alerted[uuid] = now

    save_json(ALERT_FILE, alerted)
    save_json(HISTORY_FILE, history)

    print(f"AH scan complete. Alerts found: {found}", flush=True)


while True:
    try:
        scan_ah()
    except Exception as e:
        print(f"AH scanner error: {e}", flush=True)

    time.sleep(SCAN_INTERVAL)