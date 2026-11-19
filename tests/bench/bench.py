"""Fixture-driven A/B/C benchmark harness (reproducible, no live Trae required).

A: recorded coordinates only (no semantic re-resolution).
B: semantic selector resolution, no post-state verification.
C: semantic resolution + post-state verification (GUIBridge discipline).

Scenarios simulate viewport translation/scale by transforming recorded DOM rects.
This is a deterministic model of the pipeline, not a live vision-model run; the
limitation is recorded in docs/benchmark.md. Raw per-run results are written to
tests/bench/results/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

FIXTURES = ROOT / "tests" / "fixtures"
SCENARIOS = ["send_message", "click_send", "switch_mode", "select_model",
             "new_session", "window_move", "window_resize"]
ITERATIONS = 10

# selector -> must be enabled to be actionable
TARGETS = {
    "send_message": (".chat-input-v2-input-box-editable", False),
    "click_send": (".chat-input-v2-send-button", True),
    "switch_mode": (".permissionModeTrigger", True),
    "select_model": (".icd-model-select-trigger", True),
    "new_session": (".action-label", True),
    "window_move": (".chat-input-v2-input-box-editable", False),
    "window_resize": (".chat-input-v2-input-box-editable", False),
}


def load_dom() -> list[dict]:
    raw = json.loads((FIXTURES / "trae_dom_sample.json").read_text(encoding="utf-8"))
    return raw["raws"] if isinstance(raw, dict) else raw


def is_disabled(raw: dict) -> bool:
    return bool(raw.get("disabled")) or "disabled" in str(raw.get("cls", "")).split()


def transform(raws: list[dict], scenario: str, i: int) -> list[dict]:
    out = []
    for r in raws:
        r = dict(r)
        x1, y1, x2, y2 = r["rect"]
        if scenario in ("window_move", "send_message") and i % 3 == 1:
            r["rect"] = [x1 + 80, y1 + 40, x2 + 80, y2 + 40]
        elif scenario == "window_resize" and i % 3 == 2:
            r["rect"] = [int(x1 * 1.25), int(y1 * 1.25), int(x2 * 1.25), int(y2 * 1.25)]
        out.append(r)
    return out


def locate_semantic(raws: list[dict], selector: str) -> dict | None:
    cls = selector.lstrip(".")
    for r in raws:
        tokens = str(r.get("cls", "")).split()
        if any(t == cls or t.startswith(cls + "-") for t in tokens):
            return r
        if r.get("id") == selector.lstrip("#"):
            return r
    return None


def point_in(raw: dict, x: float, y: float) -> bool:
    x1, y1, x2, y2 = raw["rect"]
    return x1 <= x <= x2 and y1 <= y <= y2


def run(iterations: int = ITERATIONS) -> dict:
    base = load_dom()
    results = []
    for scenario in SCENARIOS:
        selector, requires_enabled = TARGETS[scenario]
        recorded = locate_semantic(base, selector)
        assert recorded is not None, selector
        rx = (recorded["rect"][0] + recorded["rect"][2]) / 2
        ry = (recorded["rect"][1] + recorded["rect"][3]) / 2
        for i in range(iterations):
            raws = transform(base, scenario, i)
            truth = locate_semantic(raws, selector)

            # A: blind replay of recorded coordinates
            a_hit = bool(truth) and point_in(truth, rx, ry)
            a = {"success": a_hit, "failure": None if a_hit else "misclick_out_of_bounds",
                 "model_calls": 1, "misclick": 0 if a_hit else 1}

            # B: semantic resolve, no verification (clicks disabled targets too)
            b_hit = truth is not None
            b = {"success": b_hit, "failure": None if b_hit else "locator_missing",
                 "model_calls": 0, "misclick": 0}

            # C: semantic resolve + post-state verification; scripted drift on last iteration
            drift = i == iterations - 1 and scenario in ("switch_mode", "select_model")
            actionable = bool(truth) and not (requires_enabled and is_disabled(truth))
            c_hit = actionable and not drift
            c = {"success": c_hit,
                 "failure": None if c_hit else ("locator_missing" if not truth or drift
                                                else "unverified_state"),
                 "model_calls": 0, "misclick": 0}

            for group, row in (("A", a), ("B", b), ("C", c)):
                results.append({"scenario": scenario, "iteration": i, "group": group,
                                "model_calls": row["model_calls"],
                                "misclick": row["misclick"], "success": row["success"],
                                "failure": row["failure"]})
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "iterations": iterations,
        "mode": "fixture-simulation",
        "results": results,
    }


def summarize(run_data: dict) -> str:
    lines = ["| 场景 | 组 | 次数 | 成功 | 成功率 | 误点击 | 模型调用次数 | 失败类型 |",
             "|------|----|------|------|--------|--------|--------------|----------|"]
    rows = run_data["results"]
    for scenario in SCENARIOS:
        for group in ("A", "B", "C"):
            subset = [r for r in rows if r["scenario"] == scenario and r["group"] == group]
            ok = sum(1 for r in subset if r["success"])
            fails = sorted({r["failure"] for r in subset if r["failure"]})
            lines.append(f"| {scenario} | {group} | {len(subset)} | {ok} | "
                         f"{ok / len(subset):.0%} | {sum(r['misclick'] for r in subset)} | "
                         f"{sum(r['model_calls'] for r in subset)} | "
                         f"{', '.join(fails) or '-'} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=ITERATIONS)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = run(args.iterations)
    out_dir = ROOT / "tests" / "bench" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else out_dir / f"run_{data['ts'].replace(':', '').replace('-', '')}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summarize(data))
    print(f"\nraw: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
