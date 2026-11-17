"""Local control plane: managed launch, approvals, event stream (api.md §2)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

from engine import GUIBridgeEngine  # noqa: E402
from events.store import EventStore  # noqa: E402

CODE_STATUS = {
    "approval_required": 403, "window_not_allowed": 403,
    "conflict": 409, "identity_mismatch": 409, "locator_missing": 409, "not_submitted": 409,
    "unknown_state": 424,
}


class TaskIn(BaseModel):
    project_path: str
    task: str
    mode: Literal["chat", "agent"] = "chat"
    allow_files: list[str] | None = None
    acceptance: dict | None = None


class ApprovalIn(BaseModel):
    semantic_id: str | None = None
    action: str | None = None
    ttl_seconds: int = 600
    granted_by: str = "local-user"


class HealReviewIn(BaseModel):
    patch_id: str
    action: Literal["approve", "reject"]
    reviewed_by: str = "local-user"


def create_app(engine: GUIBridgeEngine | None = None) -> FastAPI:
    if engine is None:
        store = EventStore(str(ROOT / "var" / "guibridge.db"))
        engine = GUIBridgeEngine(store=store)
    app = FastAPI(title="GUIBridge Desktop Agent")
    app.state.engine = engine

    @app.exception_handler(Exception)
    async def error_envelope(request: Request, exc: Exception):
        code = getattr(exc, "code", "unknown_state")
        return JSONResponse({"error_code": code, "message": str(exc), "evidence": []},
                            status_code=CODE_STATUS.get(code, 500))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "stage": "s2",
                "whitelisted_windows": sorted(engine.allowed_windows)}

    @app.get("/windows")
    def windows() -> dict:
        return {"windows": engine.list_windows()}

    @app.post("/windows/{window_id}/whitelist")
    def whitelist(window_id: str) -> dict:
        return engine.allow_window(window_id)

    @app.get("/windows/{window_id}/snapshot")
    def snapshot(window_id: str) -> dict:
        return engine.get_snapshot(window_id)

    @app.get("/tasks")
    def tasks() -> dict:
        return {"tasks": engine.store.list_tasks()}

    @app.post("/tasks")
    def create_task(body: TaskIn) -> dict:
        return engine.send_task(body.project_path, body.task, body.mode,
                                body.allow_files, body.acceptance)

    @app.get("/tasks/{task_id}")
    def task(task_id: str) -> dict:
        record = engine.store.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="task not found")
        return record

    @app.get("/tasks/{task_id}/result")
    def task_result(task_id: str, max_chars: int = 8000) -> dict:
        return engine.read_result(task_id, max_chars)

    @app.get("/approvals/pending")
    def approvals_pending() -> dict:
        return {"approvals": engine.store.pending_approvals()}

    @app.post("/approvals")
    def grant_approval(body: ApprovalIn) -> dict:
        scope = {"semantic_id": body.semantic_id, "action": body.action}
        return engine.store.create_approval(scope, body.granted_by, body.ttl_seconds)

    @app.get("/locators")
    def locators() -> dict:
        return {"locators": engine.list_locators()}

    @app.post("/locators/{semantic_id}/heal-review")
    def heal_review(semantic_id: str, body: HealReviewIn) -> dict:
        status = "approved" if body.action == "approve" else "rejected"
        engine.store.review_heal_patch(body.patch_id, status, body.reviewed_by)
        return {"patch_id": body.patch_id, "semantic_id": semantic_id, "status": status}

    @app.get("/events")
    def events(request: Request, last_event_id: str | None = None):
        start = last_event_id or request.headers.get("last-event-id")

        def stream():
            cursor = start
            while True:
                batch = engine.store.events_after(cursor, 100)
                for event in batch:
                    cursor = event["event_id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                time.sleep(1.0)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


app = create_app()
