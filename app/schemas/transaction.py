from decimal import Decimal
from typing import Optional, Literal
from pydantic import BaseModel, Field


class ParsedTransaction(BaseModel):
    """
    Output of Gemini's parse_text / transcribe_and_parse.
    Represents a single transaction extracted from natural language.
    """
    type: Literal["sale", "expense", "purchase", "restock", "debt_owed", "debt_received"]
    amount: Decimal = Field(default=Decimal("0"))
    item: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    counterparty: Optional[str] = None
    note: Optional[str] = None


class ParsedTransactionList(BaseModel):
    transactions: list[ParsedTransaction]