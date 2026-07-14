"""
Business logic / service layer (Single Responsibility Principle).
Responsible ONLY for applying the purchase-suggestion condition and
deciding which products need a PO.

Condition (from po_context.txt):
    Current stock + Pending inwards < min_stock_qty + open_sale_qty
    → i.e., stock is NOT sufficient to cover min buffer + sales demand
    → a Purchase Order must be raised
"""
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class PurchaseSuggestionService:
    """
    Evaluates each product row fetched by the repository and returns a
    list of (product, suggested_qty) tuples that need a PO.
    """

    def evaluate(
        self, products: List[Dict[str, Any]]
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Apply the condition per product:
            current_stock + pending_inwards < min_stock_qty + open_sale_qty

        Returns:
            List of (product_dict, suggested_qty) for products that need a PO.
            suggested_qty = (min_stock_qty + open_sale_qty) - (current_stock + pending_inwards)
        """
        suggestions: List[Tuple[Dict[str, Any], float]] = []

        for product in products:
            product_id = product.get("product_id")
            item_name = product.get("item_name", "Unknown")

            current_stock = float(product.get("current_stock") or 0)
            pending_inwards = float(product.get("pending_inwards") or 0)
            min_stock_qty = float(product.get("min_stock_qty") or 0)
            open_sale_qty = float(product.get("open_sale_qty") or 0)

            available = current_stock + pending_inwards
            required = min_stock_qty + open_sale_qty

            logger.debug(
                f"[PurchaseSuggestionService] product_id={product_id} ({item_name}) | "
                f"available={available} (stock={current_stock} + pending={pending_inwards}) | "
                f"required={required} (min={min_stock_qty} + sales={open_sale_qty})"
            )

            if available < required:
                suggested_qty = required - available
                logger.info(
                    f"[PurchaseSuggestionService] ✅ PO needed for product_id={product_id} "
                    f"({item_name}), suggested_qty={suggested_qty}"
                )
                suggestions.append((product, suggested_qty))
            else:
                logger.debug(
                    f"[PurchaseSuggestionService] ✗ No PO needed for product_id={product_id} "
                    f"({item_name})"
                )

        logger.info(
            f"[PurchaseSuggestionService] Evaluation done. "
            f"{len(suggestions)}/{len(products)} products need a PO."
        )
        return suggestions
