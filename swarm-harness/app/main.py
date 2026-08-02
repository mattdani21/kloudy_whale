# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

@app.get("/v1/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
