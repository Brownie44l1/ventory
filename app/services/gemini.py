"""
Gemini service layer.

- parse_text: converts natural language (any Nigerian language) to structured transactions
- transcribe_and_parse: audio → structured transactions
- answer_query: RAG-style answering with shop data as context
"""

import json
import logging
import os
import re
from google import genai
from google.genai import types

from app.schemas.transaction import ParsedTransaction

logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

PARSE_PROMPT = """
You are a financial assistant for Nigerian traders.
The trader may speak English, Pidgin, Yoruba, Hausa, or Igbo.

Extract ONE OR MORE transactions from the input.
Return ONLY a JSON array. No explanation. No markdown.

Each object in the array:
{
  "type": "sale" | "expense" | "purchase" | "restock" | "debt_owed" | "debt_received",
  "amount": number,
  "item": string | null,
  "quantity": number | null,
  "unit": string | null,
  "counterparty": string | null,
  "note": "full transcript of what was said"
}

Definitions:
- "sale":          Trader sold something to a customer.
- "expense":       General business costs (rent, transport, fuel, etc.) NOT buying goods to resell.
- "purchase" / "restock": Trader bought goods to add to stock for resale.
- "debt_owed":     Customer took goods but has not paid yet.
- "debt_received": Customer paid back money they previously owed.

Amount parsing:
- "1500", "1.5k", "1,500" → 1500
- "50k" → 50000
- "2 bags of rice for 80,000" → amount=80000, item="rice", quantity=2, unit="bags"

Examples:
- "I sell garri 2 mudu 1500"
  → [{"type":"sale","amount":1500,"item":"garri","quantity":2,"unit":"mudu","note":"..."}]
- "I buy 10 bags of cement for 80k"
  → [{"type":"purchase","amount":80000,"item":"cement","quantity":10,"unit":"bags","note":"..."}]
- "I buy fuel 2000 for generator"
  → [{"type":"expense","amount":2000,"item":"fuel","note":"..."}]
- "Emeka collect goods 3000, e no pay"
  → [{"type":"debt_owed","amount":3000,"counterparty":"Emeka","note":"..."}]
- "Emeka pay me 1500"
  → [{"type":"debt_received","amount":1500,"counterparty":"Emeka","note":"..."}]
"""


def _extract_transactions(text: str) -> list[ParsedTransaction]:
    text = text.strip()
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block:
        text = code_block.group(1).strip()

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        valid = []
        for item in data:
            try:
                valid.append(ParsedTransaction(**item))
            except Exception as e:
                logger.warning("Invalid transaction item: %s", e)
        return valid
    except json.JSONDecodeError:
        logger.warning("Failed to parse Gemini response: %s", text[:200])
        return []


async def parse_text(text: str) -> list[ParsedTransaction]:
    prompt = PARSE_PROMPT + f"\nInput: {text}"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return _extract_transactions(response.text)


async def transcribe_and_parse(audio_bytes: bytes, mime_type: str) -> list[ParsedTransaction]:
    prompt = PARSE_PROMPT + "\nTranscribe and extract transactions:"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            prompt,
        ],
    )
    return _extract_transactions(response.text)


async def answer_query(trader_data: dict, question: str) -> str:
    """
    RAG-style: pass shop data + question to Gemini for a natural language answer.
    Used for keyword-detected queries that don't go through the LangGraph agent.
    """
    prompt = f"""
You are Ventory, a helpful business advisor for a Nigerian shop owner.
Reply in the same language the trader used. Keep it concise and use WhatsApp-friendly formatting.
Never use em-dashes. Format amounts as ₦.

Trader data:
{json.dumps(trader_data, default=str)}

Question: {question}
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text.strip()