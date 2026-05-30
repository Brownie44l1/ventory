SHOP_SCHEMA = """
DATABASE SCHEMA (PostgreSQL):

-- traders: registered shop owners
traders(id UUID PK, phone_number, name, business_name, onboarding_step, active_shop_id FK→shops.id)

-- shops: each trader can own multiple shops
shops(id UUID PK, trader_id FK→traders.id, name, summary_time, timezone)

-- products: items in a shop's catalogue
products(id UUID PK, shop_id FK→shops.id, name, unit, current_stock NUMERIC, unit_price NUMERIC)

-- sales: a transaction that may contain multiple items
sales(id UUID PK, shop_id FK→shops.id, trader_id, grand_total NUMERIC, recorded_at TIMESTAMP)

-- sale_items: individual lines within a sale
sale_items(id UUID PK, sale_id FK→sales.id, product_id FK→products.id,
           quantity NUMERIC, unit_price_at_sale NUMERIC, line_total NUMERIC, recorded_at TIMESTAMP)

-- restock_transactions: stock additions, optional cost
restock_transactions(id UUID PK, shop_id FK→shops.id, product_id FK→products.id,
                     quantity NUMERIC, cost NUMERIC nullable, recorded_at TIMESTAMP)

-- expenses: overhead costs (rent, fuel, transport, etc.)
expenses(id UUID PK, shop_id FK→shops.id, trader_id, description, amount NUMERIC, recorded_at TIMESTAMP)

-- debts: money owed (direction='owed' = customer owes us; direction='owing' = we owe someone)
debts(id UUID PK, shop_id FK→shops.id, direction, debtor_name, amount NUMERIC,
      amount_paid NUMERIC, is_settled BOOLEAN, created_at TIMESTAMP)

USEFUL NOTES:
- All financial columns are NUMERIC (no floats).
- Use recorded_at for time-based filtering on sales, sale_items, restock_transactions, expenses.
- Use current_stock on products for live stock levels.
- For revenue: SUM(sales.grand_total) or SUM(sale_items.line_total).
- For top sellers: JOIN sale_items → products, GROUP BY products.name, ORDER BY SUM(quantity) DESC.
"""