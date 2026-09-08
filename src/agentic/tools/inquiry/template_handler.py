"""
template_handler.py
===================
Handles inquiry creation directly via a structured template format.
Supports single-product and multi-product templates, resolves entities
(Customer, POC, Products, UOMs) from the database/APIs, and submits
the inquiry to the ERP system.
"""

import os
import re
import json
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, AsyncGenerator

import httpx
from src.utils import logger, get_db_cursor
from src.utils.database import get_db_config
from src.agentic.tools.inquiry.create_inquiery import create_inquiry

API_BASE_URL = os.getenv("BACKEND_HOST", "http://192.168.1.62:3000")

# ---------------------------------------------------------------------------
# Template definition & help
# ---------------------------------------------------------------------------

TEMPLATE_HELP_TEXT = """📋 *Inquiry Template*
Copy, fill, and send the format below to submit your inquiry directly:

*INQUIRY*
Customer: <Company or Customer Name>
Contact: <Contact Person Name or Phone> (Optional)
Delivery Date: <YYYY-MM-DD>

Product: <Product Name or Keyword>
Quantity: <Quantity>
UOM: <Unit - e.g. Ream / Kg / Sheets / Bundles / Box / Pkt>
Size: <Size - e.g. A4 / 63.5X91.5> (Optional)
GSM: <GSM value - e.g. 75 / 80 / 200> (Optional)
Notes: <Special instructions> (Optional)

_For multiple products, simply add another Product block:_
Product: <Second Product Name>
Quantity: <Quantity>
UOM: <Unit>
"""


def get_template_text() -> str:
    """Return blank template text for user to copy-paste."""
    return TEMPLATE_HELP_TEXT.strip()


def is_template_request(text: str) -> bool:
    """Check if the incoming message is asking for the template format."""
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"^[/*#]+", "", cleaned).strip()
    return cleaned in [
        "template",
        "inquiry template",
        "inquiry format",
        "inquiry form",
        "format",
        "inquiry_template",
        "send template",
        "get template",
        "template format",
    ]


# ---------------------------------------------------------------------------
# Template format detection & parsing
# ---------------------------------------------------------------------------

TEMPLATE_HEADER_PATTERNS = [
    r"^\s*\*?INQUIRY(\s+FORM|\s+TEMPLATE)?\*?",
    r"^\s*\*?NEW\s+INQUIRY\*?",
    r"^\s*\[INQUIRY\]",
]


def is_template_format(text: str) -> bool:
    """
    Determines if the message is intended as an inquiry template.
    Returns True if:
      1. Has an inquiry header (e.g. *INQUIRY*, *NEW INQUIRY*), OR
      2. Has Customer: AND Product: AND (Quantity: or Qty:).
    Returns False otherwise (for normal conversation to fall back to LLM).
    """
    if not text or not isinstance(text, str):
        return False

    cleaned = text.strip()

    # Check for explicit inquiry header
    for pattern in TEMPLATE_HEADER_PATTERNS:
        if re.search(pattern, cleaned, re.MULTILINE | re.IGNORECASE):
            return True

    # Check for core field keys
    has_customer = bool(re.search(r"(?i)\b(customer|company|client)\s*:", cleaned))
    has_product = bool(re.search(r"(?i)\b(product|item|paper)\s*:", cleaned))
    has_quantity = bool(re.search(r"(?i)\b(qty|quantity|amount)\s*:", cleaned))

    return has_customer and has_product and has_quantity


def _is_placeholder(val: str) -> bool:
    """Check if value is an unfilled template placeholder."""
    if not val:
        return True
    cleaned = val.strip()
    # Matches <anything> with optional (Optional)
    if re.match(r"^<[^>]*>(\s*\(optional\))?$", cleaned, re.IGNORECASE):
        return True
    # Contains literal placeholder keywords like <Special instructions> or <Target Price>
    if re.search(r"<\s*(special\s*instructions|target\s*price|company|contact|price|notes|quantity|unit|product)[^>]*>", cleaned, re.IGNORECASE):
        return True
    dummy_phrases = [
        "(optional)", "optional", "none", "null", "n/a", "na", "<optional>",
        "second product name", "product name", "product name or keyword",
        "quantity", "unit", "target price", "special instructions",
        "<second product name>", "<product name>", "<quantity>", "<unit>"
    ]
    if cleaned.lower() in dummy_phrases:
        return True
    return False


