"""Composition root for the local control plane.

Nothing here touches a real desktop: channel, resolver and locator registry are injected so the
fixture-backed tests drive the whole state machine before gate G1 (docs/team-plan.md §3). At G1 the
S1 `perception.cdp` channel and `semantic.resolver` are passed in unchanged.
"""

import dataclasses

from adapters.trae.adapter import TraeAdapter
from adapters.trae.states import build_verifiers
from events.store import EventStore
from execution.actions import ActionExecutor
from execution.safety import SafetyGate


class ChannelSnapshotter:
    def __init__(self, channel, store: EventStore):
        self.channel = channel
        self.store = store

    def capture(self, window_id: str) -> dict:
        identity = self.channel.window_identity(window_id)
        self.store.register_window(window_id, identity.get("process_name", ""), identity.get("title", ""),
                                   identity.get("geometry", {}))
        elements = self.channel.scan(window_id)
        image_path = self.channel.screenshot(window_id)
        snapshot_id = self.store.add_snapshot(window_id, elements, image_path)
        return {"snapshot_id": snapshot_id, "image_path": image_path, "elements": elements}


class ControlPlane:
    """Implements the frozen `mcp.server.Engine` surface over adapter + executor + store."""

    def __init__(self, channel, resolver, registry, store: EventStore, window_id: str,
                 allowed_windows: set[str] | None = None, windows_provider=None,
                 app_version: str = "3.6.13", status_timeout: float = 300.0):
        self.channel = channel
        self.resolver = resolver
        self.registry = registry
        self.store = store
        self.window_id = window_id
        self.windows_provider = windows_provider
        self.safety = SafetyGate(allowed_windows or {window_id}, store)
        self.snapshots = ChannelSnapshotter(channel, store)
        self.executor = ActionExecutor(resolver, channel, self.safety, store, self.snapshots,
                                       build_verifiers(channel, window_id, registry))
        self.adapter = TraeAdapter(window_id, channel, self.executor, store, registry, app_version,
                                   status_timeout)

    # Engine surface

    def list_windows(self) -> list[dict]:
        if self.windows_provider:
            for observed in self.windows_provider():
                self.store.register_window(observed["window_id"], observed.get("process_name", ""),
                                           observed.get("title", ""), observed.get("geometry", {}))
        self.safety.allowed_windows = {w["window_id"] for w in self.store.list_windows(True)}
        return self.store.list_windows(True)

    def inspect_window(self, window_id: str, max_depth: int = 18) -> list[dict]:
        self.safety.check_window(window_id)
        return self.channel.scan(window_id, max_depth)

    def find_element(self, window_id: str, **criteria) -> list[dict]:
        self.safety.check_window(window_id)
        semantic_id = criteria.get("semantic_id")
        if semantic_id:
            try:
                return [dataclasses.asdict(self.resolver.resolve(window_id, semantic_id))]
            except Exception:
                return []
        role, name = criteria.get("role"), criteria.get("name")
        return [e for e in self.channel.scan(window_id)
                if (not role or e.get("role") == role) and (not name or name in e.get("name", ""))]

    def perform_action(self, window_id: str, semantic_id: str, action: str,
                       args: dict | None = None, approval_token: str | None = None) -> dict:
        return dataclasses.asdict(
            self.executor.perform(window_id, semantic_id, action, args, approval_token))

    def get_snapshot(self, window_id: str) -> dict:
        self.safety.check_window(window_id)
        captured = self.snapshots.capture(window_id)
        elements = captured["elements"]
        return {"snapshot_id": captured["snapshot_id"], "image_path": captured["image_path"],
                "ts": self.store.get_snapshot(captured["snapshot_id"])["ts"], "window_id": window_id,
                "elements_summary": {"count": len(elements),
                                     "roles": sorted({e.get("role", "") for e in elements if e.get("role")})}}

    def send_task(self, project_path: str, task: str, **opts) -> dict:
        return dataclasses.asdict(self.adapter.send_task(project_path, task, **opts))

    def get_status(self, task_id: str) -> dict:
        rec = self.adapter.get_status(task_id)
        return {"task_id": rec.task_id, "app": rec.app, "state": rec.state,
                "signals": self.adapter.last_signals(task_id),
                "transitions": rec.transitions,
                "evidence": [t["evidence_id"] for t in rec.transitions if t["evidence_id"]]}

    def read_result(self, task_id: str, max_chars: int = 8000) -> dict:
        return self.adapter.read_result(task_id, max_chars)

    # control-plane extras (REST surface)

    def allow_window(self, window_id: str) -> None:
        self.store.set_whitelisted(window_id, True)
        self.safety.allow(window_id)

    def tasks(self) -> list[dict]:
        return self.store.list_tasks()

    def task(self, task_id: str) -> dict | None:
        return self.store.get_task(task_id)

    def locators(self) -> list[dict]:
        rows = self.store.list_locators(app="trae")
        if rows:
            return rows
        return [{"semantic_id": sid, "app": "trae", "app_version": locator.app_version,
                 "chain": locator.chain, "verification": locator.verification, "healed_at": locator.healed_at}
                for sid, locator in sorted(self.registry.items())]

    def grant_approval(self, scope: dict, granted_by: str = "user", request_id: str | None = None) -> str:
        return self.store.grant_approval(scope, granted_by=granted_by, request_id=request_id)
