from flask import Flask, request, render_template_string, redirect, url_for
import sqlite3
import json
import os
import time
import requests

app = Flask(__name__)

DB_PATH = "/home/collin/projects/data-collector/bazaar.db"
WATCHLIST_FILE = "/home/collin/projects/bazaar-dashboard/watchlist.json"
ALERT_FILE = "/home/collin/projects/bazaar-dashboard/alerted.json"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

MIN_ALERT_SCORE = 80
MIN_ALERT_MARGIN = 8
MAX_ALERT_MARGIN = 35
MIN_ALERT_VOLUME = 100000
ALERT_COOLDOWN_SECONDS = 60 * 30


def query_db(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def load_watchlist():
    return load_json(WATCHLIST_FILE, [])


def send_discord_alert(row):
    if not DISCORD_WEBHOOK_URL:
        return

    alerted = load_json(ALERT_FILE, {})
    now = time.time()
    item = row["item"]

    last_alert = alerted.get(item, 0)
    if now - last_alert < ALERT_COOLDOWN_SECONDS:
        return

    message = {
        "content": (
            f"🚨 **Good Bazaar Flip Found**\n"
            f"**Item:** {item}\n"
            f"**Buy Order Price:** {row['sell_price']:,.2f}\n"
            f"**Sell Offer Price:** {row['buy_price']:,.2f}\n"
            f"**Profit Each:** {row['profit_each']:,.2f}\n"
            f"**Return:** {row['margin_percent']:.2f}%\n"
            f"**Buy Volume:** {row['buy_volume']:,}\n"
            f"**Sell Volume:** {row['sell_volume']:,}\n"
            f"**Volume Ratio:** {row['volume_ratio']:.2f}\n"
            f"**Buy Orders:** {row['buy_orders']}\n"
            f"**Sell Orders:** {row['sell_orders']}\n"
            f"**Score:** {row['score']:.2f}\n"
            f"http://192.168.182.226:5000/item/{item}"
        )
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=5)

        if response.status_code in [200, 204]:
            alerted[item] = now
            save_json(ALERT_FILE, alerted)
            print(f"Dashboard Discord alert sent for {item}", flush=True)
        else:
            print(f"Dashboard Discord failed: {response.status_code} {response.text}", flush=True)

    except Exception as e:
        print("Dashboard Discord alert failed:", e, flush=True)


def get_best_flips(search="", min_volume=100000, max_price="", min_margin=5):
    max_price_filter = ""
    params = [f"%{search}%", min_volume, min_volume, min_margin]

    if max_price:
        max_price_filter = "AND l.sell_price <= ?"
        params.append(float(max_price))

    return query_db(f"""
        WITH latest AS (
            SELECT *
            FROM prices
            WHERE timestamp = (SELECT MAX(timestamp) FROM prices)
        )
        SELECT
            l.item,
            ROUND(l.buy_price, 2) AS buy_price,
            ROUND(l.sell_price, 2) AS sell_price,
            ROUND(l.buy_price - l.sell_price, 2) AS profit_each,
            ROUND(((l.buy_price - l.sell_price) / l.sell_price) * 100, 2) AS margin_percent,
            l.buy_volume,
            l.sell_volume,
            l.buy_orders,
            l.sell_orders,
            l.sell_volume + l.buy_volume AS total_volume,
            ROUND(CAST(l.buy_volume AS REAL) / l.sell_volume, 2) AS volume_ratio,
            ROUND(l.sell_price * l.sell_volume, 2) AS trade_value,

            ROUND(
                (((l.buy_price - l.sell_price) / l.sell_price) * 100) * 0.35
                + (CAST(l.buy_volume AS REAL) / l.sell_volume) * 15
                + l.buy_orders * 0.04
                + l.sell_orders * 0.04
                + (l.buy_price - l.sell_price) * 0.001,
                2
            ) AS score,

            CASE
                WHEN (((l.buy_price - l.sell_price) / l.sell_price) * 100) >= 20 THEN 'S'
                WHEN (((l.buy_price - l.sell_price) / l.sell_price) * 100) >= 12 THEN 'A'
                WHEN (((l.buy_price - l.sell_price) / l.sell_price) * 100) >= 7 THEN 'B'
                ELSE 'C'
            END AS tier,

            CASE
                WHEN (((l.buy_price - l.sell_price) / l.sell_price) * 100) > 30 THEN 'HIGH'
                WHEN l.buy_orders < 30 OR l.sell_orders < 30 THEN 'MED'
                WHEN l.buy_volume < 150000 OR l.sell_volume < 150000 THEN 'MED'
                ELSE 'LOW'
            END AS risk

        FROM latest l
        WHERE l.item LIKE ?
          AND l.sell_price > 0
          AND l.buy_price > l.sell_price
          AND l.buy_volume >= ?
          AND l.sell_volume >= ?
          AND l.buy_orders >= 20
          AND l.sell_orders >= 20
          AND (((l.buy_price - l.sell_price) / l.sell_price) * 100) >= ?
          AND (((l.buy_price - l.sell_price) / l.sell_price) * 100) <= 35
          AND l.sell_price >= 100
          AND l.buy_price <= 50000000
          {max_price_filter}

        ORDER BY score DESC
        LIMIT 75
    """, params)


HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Bazaar Dashboard</title>
<meta http-equiv="refresh" content="60">
<style>
body { font-family: Arial; background:#111; color:white; padding:20px; }
a { color:#66ccff; text-decoration:none; }
table { border-collapse: collapse; width:100%; background:#222; margin-bottom:30px; }
th, td { padding:10px; border-bottom:1px solid #444; text-align:left; }
th { background:#333; }
input, button { padding:8px; margin:5px; }
.good { color:#00ff88; font-weight:bold; }
.bad { color:#ff5555; font-weight:bold; }
.warn { color:#ffaa00; font-weight:bold; }
.card { background:#222; padding:15px; margin:10px 0; border-radius:8px; }
.S { color:#ffcc00; font-weight:bold; }
.A { color:#00ff88; font-weight:bold; }
.B { color:#66ccff; font-weight:bold; }
.C { color:#ffaa00; }
.LOW { color:#00ff88; font-weight:bold; }
.MED { color:#ffaa00; font-weight:bold; }
.HIGH { color:#ff5555; font-weight:bold; }
</style>
</head>
<body>

<h1>Hypixel Bazaar Dashboard</h1>

<div class="card">
<h2>Summary</h2>
<p>Total rows: {{ total_rows }}</p>
<p>Unique items: {{ unique_items }}</p>
<p>Latest update: {{ latest_time }}</p>
</div>

<form method="get">
<input name="search" placeholder="Search item" value="{{ search }}">
<input name="min_volume" placeholder="Min volume" value="{{ min_volume }}">
<input name="max_price" placeholder="Max price" value="{{ max_price }}">
<input name="min_margin" placeholder="Min margin %" value="{{ min_margin }}">
<button type="submit">Filter</button>
</form>

<h2>Best Current Flips</h2>
<table>
<tr>
<th>Tier</th>
<th>Risk</th>
<th>Item</th>
<th>Buy Order Price</th>
<th>Sell Offer Price</th>
<th>Profit Each</th>
<th>Return %</th>
<th>Total Volume</th>
<th>Volume Ratio</th>
<th>Buy Orders</th>
<th>Sell Orders</th>
<th>Trade Value</th>
<th>Score</th>
<th>Watch</th>
</tr>

{% for row in best_flips %}
<tr>
<td class="{{ row['tier'] }}">{{ row["tier"] }}</td>
<td class="{{ row['risk'] }}">{{ row["risk"] }}</td>
<td><a href="/item/{{ row['item'] }}">{{ row["item"] }}</a></td>
<td>{{ row["sell_price"] }}</td>
<td>{{ row["buy_price"] }}</td>
<td class="good">{{ row["profit_each"] }}</td>
<td class="good">{{ row["margin_percent"] }}%</td>
<td>{{ "{:,.0f}".format(row["total_volume"]) }}</td>
<td>{{ row["volume_ratio"] }}</td>
<td>{{ row["buy_orders"] }}</td>
<td>{{ row["sell_orders"] }}</td>
<td>{{ "{:,.0f}".format(row["trade_value"]) }}</td>
<td>{{ row["score"] }}</td>
<td><a href="/watch/{{ row['item'] }}">⭐</a></td>
</tr>
{% endfor %}
</table>

<h2>Watchlist</h2>
<table>
<tr><th>Item</th><th>Open</th></tr>
{% for item in watchlist %}
<tr>
<td>{{ item }}</td>
<td><a href="/item/{{ item }}">View</a></td>
</tr>
{% endfor %}
</table>

</body>
</html>
"""


ITEM_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>{{ item }}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body { font-family: Arial; background:#111; color:white; padding:20px; }
a { color:#66ccff; }
.card { background:#222; padding:15px; margin:10px 0; border-radius:8px; }
canvas { background:#222; padding:15px; margin-bottom:25px; }
.good { color:#00ff88; font-weight:bold; }
</style>
</head>
<body>

<a href="/">← Back</a>
<h1>{{ item }}</h1>
<a href="/watch/{{ item }}">Add/remove watchlist ⭐</a>

<div class="card">
<h2>Stats</h2>
<p>Highest profit shown: {{ highest_profit }}</p>
<p>Lowest buy order price shown: {{ lowest_price }}</p>
<p>Highest margin shown: {{ highest_margin }}%</p>
</div>

<canvas id="priceChart"></canvas>
<canvas id="profitChart"></canvas>
<canvas id="volumeChart"></canvas>

<script>
const labels = {{ labels | safe }};
const buyPrices = {{ buy_prices | safe }};
const sellPrices = {{ sell_prices | safe }};
const profits = {{ profits | safe }};
const volumes = {{ volumes | safe }};

new Chart(document.getElementById("priceChart"), {
    type: "line",
    data: { labels: labels, datasets: [
        { label: "Sell Offer Price", data: buyPrices },
        { label: "Buy Order Price", data: sellPrices }
    ]}
});

new Chart(document.getElementById("profitChart"), {
    type: "line",
    data: { labels: labels, datasets: [
        { label: "Profit Each", data: profits }
    ]}
});

new Chart(document.getElementById("volumeChart"), {
    type: "line",
    data: { labels: labels, datasets: [
        { label: "Total Volume", data: volumes }
    ]}
});
</script>

</body>
</html>
"""


@app.route("/")
def index():
    search = request.args.get("search", "")
    min_volume = request.args.get("min_volume", "100000")
    max_price = request.args.get("max_price", "")
    min_margin = request.args.get("min_margin", "5")

    try:
        min_volume_num = int(min_volume)
    except:
        min_volume_num = 100000

    try:
        min_margin_num = float(min_margin)
    except:
        min_margin_num = 5

    summary = query_db("""
        SELECT 
            COUNT(*) AS total_rows,
            COUNT(DISTINCT item) AS unique_items,
            MAX(timestamp) AS latest_time
        FROM prices
    """)[0]

    best_flips = get_best_flips(search, min_volume_num, max_price, min_margin_num)

    for row in best_flips[:5]:
        if (
            row["score"] >= MIN_ALERT_SCORE
            and row["margin_percent"] >= MIN_ALERT_MARGIN
            and row["margin_percent"] <= MAX_ALERT_MARGIN
            and row["total_volume"] >= MIN_ALERT_VOLUME
            and row["risk"] != "HIGH"
        ):
            send_discord_alert(row)

    return render_template_string(
        HTML,
        total_rows=summary["total_rows"],
        unique_items=summary["unique_items"],
        latest_time=summary["latest_time"],
        best_flips=best_flips,
        watchlist=load_watchlist(),
        search=search,
        min_volume=min_volume,
        max_price=max_price,
        min_margin=min_margin
    )


@app.route("/watch/<item>")
def watch(item):
    watchlist = load_watchlist()
    if item in watchlist:
        watchlist.remove(item)
    else:
        watchlist.append(item)
    save_json(WATCHLIST_FILE, watchlist)
    return redirect(url_for("index"))


@app.route("/item/<item>")
def item_page(item):
    rows = query_db("""
        SELECT 
            timestamp,
            buy_price,
            sell_price,
            sell_volume,
            buy_volume,
            ROUND(buy_price - sell_price, 2) AS profit_each,
            ROUND(((buy_price - sell_price) / sell_price) * 100, 2) AS margin_percent
        FROM prices
        WHERE item = ?
        ORDER BY timestamp ASC
        LIMIT 500
    """, (item,))

    labels = [row["timestamp"] for row in rows]
    buy_prices = [row["buy_price"] for row in rows]
    sell_prices = [row["sell_price"] for row in rows]
    profits = [row["profit_each"] for row in rows]
    volumes = [row["sell_volume"] + row["buy_volume"] for row in rows]

    highest_profit = max(profits) if profits else 0
    lowest_price = min(sell_prices) if sell_prices else 0
    highest_margin = max([row["margin_percent"] for row in rows]) if rows else 0

    return render_template_string(
        ITEM_HTML,
        item=item,
        labels=json.dumps(labels),
        buy_prices=json.dumps(buy_prices),
        sell_prices=json.dumps(sell_prices),
        profits=json.dumps(profits),
        volumes=json.dumps(volumes),
        highest_profit=highest_profit,
        lowest_price=lowest_price,
        highest_margin=highest_margin
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)