def _clean_val(val: str) -> str:
    """Strip markdown formatting and leading/trailing whitespace, and ignore unfilled placeholders."""
    if not val:
        return ""
    cleaned = re.sub(r"^\*+|\*+$|^_+|_\+$|^`+|`+$", "", val.strip()).strip()
    if _is_placeholder(cleaned):
        return ""
    return cleaned


def parse_inquiry_template(text: str) -> dict:
    """
    Parse the raw text of a template inquiry into structured dictionary.
    Supports single or multiple product entries.
    """
    lines = text.strip().splitlines()

    customer = ""
    contact = ""
    delivery_date_str = ""
    notes = ""

    # Temporary items collection
    raw_items: List[Dict[str, str]] = []
    current_item: Optional[Dict[str, str]] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Skip guide and instruction lines
        if re.search(r"(?i)^_?for\s+multiple\s+products", line):
            continue
        if re.search(r"(?i)^copy,\s*fill,", line):
            continue
        if line.startswith("📋"):
            continue

        # Check for header fields
        m_cust = re.match(r"(?i)^\*?(?:customer|company|client)\*?\s*:\s*(.*)$", line)
        if m_cust:
            customer = _clean_val(m_cust.group(1))
            continue

        m_contact = re.match(r"(?i)^\*?(?:contact|poc|contact\s+person|phone)\*?\s*:\s*(.*)$", line)
        if m_contact:
            contact = _clean_val(m_contact.group(1))
            continue

        m_date = re.match(r"(?i)^\*?(?:delivery\s*date|expected\s*delivery|delivery|date)\*?\s*:\s*(.*)$", line)
        if m_date:
            delivery_date_str = _clean_val(m_date.group(1))
            continue

        m_notes = re.match(r"(?i)^\*?(?:notes|remarks|special\s*instructions|comments)\*?\s*:\s*(.*)$", line)
        if m_notes:
            notes = _clean_val(m_notes.group(1))
            continue

        # Check for product / item start
        # e.g., "Product: JK Copier" or "1. Product: JK Copier" or "Item 1: JK Copier"
        m_prod = re.match(r"(?i)^\*?(?:\d+[\.\)]\s*)?(?:product(?:\s*name)?|item)\*?\s*:\s*(.*)$", line)
        if m_prod:
            if current_item and current_item.get("product_name") and not _is_placeholder(current_item.get("product_name")):
                raw_items.append(current_item)
            clean_name = _clean_val(m_prod.group(1))
            if clean_name and not _is_placeholder(clean_name):
                current_item = {"product_name": clean_name}
            else:
                current_item = None
            continue

        # Per-item attributes
        if current_item is not None:
            m_qty = re.match(r"(?i)^\*?(?:quantity|qty|amount)\*?\s*:\s*(.*)$", line)
            if m_qty:
                current_item["quantity"] = _clean_val(m_qty.group(1))
                continue

            m_uom = re.match(r"(?i)^\*?(?:uom|unit|units)\*?\s*:\s*(.*)$", line)
            if m_uom:
                current_item["uom"] = _clean_val(m_uom.group(1))
                continue

            m_size = re.match(r"(?i)^\*?(?:size|dimension|dimensions)\*?\s*:\s*(.*)$", line)
            if m_size:
                current_item["size"] = _clean_val(m_size.group(1))
                continue

            m_gsm = re.match(r"(?i)^\*?(?:gsm|weight)\*?\s*:\s*(.*)$", line)
            if m_gsm:
                current_item["gsm"] = _clean_val(m_gsm.group(1))
                continue

            m_price = re.match(r"(?i)^\*?(?:price|target\s*price|unit\s*price|rate)\*?\s*:\s*(.*)$", line)
            if m_price:
                current_item["price"] = _clean_val(m_price.group(1))
                continue

            m_item_notes = re.match(r"(?i)^\*?(?:notes|remarks|specifications?)\*?\s*:\s*(.*)$", line)
            if m_item_notes:
                current_item["specifications"] = _clean_val(m_item_notes.group(1))
                continue

    if current_item and current_item.get("product_name") and not _is_placeholder(current_item.get("product_name")):
        raw_items.append(current_item)

    return {
        "customer": customer,
        "contact": contact,
        "delivery_date": delivery_date_str,
        "notes": notes,
        "items": raw_items,
    }


