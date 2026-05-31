"""
Ventory LangGraph nodes.

Node flow:
  classify
    → dispatch_prep (write intents): list_products → resolve_products → dispatch → synthesize
    → generate_sql  (read/analytical): validate_sql → execute_sql → sql_synthesize
    → chitchat
    → clarify
"""

import asyncio
import json
import logging

from sqlalchemy import text

from app.agent.config import chat_llm, sql_llm
from app.agent.models import State
from app.agent.prompts import (
    CHITCHAT_PROMPT, CLARIFY_PROMPT, CLASSIFY_PROMPT, SYNTHESIS_PROMPT,
    SQL_GENERATION_PROMPT, SQL_SYNTHESIS_PROMPT,
)
from app.agent.schema import SHOP_SCHEMA
from app.agent.tools import (
    add_product, get_insights, get_inventory,
    log_sale, restock, log_expense, log_debt, settle_debt,
)
from app.db.connection import AsyncSessionLocal

logger = logging.getLogger(__name__)

_MAX_SQL_RETRIES = 3

_READ_INTENTS  = {"get_inventory", "get_insights", "query"}
_WRITE_INTENTS = {"log_sale", "restock", "log_expense", "log_debt", "settle_debt", "add_product"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_history(state: State) -> str:
    history = state.history
    if not history:
        return ""
    lines = []
    for h in history[-10:]:
        lines.append(f"Owner: {h['question']}\nVentory: {h['response']}")
        if h.get("unresolved_context"):
            lines.append(f"[Unresolved: {h['unresolved_context']}]")
        if h.get("partial_params"):
            lines.append(f"[Partial params: {json.dumps(h['partial_params'])}]")
        lines.append("")
    return "CONVERSATION SO FAR:\n" + "\n".join(lines)


def _get_partial_params(history: list) -> dict:
    partial: dict = {}
    for h in history:
        if h.get("partial_params"):
            partial.update(h["partial_params"])
    return partial


# ── classify ──────────────────────────────────────────────────────────────────

async def classify(state: State) -> dict:
    resolved  = state.resolved_products
    unresolved = state.unresolved_products
    history   = state.history

    prev_unresolved = history[-1].get("unresolved_context", []) if history else []
    partial_params  = _get_partial_params(history)

    context = ""
    if resolved:
        context += f"Resolved products: {json.dumps(resolved)}\n"
    if unresolved:
        context += f"Not found in system: {unresolved}\n"
    if prev_unresolved:
        context += f"Previously unresolved (owner likely clarifying): {prev_unresolved}\n"
    if partial_params:
        context += f"Already gathered from conversation: {json.dumps(partial_params)}\n"

    prompt = CLASSIFY_PROMPT.format(
        context=context,
        question=state.question,
        conversation_history=_format_history(state),
    )

    response = await chat_llm.ainvoke(prompt)
    try:
        data = json.loads(
            response.content.strip().replace("```json", "").replace("```", "")
        )
        return {
            "intent": data["intent"],
            "tool_params": data.get("params", {}),
            "clarification": data.get("clarification"),
        }
    except Exception:
        return {"intent": "unclear", "tool_params": {}, "clarification": None}


# ── dispatch ──────────────────────────────────────────────────────────────────

async def dispatch(state: State) -> dict:
    intent = state.intent
    params = dict(state.tool_params)  # copy so we can mutate
    shop_id   = state.shop_id
    trader_id = state.trader_id

    # Substitute resolved product names into tool params
    resolved = state.resolved_products
    if resolved:
        items = params.get("items")
        if items:
            for item in items:
                raw = item["product_name"]
                if raw in resolved:
                    item["product_name"] = resolved[raw]

    logger.info("Dispatch: intent=%s params=%s", intent, params)

    try:
        if intent == "log_sale":
            result = log_sale.invoke({
                "items": params.get("items", []),
                "shop_id": shop_id,
                "trader_id": trader_id,
            })
        elif intent == "restock":
            result = restock.invoke({**params, "shop_id": shop_id, "trader_id": trader_id})
        elif intent == "log_expense":
            result = log_expense.invoke({**params, "shop_id": shop_id, "trader_id": trader_id})
        elif intent == "log_debt":
            result = log_debt.invoke({**params, "shop_id": shop_id, "trader_id": trader_id})
        elif intent == "settle_debt":
            result = settle_debt.invoke({**params, "shop_id": shop_id})
        elif intent == "get_inventory":
            result = get_inventory.invoke({"shop_id": shop_id})
        elif intent == "get_insights":
            result = get_insights.invoke({
                "shop_id": shop_id,
                "period": params.get("period", "today"),
            })
        elif intent == "add_product":
            result = add_product.invoke({**params, "shop_id": shop_id, "trader_id": trader_id})
        else:
            result = None
    except Exception as e:
        result = f"Tool error: {e}"

    return {"tool_result": result}


# ── synthesize ────────────────────────────────────────────────────────────────

async def synthesize(state: State) -> dict:
    prompt = SYNTHESIS_PROMPT.format(
        conversation_history=_format_history(state),
        question=state.question,
        tool_result=state.tool_result or "",
    )
    response = await chat_llm.ainvoke(prompt)
    answer = response.content.strip()

    updated_history = state.history + [{
        "question": state.question,
        "response": answer,
    }]
    return {"response": answer, "history": updated_history}


# ── chitchat ──────────────────────────────────────────────────────────────────

async def chitchat(state: State) -> dict:
    prompt = CHITCHAT_PROMPT.format(
        conversation_history=_format_history(state),
        question=state.question,
    )
    response = await chat_llm.ainvoke(prompt)
    answer = response.content.strip()

    updated_history = state.history + [{
        "question": state.question,
        "response": answer,
    }]
    return {"response": answer, "history": updated_history}


# ── clarify ───────────────────────────────────────────────────────────────────

async def clarify(state: State) -> dict:
    unresolved    = state.unresolved_products
    available     = state.available_products
    clarification = state.clarification
    tool_params   = state.tool_params

    if clarification:
        answer = clarification
    elif unresolved:
        prompt = CLARIFY_PROMPT.format(
            question=state.question,
            unresolved=unresolved,
            available_products=[p["name"] for p in available],
        )
        response = await chat_llm.ainvoke(prompt)
        answer = response.content.strip()
    else:
        answer = (
            "I didn't quite catch that. You can tell me about a sale, restock, "
            "expense, debt, or ask what's in stock."
        )

    history_entry: dict = {
        "question": state.question,
        "response": answer,
        "partial_params": tool_params,
    }
    if unresolved:
        history_entry["unresolved_context"] = unresolved

    updated_history = state.history + [history_entry]
    return {"response": answer, "history": updated_history}


# ── SQL path ──────────────────────────────────────────────────────────────────

async def generate_sql(state: State) -> dict:
    retry_count   = state.retry_count or 0
    retry_context = ""
    if retry_count > 0:
        retry_context = (
            f"PREVIOUS ATTEMPT FAILED:\n"
            f"SQL: {state.sql}\n"
            f"ERROR: {state.sql_error}\n\n"
            f"Analyse the error and generate a corrected SQL query."
        )

    prompt = SQL_GENERATION_PROMPT.format(
        schema=SHOP_SCHEMA,
        conversation_history=_format_history(state),
        question=state.question,
        retry_context=retry_context,
    )
    response = await sql_llm.ainvoke(prompt)
    sql = response.content.strip().replace("```sql", "").replace("```", "").strip()
    logger.debug("Generated SQL: %s", sql)
    return {"sql": sql, "sql_error": ""}


async def validate_sql(state: State) -> dict:
    sql_upper = (state.sql or "").upper()

    if sql_upper.strip() == "NOT_A_DB_QUERY":
        return {"sql_validated": False, "sql_error": "not_a_db_query"}

    dangerous = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE"}
    if any(kw in sql_upper for kw in dangerous):
        return {
            "sql_validated": False,
            "sql_error": "Query contains mutating operations — only SELECT allowed.",
            "retry_count": (state.retry_count or 0) + 1,
        }

    if "SELECT" not in sql_upper:
        return {
            "sql_validated": False,
            "sql_error": "No SELECT statement found.",
            "retry_count": (state.retry_count or 0) + 1,
        }

    return {"sql_validated": True}


async def execute_sql(state: State) -> dict:
    from app.db.connection import engine

    async def _run():
        async with engine.connect() as conn:
            result = await conn.execute(text(state.sql))
            rows = [dict(row._mapping) for row in result.fetchall()]
            total = len(rows)
            truncated = total > 40
            return {
                "data": rows[:40] if truncated else rows,
                "row_count": total,
                "truncated": truncated,
            }

    try:
        result = await _run()
        logger.debug("SQL executed. %d rows returned.", result["row_count"])
        return {"sql_result": result}
    except Exception as exc:
        logger.warning("SQL execution failed: %s", exc)
        return {
            "sql_result": None,
            "sql_error": f"Execution failed: {exc}",
            "retry_count": (state.retry_count or 0) + 1,
        }


async def sql_synthesize(state: State) -> dict:
    result = state.sql_result or {}
    truncated_msg = (
        f"You're only seeing 40 of {result.get('row_count', '?')} records — mention that naturally."
        if result.get("truncated") else ""
    )

    prompt = SQL_SYNTHESIS_PROMPT.format(
        conversation_history=_format_history(state),
        question=state.question,
        sql=state.sql or "",
        results=result.get("data", []),
        truncated_message=truncated_msg,
    )
    response = await chat_llm.ainvoke(prompt)
    answer = response.content.strip()

    updated_history = state.history + [{
        "question": state.question,
        "response": answer,
    }]
    return {"response": answer, "history": updated_history}


# ── Routing ───────────────────────────────────────────────────────────────────

def route_classify(state: State) -> str:
    intent = state.intent
    if intent == "unclear":
        return "clarify"
    elif intent == "chitchat":
        return "chitchat"
    elif intent in _READ_INTENTS:
        return "generate_sql"
    return "dispatch_prep"  # write intents → list_products → resolve_products first


def route_resolve_products(state: State) -> str:
    """After resolving product names, go to clarify if any were unresolved."""
    if state.unresolved_products:
        return "clarify"
    return "dispatch"


def route_sql_validate(state: State) -> str:
    if state.sql_error == "not_a_db_query":
        return "chitchat"
    if state.sql_validated:
        return "execute_sql"
    if (state.retry_count or 0) < _MAX_SQL_RETRIES:
        return "generate_sql"
    return "end"


def route_sql_execute(state: State) -> str:
    if state.sql_result is not None:
        return "sql_synthesize"
    if (state.retry_count or 0) < _MAX_SQL_RETRIES:
        return "generate_sql"
    return "end"