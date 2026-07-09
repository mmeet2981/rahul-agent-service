"""
Product Registry
================
Server-side, in-memory store that holds confirmed product selections per
conversation.  The LLM never has to carry product_id / product_name itself;
once a product is resolved from the database it is locked here and retrieved
at inquiry-creation time.

Structure:
    _registry: {conversation_id: [{"product_id": int, "product_name": str}, ...]}
"""

from typing import Dict, List

_registry: Dict[int, List[dict]] = {}


def add_product(conv_id: int, product_id: int, product_name: str) -> None:
    """
    Add or update a product in the registry for a given conversation.
    If the same product_id already exists it is replaced (idempotent).
    """
    _registry.setdefault(conv_id, [])
    # Remove existing entry with the same product_id to avoid duplicates
    _registry[conv_id] = [
        p for p in _registry[conv_id] if p["product_id"] != product_id
    ]
    _registry[conv_id].append({"product_id": product_id, "product_name": product_name})


def get_products(conv_id: int) -> List[dict]:
    """Return the list of confirmed products for a conversation (may be empty)."""
    return list(_registry.get(conv_id, []))


def clear_products(conv_id: int) -> None:
    """Remove all products for a conversation (call after successful submission)."""
    _registry.pop(conv_id, None)


def product_count(conv_id: int) -> int:
    """Return how many products have been locked for this conversation."""
    return len(_registry.get(conv_id, []))
