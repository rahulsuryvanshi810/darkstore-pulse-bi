"""Data-quality checks: the BI reports are only as good as these hold."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def t():
    read = lambda n, **kw: pd.read_csv(DATA / f"{n}.csv", keep_default_na=False, na_values=[""], **kw)
    return {
        "orders": read("orders", parse_dates=["order_datetime"]),
        "items": read("order_items"),
        "stores": read("stores", parse_dates=["open_date"]),
        "products": read("products"),
        "customers": read("customers", parse_dates=["signup_date"]),
        "riders": read("riders"),
    }


def test_primary_keys_unique(t):
    for name, key in [("orders", "order_id"), ("stores", "store_id"), ("products", "product_id"),
                      ("customers", "customer_id"), ("riders", "rider_id")]:
        assert t[name][key].is_unique, name


def test_foreign_keys_resolve(t):
    o = t["orders"]
    assert o["store_id"].isin(t["stores"]["store_id"]).all()
    assert o["customer_id"].isin(t["customers"]["customer_id"]).all()
    assert o["rider_id"].isin(t["riders"]["rider_id"]).all()
    assert t["items"]["order_id"].isin(o["order_id"]).all()
    assert t["items"]["product_id"].isin(t["products"]["product_id"]).all()


def test_item_lines_reconcile_with_order_totals(t):
    it = t["items"]
    line = (it["quantity"] * it["mrp"] * it["fulfilled"]).groupby(it["order_id"]).sum()
    o = t["orders"].set_index("order_id")
    assert np.allclose(line.reindex(o.index), o["item_total"], atol=0.01)
    assert (it.groupby("order_id").size().reindex(o.index) == o["items_count"]).all()


def test_money_fields_add_up(t):
    o = t["orders"]
    d = o[o["status"] == "Delivered"]
    assert np.allclose(d["net_revenue"], d["item_total"] - d["discount"] + d["delivery_fee"])
    assert np.allclose(d["contribution"], d["net_revenue"] - d["cogs"] - d["rider_cost"], atol=0.02)
    c = o[o["status"] == "Cancelled"]
    assert (c["net_revenue"] == 0).all() and (c["contribution"] == 0).all()


def test_cancelled_orders_have_no_delivery_data(t):
    o = t["orders"]
    c = o[o["status"] == "Cancelled"]
    assert c["delivery_minutes"].isna().all() and c["rating"].isna().all() and c["sla_met"].isna().all()
    d = o[o["status"] == "Delivered"]
    assert d["delivery_minutes"].notna().all()
    assert ((d["delivery_minutes"] <= 10) == (d["sla_met"] == 1)).all()


def test_orders_inside_period_and_after_store_opening(t):
    o = t["orders"].merge(t["stores"][["store_id", "open_date"]], on="store_id")
    assert o["order_datetime"].min() >= pd.Timestamp("2025-10-01")
    assert o["order_datetime"].max() < pd.Timestamp("2026-10-01")
    assert (o["order_datetime"].dt.normalize() >= o["open_date"]).all()
    assert o["order_datetime"].dt.hour.between(6, 23).all()


def test_first_order_is_on_signup_date(t):
    o = t["orders"].sort_values("order_datetime")
    first = o.groupby("customer_id").first()
    signup = t["customers"].set_index("customer_id")["signup_date"]
    assert (first["order_datetime"].dt.normalize() == signup.reindex(first.index)).all()
    assert o["is_first_order"].sum() == len(t["customers"])


def test_ratings_and_values_in_range(t):
    o = t["orders"]
    assert o["rating"].dropna().between(1, 5).all()
    assert (o["discount"] <= o["item_total"]).all()
    p = t["products"]
    assert (p["unit_cost"] < p["mrp"]).all()
