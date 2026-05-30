from dotenv import load_dotenv
load_dotenv()

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import webhook, health
from app.db.connection import init_db
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Ventory",
    description="AI-powered inventory assistant for Nigerian shop owners — via WhatsApp.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(health.router)


@app.on_event("startup")
async def startup():
    await init_db()
    start_scheduler()
    logger.info("Ventory started.")