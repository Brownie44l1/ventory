import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db.connection import AsyncSessionLocal
from app.db.models import Shop, Trader
from app.db import queries
from app.services import whatsapp, gemini

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def send_daily_summaries():
    """
    Run every hour. For each shop with a summary_time set,
    send a daily summary if the current local hour matches.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Shop).where(Shop.summary_time.isnot(None))
        )
        shops = result.scalars().all()

        for shop in shops:
            try:
                tz  = pytz.timezone(shop.timezone or "Africa/Lagos")
                now = datetime.now(tz)

                if now.hour != shop.summary_time.hour:
                    continue

                res    = await db.execute(select(Trader).where(Trader.id == shop.trader_id))
                trader = res.scalar_one()

                summary_data   = await queries.get_shop_summary(db, shop.id)
                inventory_data = await queries.get_inventory(db, shop.id)
                debt_data      = await queries.get_debts(db, shop.id)

                context = {
                    "is_daily_push": True,
                    "shop_name": shop.name,
                    "summary": summary_data,
                    "inventory": [
                        {"item": p.name, "quantity": float(p.current_stock), "unit": p.unit}
                        for p in inventory_data
                    ],
                    "debts": [
                        {
                            "name": d.debtor_name,
                            "amount": float(d.amount),
                            "paid": float(d.amount_paid),
                            "balance": float(d.amount - d.amount_paid),
                        }
                        for d in debt_data
                    ],
                }

                message = await gemini.answer_query(
                    context, "Give me a concise daily summary of my business."
                )
                await whatsapp.send_message(trader.phone_number, message)
                logger.info("Sent daily summary to %s for shop %s.", trader.phone_number, shop.name)

            except Exception as e:
                logger.error("Error sending daily summary for shop %s: %s", shop.id, e)


def start_scheduler():
    scheduler.add_job(send_daily_summaries, "cron", minute=0)
    scheduler.start()
    logger.info("Background scheduler started.")