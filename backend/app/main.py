import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, SessionLocal, engine
from .routers import approvals, candidates, copilot, interviews, jobs, offers, system
from .seed import seed

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    if settings.seed_demo_data:
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(title="AI-Powered Recruitment Assistance Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
for r in (system.router, jobs.router, candidates.router, approvals.router, interviews.router, offers.router, copilot.router):
    app.include_router(r)
