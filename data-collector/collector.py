import requests
import sqlite3
from datetime import datetime
import time
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "bazaar.db")
ALERT_FILE = os.path.join(BASE_DIR, "alerted.json")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

COLLECT_INTERVAL = 300
COOLDOWN_SECONDS = 30 * 60

# Your bankroll
BANKROLL = 200_000_000

# Whale-mode filters
MIN_SPREAD_PERCENT = 1.5
MAX_SPREAD_PERCENT = 40
MIN_SPREAD_COINS = 2
MIN_DAILY_VOLUME = 2_000
MIN_SAFE_INVESTMENT = 25_000_000
MIN_DAILY_PROFIT_POTENTIAL = 500_000
MAX_ITEM_PRICE = 100_000_000

# Risk control
SAFE_VOLUME_PERCENT = 0.08  # use 8% of estimated daily volume


def create_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS prices (
        timestamp TEXT,
        item TEXT,
        sell_price REAL,
        sell_volume INTEGER,
        sell_moving_week INTEGER,
        sell_orders INTEGER,
        buy_price REAL,
        buy_volume INTEGER,
        buy_moving_week INTEGER,
        buy_orders INTEGER
    )
    """)

    conn.commit()
    conn.close()


def collect_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    response = requests.get(
        "https://api.hypixel.net/v2/skyblock/bazaar",
        timeout=15
    )
    response.raise_for_status()

    data = response.json()
    products = data["products"]
    timestamp = datetime.now().isoformat()

    for item, info in products.items():
        quick = info["quick_status"]

        cursor.execute("""
        INSERT INTO prices
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            item,
            quick["sellPrice"],
            quick["sellVolume"],
            quick["sellMovingWeek"],
            quick["sellOrders"],
            quick["buyPrice"],
            quick["buyVolume"],
            quick["buyMovingWeek"],
            quick["buyOrders"]
        ))

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM prices")
    total_rows = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT timestamp) FROM prices")
    total_snapshots = cursor.fetchone()[0]

    conn.close()

    print(f"Saved {len(products)} items at {timestamp}", flush=True)
    print(f"Total rows: {total_rows:,}", flush=True)
    print(f"Total snapshots: {total_snapshots:,}", flush=True)


def load_alerted():
    try:
        with open(ALERT_FILE, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def save_alerted(data):
    with open(ALERT_FILE, "w") as file:
        json.dump(data, file, indent=4)


def send_discord_alert(row):
    if not DISCORD_WEBHOOK_URL:
        print("No Discord webhook set.", flush=True)
        return

    alerted = load_alerted()
    now = time.time()
    item = row["item"]

    last_alert = alerted.get(item, 0)
    if now - last_alert < COOLDOWN_SECONDS:
        return

    message = {
        "content": (
            f"🐋 **Whale Bazaar Alert**\n"
            f"**Item:** {item}\n\n"

            f"**Buy Order Price:** {row['sell_price']:,.2f}\n"
            f"**Sell Offer Price:** {row['buy_price']:,.2f}\n"
            f"**Profit Each:** {row['spread']:,.2f}\n"
            f"**Return:** {row['spread_percent']:.2f}%\n\n"

            f"**Coins to Spend:** {row['coins_to_spend']:,.0f}\n"
            f"**Quantity to Buy:** {row['quantity_to_buy']:,.0f}\n\n"

            f"**Estimated Daily Volume:** {row['daily_volume']:,.0f}\n"
            f"**Safe Investment:** {row['safe_investment']:,.0f} coins\n"
            f"**Daily Profit Potential:** {row['daily_profit_potential']:,.0f} coins\n\n"

            f"**Buy Orders:** {row['buy_orders']}\n"
            f"**Sell Orders:** {row['sell_orders']}\n"
            f"**Score:** {row['score']:,.2f}\n\n"

            f"http://192.168.182.226:5000"
        )
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)

        if response.status_code in [200, 204]:
            print(f"Discord alert sent for {item}", flush=True)
            alerted[item] = now
            save_alerted(alerted)
        else:
            print(f"Discord failed: {response.status_code} {response.text}", flush=True)

    except Exception as e:
        print(f"Discord request error: {e}", flush=True)

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)

        if response.status_code in [200, 204]:
            print(f"Discord alert sent for {item}", flush=True)
            alerted[item] = now
            save_alerted(alerted)
        else:
            print(f"Discord failed: {response.status_code} {response.text}", flush=True)

    except Exception as e:
        print(f"Discord request error: {e}", flush=True)


