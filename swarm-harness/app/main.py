# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from app.api import builds, websocket

app = FastAPI(title="Swarm Agent Harness", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(builds.router)
app.include_router(websocket.router)

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/landing", include_in_schema=False)
async def landing():
    return FileResponse(STATIC_DIR / "landing.html")

@app.get("/v1/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
