"""
Train sales forecasting models (quantity + value) on the monthly
(company, product, month) dataset produced by data_prep.py.

Approach: for every (company, product) time series, use the past 3 months'
quantity/value as features (lag1, lag2, lag3, rolling mean) plus the calendar
month (seasonality) and company, to predict the current month's quantity and
value. This lets one combined model forecast any company/product instead of
training a separate model per series.
"""
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

DATA_PATH = Path(__file__).parent / "monthly_sales.csv"
MODEL_PATH = Path(__file__).parent / "model.joblib"


def add_lag_features(full: pd.DataFrame, col: str) -> pd.DataFrame:
    g = full.groupby(["company", "product"])
    full[f"{col}_lag1"] = g[col].shift(1)
    full[f"{col}_lag2"] = g[col].shift(2)
    full[f"{col}_lag3"] = g[col].shift(3)
    # a NaN lag here means the series simply isn't old enough yet to have that many
    # prior months (not that sales were zero) - filling it with 0 would tell the model
    # "sales collapsed to nothing", which is false and drags predictions down for young
    # series. Carry the last known value forward instead, so the feature says "assume
    # it continued at the level we do know about".
    full[f"{col}_lag2"] = full[f"{col}_lag2"].fillna(full[f"{col}_lag1"])
    full[f"{col}_lag3"] = full[f"{col}_lag3"].fillna(full[f"{col}_lag2"])
    full[f"{col}_rolling_mean_3"] = full[[f"{col}_lag1", f"{col}_lag2", f"{col}_lag3"]].mean(axis=1)
    # average of EVERY prior month in the series (not just the last 3) - a stable
    # long-run baseline so a single volatile recent month can't dominate the prediction
    full[f"{col}_overall_avg"] = g[col].transform(lambda s: s.shift(1).expanding().mean())
    return full


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = pd.PeriodIndex(df["month"], freq="M")

    filled_rows = []
    for (company, product), grp in df.groupby(["company", "product"]):
        grp = grp.set_index("month").sort_index()
        full_range = pd.period_range(grp.index.min(), grp.index.max(), freq="M")
        grp = grp.reindex(full_range)
        grp["company"] = company
        grp["product"] = product
        # a gap mid-series (e.g. Rahul Traders' missing 2025-04..2026-03) means the
        # export file is missing, not that sales stopped - zero-filling it would tell
        # the model "this product died", which is false and wrecks the lag features
        # for months right after the gap. Interpolate a straight line between the last
        # real month before the gap and the first real month after it instead.
        grp["quantity"] = grp["quantity"].interpolate(method="linear")
        grp["value"] = grp["value"].interpolate(method="linear")
        grp.index.name = "month"
        filled_rows.append(grp.reset_index())

    full = pd.concat(filled_rows, ignore_index=True)
    full = full.sort_values(["company", "product", "month"])

    # rate = value / quantity is true by construction in the source data (Tally
    # stores both per line item), so forecasting rate and deriving
    # value = quantity * rate keeps the two numbers consistent - instead of
    # predicting value independently, which can imply a rate that never happened.
    full["rate"] = full["value"] / full["quantity"]
    full["rate"] = full["rate"].replace([float("inf"), float("-inf")], pd.NA)
    full["rate"] = full.groupby(["company", "product"])["rate"].ffill()

    full = add_lag_features(full, "quantity")
    full = add_lag_features(full, "rate")
    full["month_num"] = full["month"].dt.month
    full["quarter"] = full["month"].dt.quarter
    # how many prior months went into *_overall_avg - needed to update the running
    # average incrementally when forecasting several months into the future
    full["n_prior_months"] = full.groupby(["company", "product"]).cumcount()

    return full


def train_target(train_df: pd.DataFrame, target: str, feature_cols: list[str]) -> tuple:
    """Evaluate on the last complete month, then refit on all rows. Returns the final fitted model."""
    months_sorted = sorted(train_df["month"].unique())
    eval_month = months_sorted[-2]
    eval_slice = train_df[train_df["month"] <= eval_month]
    test_mask = eval_slice["month"] == eval_month
    X_train, y_train = eval_slice.loc[~test_mask, feature_cols], eval_slice.loc[~test_mask, target]
    X_test, y_test = eval_slice.loc[test_mask, feature_cols], eval_slice.loc[test_mask, target]

    model = RandomForestRegressor(n_estimators=300, max_depth=12, min_samples_leaf=2, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    if len(X_test) > 0:
        preds = model.predict(X_test)
        mae = mean_absolute_error(y_test, preds)
        r2 = r2_score(y_test, preds)
        baseline_mae = mean_absolute_error(y_test, X_test[f"{target}_lag1"])
        print(f"\n[{target}] held-out month: {eval_month} (n={len(X_test)})")
        print(f"[{target}] MAE: {mae:.1f}   R^2: {r2:.3f}")
        print(f"[{target}] naive baseline (predict = last month) MAE: {baseline_mae:.1f}")

    model_full = RandomForestRegressor(n_estimators=300, max_depth=12, min_samples_leaf=2, random_state=42, n_jobs=-1)
    model_full.fit(train_df[feature_cols], train_df[target])
    return model_full


def main():
    raw = pd.read_csv(DATA_PATH)
    featured = build_features(raw)

    train_df = featured.dropna(subset=["quantity_lag1"]).copy()
    print(f"Rows with at least 1 month of prior history: {len(train_df)} / {len(featured)}")

    train_df["company_code"] = train_df["company"].astype("category").cat.codes
    company_categories = train_df["company"].astype("category").cat.categories.tolist()

    qty_feature_cols = ["quantity_lag1", "quantity_lag2", "quantity_lag3", "quantity_rolling_mean_3",
                         "quantity_overall_avg", "month_num", "quarter", "company_code"]
    rate_feature_cols = ["rate_lag1", "rate_lag2", "rate_lag3", "rate_rolling_mean_3",
                          "rate_overall_avg", "month_num", "quarter", "company_code"]
    qty_model = train_target(train_df, "quantity", qty_feature_cols)
    rate_model = train_target(train_df, "rate", rate_feature_cols)

    joblib.dump({
        "quantity_model": qty_model,
        "rate_model": rate_model,
        "qty_feature_cols": qty_feature_cols,
        "rate_feature_cols": rate_feature_cols,
        "company_categories": company_categories,
    }, MODEL_PATH)
    print(f"\nSaved trained models -> {MODEL_PATH}")

    # persist the per-series feature table (needed at predict time to build next month's lag features)
    featured.to_csv(Path(__file__).parent / "series_features.csv", index=False)


if __name__ == "__main__":
    main()
