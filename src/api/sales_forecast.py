from fastapi import APIRouter, Query
from datetime import date, timedelta
import calendar
from src.models import APIOutput
from src.utils.database import get_db_cursor, get_db_config
from src.utils import logger

router = APIRouter()

def subtract_months(d: date, months: int) -> date:
    """Helper to subtract months from a date"""
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)

@router.get("/sales/forecast")
async def get_sales_forecast(
    month: int = Query(..., ge=1, le=12, description="Month of forecast (1-12)"),
    year: int = Query(..., ge=2000, le=2100, description="Year of forecast (e.g. 2024)")
):
    """
    Generate sales forecast for a given month and year.
    Uses target_db_config (remote neon postgres database).
    """
    try:
        # 1. Calculate dates
        target_date = date(year, month, 1)
        
        # Last 3 months range
        start_date_3m = subtract_months(target_date, 3)
        end_date_3m = target_date - timedelta(days=1)
        
        # Same month previous year range
        start_date_ly = date(year - 1, month, 1)
        end_date_ly = date(year - 1, month, calendar.monthrange(year - 1, month)[1])
        
        # 2. Query target database for both periods
        db_config = get_db_config()
        
        last_3m_data = {}
        last_year_data = {}
        
        query = """
            SELECT 
                COALESCE(il.details->>'product_name', il.details->>'item_name') as product_name,
                SUM((il.details->>'quantity')::numeric) as total_qty,
                SUM((il.details->>'amount')::numeric) as total_amount
            FROM sales_details sd
            CROSS JOIN UNNEST(sd.item_line_ids) as line_id
            JOIN item_lines il ON il.id = line_id
            WHERE sd.date >= %s AND sd.date <= %s
              AND sd.is_deleted = FALSE AND il.is_deleted = FALSE
            GROUP BY COALESCE(il.details->>'product_name', il.details->>'item_name');
        """
        
        with get_db_cursor(commit=False, db_config=db_config) as cursor:
            # Execute for last 3 months
            logger.info(f"Querying sales forecast 3m from {start_date_3m} to {end_date_3m}")
            cursor.execute(query, (start_date_3m, end_date_3m))
            rows_3m = cursor.fetchall()
            for row in rows_3m:
                name = row.get("product_name")
                if not name or name.strip().lower() in ["unknown", "none", "null"]:
                    continue
                qty = float(row.get("total_qty") or 0)
                amt = float(row.get("total_amount") or 0)
                last_3m_data[name] = {
                    "avg_qty": qty / 3.0,
                    "avg_amount": amt / 3.0
                }
                
            # Execute for same month last year
            logger.info(f"Querying sales forecast same month last year from {start_date_ly} to {end_date_ly}")
            cursor.execute(query, (start_date_ly, end_date_ly))
            rows_ly = cursor.fetchall()
            for row in rows_ly:
                name = row.get("product_name")
                if not name or name.strip().lower() in ["unknown", "none", "null"]:
                    continue
                qty = float(row.get("total_qty") or 0)
                amt = float(row.get("total_amount") or 0)
                last_year_data[name] = {
                    "qty": qty,
                    "amount": amt
                }
                
        # 3. Combine and compute forecast
        all_products = set(last_3m_data.keys()).union(set(last_year_data.keys()))
        forecasted_items = []
        
        for prod in all_products:
            p_3m = last_3m_data.get(prod, {"avg_qty": 0.0, "avg_amount": 0.0})
            p_ly = last_year_data.get(prod, {"qty": 0.0, "amount": 0.0})
            
            # Forecast Formula: (Average Last 3 Months + Same Month Last Year) / 2
            pred_qty = (p_3m["avg_qty"] + p_ly["qty"]) / 2.0
            pred_amt = (p_3m["avg_amount"] + p_ly["amount"]) / 2.0
            
            if pred_qty > 0 or pred_amt > 0:
                forecasted_items.append({
                    "item_name": prod,
                    "last_3m_avg_quantity": round(p_3m["avg_qty"], 2),
                    "last_3m_avg_amount": round(p_3m["avg_amount"], 2),
                    "last_year_same_month_quantity": round(p_ly["qty"], 2),
                    "last_year_same_month_amount": round(p_ly["amount"], 2),
                    "predicted_quantity": round(pred_qty, 2),
                    "predicted_amount": round(pred_amt, 2)
                })
                
        # Sort items by forecasted amount descending
        forecasted_items.sort(key=lambda x: x["predicted_amount"], reverse=True)
        
        result = {
            "forecast_month": f"{year}-{month:02d}",
            "forecasted_items": forecasted_items
        }
        
        return APIOutput.success(
            data=result,
            message="Sales forecast generated successfully"
        )
        
    except Exception as e:
        logger.error(f"Error during sales forecast generation: {str(e)}")
        return APIOutput.failure(message=str(e))
