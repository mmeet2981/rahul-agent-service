"""
Query the trained sales forecast model for a given month/year.

Usage:
    .venv/bin/python ml_sales_forecast/predict.py --month 7 --year 2026
    .venv/bin/python ml_sales_forecast/predict.py --month 7 --year 2026 --company "Rahul Traders"
    .venv/bin/python ml_sales_forecast/predict.py --month 7 --year 2026 --product "JK-STIFNER"
"""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_PATH = Path(__file__).parent / "model.joblib"
SERIES_PATH = Path(__file__).parent / "series_features.csv"

# the model only ever trained on up to 3 months of lag history; recursively
# forecasting further out than that just compounds noise, so series whose last
# known month is older than this are reported as stale instead of guessed
MAX_FORECAST_HORIZON_MONTHS = 3


def forecast_month(target_period: pd.Period, company_filter: str | None, product_filter: str | None) -> pd.DataFrame:
    bundle = joblib.load(MODEL_PATH)
    qty_model = bundle["quantity_model"]
    rate_model = bundle["rate_model"]
    qty_cols = bundle["qty_feature_cols"]
    rate_cols = bundle["rate_feature_cols"]
    company_categories = bundle["company_categories"]

    series = pd.read_csv(SERIES_PATH)
    series["month"] = pd.PeriodIndex(series["month"], freq="M")

    if company_filter:
        series = series[series["company"].str.contains(company_filter, case=False, na=False)]
    if product_filter:
        series = series[series["product"].str.contains(product_filter, case=False, na=False)]

    last_rows = series.sort_values("month").groupby(["company", "product"], as_index=False).tail(1).copy()
    last_rows = last_rows[last_rows["company"].isin(company_categories)]

    # months already present in the data: return the actual figure, no need to predict
    known_mask = last_rows["month"] >= target_period
    known = last_rows[known_mask]
    actual = series[series["month"] == target_period]
    known_results = actual.merge(known[["company", "product"]], on=["company", "product"])[
        ["company", "product", "quantity", "value"]
    ].rename(columns={"quantity": "predicted_quantity", "value": "predicted_value"})
    known_results["basis"] = "actual (already in data)"

    # everything else needs forecasting, batched by "how many months ahead" so every
    # series in a batch takes the same number of recursive prediction steps at once
    candidates = last_rows[~known_mask].copy()
    candidates["steps_ahead"] = candidates["month"].apply(lambda m: (target_period - m).n)

    stale_mask = candidates["steps_ahead"] > MAX_FORECAST_HORIZON_MONTHS
    stale = candidates[stale_mask].copy()
    stale["predicted_quantity"] = float("nan")
    stale["predicted_value"] = float("nan")
    stale["basis"] = stale.apply(
        lambda r: f"insufficient recent data (last sale: {r['month']}, {r['steps_ahead']} months stale)", axis=1
    )

    to_forecast = candidates[~stale_mask].copy()
    to_forecast["company_code"] = to_forecast["company"].map(company_categories.index)

    qty_hist = to_forecast[["quantity", "quantity_lag1", "quantity_lag2"]].to_numpy(dtype=float)
    rate_hist = to_forecast[["rate", "rate_lag1", "rate_lag2"]].to_numpy(dtype=float)
    cursor_months = to_forecast["month"].to_numpy()
    remaining = to_forecast["steps_ahead"].to_numpy()

    # roll the "average of every month so far" forward too: fold the last known
    # actual month into it now, then keep folding in each new prediction below
    n_prior = to_forecast["n_prior_months"].to_numpy(dtype=float)
    qty_overall_avg = (to_forecast["quantity_overall_avg"].fillna(0) * n_prior + to_forecast["quantity"]) / (n_prior + 1)
    rate_overall_avg = (to_forecast["rate_overall_avg"].fillna(0) * n_prior + to_forecast["rate"]) / (n_prior + 1)
    qty_overall_avg, rate_overall_avg = qty_overall_avg.to_numpy(), rate_overall_avg.to_numpy()
    n_seen = n_prior + 1

    max_steps = int(remaining.max()) if len(remaining) else 0
    for _ in range(max_steps):
        active = remaining > 0
        if not active.any():
            break
        cursor_months = np.where(active, cursor_months + 1, cursor_months)
        month_nums = np.array([m.month for m in cursor_months])
        quarters = np.array([m.quarter for m in cursor_months])

        qty_feat = pd.DataFrame({
            "quantity_lag1": qty_hist[:, 0], "quantity_lag2": qty_hist[:, 1], "quantity_lag3": qty_hist[:, 2],
            "quantity_rolling_mean_3": qty_hist.mean(axis=1),
            "quantity_overall_avg": qty_overall_avg,
            "month_num": month_nums, "quarter": quarters,
            "company_code": to_forecast["company_code"].to_numpy(),
        })[qty_cols]
        rate_feat = pd.DataFrame({
            "rate_lag1": rate_hist[:, 0], "rate_lag2": rate_hist[:, 1], "rate_lag3": rate_hist[:, 2],
            "rate_rolling_mean_3": rate_hist.mean(axis=1),
            "rate_overall_avg": rate_overall_avg,
            "month_num": month_nums, "quarter": quarters,
            "company_code": to_forecast["company_code"].to_numpy(),
        })[rate_cols]

        pred_qty = np.clip(qty_model.predict(qty_feat), 0, None)
        pred_rate = np.clip(rate_model.predict(rate_feat), 0, None)

        new_qty_hist = qty_hist.copy()
        new_rate_hist = rate_hist.copy()
        new_qty_hist[active, 2] = qty_hist[active, 1]
        new_qty_hist[active, 1] = qty_hist[active, 0]
        new_qty_hist[active, 0] = pred_qty[active]
        new_rate_hist[active, 2] = rate_hist[active, 1]
        new_rate_hist[active, 1] = rate_hist[active, 0]
        new_rate_hist[active, 0] = pred_rate[active]
        qty_hist, rate_hist = new_qty_hist, new_rate_hist

        qty_overall_avg = np.where(active, (qty_overall_avg * n_seen + pred_qty) / (n_seen + 1), qty_overall_avg)
        rate_overall_avg = np.where(active, (rate_overall_avg * n_seen + pred_rate) / (n_seen + 1), rate_overall_avg)
        n_seen = np.where(active, n_seen + 1, n_seen)
        remaining = np.where(active, remaining - 1, remaining)

    to_forecast["predicted_quantity"] = qty_hist[:, 0].round(1)
    # value is never predicted directly - it's always quantity * rate, so the two numbers
    # can never imply a unit price that never actually happened
    to_forecast["predicted_value"] = (qty_hist[:, 0] * rate_hist[:, 0]).round(1)
    to_forecast["basis"] = to_forecast["steps_ahead"].apply(lambda n: f"forecast ({n} month(s) ahead)")

    cols = ["company", "product", "predicted_quantity", "predicted_value", "basis"]
    df = pd.concat([known_results[cols], to_forecast[cols], stale[cols]], ignore_index=True)
    df = df.sort_values("predicted_value", ascending=False, na_position="last").reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="Get sales forecast for a month/year")
    parser.add_argument("--month", type=int, required=True, help="Month (1-12)")
    parser.add_argument("--year", type=int, required=True, help="Year (e.g. 2026)")
    parser.add_argument("--company", type=str, default=None, help="Filter by company name (partial match)")
    parser.add_argument("--product", type=str, default=None, help="Filter by product name (partial match)")
    parser.add_argument("--top", type=int, default=20, help="Show top N rows by predicted value")
    args = parser.parse_args()

    target_period = pd.Period(year=args.year, month=args.month, freq="M")
    df = forecast_month(target_period, args.company, args.product)

    print(f"\nSales Forecast — {target_period}")
    print(f"(company={args.company or 'ALL'}, product={args.product or 'ALL'})\n")
    if df.empty:
        print("No matching company/product found in historical data.")
        return

    print(df.head(args.top).to_string(index=False))
    print(f"\nTotal predicted quantity: {df['predicted_quantity'].sum():,.1f}")
    print(f"Total predicted value:    {df['predicted_value'].sum():,.1f}")


if __name__ == "__main__":
    main()
