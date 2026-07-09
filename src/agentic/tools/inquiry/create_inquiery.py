import os
import httpx
from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger

# Configuration - Ensure these are in your .env
API_BASE_URL = os.getenv("BACKEND_HOST", "http://192.168.1.62:3000")

async def create_inquiry(
    expected_delivery_date: str,
    customer_id: int,
    poc_id: int,
    customer_name: str,
    poc_name: str,
    product_id: int,
    product_name: str,
    quantity: int,
    uom_id: int,
    size: str = "",
    gsm: int = 0,
    specifications: str = "",
    phone_number: str = "",
    # Product-level optional fields
    size_1: float = None,
    size_2: float = None,
    size_cm: float = None,
    size_inch: float = None,
    sheet_count: int = None,
    ream_weight: float = None,
    total_price: float = None,
    total_weight: float = None,
    extra_sheets: float = None,
    # Inquiry-level optional fields
    sla_status: str = None,
    bill_to_address_id: int = None,
    ship_to_address_id: int = None,
    bill_to_id: int = None,
    ship_to_id: int = None,
    cartage_amount: float = None,
    transporter_id: int = None,
    transport_name: str = None,
    freight_charges: float = None,
    payment_terms_id: int = None,
    auto_generate_do: bool = None,
    company_id: int = None
):
    """
    Submits a formal inquiry with full customer and product details to the ERP system.
    """
    url = f"{API_BASE_URL}/v1/inquiries-service"

    # Building the complex nested payload according to your requirement
    payload = {
        "source": "WHATSAPP",
        "source_reference": None,
        "linked_order_id": None,
        "expected_delivery_date": expected_delivery_date,
        "special_instructions": specifications,
        "transcript": None,
        "assigned_sales_person": None,
        "is_within_working_hours": True,
        "interaction_due_time": f"{expected_delivery_date}T10:40", # Defaulting time
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
            "preferred_contact_method": "WHATSAPP"
        },
        "products": [
            {
                "product_id": product_id,
                "product_name": product_name,
                "quantity": quantity,
                "uom_id": uom_id,
                "size": size,
                "gsm": gsm,
                "specifications": specifications,
                "size_1": size_1,
                "size_2": size_2,
                "size_cm": size_cm,
                "size_inch": size_inch,
                "sheet_count": sheet_count,
                "ream_weight": ream_weight,
                "total_price": total_price,
                "total_weight": total_weight,
                "extra_sheets": extra_sheets
            }
        ],
        "bill_to_address_id": bill_to_address_id,
        "ship_to_address_id": ship_to_address_id,
        "bill_to_id": bill_to_id,
        "ship_to_id": ship_to_id,
        "cartage_amount": cartage_amount,
        "transporter_id": transporter_id,
        "transport_name": transport_name,
        "freight_charges": freight_charges,
        "payment_terms_id": payment_terms_id,
        "auto_generate_do": auto_generate_do,
        "company_id": company_id
    }
    print(f"Payload : {payload}")
    try:    
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return "SUCCESS: The inquiry has been officially created in the system."
    except Exception as e:
        logger.error(f"Failed to create inquiry: {e}")
        return f"ERROR: Failed to create inquiry. {str(e)}"

create_inquiry_tool = Tool(
    name="create_inquiry",
    description="Finalizes and submits the inquiry after all customer and product details are gathered.",
    parameters=[
        ToolParam(name="expected_delivery_date", type="string", description="Date in YYYY-MM-DD format", required=True),
        ToolParam(name="customer_id", type="integer", description="The ID of the customer entity", required=True),
        ToolParam(name="poc_id", type="integer", description="The ID of the Point of Contact", required=True),
        ToolParam(name="customer_name", type="string", description="Full name of the customer/company", required=True),
        ToolParam(name="poc_name", type="string", description="Name of the Point of Contact", required=True),
        ToolParam(name="phone_number", type="string", description="Contact phone number", required=False),
        ToolParam(name="product_id", type="integer", description="The ID of the selected product", required=True),
        ToolParam(name="product_name", type="string", description="Full name of the product", required=True),
        ToolParam(name="quantity", type="integer", description="Quantity required", required=True),
        ToolParam(name="uom_id", type="integer", description="The ID for Unit of Measure", required=True),
        ToolParam(name="size", type="string", description="Product dimensions/size", required=False),
        ToolParam(name="gsm", type="integer", description="Paper GSM if applicable", required=False),
        ToolParam(name="specifications", type="string", description="Additional specs or instructions", required=False),
        # Product-level optional fields
        ToolParam(name="size_1", type="number", description="Width dimension of the product", required=False),
        ToolParam(name="size_2", type="number", description="Length dimension of the product", required=False),
        ToolParam(name="size_cm", type="number", description="Size in centimetres", required=False),
        ToolParam(name="size_inch", type="number", description="Size in inches", required=False),
        ToolParam(name="sheet_count", type="integer", description="Number of sheets per ream/packet", required=False),
        ToolParam(name="ream_weight", type="number", description="Weight of one ream in kg", required=False),
        ToolParam(name="total_price", type="number", description="Total price for the product line", required=False),
        ToolParam(name="total_weight", type="number", description="Total weight of the order in kg", required=False),
        ToolParam(name="extra_sheets", type="number", description="Number of extra sheets to add", required=False),
        # Inquiry-level optional fields
        ToolParam(name="sla_status", type="string", description="SLA status (e.g. PENDING, ON_TRACK, AT_RISK, BREACHED)", required=False),
        ToolParam(name="bill_to_address_id", type="integer", description="Address ID for billing", required=False),
        ToolParam(name="ship_to_address_id", type="integer", description="Address ID for shipping", required=False),
        ToolParam(name="bill_to_id", type="integer", description="Entity ID of the bill-to party", required=False),
        ToolParam(name="ship_to_id", type="integer", description="Entity ID of the ship-to party", required=False),
        ToolParam(name="cartage_amount", type="number", description="Cartage / loading charge amount", required=False),
        ToolParam(name="transporter_id", type="integer", description="ID of the transporter", required=False),
        ToolParam(name="transport_name", type="string", description="Name of the transporter", required=False),
        ToolParam(name="freight_charges", type="number", description="Freight charges amount", required=False),
        ToolParam(name="payment_terms_id", type="integer", description="ID of the payment terms to apply", required=False),
        ToolParam(name="auto_generate_do", type="boolean", description="Whether to auto-generate a Delivery Order on inquiry creation", required=False),
        ToolParam(name="company_id", type="integer", description="Company ID for scoping the inquiry", required=False)
    ],
    function=create_inquiry
)