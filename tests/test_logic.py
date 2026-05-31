"""
Ventory core logic tests.
Run with: pytest tests/test_logic.py -v
"""

import asyncio
import os
import pytest
import pytest_asyncio
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("WHATSAPP_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_ID", "test")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db import queries


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine):
    Session = sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def trader_shop(db):
    trader = await queries.get_or_create_trader(db, "+2348000000001")
    shop   = await queries.create_shop(db, trader.id, "Test Shop", is_active=True)
    await queries.update_trader(db, trader, onboarding_step="completed")
    return trader, shop


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_trader(db):
    trader = await queries.get_or_create_trader(db, "+234800000002")
    assert trader.phone_number == "+234800000002"
    assert trader.onboarding_step == "new"


@pytest.mark.asyncio
async def test_create_product(db, trader_shop):
    _, shop = trader_shop
    product = await queries.create_product(
        db, shop.id, None, "Coke 300ml", "bottle", Decimal("50"), Decimal("200")
    )
    assert product.name == "Coke 300ml"
    assert product.current_stock == Decimal("50")


@pytest.mark.asyncio
async def test_log_sale_deducts_stock(db, trader_shop):
    trader, shop = trader_shop
    await queries.create_product(
        db, shop.id, trader.id, "Fanta", "bottle", Decimal("20"), Decimal("150")
    )
    result = await queries.log_sale(
        db, shop.id, trader.id,
        [{"product_name": "Fanta", "quantity": Decimal("5")}]
    )
    assert result["grand_total"] == Decimal("750")
    product = await queries.get_product_by_name(db, shop.id, "Fanta")
    assert product.current_stock == Decimal("15")


@pytest.mark.asyncio
async def test_log_sale_insufficient_stock(db, trader_shop):
    trader, shop = trader_shop
    await queries.create_product(
        db, shop.id, trader.id, "Milo Sachet", "sachet", Decimal("3"), Decimal("100")
    )
    with pytest.raises(ValueError, match="Not enough stock"):
        await queries.log_sale(
            db, shop.id, trader.id,
            [{"product_name": "Milo Sachet", "quantity": Decimal("10")}]
        )
    product = await queries.get_product_by_name(db, shop.id, "Milo Sachet")
    assert product.current_stock == Decimal("3")


@pytest.mark.asyncio
async def test_restock_auto_creates_product(db, trader_shop):
    trader, shop = trader_shop
    result = await queries.log_restock(
        db, shop.id, trader.id, "Sugar", Decimal("3"), cost=Decimal("5300")
    )
    assert result["product_name"] == "Sugar"
    assert result["quantity_added"] == Decimal("3")
    assert result["new_stock"] == Decimal("3")
    
    product = await queries.get_product_by_name(db, shop.id, "Sugar")
    assert product is not None
    assert product.current_stock == Decimal("3")


@pytest.mark.asyncio
async def test_restock_adds_stock(db, trader_shop):
    trader, shop = trader_shop
    await queries.create_product(
        db, shop.id, trader.id, "Garri", "bag", Decimal("10"), Decimal("5000")
    )
    result = await queries.log_restock(
        db, shop.id, trader.id, "Garri", Decimal("20"), cost=Decimal("40000")
    )
    assert result["new_stock"] == Decimal("30")
    assert result["cost"] == Decimal("40000")


@pytest.mark.asyncio
async def test_debt_lifecycle(db, trader_shop):
    trader, shop = trader_shop
    await queries.log_debt(db, shop.id, trader.id, "owed", "Emeka", Decimal("3000"))
    debts = await queries.get_debts(db, shop.id)
    assert any(d.debtor_name == "Emeka" for d in debts)

    result = await queries.settle_debt(db, shop.id, "Emeka", Decimal("3000"))
    assert result["is_settled"] is True

    open_debts = await queries.get_debts(db, shop.id)
    assert not any(d.debtor_name == "Emeka" for d in open_debts)


@pytest.mark.asyncio
async def test_insights_revenue(db, trader_shop):
    trader, shop = trader_shop
    await queries.create_product(
        db, shop.id, trader.id, "Pepsi", "bottle", Decimal("100"), Decimal("200")
    )
    await queries.log_sale(
        db, shop.id, trader.id,
        [{"product_name": "Pepsi", "quantity": Decimal("5")}]
    )
    insights = await queries.get_insights(db, shop.id, "today")
    assert insights["total_revenue"] >= Decimal("1000")
    assert insights["total_transactions"] >= 1