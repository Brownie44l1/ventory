"""
Ventory Data Access Layer.

All DB interactions go through here — no SQL in routers or services.
Uses async SQLAlchemy throughout.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Trader, Shop, Product, Sale, SaleItem,
    RestockTransaction, Expense, Debt, DailySummary,
)


LOW_STOCK_THRESHOLD = Decimal("5")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_start(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "week":
        return now - timedelta(days=7)
    elif period == "month":
        return now - timedelta(days=30)
    else:  # today
        return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ── Trader ────────────────────────────────────────────────────────────────────

async def get_or_create_trader(db: AsyncSession, phone: str) -> Trader:
    result = await db.execute(select(Trader).where(Trader.phone_number == phone))
    trader = result.scalar_one_or_none()
    if not trader:
        trader = Trader(phone_number=phone, onboarding_step="new")
        db.add(trader)
        await db.commit()
        await db.refresh(trader)
    return trader


async def update_trader(db: AsyncSession, trader: Trader, **kwargs) -> Trader:
    for key, value in kwargs.items():
        setattr(trader, key, value)
    await db.commit()
    await db.refresh(trader)
    return trader


# ── Shop ──────────────────────────────────────────────────────────────────────

async def create_shop(
    db: AsyncSession, trader_id, name: str, is_active: bool = False
) -> Shop:
    shop = Shop(trader_id=trader_id, name=name)
    db.add(shop)
    await db.commit()
    await db.refresh(shop)

    if is_active:
        res = await db.execute(select(Trader).where(Trader.id == trader_id))
        trader = res.scalar_one()
        trader.active_shop_id = shop.id
        await db.commit()

    return shop


async def get_shops(db: AsyncSession, trader_id) -> list[Shop]:
    result = await db.execute(
        select(Shop).where(Shop.trader_id == trader_id).order_by(Shop.created_at)
    )
    return result.scalars().all()


# ── Products ──────────────────────────────────────────────────────────────────

async def get_products(db: AsyncSession, shop_id) -> list[Product]:
    result = await db.execute(
        select(Product).where(Product.shop_id == shop_id).order_by(Product.name)
    )
    return result.scalars().all()


async def get_product_by_name(db: AsyncSession, shop_id, name: str) -> Optional[Product]:
    result = await db.execute(
        select(Product).where(
            Product.shop_id == shop_id,
            func.lower(Product.name) == name.strip().lower(),
        )
    )
    return result.scalar_one_or_none()


async def create_product(
    db: AsyncSession,
    shop_id,
    trader_id,
    name: str,
    unit: str,
    initial_stock: Decimal,
    unit_price: Decimal,
) -> Product:
    existing = await get_product_by_name(db, shop_id, name)
    if existing:
        raise ValueError(f"Product '{name}' already exists.")

    product = Product(
        shop_id=shop_id,
        name=name.strip(),
        unit=unit.strip(),
        current_stock=initial_stock,
        unit_price=unit_price,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


# ── Sales ─────────────────────────────────────────────────────────────────────

async def log_sale(
    db: AsyncSession,
    shop_id,
    trader_id,
    items: list[dict],  # [{"product_name": str, "quantity": Decimal}]
    input_method: str = "text",
) -> dict:
    validated: list[tuple[Product, Decimal]] = []
    for item in items:
        product = await get_product_by_name(db, shop_id, item["product_name"])
        if not product:
            raise ValueError(f"Product '{item['product_name']}' not found. Add it first.")
        qty = Decimal(str(item["quantity"]))
        if qty <= 0:
            raise ValueError(f"Quantity for '{product.name}' must be greater than 0.")
        if product.current_stock < qty:
            raise ValueError(
                f"Not enough stock for {product.name}. "
                f"Only {product.current_stock} {product.unit}(s) left."
            )
        validated.append((product, qty))

    grand_total = sum(p.unit_price * q for p, q in validated)

    sale = Sale(
        shop_id=shop_id,
        trader_id=trader_id,
        grand_total=grand_total,
        input_method=input_method,
        recorded_at=datetime.utcnow(),
    )
    db.add(sale)
    await db.flush()

    line_items = []
    for product, quantity in validated:
        line_total = product.unit_price * quantity
        db.add(SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=quantity,
            unit_price_at_sale=product.unit_price,
            line_total=line_total,
            recorded_at=datetime.utcnow(),
        ))
        product.current_stock -= quantity
        line_items.append({
            "product_name": product.name,
            "unit": product.unit,
            "quantity": quantity,
            "unit_price": product.unit_price,
            "line_total": line_total,
            "remaining_stock": product.current_stock - quantity,
        })

    await db.commit()
    for li in line_items:
        p = await get_product_by_name(db, shop_id, li["product_name"])
        li["remaining_stock"] = p.current_stock if p else Decimal("0")

    return {"sale_id": str(sale.id), "items": line_items, "grand_total": grand_total}


# ── Restock ───────────────────────────────────────────────────────────────────

async def log_restock(
    db: AsyncSession,
    shop_id,
    product_name: str,
    quantity: Decimal,
    cost: Optional[Decimal] = None,
) -> dict:
    product = await get_product_by_name(db, shop_id, product_name)
    if not product:
        raise ValueError(f"Product '{product_name}' not found. Add it first.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")

    db.add(RestockTransaction(
        shop_id=shop_id,
        product_id=product.id,
        quantity=quantity,
        cost=cost,
        recorded_at=datetime.utcnow(),
    ))
    product.current_stock += quantity
    await db.commit()

    return {
        "product_name": product.name,
        "unit": product.unit,
        "quantity_added": quantity,
        "new_stock": product.current_stock,
        "cost": cost,
    }


# ── Expenses ──────────────────────────────────────────────────────────────────

async def log_expense(
    db: AsyncSession,
    shop_id,
    trader_id,
    description: str,
    amount: Decimal,
) -> dict:
    expense = Expense(
        shop_id=shop_id,
        trader_id=trader_id,
        description=description,
        amount=amount,
        recorded_at=datetime.utcnow(),
    )
    db.add(expense)
    await db.commit()
    return {"description": description, "amount": amount}


# ── Debts ─────────────────────────────────────────────────────────────────────

async def log_debt(
    db: AsyncSession,
    shop_id,
    trader_id,
    direction: str,
    debtor_name: str,
    amount: Decimal,
    note: Optional[str] = None,
) -> dict:
    res = await db.execute(
        select(Debt).where(
            Debt.shop_id == shop_id,
            func.lower(Debt.debtor_name) == debtor_name.strip().lower(),
            Debt.direction == direction,
            Debt.is_settled == False,
        )
    )
    debt = res.scalar_one_or_none()

    if direction == "owed":
        if not debt:
            debt = Debt(
                shop_id=shop_id,
                trader_id=trader_id,
                direction="owed",
                debtor_name=debtor_name.strip(),
                amount=amount,
                amount_paid=Decimal("0"),
                note=note,
            )
            db.add(debt)
        else:
            debt.amount += amount
    elif direction == "owing":
        if not debt:
            debt = Debt(
                shop_id=shop_id,
                trader_id=trader_id,
                direction="owing",
                debtor_name=debtor_name.strip(),
                amount=amount,
                amount_paid=Decimal("0"),
                note=note,
            )
            db.add(debt)
        else:
            debt.amount += amount

    await db.commit()
    return {"debtor_name": debtor_name, "direction": direction, "amount": amount}


async def settle_debt(
    db: AsyncSession,
    shop_id,
    debtor_name: str,
    amount_paid: Decimal,
) -> dict:
    res = await db.execute(
        select(Debt).where(
            Debt.shop_id == shop_id,
            func.lower(Debt.debtor_name) == debtor_name.strip().lower(),
            Debt.direction == "owed",
            Debt.is_settled == False,
        )
    )
    debt = res.scalar_one_or_none()
    if not debt:
        raise ValueError(f"No open debt found for '{debtor_name}'.")

    debt.amount_paid += amount_paid
    if debt.amount_paid >= debt.amount:
        debt.is_settled = True

    await db.commit()
    balance = max(Decimal("0"), debt.amount - debt.amount_paid)
    return {
        "debtor_name": debtor_name,
        "amount_paid": amount_paid,
        "balance": balance,
        "is_settled": debt.is_settled,
    }


async def get_debts(db: AsyncSession, shop_id) -> list[Debt]:
    result = await db.execute(
        select(Debt).where(
            Debt.shop_id == shop_id,
            Debt.is_settled == False,
        ).order_by(Debt.created_at.desc())
    )
    return result.scalars().all()


# ── Insights ──────────────────────────────────────────────────────────────────

async def get_insights(db: AsyncSession, shop_id, period: str = "today") -> dict:
    start = _period_start(period)

    rev_result = await db.execute(
        select(func.sum(Sale.grand_total)).where(
            Sale.shop_id == shop_id,
            Sale.recorded_at >= start,
        )
    )
    total_revenue = rev_result.scalar() or Decimal("0")

    tx_result = await db.execute(
        select(func.count(Sale.id)).where(
            Sale.shop_id == shop_id,
            Sale.recorded_at >= start,
        )
    )
    tx_count = tx_result.scalar() or 0

    top_result = await db.execute(
        select(
            Product.name,
            Product.unit,
            func.sum(SaleItem.quantity).label("units_sold"),
            func.sum(SaleItem.line_total).label("revenue"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.shop_id == shop_id, Sale.recorded_at >= start)
        .group_by(Product.id)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(5)
    )
    top_sellers = [
        {
            "product_name": r.name,
            "unit": r.unit,
            "units_sold": r.units_sold,
            "revenue": r.revenue,
        }
        for r in top_result.all()
    ]

    low_result = await db.execute(
        select(Product).where(
            Product.shop_id == shop_id,
            Product.current_stock < LOW_STOCK_THRESHOLD,
        ).order_by(Product.current_stock)
    )
    low_stock = [
        {"product_name": p.name, "current_stock": p.current_stock, "unit": p.unit}
        for p in low_result.scalars().all()
    ]

    cost_result = await db.execute(
        select(func.sum(RestockTransaction.cost)).where(
            RestockTransaction.shop_id == shop_id,
            RestockTransaction.recorded_at >= start,
            RestockTransaction.cost.isnot(None),
        )
    )
    restock_cost = cost_result.scalar()
    gross_profit = (
        round(float(total_revenue) - float(restock_cost), 2)
        if restock_cost is not None
        else None
    )

    exp_result = await db.execute(
        select(func.sum(Expense.amount)).where(
            Expense.shop_id == shop_id,
            Expense.recorded_at >= start,
        )
    )
    total_expenses = exp_result.scalar() or Decimal("0")

    return {
        "period": period,
        "total_revenue": total_revenue,
        "total_transactions": tx_count,
        "top_sellers": top_sellers,
        "low_stock_alerts": low_stock,
        "total_restock_cost": restock_cost,
        "total_expenses": total_expenses,
        "gross_profit": gross_profit,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

async def get_shop_summary(db: AsyncSession, shop_id) -> dict:
    today = date.today()

    rev_result = await db.execute(
        select(func.sum(Sale.grand_total)).where(
            Sale.shop_id == shop_id,
            func.date(Sale.recorded_at) == today,
        )
    )
    sales = float(rev_result.scalar() or 0)

    exp_result = await db.execute(
        select(func.sum(Expense.amount)).where(
            Expense.shop_id == shop_id,
            func.date(Expense.recorded_at) == today,
        )
    )
    expenses = float(exp_result.scalar() or 0)

    tx_result = await db.execute(
        select(func.count(Sale.id)).where(
            Sale.shop_id == shop_id,
            func.date(Sale.recorded_at) == today,
        )
    )
    tx_count = tx_result.scalar() or 0

    return {
        "today": {
            "sales": sales,
            "expenses": expenses,
            "profit": round(sales - expenses, 2),
            "tx_count": tx_count,
        }
    }


async def save_gemini_transactions(db: AsyncSession, shop_id, trader_id, transactions):
    from app.schemas.transaction import ParsedTransaction

    for t in transactions:
        if t.type in ("sale", "restock", "purchase") and t.item:
            product = await get_product_by_name(db, shop_id, t.item)
            if not product:
                product = await create_product(
                    db, shop_id, trader_id,
                    name=t.item,
                    unit=t.unit or "unit",
                    initial_stock=Decimal("0"),
                    unit_price=Decimal("0"),
                )
            qty = t.quantity or Decimal("1")
            if t.type == "sale":
                sale = Sale(
                    shop_id=shop_id,
                    trader_id=trader_id,
                    grand_total=product.unit_price * qty,
                    input_method="audio",
                    recorded_at=datetime.utcnow(),
                )
                db.add(sale)
                await db.flush()
                db.add(SaleItem(
                    sale_id=sale.id,
                    product_id=product.id,
                    quantity=qty,
                    unit_price_at_sale=product.unit_price,
                    line_total=product.unit_price * qty,
                ))
                product.current_stock = max(Decimal("0"), product.current_stock - qty)
            else:
                db.add(RestockTransaction(
                    shop_id=shop_id,
                    product_id=product.id,
                    quantity=qty,
                    cost=t.amount,
                    recorded_at=datetime.utcnow(),
                ))
                product.current_stock += qty

        elif t.type == "expense":
            db.add(Expense(
                shop_id=shop_id,
                trader_id=trader_id,
                description=t.item or t.note or "Expense",
                amount=t.amount,
                recorded_at=datetime.utcnow(),
            ))

        elif t.type == "debt_owed" and t.counterparty:
            await log_debt(db, shop_id, trader_id, "owed", t.counterparty, t.amount, t.note)

        elif t.type == "debt_received" and t.counterparty:
            try:
                await settle_debt(db, shop_id, t.counterparty, t.amount)
            except ValueError:
                pass

    await db.commit()


async def get_inventory(db: AsyncSession, shop_id) -> list[Product]:
    result = await db.execute(
        select(Product).where(Product.shop_id == shop_id).order_by(Product.name)
    )
    return result.scalars().all()
