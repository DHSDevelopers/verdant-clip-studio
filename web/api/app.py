"""Verdant Clip Studio — FastAPI application.

Run:
    uvicorn web.api.app:app --host 0.0.0.0 --port 8000
The UI is served from web/frontend at /.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import worker
from .logging_middleware import RequestLoggingMiddleware
from .routes import files, jobs, settings

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Verdant Clip Studio — backend starting...")
    try:
        yield
    finally:
        try:
            await worker.cancel_all_jobs()
        finally:
            print("Backend shutting down...")


app = FastAPI(
    title="Verdant Clip Studio",
    description="AI auto-clipper and teaser generator — web API",
    version="1.16.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings.router)


@app.get("/api")
async def api_root():
    return {
        "name": "Verdant Clip Studio",
        "version": "1.16.0",
        "docs": "/docs",
        "health": "/api/health",
        "ready": "/api/ready",
    }


if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.svg")
    async def favicon():
        candidate = FRONTEND_DIR / "favicon.svg"
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/svg+xml")
        return FileResponse(FRONTEND_DIR / "index.html")
