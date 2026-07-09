
import os
import httpx
from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger

API_BASE_URL = os.getenv("BACKEND_HOST", "http://192.168.1.62:3000")

async def get_poc_details(customer_id: str):
    print(f"I am called with: {customer_id} ")
    """Get POC (Point of Contact) details for a specific customer ID."""
    url = f"{API_BASE_URL}/v1/admin-service/poc-details/list"
    payload = {
        "skip": 0,
        "limit": 10,
        "filter": [{"field": "entity_id", "operator": "equals", "value": str(customer_id)}]
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response = response.json()
            if response.get("success") == False:
                logger.error(f"Error fetching POCs: {response.get('error').get('message')}")
                raise ValueError(response.get("error").get("message"))
                
            data = response.get("data", {})
            pocs = data.get("pocs", [])
            if not pocs:
                return "No POCs found for this customer."
            
            result_str = "Available Contacts (POCs):\n"
            for p in pocs:
                result_str += f"- {p['name']} (POC ID: {p['id']}, Phone: {p['mobile_number']})\n"
            return result_str
    except Exception as e:
        logger.error(f"Error fetching POCs: {e}")
        return "Error fetching POC details."

get_poc_tool = Tool(
    name="get_poc_details",
    description="Get the list of contact persons (POCs) for a specific customer_id.",
    parameters=[ToolParam(name="customer_id", type="string", description="The ID of the customer", required=True)],
    function=get_poc_details
)