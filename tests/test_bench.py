import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("guibridge_bench", ROOT / "tests" / "bench" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_semantic_beats_coordinates_under_viewport_changes():
    data = bench.run(iterations=3)
    rows = data["results"]

    def rate(scenario, group):
        subset = [r for r in rows if r["scenario"] == scenario and r["group"] == group]
        return sum(r["success"] for r in subset) / len(subset)

    assert rate("window_move", "C") > rate("window_move", "A")


def test_group_c_never_misclicks():
    data = bench.run(iterations=3)
    assert all(r["misclick"] == 0 for r in data["results"] if r["group"] == "C")


def test_verification_rejects_disabled_targets():
    data = bench.run(iterations=3)
    rows = [r for r in data["results"] if r["scenario"] == "click_send"]
    c = [r for r in rows if r["group"] == "C"]
    assert all(r["failure"] == "unverified_state" for r in c)
