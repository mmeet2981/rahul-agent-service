"""
Inquiry tools package.

All tools are stateless — the LLM is responsible for tracking product
IDs and names across turns using context from `search_products`.
"""
from .get_customer import get_customers_tool
from .poc_details import get_poc_tool
from .uom_details import get_uoms_tool
from .search_product import search_products_tool
from .create_inquiery import create_inquiry_tool

from .template_handler import (
    is_template_format,
    is_template_request,
    get_template_text,
    handle_template_inquiry,
)

__all__ = [
    "get_customers_tool",
    "get_poc_tool",
    "get_uoms_tool",
    "search_products_tool",
    "create_inquiry_tool",
]