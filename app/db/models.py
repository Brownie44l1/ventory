"""
Ventory ORM models.

Combines:
- Project 1: Product catalogue with unit_price, Sale + SaleItem (price snapshot),
  RestockTransaction with optional cost → enables gross profit calculation.
- Project 2: Trader profile + onboarding state machine, multi-Shop support,
  Debt tracking (direction, amount_paid, is_settled), DailySummary snapshots.

All financial fields use Numeric(12, 2) — no floats near money.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Numeric, Boolean, DateTime, Date, ForeignKey, Text, Time, Integer
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.connection import Base


# ── Trader ──────────────────────────────────────────────────────────────────

class Trader(Base):
    __tablename__ = "traders"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number    = Column(String(20), unique=True, nullable=False)
    name            = Column(String(100))
    business_name   = Column(String(150))
    business_type   = Column(String(100))
    language_pref   = Column(String(20), default="en")
    # Onboarding state machine: new → name → business_name → business_type → completed
    onboarding_step = Column(String(50), default="new")
    active_shop_id  = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="SET NULL"), nullable=True)
    created_at      = Column(DateTime, default=datetime.now)


# ── Shop ─────────────────────────────────────────────────────────────────────

class Shop(Base):
    """One trader can own multiple shops."""
    __tablename__ = "shops"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trader_id    = Column(UUID(as_uuid=True), ForeignKey("traders.id", ondelete="CASCADE"), nullable=False)
    name         = Column(String(150), nullable=False)
    summary_time = Column(Time, nullable=True)           # daily summary push time (local)
    timezone     = Column(String(50), default="Africa/Lagos")
    created_at   = Column(DateTime, default=datetime.now)


# ── Product ───────────────────────────────────────────────────────────────────

class Product(Base):
    """
    Named product in a shop's catalogue, with a selling price.
    Stock is tracked here as current_stock for fast lookups.
    """
    __tablename__ = "products"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id       = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(150), nullable=False)
    unit          = Column(String(50), nullable=False)   # bottle, pack, piece, tin, sachet, crate, bag, mudu …
    current_stock = Column(Numeric(10, 2), default=0)
    unit_price    = Column(Numeric(12, 2), nullable=False)  # selling price per unit, in Naira
    created_at    = Column(DateTime, default=datetime.now)


# ── Sale + SaleItem ───────────────────────────────────────────────────────────

class Sale(Base):
    """A sale transaction (may span multiple items)."""
    __tablename__ = "sales"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id      = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    trader_id    = Column(UUID(as_uuid=True), ForeignKey("traders.id", ondelete="CASCADE"), nullable=False)
    grand_total  = Column(Numeric(12, 2), nullable=False)
    input_method = Column(String(10), default="text")   # text | audio
    recorded_at  = Column(DateTime, default=datetime.now)


class SaleItem(Base):
    """
    Individual line in a sale. Stores unit_price_at_sale as a snapshot so
    historical revenue reporting stays accurate even if prices change later.
    """
    __tablename__ = "sale_items"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_id           = Column(UUID(as_uuid=True), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    product_id        = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity          = Column(Numeric(10, 2), nullable=False)
    unit_price_at_sale = Column(Numeric(12, 2), nullable=False)  # snapshot — never use current price
    line_total        = Column(Numeric(12, 2), nullable=False)
    recorded_at       = Column(DateTime, default=datetime.now)


# ── RestockTransaction ────────────────────────────────────────────────────────

class RestockTransaction(Base):
    """
    Adds stock to a product. Optional cost field enables gross profit calculation
    (revenue - restock cost) in the insights endpoint.
    """
    __tablename__ = "restock_transactions"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id    = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity   = Column(Numeric(10, 2), nullable=False)
    cost       = Column(Numeric(12, 2), nullable=True)  # what it cost to restock, optional
    recorded_at = Column(DateTime, default=datetime.now)


# ── Expense ───────────────────────────────────────────────────────────────────

class Expense(Base):
    """General business expenses: rent, transport, fuel, etc."""
    __tablename__ = "expenses"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id     = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    trader_id   = Column(UUID(as_uuid=True), ForeignKey("traders.id", ondelete="CASCADE"), nullable=False)
    description = Column(String(200))
    amount      = Column(Numeric(12, 2), nullable=False)
    recorded_at = Column(DateTime, default=datetime.now)


# ── Debt ──────────────────────────────────────────────────────────────────────

class Debt(Base):
    """
    Tracks money owed.
    - direction='owed'     → customer owes the trader (took goods without paying)
    - direction='owing'    → trader owes someone (supplier credit, etc.)
    Settlement is tracked via amount_paid; is_settled flips when amount_paid >= amount.
    """
    __tablename__ = "debts"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id      = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    trader_id    = Column(UUID(as_uuid=True), ForeignKey("traders.id", ondelete="CASCADE"), nullable=False)
    direction    = Column(String(10), nullable=False)    # owed | owing
    debtor_name  = Column(String(150), nullable=False)
    amount       = Column(Numeric(12, 2), nullable=False)
    amount_paid  = Column(Numeric(12, 2), default=0)
    is_settled   = Column(Boolean, default=False)
    due_date     = Column(Date, nullable=True)
    note         = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.now)


# ── DailySummary ──────────────────────────────────────────────────────────────

class DailySummary(Base):
    """Historical daily snapshot. Written by the scheduler or on-demand."""
    __tablename__ = "daily_summaries"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id        = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    trader_id      = Column(UUID(as_uuid=True), ForeignKey("traders.id", ondelete="CASCADE"), nullable=False)
    summary_date   = Column(Date, nullable=False)
    total_sales    = Column(Numeric(12, 2), default=0)
    total_expenses = Column(Numeric(12, 2), default=0)
    restock_cost   = Column(Numeric(12, 2), default=0)
    gross_profit   = Column(Numeric(12, 2), default=0)   # sales - restock_cost
    net_profit     = Column(Numeric(12, 2), default=0)   # gross_profit - expenses
    tx_count       = Column(Integer, default=0)