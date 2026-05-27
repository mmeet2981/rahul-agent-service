"""
create_inquiry_flow.py

A single, self-contained tool that drives the entire inquiry creation conversation.

How it works:
  - The LLM calls this tool whenever the user wants to create an inquiry.
  - The tool reads the conversation history (via the `agent` parameter) to figure
    out what data has already been collected and what's still missing.
  - It fetches needed data from backend APIs, presents choices, and returns a
    human-readable question/status string.
  - Because the agent appends the tool result to the conversation, the next user
    reply contains the answer, and the LLM calls this tool again — progressing
    one step forward each time.
  - When all data is collected the tool submits the inquiry and returns a success
    message.
"""

import os
import re
import json
import httpx
from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger
from src.utils.database import get_db_config, get_db_cursor

API_BASE_URL = os.getenv("BACKEND_HOST", "http://127.0.0.1:3000")

# ---------------------------------------------------------------------------
# Internal helpers — API calls
# ---------------------------------------------------------------------------

async def _search_customers(query: str) -> list:
    url = f"{API_BASE_URL}/v1/admin-service/entities/list"
    payload = {
        "skip": 0, "limit": 10,
        "filter": [{"field": "name", "operator": "contains", "value": query}]
    }
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json=payload)
        data = r.json().get("data", {}) or {}
        return data.get("entities", [])


async def _get_pocs(customer_id: str) -> list:
    url = f"{API_BASE_URL}/v1/admin-service/poc-details/list"
    payload = {
        "skip": 0, "limit": 10,
        "filter": [{"field": "entity_id", "operator": "equals", "value": str(customer_id)}]
    }
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json=payload)
        data = r.json().get("data", {}) or {}
        return data.get("pocs", [])


async def _search_products(query: str) -> list:
    sql = """
        SELECT id, product_name, sku_code
        FROM product_list
        WHERE product_name ILIKE %s OR attributes::text ILIKE %s
        LIMIT 10
    """
    term = f"%{query}%"
    with get_db_cursor(db_config=get_db_config()) as cur:
        cur.execute(sql, (term, term))
        return cur.fetchall()


async def _get_uoms() -> list:
    url = f"{API_BASE_URL}/v1/admin-service/uoms/list"
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json={})
        raw = r.json().get("data", [])
        # API may return a list or a dict with a nested list
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for key in ("uoms", "items", "results"):
                if key in raw:
                    return raw[key]
        return []


async def _submit_inquiry(data: dict) -> str:
    url = f"{API_BASE_URL}/v1/inquiries-service"
    delivery = data["delivery_date"]
    payload = {
        "source": "WHATSAPP",
        "source_reference": None,
        "linked_order_id": None,
        "expected_delivery_date": delivery,
        "special_instructions": data.get("specifications", ""),
        "transcript": None,
        "assigned_sales_person": None,
        "is_within_working_hours": True,
        "interaction_due_time": f"{delivery}T10:40",
        "sla_status": "",
        "customer": {
            "customer_id": data["customer_id"],
            "poc_id": data["poc_id"],
            "name": data["customer_name"],
            "poc_name": data["poc_name"],
            "phone_number": data["poc_phone"],
            "whatsapp_number": data["poc_phone"],
            "email": "",
            "address": "",
            "preferred_contact_method": "WHATSAPP"
        },
        "products": [{
            "product_id": data["product_id"],
            "product_name": data["product_name"],
            "quantity": data["quantity"],
            "uom_id": data["uom_id"],
            "unit_price": data["unit_price"],
            "size": data.get("size", ""),
            "gsm": data.get("gsm", 0),
            "specifications": data.get("specifications", "")
        }]
    }
    logger.info(f"Submitting inquiry payload: {payload}")
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
    return "✅ Inquiry successfully created in the system!"


# ---------------------------------------------------------------------------
# State extraction — parse collected data from conversation history
# ---------------------------------------------------------------------------

def _extract_state(agent) -> dict:
    """
    Walk through tool messages in conversation history and collect any
    structured state blocks written by previous calls to this tool.
    The latest __STATE__ block wins.
    """
    state = {}
    for msg in agent.messages:
        if msg.role == "tool":
            try:
                content = msg.content or ""
                # Look for an embedded JSON state block
                match = re.search(r"__STATE__(\{.*?\})__END__", content, re.DOTALL)
                if match:
                    state.update(json.loads(match.group(1)))
            except Exception:
                pass
    return state


def _format_state(state: dict) -> str:
    """Return the hidden state line that the infra will strip before sending to users."""
    return f"\n__STATE__{json.dumps(state)}__END__"


def _user_msg(visible: str, state: dict) -> str:
    """
    Combine the user-visible message with the hidden state block.
    The __STATE__ marker sits on its own line at the very end so:
      1. The LLM can see the clear boundary and should not relay it.
      2. The infra (llm_worker) strips it unconditionally before sending to WhatsApp.
    """
    return visible.rstrip() + _format_state(state)


