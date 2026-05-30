"""
Ventory webhook router.

Handles:
1. WhatsApp verification (GET /webhook)
2. Incoming messages (POST /webhook)
   - Onboarding state machine (new traders)
   - Keyword-detected queries → Gemini answer_query (fast path)
   - Export requests → exports service
   - Everything else → LangGraph agent
"""

import logging
import os
from langchain_core.messages import HumanMessage

from fastapi import APIRouter, Request, Response, BackgroundTasks
from app.db.connection import AsyncSessionLocal
from app.db import queries
from app.services import gemini, whatsapp
from app.services.exports import generate_and_send_export

logger = logging.getLogger(__name__)

router = APIRouter()
VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]

# Build the LangGraph graph once at startup — compilation is expensive
from app.agent.graph import build_graph
graph = build_graph()

# In-memory session store keyed by phone number.
# Replace with Redis for multi-process / production deployments.
session_store: dict[str, list] = {}


# ── WhatsApp verification ─────────────────────────────────────────────────────

@router.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params["hub.challenge"], media_type="text/plain")
    return Response(status_code=403)


# ── Incoming messages ─────────────────────────────────────────────────────────

@router.post("/webhook")
async def handle_message(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    try:
        entry    = body["entry"][0]["changes"][0]["value"]
        msg      = entry["messages"][0]
        phone    = msg["from"]
        msg_type = msg["type"]
    except (KeyError, IndexError):
        return {"status": "ignored"}

    # Return 200 immediately so WhatsApp doesn't retry, process in background
    background_tasks.add_task(_process, msg, phone, msg_type)
    return Response(status_code=200)


async def _process(msg: dict, phone: str, msg_type: str):
    async with AsyncSessionLocal() as db:
        try:
            trader = await queries.get_or_create_trader(db, phone)

            # ── Onboarding ────────────────────────────────────────────────────
            if trader.onboarding_step != "completed" and msg_type == "text":
                text = msg["text"]["body"]
                await _onboard(db, trader, phone, text)
                return

            # Ensure there's an active shop
            if not trader.active_shop_id:
                shops = await queries.get_shops(db, trader.id)
                if shops:
                    await queries.update_trader(db, trader, active_shop_id=str(shops[0].id))
                else:
                    shop = await queries.create_shop(
                        db, trader.id, trader.business_name or "My Shop", is_active=True
                    )
                await db.refresh(trader)

            shop_id   = str(trader.active_shop_id)
            trader_id = str(trader.id)

            # ── Audio → Gemini parse ──────────────────────────────────────────
            if msg_type == "audio":
                media_id  = msg["audio"]["id"]
                mime_type = msg["audio"].get("mime_type", "audio/ogg; codecs=opus")
                audio     = await whatsapp.download_media(media_id)
                txns      = await gemini.transcribe_and_parse(audio, mime_type)

                if not txns:
                    await whatsapp.send_message(phone, "Couldn't parse that audio. Try typing it out.")
                    return

                await queries.save_gemini_transactions(db, shop_id, trader_id, txns)
                await whatsapp.send_message(phone, _format_confirmation(txns))
                return

            # ── Text ──────────────────────────────────────────────────────────
            if msg_type != "text":
                return

            text = msg["text"]["body"]

            # Export shortcut
            if any(kw in text.lower() for kw in ["export", "download", "csv", "pdf"]):
                fmt = "pdf" if "pdf" in text.lower() else "csv"
                await generate_and_send_export(phone, shop_id, fmt)
                return

            # Fast-path keyword queries → Gemini RAG (no agent overhead)
            _QUERY_KW = [
                "how much", "how many", "summary", "profit", "wetin i",
                "show me", "inventory", "stock", "remain", "debt", "owe",
                "pay", "customer", "switch", "business",
            ]
            if any(kw in text.lower() for kw in _QUERY_KW):
                inv_data  = await queries.get_inventory(db, shop_id)
                debt_data = await queries.get_debts(db, shop_id)
                summary   = await queries.get_shop_summary(db, shop_id)
                shops     = await queries.get_shops(db, trader.id)

                context = {
                    "active_shop": next(
                        (s.name for s in shops if str(s.id) == shop_id), "Unknown"
                    ),
                    "all_shops": [s.name for s in shops],
                    "summary": summary,
                    "inventory": [
                        {"item": p.name, "quantity": float(p.current_stock), "unit": p.unit}
                        for p in inv_data
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
                reply = await gemini.answer_query(context, text)
                await whatsapp.send_message(phone, reply)
                return

            # ── LangGraph agent ───────────────────────────────────────────────
            history = session_store.get(phone, [])

            result = await graph.ainvoke({
                "messages":          [HumanMessage(content=text)],
                "question":          text,
                "history":           history,
                "shop_id":           shop_id,
                "trader_id":         trader_id,
                "sql":               None,
                "sql_result":        None,
                "sql_validated":     False,
                "retry_count":       0,
                "sql_error":         None,
                "resolved_products": {},
                "unresolved_products": [],
                "available_products":  [],
            })

            session_store[phone] = result.get("history", history)[-20:]
            reply = result.get("response") or ""

            if reply:
                await whatsapp.send_message(phone, reply)

        except Exception as e:
            logger.error("Error processing message from %s: %s", phone, e, exc_info=True)
            try:
                await whatsapp.send_message(phone, "Something went wrong. Please try again.")
            except Exception:
                pass


# ── Onboarding state machine ──────────────────────────────────────────────────

async def _onboard(db, trader, phone: str, text: str):
    step = trader.onboarding_step
    if step == "new":
        await queries.update_trader(db, trader, onboarding_step="name")
        await whatsapp.send_message(
            phone,
            "Welcome to *Ventory*! I help you track sales, stock, expenses, and debts.\n\nWhat is your name?"
        )
    elif step == "name":
        await queries.update_trader(db, trader, name=text, onboarding_step="business_name")
        await whatsapp.send_message(phone, f"Nice to meet you, {text}! What is the name of your business?")
    elif step == "business_name":
        await queries.update_trader(db, trader, business_name=text, onboarding_step="business_type")
        await whatsapp.send_message(phone, "What do you primarily sell? (e.g. Provisions, Foodstuffs, Electronics)")
    elif step == "business_type":
        await queries.update_trader(db, trader, business_type=text, onboarding_step="completed")
        await queries.create_shop(db, trader.id, trader.business_name or "My Shop", is_active=True)
        await whatsapp.send_message(
            phone,
            f"You're all set! Here's what I can do:\n\n"
            f"📦 *Record sales* — \"I sold 3 Coke and 2 Fanta\"\n"
            f"🔄 *Restock* — \"Got 20 more Milo, cost 15k\"\n"
            f"💸 *Expenses* — \"Paid 5k rent\"\n"
            f"📝 *Debts* — \"Emeka took 3k goods, no pay\"\n"
            f"📊 *Insights* — \"How did today go?\"\n"
            f"📤 *Export* — \"Export my transactions as CSV\"\n\n"
            f"Go ahead — tell me what you've sold today."
        )


# ── Confirmation formatter (for Gemini-parsed transactions) ──────────────────

def _format_confirmation(txns) -> str:
    EMOJI = {
        "sale": "💰", "expense": "💸", "purchase": "📦",
        "restock": "📦", "debt_owed": "📝", "debt_received": "🤝",
    }
    lines = ["✅ *Recorded!*"]
    for t in txns:
        emoji    = EMOJI.get(t.type, "📋")
        item     = f" {t.item}" if t.item else ""
        qty      = f" ({t.quantity} {t.unit or ''})" if t.quantity else ""
        party    = f" — {t.counterparty}" if t.counterparty else ""
        type_str = t.type.replace("_", " ").capitalize()
        lines.append(f"{emoji} {type_str}{item}{qty}{party}: ₦{t.amount:,.0f}")
    return "\n".join(lines)