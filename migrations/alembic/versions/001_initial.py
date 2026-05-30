"""initial

Revision ID: 001_initial
Revises:
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "traders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100)),
        sa.Column("business_name", sa.String(150)),
        sa.Column("business_type", sa.String(100)),
        sa.Column("language_pref", sa.String(20), server_default="en"),
        sa.Column("onboarding_step", sa.String(50), server_default="new"),
        sa.Column("active_shop_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number"),
    )

    op.create_table(
        "shops",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("summary_time", sa.Time, nullable=True),
        sa.Column("timezone", sa.String(50), server_default="Africa/Lagos"),
        sa.Column("created_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["trader_id"], ["traders.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("current_stock", sa.Numeric(10, 2), server_default="0"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("input_method", sa.String(10), server_default="text"),
        sa.Column("recorded_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trader_id"], ["traders.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "sale_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_price_at_sale", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("recorded_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "restock_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("recorded_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.String(200)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("recorded_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trader_id"], ["traders.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "debts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("debtor_name", sa.String(150), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(12, 2), server_default="0"),
        sa.Column("is_settled", sa.Boolean, server_default="false"),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trader_id"], ["traders.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "daily_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_date", sa.Date, nullable=False),
        sa.Column("total_sales", sa.Numeric(12, 2), server_default="0"),
        sa.Column("total_expenses", sa.Numeric(12, 2), server_default="0"),
        sa.Column("restock_cost", sa.Numeric(12, 2), server_default="0"),
        sa.Column("gross_profit", sa.Numeric(12, 2), server_default="0"),
        sa.Column("net_profit", sa.Numeric(12, 2), server_default="0"),
        sa.Column("tx_count", sa.Integer, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trader_id"], ["traders.id"], ondelete="CASCADE"),
    )

    op.create_foreign_key(
        "fk_traders_active_shop",
        "traders", "shops",
        ["active_shop_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_traders_active_shop", "traders", type_="foreignkey")
    for table in ["daily_summaries", "debts", "expenses", "restock_transactions",
                  "sale_items", "sales", "products", "shops", "traders"]:
        op.drop_table(table)
