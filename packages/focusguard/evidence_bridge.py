"""Phase 2 evidence-persistence bridge (design 11.4 gap 3; approved R1 2026-11-17).

The draft four-state ActionResult carries inline FocusSnapshot before/after plus a
dict of interference evidence, while the frozen MCP envelope references evidence as
a list of store snapshot ids. This bridge persists the focus snapshots + evidence
into the EventStore as append-only snapshots and injects their ids into the R2a
extended envelope, closing the dict-vs-id-list mismatch WITHOUT modifying the frozen
store/schema/semantic.element. Snapshots are append-only (sql.md), so copying the
focus summary into a snapshot is safe and auditable.
"""

from __future__ import annotations

from dataclasses import asdict

from .extended_envelope import ExtendedEnvelope, to_extended_envelope
from .outcome import ActionResult


def persist_focus_evidence(result: ActionResult, window_id: str, store):
    """Persist before/after FocusSnapshot + interference evidence; return ids.

    Returns (before_id, after_id, all_ids); a missing snapshot yields None for its
    slot and contributes no id, so callers never mislabel an after-only snapshot.
    """
    before_id = after_id = None
    ids: list[str] = []
    for label, snap in (("before", result.focus_before), ("after", result.focus_after)):
        if snap is None:
            continue
        summary = {
            "label": label,
            "focus": asdict(snap),
            "state": result.state.value,
            "risk": result.risk.value,
            "channel": result.channel.value,
            "unexpected_focus_switch": result.unexpected_focus_switch,
            "evidence": result.evidence,
        }
        sid = store.add_snapshot(window_id, summary)
        ids.append(sid)
        if label == "before":
            before_id = sid
        else:
            after_id = sid
    return before_id, after_id, ids


def to_api_envelope(result: ActionResult, window_id: str, store) -> ExtendedEnvelope:
    """Persist evidence and build the api.md extended envelope with ids injected."""
    before_id, after_id, ids = persist_focus_evidence(result, window_id, store)
    return to_extended_envelope(result, before_id, after_id, ids)