
import os
import httpx
from RAW.modals import Tool
from RAW.modals.tools import ToolParam
from src.utils import logger

API_BASE_URL = os.getenv("BACKEND_HOST", "http://127.0.0.1:3000")

async def get_uoms():
    """Fetch the list of valid Units of Measure (UOM)."""
    url = f"{API_BASE_URL}/v1/admin-service/uoms/list"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={})
            uoms = response.json().get("data", {}).get("data",[])
            result_str = "Available Units of Measure (UOM):\n"
            for u in uoms:
                result_str += f"{u['id']} - {u['unit_name']} - {u['unit_code']}\n"
            return result_str
    except Exception as e:
        logger.error(f"Error fetching UOMs: {e}")
        return "Error fetching UOM list."

get_uoms_tool = Tool(
    name="get_uoms",
    description="Get the list of valid units of measure (UOM) for products.",
    parameters=[],
    function=get_uoms
)