# ---------------------------------------------------------------------------
# Entity Resolution & Validation
# ---------------------------------------------------------------------------

def _normalize_date(date_str: str) -> Optional[str]:
    """Parse various date formats into YYYY-MM-DD."""
    if not date_str:
        return (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    date_str = date_str.strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", date_str)
    if m:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mth:02d}-{d:02d}"

    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", date_str)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mth:02d}-{d:02d}"

    if date_str.lower() in ["tomorrow", "tmrw"]:
        return (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    return None


async def _resolve_customer(customer_query: str) -> Tuple[Optional[dict], Optional[str]]:
    """Resolve customer entity from Admin Service API matching get_customer.py, with database fallback."""
    if not customer_query:
        return None, "Customer name is missing."

    # 1. API Call matching get_customer.py
    url = f"{API_BASE_URL}/v1/admin-service/entities/list"
    payload = {
        "skip": 0,
        "limit": 10,
        "filter": [{"field": "name", "operator": "contains", "value": customer_query.strip()}]
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                data_inner = data.get("data", {}) or {}
                entities = data_inner.get("entities", []) if isinstance(data_inner, dict) else []
                if not entities and isinstance(data, list):
                    entities = data
                if entities:
                    # Pick exact match if available, else first
                    for ent in entities:
                        if ent.get("name", "").strip().lower() == customer_query.strip().lower():
                            return ent, None
                    return entities[0], None
                return None, f"No customer found matching '*{customer_query}*'. Please check the company name."
    except Exception as api_err:
        logger.warning(f"Admin API error resolving customer '{customer_query}': {api_err}. Falling back to database...")

    # 2. Database Fallback
    sql = """
        SELECT id, name, entity_code
        FROM entity_master
        WHERE is_deleted = FALSE
          AND (name ILIKE %s OR entity_code ILIKE %s)
        ORDER BY
            CASE WHEN lower(name) = lower(%s) THEN 0 ELSE 1 END,
            length(name) ASC
        LIMIT 5;
    """
    term = f"%{customer_query.strip()}%"
    try:
        with get_db_cursor(db_config=get_db_config()) as cur:
            cur.execute(sql, (term, term, customer_query.strip()))
            rows = cur.fetchall()
            if not rows:
                return None, f"No customer found matching '*{customer_query}*'. Please check the company name."
            return dict(rows[0]), None
    except Exception as e:
        logger.error(f"Error resolving customer '{customer_query}': {e}")
        return None, f"Database error resolving customer: {e}"


async def _resolve_poc(customer_id: int, contact_query: str, sender_phone: str = None) -> Tuple[Optional[dict], Optional[str]]:
    """Resolve POC from Admin Service API matching poc_details.py, with database fallback."""
    # 1. API Call matching poc_details.py
    url = f"{API_BASE_URL}/v1/admin-service/poc-details/list"
    payload = {
        "skip": 0,
        "limit": 10,
        "filter": [{"field": "entity_id", "operator": "equals", "value": str(customer_id)}]
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                data_inner = data.get("data", {}) or {}
                pocs = data_inner.get("pocs", []) if isinstance(data_inner, dict) else []
                if pocs:
                    if contact_query:
                        query_clean = contact_query.strip().lower()
                        for p in pocs:
                            p_name = (p.get("name") or "").lower()
                            p_mob = (p.get("mobile_number") or "").replace(" ", "").replace("-", "")
                            if query_clean in p_name or (query_clean and query_clean in p_mob):
                                return p, None
                    if sender_phone:
                        phone_clean = re.sub(r"[^\d]", "", sender_phone)[-10:]
                        for p in pocs:
                            p_mob = re.sub(r"[^\d]", "", p.get("mobile_number") or "")[-10:]
                            if p_mob and phone_clean and p_mob == phone_clean:
                                return p, None
                    return pocs[0], None
    except Exception as api_err:
        logger.warning(f"Admin API error resolving POC for customer {customer_id}: {api_err}. Falling back to database...")

    # 2. Database Fallback
    sql = """
        SELECT id, entity_id, name, mobile_number
        FROM poc_details
        WHERE entity_id = %s
        ORDER BY id ASC;
    """
    try:
        with get_db_cursor(db_config=get_db_config()) as cur:
            cur.execute(sql, (customer_id,))
            pocs = cur.fetchall()

            if not pocs:
                return {
                    "id": 1,
                    "name": contact_query or "Primary Contact",
                    "mobile_number": sender_phone or "",
                }, None

            # If contact_query is provided, match by name or phone
            if contact_query:
                query_clean = contact_query.strip().lower()
                for p in pocs:
                    p_name = (p["name"] or "").lower()
                    p_mob = (p["mobile_number"] or "").replace(" ", "").replace("-", "")
                    if query_clean in p_name or (query_clean and query_clean in p_mob):
                        return dict(p), None

            # If sender_phone provided, try to match by mobile_number
            if sender_phone:
                phone_clean = re.sub(r"[^\d]", "", sender_phone)[-10:]
                for p in pocs:
                    p_mob = re.sub(r"[^\d]", "", p["mobile_number"] or "")[-10:]
                    if p_mob and phone_clean and p_mob == phone_clean:
                        return dict(p), None

            return dict(pocs[0]), None
    except Exception as e:
        logger.error(f"Error resolving POC for customer {customer_id}: {e}")
        return None, f"Database error resolving contact person: {e}"


def _resolve_product(product_query: str) -> Tuple[Optional[dict], Optional[str]]:
    """Resolve product from product_list."""
    if not product_query:
        return None, "Product name is missing."

    sql = """
        SELECT id, product_name, sku_code
        FROM product_list
        WHERE product_name ILIKE %s
           OR attributes::text ILIKE %s
           OR sku_code ILIKE %s
        ORDER BY
            CASE WHEN lower(product_name) = lower(%s) THEN 0 ELSE 1 END,
            length(product_name) ASC
        LIMIT 5;
    """
    term = f"%{product_query.strip()}%"
    try:
        with get_db_cursor(db_config=get_db_config()) as cur:
            cur.execute(sql, (term, term, term, product_query.strip()))
            rows = cur.fetchall()
            if not rows:
                return None, f"No product found matching '*{product_query}*'. Please check the catalog."
            return dict(rows[0]), None
    except Exception as e:
        logger.error(f"Error resolving product '{product_query}': {e}")
        return None, f"Database error resolving product: {e}"


def _resolve_uoms() -> Dict[str, dict]:
    """Fetch and index UOMs from uom_master."""
    sql = "SELECT id, unit_name, unit_code FROM uom_master;"
    index = {}
    try:
        with get_db_cursor(db_config=get_db_config()) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            for r in rows:
                row_dict = dict(r)
                code = (row_dict.get("unit_code") or "").strip().lower()
                name = (row_dict.get("unit_name") or "").strip().lower()
                if code:
                    index[code] = row_dict
                if name:
                    index[name] = row_dict

            alias_map = {
                "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
                "ream": "ream", "reams": "ream", "rm": "ream",
                "bundle": "bundles", "bundles": "bundles", "bdl": "bundles",
                "box": "box", "boxes": "box",
                "pkt": "pkt", "packet": "pkt", "packets": "pkt", "pkts": "pkt",
                "sheet": "sheets", "sheets": "sheets",
            }
            for alias, target in alias_map.items():
                if target in index and alias not in index:
                    index[alias] = index[target]

    except Exception as e:
        logger.error(f"Error loading UOMs: {e}")
    return index


def _match_uom(user_uom: str, uom_index: Dict[str, dict]) -> Optional[dict]:
    """Match user UOM against known units."""
    if not user_uom:
        return None
    cleaned = user_uom.strip().lower()
    if cleaned in uom_index:
        return uom_index[cleaned]

    for key, val in uom_index.items():
        if key and (key in cleaned or cleaned in key):
            return val

    if uom_index:
        return next(iter(uom_index.values()))
    return None


# ---------------------------------------------------------------------------
# Template Inquiry Execution
# ---------------------------------------------------------------------------

async def execute_template_inquiry(
    parsed: dict,
    sender_phone: str = None
) -> Tuple[bool, str]:
    """
    Validates and executes the inquiry submission from parsed template data.
    Returns (success: bool, response_message: str).
    """
    errors = []

    # 1. Customer Resolution
    customer_query = parsed.get("customer", "")
    if not customer_query:
        errors.append("Customer / Company name is missing.")
        customer_obj = None
    else:
        customer_obj, err = await _resolve_customer(customer_query)
        if err:
            errors.append(err)

    # 2. POC Resolution
    poc_obj = None
    if customer_obj:
        poc_obj, err = await _resolve_poc(
            customer_id=customer_obj["id"],
            contact_query=parsed.get("contact", ""),
            sender_phone=sender_phone
        )
        if err:
            errors.append(err)

    # 3. Delivery Date
    deliv_date = _normalize_date(parsed.get("delivery_date", ""))
    if not deliv_date:
        errors.append(f"Invalid delivery date '{parsed.get('delivery_date')}'. Please use YYYY-MM-DD or DD-MM-YYYY format.")

    # 4. Items & Products Resolution
    raw_items = parsed.get("items", [])
    if not raw_items:
        errors.append("No product items found in the template. Please specify at least one product.")

    resolved_products = []
    uom_index = _resolve_uoms()

    for idx, item in enumerate(raw_items):
        item_num = idx + 1
        prod_name_query = item.get("product_name", "")
        if not prod_name_query:
            errors.append(f"Item {item_num}: Product name is missing.")
            continue

        prod_obj, err = _resolve_product(prod_name_query)
        if err:
            errors.append(f"Item {item_num}: {err}")
            continue

        # Quantity
        qty_str = item.get("quantity", "0")
        try:
            qty_clean = re.sub(r"[^\d.]", "", qty_str)
            qty = float(qty_clean) if qty_clean else 0.0
            if qty <= 0:
                errors.append(f"Item {item_num}: Invalid quantity '{qty_str}'.")
                continue
        except ValueError:
            errors.append(f"Item {item_num}: Invalid quantity '{qty_str}'.")
            continue

        # UOM
        uom_str = item.get("uom", "")
        uom_obj = _match_uom(uom_str, uom_index)
        if not uom_obj:
            errors.append(f"Item {item_num}: Unit of measure '{uom_str}' not recognized.")
            continue

        # Size & GSM (extract from product name if omitted)
        extracted_gsm = 0
        extracted_size = ""
        m_gsm = re.search(r"(\d+)\s*GSM", prod_obj["product_name"], re.IGNORECASE)
        if m_gsm:
            extracted_gsm = int(m_gsm.group(1))

        m_size = re.search(r"(\d+(?:\.\d+)?\s*[Xx]\s*\d+(?:\.\d+)?(?:CMS)?)", prod_obj["product_name"], re.IGNORECASE)
        if m_size:
            extracted_size = m_size.group(1)

        user_gsm = item.get("gsm")
        final_gsm = int(re.sub(r"[^\d]", "", user_gsm)) if user_gsm and re.sub(r"[^\d]", "", user_gsm) else extracted_gsm

        user_size = item.get("size")
        final_size = user_size if user_size else extracted_size

        # Price
        user_price = item.get("price")
        unit_price = float(re.sub(r"[^\d.]", "", user_price)) if user_price and re.sub(r"[^\d.]", "", user_price) else 0.0

        resolved_products.append({
            "product_id": prod_obj["id"],
            "product_name": prod_obj["product_name"],
            "sku_code": prod_obj.get("sku_code", "N/A"),
            "quantity": qty,
            "uom_id": uom_obj["id"],
            "uom_name": uom_obj.get("unit_name") or uom_obj.get("unit_code"),
            "size": final_size or "",
            "gsm": final_gsm or 0,
            "unit_price": unit_price,
            "specifications": item.get("specifications", "") or parsed.get("notes", ""),
        })

    # If validation errors occurred, return them
    if errors:
        err_msg = "⚠️ *Could not create inquiry from template:*\n\n"
        for e in errors:
            err_msg += f"• {e}\n"
        err_msg += (
            "\n💡 *Tip:* Send `/template` to copy the blank format, "
            "or just message me directly and I will guide you step-by-step!"
        )
        return False, err_msg

    # 5. Build submission payload for create_inquiry
    product_ids = json.dumps([p["product_id"] for p in resolved_products])
    product_names = json.dumps([p["product_name"] for p in resolved_products])
    quantities = json.dumps([p["quantity"] for p in resolved_products])
    uom_ids = json.dumps([p["uom_id"] for p in resolved_products])
    sizes = json.dumps([p["size"] for p in resolved_products])
    gsms = json.dumps([p["gsm"] for p in resolved_products])
    specs = json.dumps([p["specifications"] for p in resolved_products])

    poc_name = poc_obj["name"] if poc_obj else "Primary Contact"
    poc_phone = poc_obj.get("mobile_number", "") if poc_obj else (sender_phone or "")
    poc_id = poc_obj["id"] if poc_obj else 1

    try:
        submission_result = await create_inquiry(
            expected_delivery_date=deliv_date,
            customer_id=customer_obj["id"],
            poc_id=poc_id,
            customer_name=customer_obj["name"],
            poc_name=poc_name,
            product_ids=product_ids,
            product_names=product_names,
            quantities=quantities,
            uom_ids=uom_ids,
            sizes=sizes,
            gsms=gsms,
            specifications=specs,
            phone_number=poc_phone,
        )

        if "ERROR:" in submission_result:
            return False, f"⚠️ *ERP Submission Failed:*\n{submission_result}"

        # Extract inquiry code if returned
        m_code = re.search(r"\[Code:\s*([^\]]+)\]", submission_result)
        inquiry_code_val = m_code.group(1).strip() if m_code else ""

        # Build clean WhatsApp confirmation message
        lines = [
            "✅ *Inquiry Created Successfully!*\n",
        ]
        if inquiry_code_val:
            lines.append(f"🆔 *Inquiry Code:* {inquiry_code_val}")

        lines.extend([
            f"🏢 *Customer:* {customer_obj['name']}",
            f"👤 *Contact:* {poc_name} ({poc_phone or 'N/A'})",
            f"📅 *Delivery Date:* {deliv_date}\n",
            "*Products Included:*",
        ])

        for i, p in enumerate(resolved_products):
            gsm_str = f" | GSM: {p['gsm']}" if p['gsm'] else ""
            size_str = f" | Size: {p['size']}" if p['size'] else ""
            lines.append(
                f"{i+1}. *{p['product_name']}*\n"
                f"   • Qty: {p['quantity']} {p['uom_name']}{gsm_str}{size_str}"
            )

        if parsed.get("notes"):
            lines.append(f"\n📝 *Notes:* {parsed['notes']}")

        lines.append("\n_Inquiry has been recorded in the ERP system._")
        return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"Error submitting template inquiry: {e}")
        return False, f"⚠️ *Error submitting inquiry:* {str(e)}"


async def handle_template_inquiry(
    text: str,
    conversation_id: int,
    user_id: int,
    sender_phone: str = None
) -> AsyncGenerator[str, None]:
    """
    Main entry point for template processing in invoke_agent.
    Yields response text chunks.
    """
    parsed = parse_inquiry_template(text)
    success, message = await execute_template_inquiry(parsed, sender_phone=sender_phone)
    yield message
