"""
Create Inquiry Tool
===================
Submits a formal inquiry to the ERP system.

The LLM is responsible for tracking which products have been selected
(via the `search_products` tool) and passes them directly as JSON arrays.
No server-side product registry is used.
"""

import os
import json
import httpx
from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger, get_db_cursor
from src.utils.database import get_db_config

API_BASE_URL = os.getenv("BACKEND_HOST", "http://192.168.1.62:3000")


async def create_inquiry(
    expected_delivery_date: str,
    customer_id: int,
    poc_id: int,
    customer_name: str,
    poc_name: str,
    # Per-product lists (JSON arrays) — parallel arrays, one entry per product
    product_ids: str,
    product_names: str,
    quantities: str,
    uom_ids: str,
    sizes: str = "[]",
    gsms: str = "[]",
    # Optional per-product fields (JSON arrays)
    specifications: str = "[]",
    size_1s: str = "[]",
    size_2s: str = "[]",
    size_cms: str = "[]",
    size_inches: str = "[]",
    sheet_counts: str = "[]",
    ream_weights: str = "[]",
    total_prices: str = "[]",
    total_weights: str = "[]",
    extra_sheets_list: str = "[]",
    # Inquiry-level fields
    phone_number: str = "",
    sla_status: str = None,
    # Address fields are auto-resolved from entity_address using customer_id
    cartage_amount: float = None,
    transporter_id: int = None,
    transport_name: str = None,
    freight_charges: float = None,
    payment_terms_id: int = None,
    auto_generate_do: bool = None,
    company_id: int = None,
) -> str:
    """
    Finalizes and submits the inquiry. All product details are provided directly
    by the LLM as parallel JSON arrays (product_ids, product_names, quantities, etc.).
    """

    # --- 1. Parse per-product lists ---
    def _parse_list(raw: str) -> list:
        """Parse a JSON array string; return empty list on failure."""
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return []

    id_list = _parse_list(product_ids)
    name_list = _parse_list(product_names)
    qty_list = _parse_list(quantities)
    uom_list = _parse_list(uom_ids)
    size_list = _parse_list(sizes)
    gsm_list = _parse_list(gsms)
    spec_list = _parse_list(specifications)
    size1_list = _parse_list(size_1s)
    size2_list = _parse_list(size_2s)
    size_cm_list = _parse_list(size_cms)
    size_inch_list = _parse_list(size_inches)
    sheet_list = _parse_list(sheet_counts)
    ream_list = _parse_list(ream_weights)
    price_list = _parse_list(total_prices)
    weight_list = _parse_list(total_weights)
    extra_list = _parse_list(extra_sheets_list)

    # --- 2. Validate required arrays ---
    if not id_list:
        return "ERROR: No product_ids provided. Please provide at least one product."
    if len(id_list) != len(name_list):
        return (
            f"ERROR: product_ids has {len(id_list)} item(s) but product_names has "
            f"{len(name_list)}. They must be the same length."
        )
    if len(qty_list) != len(id_list):
        return (
            f"ERROR: {len(id_list)} product(s) provided but {len(qty_list)} quantity "
            f"value(s). Please provide exactly {len(id_list)} value(s) in quantities."
        )
    if len(uom_list) != len(id_list):
        return (
            f"ERROR: {len(id_list)} product(s) provided but {len(uom_list)} uom_id "
            f"value(s). Please provide exactly {len(id_list)} value(s) in uom_ids."
        )

    def _get(lst: list, idx: int, default=None):
        return lst[idx] if idx < len(lst) else default

    # --- 3. Auto-resolve address from entity_address using customer_id ---
    resolved_address_id = None
    try:
        addr_sql = """
            SELECT address_id
            FROM entity_address
            WHERE entity_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        with get_db_cursor(db_config=get_db_config()) as cur:
            cur.execute(addr_sql, (customer_id,))
            addr_row = cur.fetchone()
            if addr_row:
                resolved_address_id = addr_row["address_id"]
                logger.info(
                    f"Resolved address_id={resolved_address_id} "
                    f"for customer_id={customer_id}"
                )
            else:
                logger.warning(
                    f"No address found in entity_address for customer_id={customer_id}"
                )
    except Exception as addr_err:
        logger.error(f"Failed to resolve address for customer_id={customer_id}: {addr_err}")
        # Non-fatal — proceed with None; API may handle missing addresses gracefully

    # --- 4. Build products array ---
    products_payload = []
    for i in range(len(id_list)):
        products_payload.append({
            "product_id":   id_list[i],
            "product_name": name_list[i],
            "quantity":     _get(qty_list, i, 0),
            "uom_id":       _get(uom_list, i),
            "size":         _get(size_list, i, ""),
            "gsm":          _get(gsm_list, i, 0),
            "specifications": _get(spec_list, i, ""),
            "size_1":       _get(size1_list, i),
            "size_2":       _get(size2_list, i),
            "size_cm":      _get(size_cm_list, i),
            "size_inch":    _get(size_inch_list, i),
            "sheet_count":  _get(sheet_list, i),
            "ream_weight":  _get(ream_list, i),
            "total_price":  _get(price_list, i),
            "total_weight": _get(weight_list, i),
            "extra_sheets": _get(extra_list, i),
        })

    # --- 5. Build full payload ---
    url = f"{API_BASE_URL}/v1/inquiries-service"
    payload = {
        "source": "WHATSAPP",
        "source_reference": None,
        "linked_order_id": None,
        "expected_delivery_date": expected_delivery_date,
        "special_instructions": "",
        "transcript": None,
        "assigned_sales_person": None,
        "is_within_working_hours": True,
        "interaction_due_time": f"{expected_delivery_date}T10:40",
        "sla_status": sla_status or "PENDING",
        "customer": {
            "customer_id": customer_id,
            "poc_id": poc_id,
            "name": customer_name,
            "poc_name": poc_name,
            "phone_number": phone_number,
            "whatsapp_number": phone_number,
            "email": "",
            "address": "",
            "preferred_contact_method": "WHATSAPP",
        },
        "products": products_payload,
        "bill_to_address_id": resolved_address_id,
        "ship_to_address_id": resolved_address_id,
        "cartage_amount": cartage_amount,
        "transporter_id": transporter_id,
        "transport_name": transport_name,
        "freight_charges": freight_charges,
        "payment_terms_id": payment_terms_id,
        "auto_generate_do": auto_generate_do,
        "company_id": company_id,
    }
    print(f"Inquiry Payload: {payload}")

    # --- 6. Submit ---
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        product_names_str = ", ".join(name_list)
        return (
            f"SUCCESS: Inquiry created successfully for {len(id_list)} product(s): "
            f"{product_names_str}."
        )
    except Exception as e:
        logger.error(f"Failed to create inquiry: {e}")
        return f"ERROR: Failed to create inquiry. {str(e)}"


create_inquiry_tool = Tool(
    name="create_inquiry",
    description=(
        "Finalizes and submits the inquiry after all customer and product details "
        "are gathered. All product details must be provided as parallel JSON arrays "
        "(product_ids, product_names, quantities, uom_ids, etc.) where index 0 of "
        "each array corresponds to the first product, index 1 to the second, and so on."
    ),
    parameters=[
        # Inquiry-level required fields
        ToolParam(name="expected_delivery_date", type="string",
                  description="Expected delivery date in YYYY-MM-DD format.", required=True),
        ToolParam(name="customer_id", type="integer",
                  description="The ID of the customer entity.", required=True),
        ToolParam(name="poc_id", type="integer",
                  description="The ID of the Point of Contact.", required=True),
        ToolParam(name="customer_name", type="string",
                  description="Full name of the customer/company.", required=True),
        ToolParam(name="poc_name", type="string",
                  description="Name of the Point of Contact.", required=True),
        # Per-product list fields (required)
        ToolParam(name="product_ids", type="string",
                  description=(
                      "JSON array of product IDs from search_products results. "
                      "Example: '[101, 205]' for two products."
                  ), required=True),
        ToolParam(name="product_names", type="string",
                  description=(
                      "JSON array of product names matching product_ids. "
                      "Example: '[\"A4 Copy Paper\", \"White Envelope\"]'"
                  ), required=True),
        ToolParam(name="quantities", type="string",
                  description=(
                      "JSON array of quantities — one per product, in the same order as product_ids. "
                      "Example: '[500, 200]'"
                  ), required=True),
        ToolParam(name="uom_ids", type="string",
                  description=(
                      "JSON array of UOM IDs — one per product, in the same order as product_ids. "
                      "Example: '[3, 3]'"
                  ), required=True),
        # Per-product list fields (optional)
        ToolParam(name="sizes", type="string",
                  description="JSON array of size strings per product. Example: '[\"A4\", \"DL\"]'",
                  required=False),
        ToolParam(name="gsms", type="string",
                  description="JSON array of GSM values per product. Example: '[80, 90]'",
                  required=False),
        ToolParam(name="specifications", type="string",
                  description="JSON array of specification strings per product.",
                  required=False),
        ToolParam(name="size_1s", type="string",
                  description="JSON array of width dimensions per product.", required=False),
        ToolParam(name="size_2s", type="string",
                  description="JSON array of length dimensions per product.", required=False),
        ToolParam(name="size_cms", type="string",
                  description="JSON array of sizes in cm per product.", required=False),
        ToolParam(name="size_inches", type="string",
                  description="JSON array of sizes in inches per product.", required=False),
        ToolParam(name="sheet_counts", type="string",
                  description="JSON array of sheet counts per product.", required=False),
        ToolParam(name="ream_weights", type="string",
                  description="JSON array of ream weights (kg) per product.", required=False),
        ToolParam(name="total_prices", type="string",
                  description="JSON array of total prices per product.", required=False),
        ToolParam(name="total_weights", type="string",
                  description="JSON array of total weights (kg) per product.", required=False),
        ToolParam(name="extra_sheets_list", type="string",
                  description="JSON array of extra sheet counts per product.", required=False),
        # Inquiry-level optional fields
        ToolParam(name="phone_number", type="string",
                  description="Contact phone number.", required=False),
        ToolParam(name="sla_status", type="string",
                  description="SLA status (PENDING, ON_TRACK, AT_RISK, BREACHED).", required=False),
        ToolParam(name="cartage_amount", type="number",
                  description="Cartage / loading charge amount.", required=False),
        ToolParam(name="transporter_id", type="integer",
                  description="ID of the transporter.", required=False),
        ToolParam(name="transport_name", type="string",
                  description="Name of the transporter.", required=False),
        ToolParam(name="freight_charges", type="number",
                  description="Freight charges amount.", required=False),
        ToolParam(name="payment_terms_id", type="integer",
                  description="ID of the payment terms to apply.", required=False),
        ToolParam(name="auto_generate_do", type="boolean",
                  description="Whether to auto-generate a Delivery Order.", required=False),
        ToolParam(name="company_id", type="integer",
                  description="Company ID for scoping the inquiry.", required=False),
    ],
    function=create_inquiry,
)