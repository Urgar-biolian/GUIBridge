"""Local control plane (127.0.0.1 only): managed launch, approvals, event stream, MCP entry.

Endpoints follow docs/api.md §2. Before gate G1 the plane runs against `simulated.SimulatedTrae`;
`--live` wires the S1 CDP channel + resolver in instead and refuses to start if they are absent.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from events.store import EventStore

STATUS_BY_CODE = {"approval_required": 403, "window_not_allowed": 403, "conflict": 409,
                  "identity_mismatch": 409, "locator_missing": 404, "not_submitted": 502,
                  "unknown_state": 424}
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "trae" / "dom_ide_idle.json"


def _failure(exc: Exception) -> JSONResponse:
    code = getattr(exc, "code", "unknown_state")
    return JSONResponse(status_code=STATUS_BY_CODE.get(code, 500),
                        content={"error_code": code, "message": str(exc), "evidence": []})


def _invalid(message: str) -> JSONResponse:
    """A malformed body is rejected before anything reaches the desktop: it has no MCP error code."""
    return JSONResponse(status_code=422, content={"error_code": "invalid_request",
                                                   "message": message, "evidence": []})


def build_plane(mode: str, db_path: str = ":memory:", fixture: str | Path = DEFAULT_FIXTURE,
                window_id: str | None = None, status_timeout: float = 300.0):
    from registry import load_registry
    registry, meta = load_registry()
    store = EventStore(db_path)
    if mode == "live":
        raise SystemExit("live mode needs the S1 CDP channel + resolver (gate G1); nothing is faked here")
    from simulated import RegistryResolver, SimulatedTrae
    channel = SimulatedTrae(json.loads(Path(fixture).read_text(encoding="utf-8")))
    wid = window_id or channel.window["window_id"]
    from engine import ControlPlane
    plane = ControlPlane(channel, RegistryResolver(channel, registry, wid), registry, store, wid,
                         app_version=meta["app_version"], status_timeout=status_timeout)
    for semantic_id, locator in registry.items():
        store.save_locator(semantic_id, meta["app"], meta["app_version"], locator.chain, locator.verification)
    store.register_window(wid, channel.window["process_name"], channel.window["title"], channel.window["geometry"],
                          whitelisted=True)
    return plane


def create_app(plane, store: EventStore) -> FastAPI:
    app = FastAPI(title="GUIBridge Desktop Agent")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "stage": "s2", "window_id": plane.window_id, "channel": plane.channel.name}

    @app.get("/windows")
    def windows(all: bool = False) -> dict:
        return {"windows": plane.store.list_windows() if all else plane.list_windows()}

    @app.post("/windows/{window_id}/whitelist")
    def whitelist(window_id: str) -> JSONResponse:
        try:
            plane.allow_window(window_id)
        except KeyError:
            return JSONResponse(status_code=403, content={"error_code": "window_not_allowed",
                                                           "message": f"window {window_id} is not known",
                                                           "evidence": []})
        except Exception as exc:
            return _failure(exc)
        return JSONResponse({"window_id": window_id, "whitelisted": True})

    @app.get("/windows/{window_id}/snapshot")
    def snapshot(window_id: str):
        try:
            return plane.get_snapshot(window_id)
        except Exception as exc:
            return _failure(exc)

    @app.get("/tasks")
    def tasks() -> dict:
        return {"tasks": plane.tasks()}

    @app.post("/tasks")
    def create_task(body: dict):
        required = {"project_path", "task"}
        if missing := sorted(required - body.keys()):
            return _invalid(f"missing field {missing[0]!r}")
        try:
            return plane.send_task(body["project_path"], body["task"], mode=body.get("mode", "chat"),
                                   allow_files=body.get("allow_files"), acceptance=body.get("acceptance"),
                                   approval_token=body.get("approval_token"),
                                   allow_auto_approval=body.get("allow_auto_approval", False))
        except Exception as exc:
            return _failure(exc)

    @app.get("/tasks/{task_id}")
    def task_status(task_id: str):
        try:
            return plane.get_status(task_id)
        except Exception as exc:
            return _failure(exc)

    @app.get("/tasks/{task_id}/result")
    def task_result(task_id: str, max_chars: int = 8000):
        try:
            return plane.read_result(task_id, max_chars)
        except Exception as exc:
            return _failure(exc)

    @app.get("/approvals/pending")
    def pending_approvals() -> dict:
        return {"requests": store.pending_approvals()}

    @app.post("/approvals")
    def grant_approval(body: dict):
        """Grant either shape: the Dashboard's `{scope: {...}}` or a flat `{semantic_id, action}`.

        A scope that names no window would validate a click in any window, so the plane pins it to
        its own (docs/security.md); an empty scope is refused before it can be minted.
        """
        scope = dict(body.get("scope") or {})
        for key in ("semantic_ids", "actions", "semantic_id", "action"):
            if key not in scope and key in body:
                scope[key] = body[key]
        if not set(scope) & {"semantic_ids", "actions", "semantic_id", "action"}:
            return _invalid("missing field 'scope'")
        scope.setdefault("window_id", plane.window_id)
        ttl = int(scope.pop("ttl_seconds", None) or body.get("ttl_seconds") or 600)
        token = plane.grant_approval(scope, body.get("granted_by", "user"), body.get("request_id"), ttl)
        store.record("approval_issued", {"scope": scope, "request_id": body.get("request_id")},
                     window_id=scope.get("window_id"))
        return JSONResponse({"token": token, "scope": scope})

    @app.get("/events")
    async def events(request: Request, limit: int = 200, last_event_id: str | None = None):
        anchor = last_event_id or request.headers.get("last-event-id")
        # The published `id:` is an event id, not a row number, so a resuming client — including the
        # Dashboard's EventSource, which echoes that header back by itself — is looked up before it
        # can be used as a cursor. An unknown id replays the log rather than dropping events silently.
        cursor = (store.get_event(anchor) or {}).get("seq", 0) if anchor else 0

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                for event in store.events(after_seq=cursor, limit=limit):
                    cursor = event["seq"]
                    yield f"id: {event['event_id']}\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/locators")
    def locators() -> dict:
        return {"locators": plane.locators(), "heal_patches": store.list_heal_patches()}

    @app.post("/locators/{semantic_id}/heal-review")
    def heal_review(semantic_id: str, body: dict):
        patch_id, decision = body.get("patch_id"), body.get("decision")
        if not patch_id:
            return _invalid("missing field 'patch_id'")
        if decision not in ("approved", "rejected"):
            return _invalid("decision must be 'approved' or 'rejected'")
        try:
            return store.review_heal_patch(patch_id, decision, body.get("reviewed_by", "user"))
        except KeyError:
            return JSONResponse(status_code=404, content={"error_code": "locator_missing",
                                                           "message": f"no such heal patch: {patch_id}",
                                                           "evidence": []})
        except PermissionError as exc:
            return JSONResponse(status_code=409, content={"error_code": "conflict",
                                                           "message": str(exc), "evidence": []})
        except Exception as exc:
            return _failure(exc)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="GUIBridge desktop control plane")
    parser.add_argument("--mode", choices=("simulated", "live"), default="simulated")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--db", default=str(ROOT / "guibridge.sqlite3"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--mcp", action="store_true", help="serve the 8 MCP tools over stdio instead of REST")
    cli = parser.parse_args()
    if cli.host != "127.0.0.1":
        raise SystemExit("the control plane binds to loopback only (docs/security.md)")

    plane = build_plane(cli.mode, cli.db, cli.fixture)
    if cli.mcp:
        from mcp.server import serve
        serve(plane, plane.store)
        return
    import uvicorn
    uvicorn.run(create_app(plane, plane.store), host=cli.host, port=cli.port)


def _default_app():
    """`uvicorn main:app` entry (README quick start); override with GUIBRIDGE_MODE / GUIBRIDGE_DB."""
    plane = build_plane(os.environ.get("GUIBRIDGE_MODE", "simulated"),
                        os.environ.get("GUIBRIDGE_DB", ":memory:"))
    return create_app(plane, plane.store)


def __getattr__(name: str):
    if name == "app":
        return _default_app()
    raise AttributeError(name)


if __name__ == "__main__":
    main()
