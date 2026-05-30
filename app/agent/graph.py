from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.models import State
from app.agent.nodes import (
    chitchat, clarify, classify, dispatch, route_classify, synthesize,
    generate_sql, validate_sql, execute_sql, sql_synthesize,
    route_sql_validate, route_sql_execute,
)
from app.agent.utils import list_products, resolve_products


def build_graph() -> CompiledStateGraph:
    workflow = StateGraph(State)

    # Core nodes
    workflow.add_node("classify",        classify)
    workflow.add_node("list_products",   list_products)
    workflow.add_node("resolve_products", resolve_products)
    workflow.add_node("dispatch",        dispatch)
    workflow.add_node("synthesize",      synthesize)
    workflow.add_node("chitchat",        chitchat)
    workflow.add_node("clarify",         clarify)

    # SQL path nodes
    workflow.add_node("generate_sql",   generate_sql)
    workflow.add_node("validate_sql",   validate_sql)
    workflow.add_node("execute_sql",    execute_sql)
    workflow.add_node("sql_synthesize", sql_synthesize)

    workflow.set_entry_point("classify")

    # Routing from classify
    workflow.add_conditional_edges("classify", route_classify, {
        "dispatch_prep": "list_products",
        "generate_sql":  "generate_sql",
        "chitchat":      "chitchat",
        "clarify":       "clarify",
    })

    # Write path
    workflow.add_edge("list_products",    "resolve_products")
    workflow.add_edge("resolve_products", "dispatch")
    workflow.add_edge("dispatch",         "synthesize")
    workflow.add_edge("synthesize",       END)

    # SQL path
    workflow.add_conditional_edges("generate_sql",  lambda _: "validate_sql")
    workflow.add_conditional_edges("validate_sql",  route_sql_validate, {
        "execute_sql":  "execute_sql",
        "generate_sql": "generate_sql",
        "chitchat":     "chitchat",
        "end":          END,
    })
    workflow.add_conditional_edges("execute_sql",   route_sql_execute, {
        "sql_synthesize": "sql_synthesize",
        "generate_sql":   "generate_sql",
        "end":            END,
    })
    workflow.add_edge("sql_synthesize", END)

    # Conversations
    workflow.add_edge("chitchat", END)
    workflow.add_edge("clarify",  END)

    return workflow.compile()