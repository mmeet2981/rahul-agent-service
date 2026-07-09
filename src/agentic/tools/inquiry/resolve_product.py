"""
Resolve Product Tool
====================
Replaces the old `search_products` tool.

Behaviour:
  - Searches the database for products matching the query.
  - **Exactly 1 match** → locked into ProductRegistry; returns confirmation.
  - **Multiple matches** → returns a numbered list for user to choose from;
    the LLM must ask the user to pick one, then call this tool again with
    the specific product name.
  - **0 matches** → returns a "not found" message.

Design: built as a closure factory so `conversation_id` is captured at
agent-init time and is invisible to the LLM (the LLM only provides `query`).
"""

from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger, get_db_cursor
from src.utils.database import get_db_config
from src.agentic.tools.inquiry.product_registry import add_product


def make_resolve_product_tool(conversation_id: int) -> Tool:
    """
    Factory that returns a `resolve_product` Tool with `conversation_id`
    baked in via closure — the LLM never sees or passes the conversation_id.
    """

    async def resolve_product(query: str) -> str:
        """
        Search the product catalog and lock the result into the session registry.
        Call this whenever the user mentions a product they want to inquire about.
        If multiple products are found, return the list so the user can choose.
        """
        sql = """
            SELECT id, product_name, sku_code
            FROM product_list
            WHERE product_name ILIKE %s
               OR attributes::text ILIKE %s
            LIMIT 10
        """
        search_term = f"%{query}%"

        try:
            with get_db_cursor(db_config=get_db_config()) as cur:
                cur.execute(sql, (search_term, search_term))
                results = cur.fetchall()

            if not results:
                return (
                    f"No products found matching '{query}'. "
                    "Please try a different keyword or check the spelling."
                )

            if len(results) == 1:
                row = results[0]
                product_id = row["id"]
                product_name = row["product_name"]
                add_product(conversation_id, product_id, product_name)
                return (
                    f"✅ Product locked: **{product_name}** (ID: {product_id}, SKU: {row['sku_code']}). "
                    "This product has been added to the inquiry. "
                    "You may search for additional products or proceed to collect quantity and UOM details."
                )

            # Multiple matches — ask user to choose
            lines = [
                f"{i+1}. {r['product_name']} (SKU: {r['sku_code']})"
                for i, r in enumerate(results)
            ]
            product_list = "\n".join(lines)
            return (
                f"Multiple products found for '{query}'. "
                "Please ask the user to choose one:\n"
                f"{product_list}\n\n"
                "Once the user selects a product, call `resolve_product` again "
                "with the exact product name they chose."
            )

        except Exception as e:
            logger.error(f"Error resolving product '{query}': {e}")
            return "Error: Unable to search the product catalog at this time."

    return Tool(
        name="resolve_product",
        description=(
            "Search the product catalog for a product by name or keyword and lock "
            "the confirmed result into the inquiry session. Call this whenever the "
            "user mentions a product. If multiple products match, present the list "
            "and call this tool again once the user picks one."
        ),
        parameters=[
            ToolParam(
                name="query",
                type="string",
                description=(
                    "The product name or keyword to search for "
                    "(e.g., 'A4 paper', 'white envelopes'). "
                    "When confirming a user selection, pass the exact product name."
                ),
                required=True,
            )
        ],
        function=resolve_product,
    )
