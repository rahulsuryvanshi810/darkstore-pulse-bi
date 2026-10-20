"""Generate the DarkStore Pulse dataset: 12 months of quick-commerce orders
from 8 dark stores in Pune (Oct 2025 - Sep 2026).

The data is synthetic but built from explicit business rules (festival spikes,
monsoon rain, rush hours, new-store ramp-up, customer churn), so every pattern
the dashboards show has a known cause. Fixed seed -> same files on every run.

    python scripts/generate_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
START, END = "2025-10-01", "2026-09-30"
SLA_MINUTES = 10
OUT = Path(__file__).resolve().parents[1] / "data"

rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------- stores
# k_base = orders/day at full ramp, dist = mean delivery distance (km),
# traffic = travel-time multiplier, aov = basket-size multiplier
STORES = [
    # id, name, area, lat, lon, open_date, base, dist, traffic, aov, riders
    ("S01", "Kothrud", "West", 18.5074, 73.8077, "2025-10-01", 34, 1.6, 1.00, 1.00, 14),
    ("S02", "Baner", "North-West", 18.5590, 73.7868, "2025-10-01", 36, 1.7, 1.02, 1.12, 15),
    ("S03", "Hinjewadi", "North-West", 18.5913, 73.7389, "2025-10-01", 30, 2.3, 1.22, 0.95, 11),
    ("S04", "Viman Nagar", "East", 18.5679, 73.9143, "2025-10-01", 33, 1.6, 1.05, 1.08, 14),
    ("S05", "Hadapsar", "South-East", 18.5089, 73.9260, "2025-10-01", 28, 2.0, 1.12, 0.90, 11),
    ("S06", "Koregaon Park", "Central", 18.5362, 73.8940, "2025-10-01", 26, 1.3, 0.98, 1.30, 11),
    ("S07", "Wakad", "North-West", 18.5987, 73.7688, "2026-01-15", 30, 1.9, 1.08, 1.00, 12),
    ("S08", "Kharadi", "East", 18.5515, 73.9348, "2026-04-01", 32, 1.8, 1.06, 1.05, 12),
]
stores = pd.DataFrame(STORES, columns=[
    "store_id", "store_name", "zone", "latitude", "longitude", "open_date",
    "k_base", "k_dist", "k_traffic", "k_aov", "riders"])
stores["open_date"] = pd.to_datetime(stores["open_date"])
stores["city"] = "Pune"
stores["sla_minutes"] = SLA_MINUTES

# ---------------------------------------------------------------- products
CATEGORIES = {
    # category: (n_sku, price_range, margin_pct, base_weight)
    "Fruits & Vegetables": (16, (25, 160), 0.30, 16),
    "Dairy, Bread & Eggs": (14, (25, 120), 0.12, 18),
    "Snacks & Munchies": (16, (20, 199), 0.28, 14),
    "Cold Drinks & Juices": (12, (20, 160), 0.25, 10),
    "Atta, Rice & Dal": (12, (60, 450), 0.10, 8),
    "Instant & Frozen Food": (12, (35, 299), 0.24, 8),
    "Sweets & Festive": (10, (99, 499), 0.32, 1.2),
    "Personal Care": (12, (49, 499), 0.35, 7),
    "Cleaning & Household": (10, (49, 399), 0.30, 6),
    "Baby Care": (8, (99, 799), 0.22, 1.8),
    "Tea, Coffee & Breakfast": (10, (49, 499), 0.20, 7),
}
rows = []
for cat, (n, (lo, hi), margin, _) in CATEGORIES.items():
    prices = np.round(np.exp(rng.uniform(np.log(lo), np.log(hi), n)))
    for i, p in enumerate(prices, 1):
        m = np.clip(rng.normal(margin, 0.04), 0.04, 0.6)
        rows.append((cat, f"{cat.split()[0].strip(',')} item {i:02d}", p, round(p * (1 - m), 2)))
products = pd.DataFrame(rows, columns=["category", "product_name", "mrp", "unit_cost"])
products.insert(0, "product_id", [f"P{i:03d}" for i in range(1, len(products) + 1)])
products["shelf_life"] = products["category"].map(
    lambda c: "Perishable" if c in ("Fruits & Vegetables", "Dairy, Bread & Eggs") else "Packaged")

# ---------------------------------------------------------------- calendar
dates = pd.date_range(START, END, freq="D")
FESTIVALS = {  # name: (first day, last day, demand multiplier)
    "Diwali": ("2025-10-17", "2025-10-23", 1.55),
    "Christmas & New Year": ("2025-12-24", "2026-01-01", 1.30),
    "Holi": ("2026-03-02", "2026-03-04", 1.35),
    "Ganesh Chaturthi": ("2026-09-14", "2026-09-24", 1.40),
}
festival_of = pd.Series("No Festival", index=dates)
festival_mult = pd.Series(1.0, index=dates)
for name, (a, b, m) in FESTIVALS.items():
    festival_of[a:b] = name
    festival_mult[a:b] = m

# Pune monsoon: rain days are common Jun-Sep, rare otherwise
rain_p = {1: .02, 2: .02, 3: .03, 4: .05, 5: .10, 6: .45, 7: .75, 8: .65, 9: .45,
          10: .15, 11: .05, 12: .02}
is_rain = pd.Series([rng.random() < rain_p[d.month] for d in dates], index=dates)

# hour-of-day demand: breakfast bump, evening peak, late-night snacking
HOURS = np.arange(6, 25) % 24  # 06:00 .. 00:00 (0 = midnight)
hour_w = np.array([2, 5, 7, 6, 4, 4, 5, 5, 4, 4, 5, 6, 8, 10, 11, 10, 8, 5, 3], float)
hour_w /= hour_w.sum()
PEAK_HOURS = {8, 18, 19, 20, 21, 22}

# category mix shifts by time of day
cat_names = list(CATEGORIES)
base_cat_w = np.array([CATEGORIES[c][3] for c in cat_names], float)


def category_weights(hour, festival):
    w = base_cat_w.copy()
    if hour in (6, 7, 8, 9):
        w[cat_names.index("Dairy, Bread & Eggs")] *= 2.2
        w[cat_names.index("Tea, Coffee & Breakfast")] *= 1.8
    if hour in (21, 22, 23):
        w[cat_names.index("Snacks & Munchies")] *= 2.0
        w[cat_names.index("Cold Drinks & Juices")] *= 1.7
        w[cat_names.index("Instant & Frozen Food")] *= 1.6
    if festival:
        w[cat_names.index("Sweets & Festive")] *= 6.0
    return w / w.sum()


prod_by_cat = {c: products.index[products["category"] == c].to_numpy() for c in cat_names}

# ---------------------------------------------------------------- riders
rider_rows = []
for s in stores.itertuples():
    for i in range(1, s.riders + 1):
        rider_rows.append((f"{s.store_id}-R{i:02d}", s.store_id,
                           "EV scooter" if rng.random() < 0.45 else "Petrol bike",
                           s.open_date + pd.Timedelta(days=int(rng.integers(0, 60)))))
riders = pd.DataFrame(rider_rows, columns=["rider_id", "store_id", "vehicle_type", "join_date"])

# ---------------------------------------------------------------- orders
CHANNELS = ["Organic", "Referral", "Paid Ads", "Society Activation"]
CHANNEL_P = [0.42, 0.22, 0.26, 0.10]
PAYMENTS = ["UPI", "Card", "Cash on Delivery", "Wallet"]
PAYMENT_P = [0.62, 0.14, 0.16, 0.08]

customers = []          # rows for customers.csv
pool = {s: {"ids": [], "loyal": [], "first": [], "life": []} for s in stores["store_id"]}
order_rows, item_rows = [], []
cust_seq = order_seq = 0

for d in dates:
    dow_mult = 1.18 if d.dayofweek >= 5 else 1.0
    fest = festival_of[d]
    rain = bool(is_rain[d])
    for s in stores.itertuples():
        if d < s.open_date:
            continue
        age = (d - s.open_date).days
        ramp = 0.45 + 0.55 * min(1.0, age / 75)            # new-store ramp-up
        growth = 1 + 0.25 * (d - dates[0]).days / 365        # city-wide growth
        lam = s.k_base * ramp * growth * dow_mult * festival_mult[d] * (1.12 if rain else 1)
        n = rng.poisson(lam)
        if n == 0:
            continue

        # who orders: returning customers still "alive", plus new sign-ups
        P = pool[s.store_id]
        p_new = 0.55 if age < 30 else 0.30 if age < 90 else 0.17
        n_new = rng.binomial(n, p_new)
        alive = np.array([(d - f).days < l for f, l in zip(P["first"], P["life"])], bool)
        if not alive.any():
            n_new = n
        ids_today = []
        if n - n_new > 0:
            w = np.array(P["loyal"])[alive]
            pick = rng.choice(np.flatnonzero(alive), size=n - n_new, p=w / w.sum())
            ids_today += [P["ids"][i] for i in pick]
        for _ in range(n_new):
            cust_seq += 1
            cid = f"C{cust_seq:05d}"
            ch = rng.choice(CHANNELS, p=CHANNEL_P)
            life = rng.exponential(55 if ch == "Paid Ads" else 140)   # paid users churn faster
            P["ids"].append(cid); P["loyal"].append(rng.gamma(1.5, 1.0))
            P["first"].append(d); P["life"].append(life)
            customers.append((cid, s.store_id, d, ch))
            ids_today.append(cid)

        first_today = set(ids_today[len(ids_today) - n_new:])
        hours = rng.choice(HOURS, size=n, p=hour_w)
        for cid, hr in zip(ids_today, hours):
            order_seq += 1
            oid = f"O{order_seq:06d}"
            hr = 23 if hr == 0 else int(hr)   # midnight slot folds into the 23:00 hour
            ts = d + pd.Timedelta(hours=hr, minutes=int(rng.integers(0, 60)))
            peak = hr in PEAK_HOURS
            first_order = cid in first_today

            # basket
            n_items = 1 + rng.poisson(1.9 * s.k_aov * (1.25 if fest != "No Festival" else 1) * (1.15 if d.dayofweek >= 5 else 1))
            cw = category_weights(hr, fest != "No Festival")
            cats = rng.choice(len(cat_names), size=n_items, p=cw)
            item_total = cogs = 0.0
            oos_any = False
            oos_rate = 0.03 + (0.05 if fest != "No Festival" else 0) + (0.03 if age < 45 else 0)
            for ci in cats:
                pid = rng.choice(prod_by_cat[cat_names[ci]])
                qty = int(rng.choice([1, 1, 1, 2, 2, 3]))
                oos = rng.random() < oos_rate
                oos_any |= oos
                mrp, uc = products.at[pid, "mrp"], products.at[pid, "unit_cost"]
                if not oos:
                    item_total += mrp * qty
                    cogs += uc * qty
                item_rows.append((oid, products.at[pid, "product_id"], qty, mrp, uc, int(not oos)))

            # pricing
            coupon = first_order or rng.random() < 0.18
            discount = 0.0
            if coupon and item_total > 0:
                discount = min(100.0, round(item_total * (0.5 if first_order else rng.choice([0.1, 0.15]))))
            delivery_fee = (30 if item_total < 199 else 0) + (15 if rain else 0)
            payment = rng.choice(PAYMENTS, p=PAYMENT_P)

            # operations
            dist = max(0.3, rng.gamma(4, s.k_dist / 4))
            load = 1.0 + (0.18 if peak else 0) + (0.25 if fest != "No Festival" else 0)
            pick_pack = max(1.0, rng.normal(2.2 + 0.25 * (n_items > 5) + (0.8 if age < 45 else 0), 0.6))
            travel = dist * 3.1 * s.k_traffic * (1.38 if rain else 1) * load * rng.lognormal(0, 0.18)
            wait = rng.exponential(1.4 if peak else 0.6) * (1.6 if fest != "No Festival" else 1)
            minutes = round(pick_pack + travel + wait, 1)

            p_cancel = (0.018 + (0.035 if rain else 0) + (0.012 if peak else 0)
                        + (0.05 if oos_any else 0) + (0.03 if payment == "Cash on Delivery" else 0)
                        + (0.03 if minutes > 16 else 0))
            cancelled = rng.random() < p_cancel or item_total == 0
            if cancelled:
                reason = rng.choice(["Item unavailable", "Delay", "Customer cancelled", "Payment failed"],
                                    p=[.35, .25, .30, .10] if oos_any else [.05, .40, .40, .15])
                status, minutes_out, rating = "Cancelled", np.nan, np.nan
            else:
                reason, status, minutes_out = "", "Delivered", minutes
                late = max(0.0, minutes - SLA_MINUTES)
                rating = (np.clip(round(rng.normal(4.65 - 0.22 * late - (0.4 if oos_any else 0), 0.55)), 1, 5)
                          if rng.random() < 0.62 else np.nan)
            rider = f"{s.store_id}-R{int(rng.integers(1, s.riders + 1)):02d}"
            rider_cost = round(28 + 7 * dist + (12 if rain else 0), 2)

            order_rows.append((oid, ts, s.store_id, cid, rider, status, reason, payment,
                               int(first_order), int(coupon), int(rain), fest, n_items,
                               round(item_total, 2), discount, delivery_fee, round(cogs, 2),
                               rider_cost, round(dist, 2), minutes_out, rating, int(oos_any)))

orders = pd.DataFrame(order_rows, columns=[
    "order_id", "order_datetime", "store_id", "customer_id", "rider_id", "status",
    "cancel_reason", "payment_method", "is_first_order", "coupon_used", "is_rain_day",
    "festival", "items_count", "item_total", "discount", "delivery_fee", "cogs",
    "rider_cost", "distance_km", "delivery_minutes", "rating", "had_stockout"])
orders["sla_met"] = np.where(orders["status"] == "Delivered",
                             (orders["delivery_minutes"] <= SLA_MINUTES).astype(int), np.nan)
# cancelled orders earn nothing and cost no rider payout
c = orders["status"] == "Cancelled"
orders.loc[c, "rider_cost"] = 0.0
orders["net_revenue"] = np.where(c, 0.0, orders["item_total"] - orders["discount"] + orders["delivery_fee"])
orders["contribution"] = np.where(
    c, 0.0, orders["net_revenue"] - orders["cogs"] - orders["rider_cost"]).round(2)

items = pd.DataFrame(item_rows, columns=["order_id", "product_id", "quantity", "mrp", "unit_cost", "fulfilled"])
customers = pd.DataFrame(customers, columns=["customer_id", "home_store_id", "signup_date", "acquisition_channel"])

weather = pd.DataFrame({"date": dates, "is_rain_day": is_rain.astype(int).values,
                        "festival": festival_of.values})

# ---------------------------------------------------------------- save
OUT.mkdir(exist_ok=True)
stores.drop(columns=[c for c in stores if c.startswith("k_")]).to_csv(OUT / "stores.csv", index=False, date_format="%Y-%m-%d")
products.to_csv(OUT / "products.csv", index=False)
customers.to_csv(OUT / "customers.csv", index=False, date_format="%Y-%m-%d")
riders.to_csv(OUT / "riders.csv", index=False, date_format="%Y-%m-%d")
weather.to_csv(OUT / "calendar_events.csv", index=False, date_format="%Y-%m-%d")
orders.to_csv(OUT / "orders.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
items.to_csv(OUT / "order_items.csv", index=False)

print(f"stores {len(stores)}, products {len(products)}, customers {len(customers):,}, "
      f"riders {len(riders)}, orders {len(orders):,}, order_items {len(items):,}")
