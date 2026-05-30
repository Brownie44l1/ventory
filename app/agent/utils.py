import json
import logging

from app.agent.config import chat_llm
from app.agent.models import State
from app.agent.prompts import RESOLVE_PRODUCTS_PROMPT
from app.db.connection import AsyncSessionLocal
import app.db.queries as queries

logger = logging.getLogger(__name__)


async def list_products(state: State) -> State:
    """Fetch all products for the active shop and store in state."""
    async with AsyncSessionLocal() as db:
        products = await queries.get_products(db, state.shop_id)
    available = [
        {"name": p.name, "unit": p.unit, "stock": float(p.current_stock)}
        for p in products
    ]
    return {"available_products": available}


async def resolve_products(state: State) -> State:
    """
    Use the LLM to match the owner's raw product mentions to catalogue names.
    Populates resolved_products and unresolved_products.
    """
    available = state.available_products
    if not available:
        return {"resolved_products": {}, "unresolved_products": []}

    product_list = "\n".join(f"- {p['name']}" for p in available)
    prompt = RESOLVE_PRODUCTS_PROMPT.format(
        question=state.question,
        product_list=product_list,
    )

    response = await chat_llm.ainvoke(prompt)
    try:
        data = json.loads(
            response.content.strip().replace("```json", "").replace("```", "")
        )
        return {
            "resolved_products": data.get("found", {}),
            "unresolved_products": data.get("not_found", []),
        }
    except Exception:
        logger.warning("Could not parse resolve_products response.")
        return {"resolved_products": {}, "unresolved_products": []}