def check_for_alerts():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            item,
            buy_price,
            sell_price,

            buy_price - sell_price AS spread,
            ((buy_price - sell_price) / sell_price) * 100 AS spread_percent,

            buy_volume,
            sell_volume,
            buy_moving_week,
            sell_moving_week,
            buy_orders,
            sell_orders,

            MIN(buy_moving_week, sell_moving_week) / 7.0 AS daily_volume,

            MIN(
                ?,
                sell_price * ((MIN(buy_moving_week, sell_moving_week) / 7.0) * ?)
            ) AS safe_investment,

            MIN(
                ?,
                sell_price * ((MIN(buy_moving_week, sell_moving_week) / 7.0) * ?)
            ) AS coins_to_spend,

            CAST(
                MIN(
                    ?,
                    sell_price * ((MIN(buy_moving_week, sell_moving_week) / 7.0) * ?)
                ) / sell_price
            AS INTEGER) AS quantity_to_buy,

            (
                MIN(
                    ?,
                    sell_price * ((MIN(buy_moving_week, sell_moving_week) / 7.0) * ?)
                ) / sell_price
            ) * (buy_price - sell_price) AS daily_profit_potential,

            (
                ((buy_price - sell_price) / sell_price)
                * (MIN(buy_moving_week, sell_moving_week) / 7.0)
            ) AS capital_efficiency,

            (
                (
                    (
                        MIN(
                            ?,
                            sell_price * ((MIN(buy_moving_week, sell_moving_week) / 7.0) * ?)
                        ) / sell_price
                    ) * (buy_price - sell_price)
                ) * 0.00001

                + (((buy_price - sell_price) / sell_price) * 100) * 3
                + (MIN(buy_moving_week, sell_moving_week) / 7.0) * 0.01
                + buy_orders * 0.05
                + sell_orders * 0.05
            ) AS score

        FROM prices
        WHERE timestamp = (SELECT MAX(timestamp) FROM prices)
          AND sell_price > 0
          AND buy_price > sell_price
          AND sell_price <= ?
          AND ((buy_price - sell_price) / sell_price) * 100 BETWEEN ? AND ?
          AND (buy_price - sell_price) >= ?
          AND (MIN(buy_moving_week, sell_moving_week) / 7.0) >= ?
          AND buy_orders >= 10
          AND sell_orders >= 10

        ORDER BY daily_profit_potential DESC
        LIMIT 50
    """, (
        BANKROLL, SAFE_VOLUME_PERCENT,
        BANKROLL, SAFE_VOLUME_PERCENT,
        BANKROLL, SAFE_VOLUME_PERCENT,
        BANKROLL, SAFE_VOLUME_PERCENT,
        BANKROLL, SAFE_VOLUME_PERCENT,

        MAX_ITEM_PRICE,
        MIN_SPREAD_PERCENT,
        MAX_SPREAD_PERCENT,
        MIN_SPREAD_COINS,
        MIN_DAILY_VOLUME
    ))

    rows = cursor.fetchall()
    conn.close()

    rows = [
        row for row in rows
        if row["safe_investment"] >= MIN_SAFE_INVESTMENT
        and row["daily_profit_potential"] >= MIN_DAILY_PROFIT_POTENTIAL
    ]

    rows = rows[:20]

    print(f"Whale alert rows found: {len(rows)}", flush=True)

    for row in rows:
        print(
            f"{row['item']} | buy={row['quantity_to_buy']:,.0f} | "
            f"spend={row['coins_to_spend']:,.0f} | "
            f"return={row['spread_percent']:.2f}% | "
            f"profit={row['daily_profit_potential']:,.0f}",
            flush=True
        )

        send_discord_alert(row)

def show_preview():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM prices")
    print("Starting rows:", cursor.fetchone()[0], flush=True)

    cursor.execute("SELECT COUNT(DISTINCT timestamp) FROM prices")
    print("Starting snapshots:", cursor.fetchone()[0], flush=True)

    conn.close()


print("Using database:", DB_NAME, flush=True)

create_database()
show_preview()

while True:
    try:
        collect_data()
        check_for_alerts()
    except Exception as e:
        print(f"Error: {e}", flush=True)

    time.sleep(COLLECT_INTERVAL)