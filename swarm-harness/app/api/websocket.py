# app/api/websocket.py
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.models import BuildState
from app.persistence import RedisStore
from app.config import CONFIG

router = APIRouter()
store = RedisStore()

TERMINAL_STATES = {BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED}

@router.websocket("/v1/build/{build_id}/stream")
async def stream_build(websocket: WebSocket, build_id: str, api_key: str = ""):
    if api_key not in CONFIG.API_KEYS:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            build = await store.load(build_id)
            if not build:
                await websocket.send_json({"error": "Build not found"})
                await websocket.close(code=4404)
                return
            await websocket.send_json({
                "build_id": build.id,
                "state": build.state.value,
                "token_usage": build.token_usage,
                "steps_done": sum(1 for s in build.steps if s.completed_at),
                "steps_total": len(build.steps),
                "needs_human": build.state == BuildState.WAITING_HUMAN,
                "human_question": build.human_input_queue[-1] if build.human_input_queue else None,
                "final_output": build.final_output if build.state in TERMINAL_STATES else None,
            })
            if build.state in TERMINAL_STATES:
                await websocket.close()
                return
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
            await websocket.close(code=1011)
        except Exception:
            pass
