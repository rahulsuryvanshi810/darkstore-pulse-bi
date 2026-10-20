"""Answer the business questions, export BI-ready tables, draw the README charts
and build the data file for the web dashboard (docs/).

    python scripts/analyze.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA, OUT, FIG = ROOT / "data", ROOT / "outputs", ROOT / "reports" / "figures"
OUT.mkdir(exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2 = "#0b0b0b", "#52514e"
plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 10, "axes.edgecolor": "#d6d5d0",
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#ecebe8", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "semibold", "axes.titlesize": 12, "axes.titlelocation": "left",
    "figure.dpi": 130, "savefig.bbox": "tight", "figure.facecolor": "white",
})

# ------------------------------------------------------------------ load
orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_datetime"], keep_default_na=False,
                     na_values=[""])
items = pd.read_csv(DATA / "order_items.csv")
stores = pd.read_csv(DATA / "stores.csv", parse_dates=["open_date"])
products = pd.read_csv(DATA / "products.csv")
customers = pd.read_csv(DATA / "customers.csv", parse_dates=["signup_date"])

orders = orders.merge(stores[["store_id", "store_name"]], on="store_id")
orders["date"] = orders["order_datetime"].dt.normalize()
orders["month"] = orders["order_datetime"].dt.to_period("M")
orders["hour"] = orders["order_datetime"].dt.hour
orders["weekday"] = orders["order_datetime"].dt.dayofweek
orders["delivered"] = (orders["status"] == "Delivered").astype(int)
orders["cancelled"] = 1 - orders["delivered"]
dl = orders[orders["delivered"] == 1]

# ------------------------------------------------------------------ KPIs
k = {
    "orders": len(orders),
    "delivered": int(orders["delivered"].sum()),
    "customers": int(orders["customer_id"].nunique()),
    "gmv": float(orders["item_total"].sum()),
    "net_revenue": float(orders["net_revenue"].sum()),
    "contribution": float(orders["contribution"].sum()),
    "aov": float(dl["net_revenue"].mean()),
    "cancel_rate": float(orders["cancelled"].mean()),
    "sla_rate": float(dl["sla_met"].mean()),
    "avg_minutes": float(dl["delivery_minutes"].mean()),
    "median_minutes": float(dl["delivery_minutes"].median()),
    "avg_rating": float(dl["rating"].mean()),
}
k["contribution_margin"] = k["contribution"] / k["net_revenue"]
per_cust = orders.groupby("customer_id").size()
k["repeat_customer_share"] = float((per_cust > 1).mean())
k["orders_from_repeat_customers"] = float(per_cust[per_cust > 1].sum() / len(orders))
pd.Series(k).to_csv(OUT / "kpi_summary.csv", header=["value"])

# ------------------------------------------------------------------ stores
store = dl.groupby(["store_id", "store_name"]).agg(
    delivered=("order_id", "size"), sla_rate=("sla_met", "mean"),
    avg_minutes=("delivery_minutes", "mean"), avg_distance_km=("distance_km", "mean"),
    aov=("net_revenue", "mean"), contribution_per_order=("contribution", "mean"),
    avg_rating=("rating", "mean")).reset_index()
store = store.merge(orders.groupby("store_id")["cancelled"].mean().rename("cancel_rate"), on="store_id")
store = store.sort_values("sla_rate", ascending=False).round(3)
store.to_csv(OUT / "store_scorecard.csv", index=False)

monthly = orders.groupby(["month", "store_name"]).agg(
    orders=("order_id", "size"), net_revenue=("net_revenue", "sum"),
    contribution=("contribution", "sum")).reset_index()
monthly.to_csv(OUT / "monthly_store.csv", index=False)
month_tot = orders.groupby("month").agg(orders=("order_id", "size"), net_revenue=("net_revenue", "sum"))

# ------------------------------------------------------------------ time of day
heat = dl.groupby(["weekday", "hour"]).agg(orders=("order_id", "size"), sla_rate=("sla_met", "mean")).reset_index()
heat.to_csv(OUT / "hour_weekday.csv", index=False)
peak = dl["hour"].isin([8, 18, 19, 20, 21, 22])
hour_sla = {"peak": float(dl.loc[peak, "sla_met"].mean()), "off_peak": float(dl.loc[~peak, "sla_met"].mean()),
            "peak_order_share": float(peak.mean())}

# ------------------------------------------------------------------ rain
rain = orders.groupby("is_rain_day").agg(
    days=("date", "nunique"), orders=("order_id", "size"), cancel_rate=("cancelled", "mean")).reset_index()
rain["orders_per_store_day"] = orders.groupby(["is_rain_day", "date", "store_id"]).size() \
    .groupby("is_rain_day").mean().values
rain = rain.merge(dl.groupby("is_rain_day").agg(sla_rate=("sla_met", "mean"),
                                                 avg_minutes=("delivery_minutes", "mean")).reset_index())
rain.to_csv(OUT / "rain_impact.csv", index=False)
# demand effect measured inside the monsoon months only, so business growth does not inflate it
mon = orders[orders["order_datetime"].dt.month.isin([6, 7, 8, 9])]
per_day = mon.groupby(["is_rain_day", "date", "store_id"]).size().groupby("is_rain_day").mean()
rain_demand_monsoon = float(per_day[1] / per_day[0] - 1)
rain_by_store = dl.groupby(["store_name", "is_rain_day"])["sla_met"].mean().unstack()

# ------------------------------------------------------------------ festivals
daily = orders.groupby(["date", "festival"]).size().rename("orders").reset_index()
fest = daily.groupby("festival")["orders"].mean().rename("orders_per_day").reset_index()
normal = fest.loc[fest["festival"] == "No Festival", "orders_per_day"].iloc[0]
fest["uplift_vs_normal"] = fest["orders_per_day"] / normal - 1
fest.to_csv(OUT / "festival_impact.csv", index=False)
# compare each festival with the 14 normal days before it (removes the growth trend)
fest_rel = {}
for name, g in daily[daily["festival"] != "No Festival"].groupby("festival"):
    start = g["date"].min()
    before = daily[(daily["date"] < start) & (daily["date"] >= start - pd.Timedelta(days=14))
                   & (daily["festival"] == "No Festival")]["orders"].mean()
    fest_rel[name] = float(g["orders"].mean() / before - 1)

# ------------------------------------------------------------------ categories
it = items.merge(products, on=["product_id", "mrp", "unit_cost"]).merge(
    orders[["order_id", "status", "month", "store_name", "festival"]], on="order_id")
sold = it[(it["status"] == "Delivered") & (it["fulfilled"] == 1)].copy()
sold["revenue"] = sold["quantity"] * sold["mrp"]
sold["gross_profit"] = sold["quantity"] * (sold["mrp"] - sold["unit_cost"])
cat = sold.groupby("category").agg(units=("quantity", "sum"), revenue=("revenue", "sum"),
                                   gross_profit=("gross_profit", "sum")).reset_index()
cat["margin_pct"] = cat["gross_profit"] / cat["revenue"]
cat["revenue_share"] = cat["revenue"] / cat["revenue"].sum()
cat = cat.sort_values("revenue", ascending=False).round(4)
cat.to_csv(OUT / "category_performance.csv", index=False)
oos = it.groupby("category")["fulfilled"].apply(lambda s: 1 - s.mean()).rename("stockout_rate")
oos.round(4).to_csv(OUT / "stockout_by_category.csv")
sweets_fest = sold[sold["category"] == "Sweets & Festive"].groupby(
    sold["festival"] != "No Festival")["revenue"].sum()

# ------------------------------------------------------------------ customers
first_m = customers.set_index("customer_id")["signup_date"].dt.to_period("M")
o2 = orders[["customer_id", "month"]].copy()
o2["cohort"] = o2["customer_id"].map(first_m)
o2["age"] = (o2["month"] - o2["cohort"]).apply(lambda x: x.n)
coh = o2.groupby(["cohort", "age"])["customer_id"].nunique().unstack()
coh_pct = coh.div(coh[0], axis=0)
coh_pct.round(4).to_csv(OUT / "cohort_retention.csv")
m1 = float(coh_pct[1].mean())
m3 = float(coh_pct[3].mean())

ch = orders.merge(customers[["customer_id", "acquisition_channel"]], on="customer_id")
channel = ch.groupby("acquisition_channel").agg(
    customers=("customer_id", "nunique"), orders=("order_id", "size"),
    net_revenue=("net_revenue", "sum")).reset_index()
channel["orders_per_customer"] = channel["orders"] / channel["customers"]
channel["revenue_per_customer"] = channel["net_revenue"] / channel["customers"]
channel.round(2).to_csv(OUT / "channel_value.csv", index=False)

pay = orders.groupby("payment_method").agg(orders=("order_id", "size"), cancel_rate=("cancelled", "mean")).reset_index()
pay.to_csv(OUT / "payment_cancellations.csv", index=False)

dl2 = dl.dropna(subset=["rating"]).copy()
dl2["delay_band"] = pd.cut(dl2["delivery_minutes"], [0, 10, 12, 15, 20, 999],
                           labels=["On time (<=10)", "10-12", "12-15", "15-20", "20+"])
rating_band = dl2.groupby("delay_band", observed=True).agg(
    rated_orders=("order_id", "size"), avg_rating=("rating", "mean"),
    low_rating_share=("rating", lambda r: (r <= 2).mean())).reset_index()
rating_band.to_csv(OUT / "rating_vs_delay.csv", index=False)

reasons = orders[orders["cancelled"] == 1]["cancel_reason"].value_counts(normalize=True)
coupon = dl.groupby("coupon_used")["contribution"].mean()

# ------------------------------------------------------------------ findings
best, worst = store.iloc[0], store.iloc[-1]
findings = {
    "kpis": k, "hour_sla": hour_sla, "festival_uplift_vs_prior_14d": fest_rel,
    "rain": rain.to_dict("records"), "rain_demand_uplift_monsoon": rain_demand_monsoon, "m1_retention": m1, "m3_retention": m3,
    "best_store": best.to_dict(), "worst_store": worst.to_dict(),
    "sweets_festival_revenue_share": float(sweets_fest.get(True, 0) / sweets_fest.sum()),
    "cancel_reasons": reasons.round(4).to_dict(),
    "contribution_per_order_coupon": coupon.round(2).to_dict(),
    "rating_vs_delay": rating_band.round(3).astype({"delay_band": str}).to_dict("records"),
    "channel": channel.round(2).to_dict("records"),
    "payments": pay.round(4).to_dict("records"),
    "category_top": cat.head(3).to_dict("records"),
    "rain_sla_by_store": rain_by_store.round(3).reset_index().to_dict("records"),
}
(OUT / "findings.json").write_text(json.dumps(findings, indent=2, default=str))


# ------------------------------------------------------------------ charts
def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)


fig, ax = plt.subplots(figsize=(9, 3.6))
x = month_tot.index.to_timestamp()
ax.plot(x, month_tot["net_revenue"] / 1e5, color=BLUE, lw=2, marker="o", ms=4)
for i in [0, len(x) - 1]:
    ax.annotate(f"₹{month_tot['net_revenue'].iloc[i] / 1e5:.1f} L", (x[i], month_tot["net_revenue"].iloc[i] / 1e5),
                textcoords="offset points", xytext=(0, 8), ha="center", color=INK)
for lbl, d in [("Wakad opens", "2026-01-15"), ("Kharadi opens", "2026-04-01")]:
    ax.axvline(pd.Timestamp(d), color=GREY, lw=1, ls=":")
    ax.text(pd.Timestamp(d), ax.get_ylim()[1] * 0.97, " " + lbl, color=INK2, fontsize=8, va="top")
ax.set_title("Monthly net revenue (₹ lakh), all stores")
ax.set_ylim(0)
save(fig, "monthly_revenue.png")

fig, ax = plt.subplots(figsize=(8, 3.8))
s = store.sort_values("sla_rate")
bars = ax.barh(s["store_name"], s["sla_rate"] * 100, color=[ORANGE if v < .5 else BLUE for v in s["sla_rate"]],
               height=0.6)
for b, v, m in zip(bars, s["sla_rate"], s["avg_minutes"]):
    ax.text(b.get_width() + 1, b.get_y() + b.get_height() / 2, f"{v:.0%}  ·  avg {m:.1f} min", va="center",
            color=INK2, fontsize=9)
ax.set_xlim(0, 100)
ax.set_title("Orders delivered within 10 minutes, by dark store (%)")
ax.grid(axis="y", visible=False)
save(fig, "sla_by_store.png")

fig, ax = plt.subplots(figsize=(9, 3.4))
pv = heat.pivot(index="weekday", columns="hour", values="sla_rate") * 100
im = ax.imshow(pv, aspect="auto", cmap="Blues", vmin=30, vmax=75)
ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
ax.set_xticks(range(len(pv.columns)), [f"{h}" for h in pv.columns])
ax.set_xlabel("Hour of day")
ax.grid(False)
ax.set_title("10-minute SLA (%) by weekday and hour: evening rush is where promises break")
fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
save(fig, "sla_heatmap.png")

fig, ax = plt.subplots(figsize=(8, 3.8))
rb = rain_by_store.loc[store.sort_values("sla_rate", ascending=False)["store_name"]] * 100
y = np.arange(len(rb))
ax.barh(y - 0.19, rb[0], 0.36, color=BLUE, label="Dry day")
ax.barh(y + 0.19, rb[1], 0.36, color=ORANGE, label="Rain day")
ax.set_yticks(y, rb.index)
ax.invert_yaxis()
ax.set_xlim(0, 100)
ax.grid(axis="y", visible=False)
ax.legend(frameon=False, loc="lower right")
ax.set_title("10-minute SLA (%) on dry vs rain days")
save(fig, "rain_impact.png")

fig, ax = plt.subplots(figsize=(8, 4.4))
cp = coh_pct.iloc[:, :7] * 100
im = ax.imshow(cp, aspect="auto", cmap="Blues", vmin=0, vmax=100)
for (i, j), v in np.ndenumerate(cp.values):
    if not np.isnan(v):
        ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8, color="white" if v > 60 else INK)
ax.set_yticks(range(len(cp)), [str(p) for p in cp.index])
ax.set_xticks(range(cp.shape[1]), [f"M{j}" for j in cp.columns])
ax.grid(False)
ax.set_title("Customer retention by signup month (% still ordering)")
save(fig, "cohort_retention.png")

fig, ax = plt.subplots(figsize=(8, 4))
c2 = cat.sort_values("revenue")
ax.barh(c2["category"], c2["revenue"] / 1e5, color=BLUE, height=0.6)
for yv, (r, m) in enumerate(zip(c2["revenue"], c2["margin_pct"])):
    ax.text(r / 1e5 + 1, yv, f"margin {m:.0%}", va="center", fontsize=8.5, color=INK2)
ax.set_title("Revenue by category (₹ lakh) with gross margin")
ax.grid(axis="y", visible=False)
save(fig, "category_revenue.png")

# ------------------------------------------------------------------ Tableau flat file
# one row per order with store + customer attributes joined in (Tableau Public
# handles one wide CSV more easily than six related ones)
flat = orders.drop(columns=["date", "month", "hour", "weekday", "delivered", "cancelled", "store_name"]) \
    .merge(stores[["store_id", "store_name", "zone", "latitude", "longitude"]], on="store_id") \
    .merge(customers.rename(columns={"home_store_id": "customer_home_store"}), on="customer_id")
flat["signup_month"] = flat["signup_date"].dt.strftime("%Y-%m")
flat.drop(columns=["signup_date", "customer_home_store"]).to_csv(
    ROOT / "tableau" / "darkstore_orders_flat.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")

# ------------------------------------------------------------------ web dashboard data
ds = orders.groupby(["date", "store_id"]).agg(
    o=("order_id", "size"), d=("delivered", "sum"), r=("net_revenue", "sum"), c=("contribution", "sum"),
    s=("sla_met", "sum"), m=("delivery_minutes", "sum"), rs=("rating", "sum"), rn=("rating", "count"),
    n=("is_first_order", "sum"), rain=("is_rain_day", "max")).reset_index()
hw = dl.groupby(["store_id", "weekday", "hour"]).agg(d=("order_id", "size"), s=("sla_met", "sum")).reset_index()
cm = sold.merge(stores[["store_id", "store_name"]], on="store_name").groupby(
    ["month", "store_id", "category"]).agg(r=("revenue", "sum"), g=("gross_profit", "sum")).reset_index()
web = {
    "stores": stores[["store_id", "store_name", "zone", "latitude", "longitude", "open_date"]]
        .assign(open_date=lambda f: f["open_date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
    "categories": list(cat["category"]),
    "daily": [[d.strftime("%Y-%m-%d"), s, int(o), int(dd), round(r), round(c), int(sl), round(m, 1), int(rs), int(rn),
               int(n), int(rn_)] for d, s, o, dd, r, c, sl, m, rs, rn, n, rn_ in ds.itertuples(index=False)],
    "hourly": hw.values.tolist(),
    "catMonthly": [[str(m), s, c, round(r), round(g)] for m, s, c, r, g in cm.itertuples(index=False)],
    "headline": {
        "sla": k["sla_rate"], "bestSla": float(best["sla_rate"]), "worstSla": float(worst["sla_rate"]),
        "ratingOnTime": float(rating_band["avg_rating"].iloc[0]), "rating20": float(rating_band["avg_rating"].iloc[-1]),
        "low20": float(rating_band["low_rating_share"].iloc[-1]),
        "rainDemand": rain_demand_monsoon,
        "rainGap": float((rain.loc[rain["is_rain_day"] == 0, "sla_rate"].iloc[0]
                          - rain.loc[rain["is_rain_day"] == 1, "sla_rate"].iloc[0]) * 100),
        "diwali": fest_rel["Diwali"], "sweets": findings["sweets_festival_revenue_share"],
        "paidOpc": float(channel.set_index("acquisition_channel").at["Paid Ads", "orders_per_customer"]),
        "orgOpc": float(channel.set_index("acquisition_channel").at["Organic", "orders_per_customer"]),
        "cpnYes": float(coupon[1]), "cpnNo": float(coupon[0]),
    },
    "cohort": {"labels": [str(p) for p in coh_pct.index],
               "values": [[None if np.isnan(v) else round(v * 100, 1) for v in row] for row in coh_pct.values]},
}
(ROOT / "docs" / "data.js").write_text("window.DSP_DATA = " + json.dumps(web, separators=(",", ":")) + ";\n")

print(json.dumps({kk: round(v, 4) if isinstance(v, float) else v for kk, v in k.items()}, indent=1))
print("peak/off-peak SLA", hour_sla, "\nfestival uplift", fest_rel, "\nM1/M3", m1, m3)
print(store.to_string(index=False))
print(rain.to_string(index=False))
print(cat.to_string(index=False))
print(channel.round(2).to_string(index=False))
print(pay.round(3).to_string(index=False))
print(rating_band.round(3).to_string(index=False))
print(reasons.round(3).to_string(), "\ncoupon", coupon.round(1).to_dict(), "\nsweets fest share",
      findings["sweets_festival_revenue_share"], "\n", oos.round(3).to_string())
