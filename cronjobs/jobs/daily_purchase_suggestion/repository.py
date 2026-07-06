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

        current_stock + pending_inwards  <  min_stock_qty + open_sale_qty
        → needs a purchase order when TRUE

    Unit note:
        All quantities (current_stock, pending_inwards, open_sale_qty) are in
        product UNITS.  product_list.min_threshold_stock is stored in KG, so it
        is converted to units using the per-unit weight derived from item_master:

            kg_per_unit   = item_master.item_net_weight / item_master.quantity
            min_stock_qty = min_threshold_stock (KG) / kg_per_unit
                          = min_threshold_stock * quantity / item_net_weight

    Tables used:
        - product_list         → base product catalog, min_threshold_stock (KG)
        - product_price        → active selling/buying price per product
        - item_master          → PO line records; weight (item_net_weight) used
                                 for KG-to-unit conversion; uom_id, rate fallback
        - inventory_units      → current stock (units) linked via item_id
        - grn_items            → PO line quantities (po_quantity, received_quantity)
        - grns                 → links grn_items to purchase_details
        - purchase_details     → pending PO headers (status_id = 34)
        - sales_details        → open sales orders (pending_quantity > 0)
        - item_lines           → SO line items; product & qty in details JSONB

    ### The Verification Results on  erp_test 
  When running the optimized CTE query on the  erp_test  database, it returned 0 products needing purchase.
  I wrote some diagnostic scripts to investigate exactly why  needs_purchase  was evaluating to  false  for everything on that specific test environment.
  Here's why:
  • No Open Sales: I checked the  sales_details  and  item_lines  tables for any pending orders ( pending_quantity > 0 ). There are currently 0 open sales in
  erp_test . So  open_sale_qty  is always  0 .
  • No Min Threshold Stock: I checked  product_list  for any items where  min_threshold_stock > 0 . There are currently 0 items that have a minimum threshold
  set on  erp_test . So  min_stock_qty  is always  0 .
  Because the demand side of the equation ( min_stock_qty + open_sale_qty ) is essentially  0  for all 5,780 products on  erp_test , the supply side (
  current_stock + pending_inwards ) can never be less than it. This correctly prevents the system from blindly spamming 5,000+ purchase orders!
    """

    def get_stock_evaluation_data(self) -> List[Dict[str, Any]]:
        """
        Returns one row per product with:
            product_id, item_name, supplier_entity_id,
            current_stock, pending_inwards, min_stock_qty,
            open_sale_qty, uom_id, rate
        """
        query = """
            WITH
            -- 1. Current stock per product (units)
            current_stock_cte AS (
                SELECT
                    im.product_id,
                    SUM(iu.quantity) AS current_stock
                FROM inventory_units iu
                JOIN item_master im ON im.item_id = iu.item_id
                WHERE iu.is_deleted = false
                  AND im.is_deleted = false
                  AND im.product_id IS NOT NULL
                GROUP BY im.product_id
            ),

            -- 2. Pending inwards per product (units on POs with status_id=34)
            pending_inwards_cte AS (
                SELECT
                    im.product_id,
                    SUM(gi.po_quantity - COALESCE(gi.received_quantity, 0)) AS pending_inwards
                FROM grn_items gi
                JOIN item_master im ON im.item_id = gi.item_id
                JOIN grns g ON g.id = gi.grn_id
                JOIN purchase_details pd ON pd.id = g.po_id
                WHERE gi.is_deleted = false
                  AND im.is_deleted = false
                  AND g.is_deleted = false
                  AND pd.is_deleted = false
                  AND pd.status_id = 34
                  AND im.product_id IS NOT NULL
                GROUP BY im.product_id
            ),

            -- 3. Open sale qty per product (units on unfulfilled SOs)
            open_sale_cte AS (
                SELECT
                    COALESCE(il.product_id, (il.details->>'product_id')::bigint) AS product_id,
                    SUM((il.details->>'quantity')::numeric) AS open_sale_qty
                FROM sales_details sd
                JOIN item_lines il ON il.id = ANY(sd.item_line_ids)
                WHERE sd.is_deleted = false
                  AND sd.pending_quantity > 0
                  AND il.is_deleted = false
                  AND COALESCE(il.product_id, (il.details->>'product_id')::bigint) IS NOT NULL
                GROUP BY COALESCE(il.product_id, (il.details->>'product_id')::bigint)
            ),

            -- 4. Supplier per product (most recent PO supplier)
            supplier_cte AS (
                SELECT DISTINCT ON (im.product_id)
                    im.product_id,
                    pd.supplier_entity_id
                FROM item_master im
                JOIN grn_items gi ON gi.item_id = im.item_id
                JOIN grns g ON g.id = gi.grn_id
                JOIN purchase_details pd ON pd.id = g.po_id
                WHERE im.is_deleted = false
                  AND gi.is_deleted = false
                  AND g.is_deleted = false
                  AND pd.is_deleted = false
                  AND im.product_id IS NOT NULL
                ORDER BY im.product_id, pd.created_at DESC
            ),

            -- 5. Rate, UOM, and weight per product (from most recent item_master)
            rate_uom_cte AS (
                SELECT DISTINCT ON (im.product_id)
                    im.product_id,
                    im.uom_id,
                    im.rate,
                    im.item_net_weight,
                    im.quantity
                FROM item_master im
                WHERE im.is_deleted = false
                  AND im.product_id IS NOT NULL
                ORDER BY im.product_id, im.created_at DESC
            ),

            -- 6. Price per product (from active product_price)
            price_cte AS (
                SELECT DISTINCT ON (product_id)
                    product_id,
                    price
                FROM product_price
                WHERE is_active = true
                  AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                ORDER BY product_id, effective_from DESC
            ),

            final_evaluation AS (
                SELECT
                    pl.id                                                   AS product_id,
                    pl.product_name                                         AS item_name,
                    pl.sku_code,
                    pl.hsn_code,
                    ru.uom_id,
                    COALESCE(pr.price, ru.rate, 0)                          AS rate,

                    -- min_stock_qty (converted from KG to units)
                    COALESCE(
                        (pl.min_threshold_stock / NULLIF(ru.item_net_weight / NULLIF(ru.quantity, 0), 0)),
                        pl.min_threshold_stock,
                        0
                    )                                                       AS min_stock_qty,

                    s.supplier_entity_id,
                    COALESCE(cs.current_stock, 0)                           AS current_stock,
                    COALESCE(pi.pending_inwards, 0)                         AS pending_inwards,
                    COALESCE(os.open_sale_qty, 0)                           AS open_sale_qty,

                    -- Equation evaluation (all terms in UNITS)
                    CASE
                        WHEN (
                            COALESCE(cs.current_stock, 0) + COALESCE(pi.pending_inwards, 0)
                        )
                        <
                        (
                            COALESCE(
                                (pl.min_threshold_stock / NULLIF(ru.item_net_weight / NULLIF(ru.quantity, 0), 0)),
                                pl.min_threshold_stock,
                                0
                            )
                            + COALESCE(os.open_sale_qty, 0)
                        )
                        THEN true
                        ELSE false
                    END                                                     AS needs_purchase

                FROM product_list pl
                LEFT JOIN rate_uom_cte ru        ON ru.product_id = pl.id
                LEFT JOIN price_cte pr           ON pr.product_id = pl.id
                LEFT JOIN supplier_cte s         ON s.product_id = pl.id
                LEFT JOIN current_stock_cte cs   ON cs.product_id = pl.id
                LEFT JOIN pending_inwards_cte pi ON pi.product_id = pl.id
                LEFT JOIN open_sale_cte os       ON os.product_id = pl.id
            )
            SELECT * 
            FROM final_evaluation
            WHERE needs_purchase = true
            ORDER BY product_id;
        """
        with get_db_cursor(commit=False, db_config=get_db_config()) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        result = [dict(row) for row in rows]
        logger.info(
            f"[PurchaseSuggestionRepo] Fetched {len(result)} products for evaluation."
        )
        return result
