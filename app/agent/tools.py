"""
LangChain tools for Ventory's agent dispatch path.

These are called synchronously by the agent's dispatch node.
They open their own DB session to avoid async complexity in the tool layer.
"""

import asyncio
from decimal import Decimal
from langchain_core.tools import tool

from app.db.connection import AsyncSessionLocal
import app.db.queries as queries


def _run(coro):
    """Run an async coroutine from a sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Tool 1: Log a sale ────────────────────────────────────────────────────────

@tool
def log_sale(items: list[dict], shop_id: str, trader_id: str) -> str:
    """
    Log one or more items sold. Call when the owner records a sale.

    Args:
        items: list of dicts with 'product_name' (str) and 'quantity' (number).
        shop_id: UUID of the active shop.
        trader_id: UUID of the trader.
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            parsed = [
                {"product_name": i["product_name"], "quantity": Decimal(str(i["quantity"]))}
                for i in items
            ]
            return await queries.log_sale(db, shop_id, trader_id, parsed)

    try:
        result = _run(_inner())
        lines = [
            f"{li['quantity']} {li['product_name']} = ₦{li['line_total']:,.0f} "
            f"({li['remaining_stock']} {li['unit']}(s) left)"
            for li in result["items"]
        ]
        return "\n".join(lines) + f"\nTotal: ₦{result['grand_total']:,.0f}"
    except Exception as e:
        return f"Could not log sale: {e}"


# ── Tool 2: Restock ────────────────────────────────────────────────────────────

@tool
def restock(product_name: str, quantity: float, shop_id: str, cost: float = None) -> str:
    """
    Add stock to a product. Call when the owner says they got more of something.

    Args:
        product_name: name of the product
        quantity: how many units were added
        shop_id: UUID of the active shop
        cost: optional — what it cost to restock (Naira)
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.log_restock(
                db, shop_id, product_name,
                Decimal(str(quantity)),
                Decimal(str(cost)) if cost is not None else None,
            )

    try:
        result = _run(_inner())
        cost_str = f" (cost: ₦{cost:,.0f})" if cost else ""
        return (
            f"Restocked {result['quantity_added']} {result['product_name']}{cost_str}. "
            f"New stock: {result['new_stock']} {result['unit']}(s)."
        )
    except Exception as e:
        return f"Could not restock: {e}"


# ── Tool 3: Log expense ────────────────────────────────────────────────────────

@tool
def log_expense(description: str, amount: float, shop_id: str, trader_id: str) -> str:
    """
    Record a business expense (rent, fuel, transport, etc.).

    Args:
        description: what the money was spent on
        amount: amount in Naira
        shop_id: UUID of the active shop
        trader_id: UUID of the trader
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.log_expense(
                db, shop_id, trader_id, description, Decimal(str(amount))
            )

    try:
        _run(_inner())
        return f"Expense recorded: {description} — ₦{amount:,.0f}."
    except Exception as e:
        return f"Could not log expense: {e}"


# ── Tool 4: Log debt ────────────────────────────────────────────────────────────

@tool
def log_debt(counterparty: str, amount: float, shop_id: str, trader_id: str) -> str:
    """
    Record that a customer took goods without paying.

    Args:
        counterparty: customer name
        amount: value of goods owed (Naira)
        shop_id: UUID of the active shop
        trader_id: UUID of the trader
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.log_debt(
                db, shop_id, trader_id, "owed", counterparty, Decimal(str(amount))
            )

    try:
        _run(_inner())
        return f"Debt recorded: {counterparty} owes ₦{amount:,.0f}."
    except Exception as e:
        return f"Could not log debt: {e}"


# ── Tool 5: Settle debt ────────────────────────────────────────────────────────

@tool
def settle_debt(counterparty: str, amount_paid: float, shop_id: str) -> str:
    """
    Record a debt payment from a customer.

    Args:
        counterparty: customer name
        amount_paid: how much they paid (Naira)
        shop_id: UUID of the active shop
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.settle_debt(
                db, shop_id, counterparty, Decimal(str(amount_paid))
            )

    try:
        result = _run(_inner())
        if result["is_settled"]:
            return f"{counterparty} has fully settled their debt. "
        balance = result["balance"]
        return f"Payment of ₦{amount_paid:,.0f} from {counterparty} recorded. Balance: ₦{balance:,.0f}."
    except Exception as e:
        return f"Could not settle debt: {e}"


# ── Tool 6: Get inventory ──────────────────────────────────────────────────────

@tool
def get_inventory(shop_id: str) -> str:
    """
    Get current stock levels for all products.
    Call when the owner asks what they have or anything about their inventory.
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.get_products(db, shop_id)

    try:
        products = _run(_inner())
        if not products:
            return "No products found. Add products first."
        lines = [
            f"{p.name}: {p.current_stock} {p.unit}(s) @ ₦{p.unit_price:,.0f} each"
            for p in products
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Could not get inventory: {e}"


# ── Tool 7: Get insights ───────────────────────────────────────────────────────

@tool
def get_insights(shop_id: str, period: str = "today") -> str:
    """
    Get a business summary — revenue, top sellers, low stock alerts, gross profit.

    Args:
        shop_id: UUID of the active shop
        period: 'today' (default), 'week', or 'month'
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.get_insights(db, shop_id, period)

    try:
        r = _run(_inner())
        top = "\n".join(
            f"  {i+1}. {s['product_name']} — {s['units_sold']} units, ₦{s['revenue']:,.0f}"
            for i, s in enumerate(r["top_sellers"])
        ) or "  No sales yet."
        alerts = "\n".join(
            f"  ⚠ {a['product_name']}: {a['current_stock']} {a['unit']}(s) left"
            for a in r["low_stock_alerts"]
        ) or "  All products well stocked."
        cost_line = f"\nRestock cost: ₦{r['total_restock_cost']:,.0f}" if r["total_restock_cost"] else ""
        profit_line = f"\nGross profit: ₦{r['gross_profit']:,.0f}" if r["gross_profit"] is not None else ""
        return (
            f"Period: {r['period']}\n"
            f"Revenue: ₦{r['total_revenue']:,.0f}\n"
            f"Transactions: {r['total_transactions']}"
            f"{cost_line}{profit_line}\n\n"
            f"Top sellers:\n{top}\n\n"
            f"Low stock:\n{alerts}"
        )
    except Exception as e:
        return f"Could not get insights: {e}"


# ── Tool 8: Add product ────────────────────────────────────────────────────────

@tool
def add_product(
    name: str,
    unit: str,
    initial_stock: float,
    unit_price: float,
    shop_id: str,
    trader_id: str,
) -> str:
    """
    Add a new product to the shop catalogue.
    Call when the owner explicitly wants to register a new product.
    """
    async def _inner():
        async with AsyncSessionLocal() as db:
            return await queries.create_product(
                db, shop_id, trader_id, name, unit,
                Decimal(str(initial_stock)), Decimal(str(unit_price)),
            )

    try:
        result = _run(_inner())
        return (
            f"Added '{result.name}' — {result.current_stock} {result.unit}(s) "
            f"at ₦{result.unit_price:,.0f} each."
        )
    except Exception as e:
        return f"Could not add product: {e}"