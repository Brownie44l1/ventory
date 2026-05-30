import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

_GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GEMINI_MODEL = "gemini-2.5-flash"

# General-purpose LLM (chitchat, synthesis, clarification) — slight creativity
chat_llm = ChatOpenAI(
    temperature=0.5,
    model=_GEMINI_MODEL,
    api_key=_GEMINI_API_KEY,
    base_url=_GEMINI_BASE_URL,
)

# Deterministic LLM for SQL generation — reduces hallucinated SQL and retry loops
sql_llm = ChatOpenAI(
    temperature=0,
    model=_GEMINI_MODEL,
    api_key=_GEMINI_API_KEY,
    base_url=_GEMINI_BASE_URL,
)