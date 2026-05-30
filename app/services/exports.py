import os
import logging
from datetime import datetime

import pandas as pd
from fpdf import FPDF
from sqlalchemy import select

from app.db.connection import AsyncSessionLocal
from app.db.models import Sale, SaleItem, Expense, RestockTransaction, Product, Shop
from app.services import whatsapp

logger = logging.getLogger(__name__)


async def export_transactions(shop_id, fmt: str = "csv"):
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Shop).where(Shop.id == shop_id))
        shop = res.scalar_one()

        # Sales
        sale_res = await db.execute(
            select(
                Sale.recorded_at,
                SaleItem.quantity,
                SaleItem.unit_price_at_sale,
                SaleItem.line_total,
                Product.name.label("product"),
                Product.unit,
            )
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .join(Product, Product.id == SaleItem.product_id)
            .where(Sale.shop_id == shop_id)
            .order_by(Sale.recorded_at.desc())
        )
        rows = []
        for r in sale_res.all():
            rows.append({
                "Date": r.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Type": "sale",
                "Item": r.product,
                "Qty": float(r.quantity),
                "Unit": r.unit,
                "Amount": float(r.line_total),
                "Note": "",
            })

        # Expenses
        exp_res = await db.execute(
            select(Expense).where(Expense.shop_id == shop_id).order_by(Expense.recorded_at.desc())
        )
        for e in exp_res.scalars().all():
            rows.append({
                "Date": e.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Type": "expense",
                "Item": e.description,
                "Qty": "",
                "Unit": "",
                "Amount": float(e.amount),
                "Note": "",
            })

        # Restocks
        rr = await db.execute(
            select(RestockTransaction, Product.name.label("pname"), Product.unit.label("punit"))
            .join(Product, Product.id == RestockTransaction.product_id)
            .where(RestockTransaction.shop_id == shop_id)
            .order_by(RestockTransaction.recorded_at.desc())
        )
        for tx, pname, punit in rr.all():
            rows.append({
                "Date": tx.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Type": "restock",
                "Item": pname,
                "Qty": float(tx.quantity),
                "Unit": punit,
                "Amount": float(tx.cost) if tx.cost else 0,
                "Note": "",
            })

        if not rows:
            return None

        rows.sort(key=lambda x: x["Date"], reverse=True)
        df = pd.DataFrame(rows)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = shop.name.replace(" ", "_")
        filename = f"ventory_{slug}_{timestamp}"

        if fmt == "csv":
            path = f"/tmp/{filename}.csv"
            df.to_csv(path, index=False)
            return path, "text/csv"

        elif fmt == "pdf":
            path = f"/tmp/{filename}.pdf"
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(190, 10, f"Ventory Report: {shop.name}", ln=True, align="C")
            pdf.set_font("Arial", size=9)

            # Header
            pdf.set_fill_color(200, 200, 200)
            for header, w in [("Date", 35), ("Type", 20), ("Item", 45), ("Qty", 15), ("Amount", 30), ("Note", 45)]:
                pdf.cell(w, 9, header, 1, 0, "C", True)
            pdf.ln()

            for _, row in df.iterrows():
                pdf.cell(35, 8, str(row["Date"]), 1)
                pdf.cell(20, 8, str(row["Type"]), 1)
                pdf.cell(45, 8, str(row["Item"])[:20], 1)
                pdf.cell(15, 8, str(row["Qty"]), 1)
                pdf.cell(30, 8, f"₦{row['Amount']:,.0f}", 1)
                pdf.cell(45, 8, str(row["Note"])[:20], 1, 1)

            pdf.output(path)
            return path, "application/pdf"

        return None


async def generate_and_send_export(phone: str, shop_id, fmt: str = "csv"):
    result = await export_transactions(shop_id, fmt)
    if not result:
        await whatsapp.send_message(phone, "You don't have any transactions to export yet.")
        return

    file_path, mime_type = result
    try:
        media_id = await whatsapp.upload_media(file_path, mime_type)
        await whatsapp.send_document(phone, media_id, os.path.basename(file_path))
    except Exception as e:
        logger.error("Export send failed: %s", e)
        await whatsapp.send_message(phone, "Export failed. Please try again.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)