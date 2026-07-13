from fastapi import APIRouter, Query
import pandas as pd

from src.models import APIOutput
from src.utils import logger
from ml_sales_forecast.predict import forecast_month

router = APIRouter()


@router.get("/sales/ml-forecast")
async def get_ml_sales_forecast(
    month: int = Query(..., ge=1, le=12, description="Month of forecast (1-12)"),
    year: int = Query(..., ge=2000, le=2100, description="Year of forecast (e.g. 2026)"),
    company: str | None = Query(None, description="Filter by company name (partial match)"),
    product: str | None = Query(None, description="Filter by product name (partial match)"),
    top: int = Query(20, ge=1, le=500, description="Max number of items to return"),
):
    """
    Sales forecast from the trained ML model (ml_sales_forecast/model.joblib),
    trained on the historical Tally sales registers under ml_sales_forecast/monthly_sales.csv.
    """
    try:
        target_period = pd.Period(year=year, month=month, freq="M")
        df = forecast_month(target_period, company, product)

        items = df.head(top).to_dict(orient="records")
        result = {
            "forecast_month": str(target_period),
            "items": items,
        }
        return APIOutput.success(data=result, message="ML sales forecast generated successfully")
    except FileNotFoundError:
        return APIOutput.failure(message="Model not trained yet - run `uv run python -m ml_sales_forecast.train` first")
    except Exception as e:
        logger.error(f"Error during ML sales forecast generation: {str(e)}")
        return APIOutput.failure(message=str(e))
