"""
Verify the model: for a given month, train using only data BEFORE that month,
predict that month, then compare against the actual figures for that month.

Usage:
    .venv/bin/python ml_sales_forecast/verify.py --month 6 --year 2026
    .venv/bin/python ml_sales_forecast/verify.py --month 6 --year 2026 --company "Rahul Traders" --top 10
"""
import argparse
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from ml_sales_forecast.train import build_features

DATA_PATH = Path(__file__).parent / "monthly_sales.csv"

QTY_COLS = ["quantity_lag1", "quantity_lag2", "quantity_lag3", "quantity_rolling_mean_3",
            "quantity_overall_avg", "month_num", "quarter", "company_code"]


def main():
    parser = argparse.ArgumentParser(description="Verify model: actual vs predicted for a given month")
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--company", type=str, default=None, help="Filter by company name (partial match)")
    parser.add_argument("--top", type=int, default=15, help="Show top N rows by actual quantity")
    args = parser.parse_args()

    target = pd.Period(year=args.year, month=args.month, freq="M")

    raw = pd.read_csv(DATA_PATH)
    available_months = pd.PeriodIndex(raw["month"], freq="M").unique()
    if target not in available_months:
        print(f"No actual data exists for {target} in the source files — can't verify against a real month.")
        print(f"Months with data: {sorted(str(m) for m in available_months)}")
        return

    featured = build_features(raw)
    df = featured.dropna(subset=["quantity_lag1"]).copy()
    df["company_code"] = df["company"].astype("category").cat.codes

    train_rows = df[df["month"] < target]
    test_rows = df[df["month"] == target].copy()
    if args.company:
        test_rows = test_rows[test_rows["company"].str.contains(args.company, case=False, na=False)]

    if test_rows.empty:
        print("No rows to verify (check --company filter).")
        return

    model = RandomForestRegressor(n_estimators=300, max_depth=12, min_samples_leaf=2, random_state=42, n_jobs=-1)
    model.fit(train_rows[QTY_COLS], train_rows["quantity"])

    test_rows["predicted_quantity"] = model.predict(test_rows[QTY_COLS]).round(1)
    test_rows["error"] = (test_rows["predicted_quantity"] - test_rows["quantity"]).round(1)
    test_rows["error_pct"] = (test_rows["error"].abs() / test_rows["quantity"].replace(0, pd.NA) * 100).round(1)

    mae = mean_absolute_error(test_rows["quantity"], test_rows["predicted_quantity"])
    r2 = r2_score(test_rows["quantity"], test_rows["predicted_quantity"])
    naive_mae = mean_absolute_error(test_rows["quantity"], test_rows["quantity_lag1"])

    print(f"\nVerifying {target}  (model trained only on data before this month, never saw it)")
    print(f"Rows tested: {len(test_rows)}")
    print(f"MAE:  {mae:.1f} units   |   naive (repeat last month) MAE: {naive_mae:.1f}")
    print(f"R^2:  {r2:.3f}\n")

    cols = ["company", "product", "quantity", "predicted_quantity", "error", "error_pct"]
    show = test_rows[cols].rename(columns={"quantity": "actual_quantity"})
    print("Sample rows (sorted by actual quantity, biggest sellers first):")
    print(show.sort_values("actual_quantity", ascending=False).head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