def _numbered_list(items: list, label_fn) -> str:
    return "\n".join(f"{i+1}. {label_fn(item)}" for i, item in enumerate(items))


def _pick_by_number(user_input: str, items: list):
    """Return items[n-1] if user typed a number, else None."""
    try:
        n = int(user_input.strip())
        if 1 <= n <= len(items):
            return items[n - 1]
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------

async def create_inquiry(user_response: str = "", agent=None):
    """
    Drives the full inquiry creation flow one step at a time.
    Call this tool whenever the user wants to create a new inquiry.
    Pass the latest user message as `user_response`.
    """
    try:
        state = _extract_state(agent) if agent else {}
        step = state.get("step", "ask_customer")
        user_input = (user_response or "").strip()

        # ── STEP: ask_customer ────────────────────────────────────────────
        if step == "ask_customer":
            state["step"] = "search_customer"
            return _user_msg(
                "Sure! Let's create a new inquiry.\n\n"
                "👉 What is the name of the company or customer?",
                state
            )

        # ── STEP: search_customer ─────────────────────────────────────────
        if step == "search_customer":
            customers = await _search_customers(user_input)
            if not customers:
                return _user_msg(
                    f"❌ No customers found for *{user_input}*. Please try a different name.",
                    {**state, "step": "search_customer"}
                )
            state["_customers"] = customers
            state["step"] = "pick_customer"
            listing = _numbered_list(customers, lambda c: c["name"])
            return _user_msg(
                f"Found these customers:\n{listing}\n\n"
                "👉 Which one? (reply with the number)",
                state
            )

        # ── STEP: pick_customer ───────────────────────────────────────────
        if step == "pick_customer":
            customers = state.get("_customers", [])
            picked = _pick_by_number(user_input, customers)
            if not picked:
                listing = _numbered_list(customers, lambda c: c["name"])
                return _user_msg(
                    f"Please reply with a number between 1 and {len(customers)}:\n{listing}",
                    state
                )
            state["customer_id"] = picked["id"]
            state["customer_name"] = picked["name"]
            state.pop("_customers", None)

            # Fetch POCs immediately
            pocs = await _get_pocs(str(picked["id"]))
            if not pocs:
                return _user_msg(
                    "⚠️ No contacts (POCs) found for this customer. Please contact your admin.",
                    {**state, "step": "pick_customer"}
                )
            state["_pocs"] = pocs
            state["step"] = "pick_poc"
            listing = _numbered_list(pocs, lambda p: f"{p['name']} ({p.get('mobile_number', 'N/A')})")
            return _user_msg(
                f"Customer: *{state['customer_name']}*\n\n"
                f"Available contacts:\n{listing}\n\n"
                "👉 Which contact person? (reply with the number)",
                state
            )

        # ── STEP: pick_poc ────────────────────────────────────────────────
        if step == "pick_poc":
            pocs = state.get("_pocs", [])
            picked = _pick_by_number(user_input, pocs)
            if not picked:
                listing = _numbered_list(pocs, lambda p: f"{p['name']} ({p.get('mobile_number', 'N/A')})")
                return _user_msg(
                    f"Please reply with a number between 1 and {len(pocs)}:\n{listing}",
                    state
                )
            state["poc_id"] = picked["id"]
            state["poc_name"] = picked["name"]
            state["poc_phone"] = picked.get("mobile_number", "")
            state.pop("_pocs", None)
            state["step"] = "ask_product"
            return _user_msg(
                f"Contact: *{state['poc_name']}*\n\n"
                "👉 What product are you looking for?",
                state
            )

        # ── STEP: ask_product ─────────────────────────────────────────────
        if step == "ask_product":
            products = await _search_products(user_input)
            if not products:
                return _user_msg(
                    f"❌ No products found for *{user_input}*. Please try again.",
                    {**state, "step": "ask_product"}
                )
            state["_products"] = [dict(p) for p in products]
            state["step"] = "pick_product"
            listing = _numbered_list(state["_products"], lambda p: f"{p['product_name']} (SKU: {p['sku_code']})")
            return _user_msg(
                f"Found these products:\n{listing}\n\n"
                "👉 Which one? (reply with the number)",
                state
            )

        # ── STEP: pick_product ────────────────────────────────────────────
        if step == "pick_product":
            products = state.get("_products", [])
            picked = _pick_by_number(user_input, products)
            if not picked:
                listing = _numbered_list(products, lambda p: f"{p['product_name']} (SKU: {p['sku_code']})")
                return _user_msg(
                    f"Please reply with a number between 1 and {len(products)}:\n{listing}",
                    state
                )
            state["product_id"] = picked["id"]
            state["product_name"] = picked["product_name"]
            state.pop("_products", None)
            state["step"] = "ask_quantity"
            return _user_msg(
                f"Product: *{state['product_name']}*\n\n"
                "👉 What quantity do you need?",
                state
            )

        # ── STEP: ask_quantity ────────────────────────────────────────────
        if step == "ask_quantity":
            try:
                state["quantity"] = int(re.sub(r"[^\d]", "", user_input))
            except ValueError:
                return _user_msg("Please enter a valid whole number for quantity.", state)
            state["step"] = "ask_price"
            return _user_msg("👉 What is your target unit price?", state)

        # ── STEP: ask_price ───────────────────────────────────────────────
        if step == "ask_price":
            try:
                state["unit_price"] = float(re.sub(r"[^\d.]", "", user_input))
            except ValueError:
                return _user_msg("Please enter a valid price (e.g. 150 or 12.50).", state)
            state["step"] = "ask_size"
            return _user_msg("👉 What size do you need? (e.g. A3, A4 — or type 'skip' to skip)", state)

        # ── STEP: ask_size ────────────────────────────────────────────────
        if step == "ask_size":
            state["size"] = "" if user_input.lower() == "skip" else user_input
            state["step"] = "ask_gsm"
            return _user_msg("👉 What GSM (paper weight) do you need? (e.g. 80, 100 — or type 'skip')", state)

        # ── STEP: ask_gsm ─────────────────────────────────────────────────
        if step == "ask_gsm":
            if user_input.lower() == "skip":
                state["gsm"] = 0
            else:
                try:
                    state["gsm"] = int(re.sub(r"[^\d]", "", user_input))
                except ValueError:
                    return _user_msg("Please enter a valid GSM number or type 'skip'.", state)

            # Fetch UOMs
            uoms = await _get_uoms()
            if not uoms:
                return _user_msg(
                    "⚠️ Could not fetch units of measure. Please try again later.",
                    {**state, "step": "ask_gsm"}
                )
            state["_uoms"] = uoms
            state["step"] = "pick_uom"
            listing = _numbered_list(uoms, lambda u: u.get("unit_name", str(u)))
            return _user_msg(
                f"Available units of measure:\n{listing}\n\n"
                "👉 Which unit applies? (reply with the number)",
                state
            )

        # ── STEP: pick_uom ────────────────────────────────────────────────
        if step == "pick_uom":
            uoms = state.get("_uoms", [])
            picked = _pick_by_number(user_input, uoms)
            if not picked:
                listing = _numbered_list(uoms, lambda u: u.get("unit_name", str(u)))
                return _user_msg(
                    f"Please reply with a number between 1 and {len(uoms)}:\n{listing}",
                    state
                )
            state["uom_id"] = picked["id"]
            state["uom_name"] = picked.get("unit_name", "")
            state.pop("_uoms", None)
            state["step"] = "ask_delivery"
            return _user_msg(
                f"Unit: *{state['uom_name']}*\n\n"
                "👉 What is the expected delivery date? (Format: YYYY-MM-DD)",
                state
            )

        # ── STEP: ask_delivery ────────────────────────────────────────────
        if step == "ask_delivery":
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", user_input):
                return _user_msg(
                    "Please provide the date in YYYY-MM-DD format (e.g. 2025-08-15).",
                    state
                )
            state["delivery_date"] = user_input
            state["step"] = "confirm"

            # Build summary
            summary = (
                "📋 *Inquiry Summary*\n\n"
                f"Customer    : {state['customer_name']}\n"
                f"Contact     : {state['poc_name']} ({state['poc_phone']})\n"
                f"Product     : {state['product_name']}\n"
                f"Quantity    : {state['quantity']} {state['uom_name']}\n"
                f"Unit Price  : {state['unit_price']}\n"
                f"Size        : {state.get('size') or 'N/A'}\n"
                f"GSM         : {state.get('gsm') or 'N/A'}\n"
                f"Delivery    : {state['delivery_date']}\n"
            )
            return _user_msg(summary + "\n👉 Should I submit this inquiry? (Yes / No)", state)

        # ── STEP: confirm ─────────────────────────────────────────────────
        if step == "confirm":
            if user_input.lower() in ("yes", "y", "yeah", "ok", "okay", "submit", "confirm"):
                result = await _submit_inquiry(state)
                return result  # No state embed — flow is complete
            else:
                return (
                    "❌ Inquiry cancelled. Let me know if you'd like to start over or change anything.\n"
                )

        # Fallback
        state["step"] = "ask_customer"
        return "Let's start fresh. " + await create_inquiry("", agent)

    except Exception as e:
        logger.error(f"create_inquiry_flow error: {e}")
        return f"⚠️ Something went wrong: {e}. Please try again."


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

create_inquiry_flow_tool = Tool(
    name="create_inquiry",
    description=(
        "Use this tool to create a new product inquiry. "
        "Call it whenever the user wants to raise an inquiry. "
        "Pass the user's latest message as `user_response`. "
        "The tool will guide the conversation step by step."
    ),
    parameters=[
        ToolParam(
            name="user_response",
            type="string",
            description="The user's latest message or answer (pass empty string on first call)",
            required=False
        )
    ],
    function=create_inquiry
)
