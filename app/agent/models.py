from typing import Optional, Annotated
from langgraph.graph.message import add_messages
from pydantic import BaseModel


class State(BaseModel):
    # Conversation
    messages: Annotated[list, add_messages] = []
    question: str = ""
    history: list[dict] = []

    # Context injected before classify
    shop_id: str = ""
    trader_id: str = ""

    # Classify output
    intent: str = ""
    tool_params: dict = {}
    clarification: Optional[str] = None

    # Product resolution
    available_products: list[dict] = []
    resolved_products: dict = {}
    unresolved_products: list[str] = []

    # Tool execution
    tool_result: Optional[str] = None

    # SQL path
    sql: Optional[str] = None
    sql_result: Optional[dict] = None
    sql_validated: bool = False
    sql_error: Optional[str] = None
    retry_count: int = 0

    # Agent response
    response: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True