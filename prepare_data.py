
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data")

COUNTRY_REGION_MAP = {
    "United States": "NA",
    "Canada": "NA",
    "Mexico": "LATAM",
    "Brazil": "LATAM",
    "Argentina": "LATAM",
    "Colombia": "LATAM",
    "United Kingdom": "EU",
    "Germany": "EU",
    "France": "EU",
    "Netherlands": "EU",
    "Spain": "EU",
    "Italy": "EU",
    "Sweden": "EU",
    "Poland": "EU",
    "Belgium": "EU",
    "Australia": "APAC",
    "Japan": "APAC",
    "India": "APAC",
    "Singapore": "APAC",
    "New Zealand": "APAC",
    "South Korea": "APAC",
}

def load_csv(file_name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / file_name)

def save_csv(df: pd.DataFrame, file_name: str) -> None:
    output_path = DATA_DIR / file_name

    if output_path.exists():
        output_path.unlink()
        print(f"Deleted old file: {output_path}")

    df.to_csv(output_path, index=False)
    print(f"Saved {output_path} ({len(df):,} rows)")

print("Loading raw data...")
customers = load_csv("Customers.csv")
events = load_csv("Events.csv")
products = load_csv("Products.csv")

print("\nCleaning Customers...")
customers = customers.copy()
customers["signup_date"] = pd.to_datetime(customers["signup_date"], errors="coerce")

customers["region"] = customers.apply(
    lambda row: COUNTRY_REGION_MAP.get(row["country"], row["region"])
    if pd.isna(row["region"])
    else row["region"],
    axis=1,
)

customers["region"] = customers["region"].fillna("Other")

save_csv(customers, "customers_clean.csv")

print("\nCleaning Events...")
events = events.copy()

events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce")
events["refund_datetime"] = pd.to_datetime(
    events["refund_datetime"],
    errors="coerce"
)

events["discount_code"] = events["discount_code"].fillna("No Discount").astype(str)
events["refund_reason"] = events["refund_reason"].fillna("Not Refunded")

events["region"] = events.apply(
    lambda row: COUNTRY_REGION_MAP.get(row["country"], "Other")
    if pd.isna(row["region"])
    else row["region"],
    axis=1,
)

events["year"] = events["event_date"].dt.year
events["month_num"] = events["event_date"].dt.month
events["month_name"] = events["event_date"].dt.strftime("%b")
events["quarter"] = events["event_date"].dt.quarter.apply(lambda x: f"Q{x}")
events["year_month"] = events["event_date"].dt.to_period("M").astype(str)

events["is_order"] = (events["event_type"] == "order").astype(int)
events["is_invoice"] = (events["event_type"] == "invoice").astype(int)
events["has_discount"] = (events["discount_code"] != "No Discount").astype(int)

events["revenue_net"] = np.where(
    events["is_refunded"],
    -events["net_revenue_usd"],
    events["net_revenue_usd"]
)

save_csv(events, "events_clean.csv")

print("\nBuilding Loyal Customers table...")

orders_only = events[events["event_type"] == "order"].copy()

customer_dates = (
    orders_only.sort_values("event_date")
    .groupby("customer_id")["event_date"]
    .agg(["min", "max", "count"])
    .reset_index()
)

customer_dates.columns = [
    "customer_id",
    "first_purchase_date",
    "last_purchase_date",
    "order_count",
]

second_purchase = (
    orders_only.sort_values("event_date")
    .groupby("customer_id")
    .nth(1)
    .reset_index()[["customer_id", "event_date"]]
)

second_purchase.columns = [
    "customer_id",
    "second_purchase_date"
]

customer_dates = customer_dates.merge(
    second_purchase,
    on="customer_id",
    how="left"
)

customer_dates["days_to_second_purchase"] = (
    customer_dates["second_purchase_date"]
    - customer_dates["first_purchase_date"]
).dt.days

customer_revenue = (
    events[~events["is_refunded"]]
    .groupby("customer_id")["net_revenue_usd"]
    .sum()
    .reset_index()
)

customer_revenue.columns = [
    "customer_id",
    "total_revenue_usd"
]

loyal_customers = customer_dates.merge(
    customer_revenue,
    on="customer_id",
    how="left"
)

loyal_customers = loyal_customers.merge(
    customers[
        [
            "customer_id",
            "segment",
            "acquisition_channel",
            "region",
            "country",
            "age_band",
            "signup_date",
        ]
    ],
    on="customer_id",
    how="left",
)

# ---------------------------------------------------------
# DYNAMIC LOYALTY THRESHOLD (Top 25% Customers)
# ---------------------------------------------------------

threshold = int(
    np.ceil(
        loyal_customers["order_count"].quantile(0.75)
    )
)

print("\nLoyal Customer Threshold")
print(f"Customers with {threshold}+ orders are classified as Loyal")

loyal_customers["is_loyal"] = (
    loyal_customers["order_count"] >= threshold
).astype(int)

loyal_customers["loyalty_label"] = loyal_customers["is_loyal"].map(
    {
        1: "Loyal",
        0: "One-Time"
    }
)

print("\nLoyality Distribution")
print(loyal_customers["loyalty_label"].value_counts())

print("\nOrder Count Statistics")
print(loyal_customers["order_count"].describe())

print("\nLoyality Distribution")
print(loyal_customers["is_loyal"].value_counts())

print("\nOrder Count Statistics")
print(loyal_customers["order_count"].describe())

save_csv(loyal_customers, "loyal_customers.csv")

print("\nBuilding Monthly Summary...")

events_loyal = events.merge(
    loyal_customers[
        [
            "customer_id",
            "is_loyal",
            "loyalty_label"
        ]
    ],
    on="customer_id",
    how="left",
)

monthly_summary = (
    events_loyal[
        events_loyal["event_type"] == "order"
    ]
    .groupby("year_month")
    .agg(
        total_orders=("event_id", "count"),
        loyal_orders=("is_loyal", "sum"),
        total_revenue=("net_revenue_usd", "sum"),
        total_customers=("customer_id", "nunique"),
    )
    .reset_index()
)

monthly_summary["loyal_order_pct"] = (
    monthly_summary["loyal_orders"]
    / monthly_summary["total_orders"]
    * 100
).round(1)

monthly_summary["avg_order_value"] = (
    monthly_summary["total_revenue"]
    / monthly_summary["total_orders"]
).round(2)

save_csv(monthly_summary, "monthly_summary.csv")

print("\nAll requested files created successfully")
print("data/customers_clean.csv")
print("data/events_clean.csv")
print("data/loyal_customers.csv")
print("data/monthly_summary.csv")

