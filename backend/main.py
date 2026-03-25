from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes_config import router as config_router
from backend.api.routes_dashboard import router as dashboard_router
from backend.api.routes_fetch import router as fetch_router
from backend.api.routes_rules import router as rules_router
from backend.api.routes_schedule import router as schedule_router
from backend.api.routes_tickets import router as tickets_router
from backend.api.routes_violations import router as violations_router
from backend.services.scheduler_service import load_schedule_from_db
from backend.services.scheduler_service import shutdown as shutdown_scheduler
from backend.storage.db import init_db


init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: restore any saved schedule from DB
    load_schedule_from_db()
    yield
    # Shutdown: stop background scheduler cleanly
    shutdown_scheduler()


app = FastAPI(title="ITGC SOX Compliance Monitoring Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "itgc-sox-agent",
        "status": "ok",
        "api_health": "/api/health",
        "docs": "/docs",
        "ui_dev_server": "http://127.0.0.1:5173",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return JSONResponse(status_code=204, content=None)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "itgc-sox-agent"}


app.include_router(config_router)
app.include_router(fetch_router)
app.include_router(dashboard_router)
app.include_router(violations_router)
app.include_router(tickets_router)
app.include_router(rules_router)
app.include_router(schedule_router)
