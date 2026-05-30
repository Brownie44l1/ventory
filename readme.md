# Ventory

An AI-powered inventory and sales assistant for Nigerian shop owners — via WhatsApp.

Speak or type in **English, Pidgin, Yoruba, Hausa, or Igbo**. Ventory records sales, restocks, expenses, and debts, tracks your stock, and answers business questions in real time.

**Stack:** FastAPI · SQLAlchemy (async, PostgreSQL) · Alembic · Google Gemini · LangGraph · WhatsApp Cloud API · APScheduler · Docker · uv

---

## What makes Ventory different

| Feature | Detail |
|---|---|
| Smart agent | LangGraph graph: classifies intent → SQL read path or tool dispatch path |
| Rich data model | Per-unit pricing, sale snapshots, restock cost tracking, gross profit |
| Debt tracking | Records what customers owe and marks debts settled when paid |
| Multi-shop | One phone number, multiple businesses |
| Onboarding flow | Guided first-time setup (name, business name, type) |
| Daily summaries | Proactive push at a time you set, per shop |
| Export | Download transactions as CSV or PDF via WhatsApp |
| Decimal precision | All financials use `Decimal`, never floats |

---

## Setup

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

cd ventory
uv sync

cp .env.example .env
# Edit .env with your keys

# Run migrations
alembic upgrade head

# Start
uv run uvicorn main:app --reload
```

> Requires Python 3.11+ and a running PostgreSQL instance.

---

## Environment Variables

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/ventory
GEMINI_API_KEY=...
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_ID=...
WHATSAPP_VERIFY_TOKEN=...
```

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/webhook` | WhatsApp verification |
| POST | `/webhook` | Incoming messages |
| GET | `/health` | Liveness probe |

---

## Project structure

```
ventory/
├── main.py                  → FastAPI entry point, router + scheduler startup
├── pyproject.toml           → Dependencies (uv)
├── Dockerfile
├── app/
│   ├── agent/
│   │   ├── config.py        → LLM clients (Gemini via OpenAI-compat)
│   │   ├── graph.py         → LangGraph workflow
│   │   ├── nodes.py         → Node implementations (classify, dispatch, SQL…)
│   │   ├── prompts.py       → All prompts
│   │   ├── schema.py        → DB schema string for SQL generation
│   │   ├── models.py        → LangGraph State
│   │   ├── tools.py         → LangChain tools (log_sale, restock, …)
│   │   └── utils.py         → Product list/resolve helpers
│   ├── db/
│   │   ├── connection.py    → Async engine + session
│   │   ├── models.py        → ORM: Trader, Shop, Product, Sale, Debt, …
│   │   └── queries.py       → Data access layer
│   ├── routers/
│   │   ├── webhook.py       → WhatsApp webhook + onboarding state machine
│   │   └── health.py        → /health
│   ├── schemas/
│   │   └── transaction.py   → Pydantic models
│   └── services/
│       ├── gemini.py        → Gemini: parse, transcribe, answer_query
│       ├── whatsapp.py      → Send/download/upload WhatsApp media
│       ├── scheduler.py     → Daily summary push (APScheduler)
│       └── exports.py       → CSV / PDF export
├── migrations/              → Alembic
└── tests/
    └── test_logic.py
```