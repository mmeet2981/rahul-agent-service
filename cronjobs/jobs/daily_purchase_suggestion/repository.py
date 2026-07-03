"""
Repository layer (Single Responsibility Principle).
Responsible ONLY for reading stock / sale / GRN data from the database.
"""
import logging
from typing import List, Dict, Any
from src.utils.database import get_db_cursor, get_db_config

logger = logging.getLogger(__name__)


class PurchaseSuggestionRepository:
    """
    Fetches all data needed to evaluate the purchase suggestion condition:

        Current stock + Pending inwards > min_stock_qty + sale order items

    Tables used:
        - item_master          → product list, min_stock_qty
        - inventory_units      → current stock per product
        - purchase_details     → pending PO headers
        - item_lines           → PO line items (pending inwards)
        - sale_details         → open sales orders
        - grns                 → goods receipt notes
        - grn_items            → GRN line items
    """

    def get_stock_evaluation_data(self) -> List[Dict[str, Any]]:
        """
        Returns one row per product with:
            product_id, item_name, supplier_entity_id,
            current_stock, pending_inwards, min_stock_qty,
            open_sale_qty, uom_id, rate
        """
        query = """
            SELECT
                im.product_id,
                im.item_name,
                im.supplier_entity_id,
                im.uom_id,
                im.rate,
                COALESCE(im.min_stock_qty, 0)             AS min_stock_qty,

                -- Current stock from inventory_units
                COALESCE(
                    (
                        SELECT SUM(iu.quantity)
                        FROM inventory_units iu
                        WHERE iu.product_id = im.product_id
                    ), 0
                )                                          AS current_stock,

                -- Pending inwards: sum of quantities on open/pending POs
                COALESCE(
                    (
                        SELECT SUM(il.quantity)
                        FROM item_lines il
                        JOIN purchase_details pd ON pd.id = il.purchase_id
                        WHERE il.product_id = im.product_id
                          AND pd.status_id = 34          -- pending status
                    ), 0
                )                                          AS pending_inwards,

                -- Open sales order quantities
                COALESCE(
                    (
                        SELECT SUM(sd.quantity)
                        FROM sale_details sd
                        WHERE sd.product_id = im.product_id
                          AND sd.is_fulfilled = false
                    ), 0
                )                                          AS open_sale_qty

            FROM item_master im
            WHERE im.is_deleted = false
              AND im.supplier_entity_id IS NOT NULL
        """
        with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        result = [dict(row) for row in rows]
        logger.info(
            f"[PurchaseSuggestionRepo] Fetched {len(result)} products for evaluation."
        )
        return result
