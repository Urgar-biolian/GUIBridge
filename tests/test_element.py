from semantic.element import ActionResult, GUIElement, Locator, TaskRecord


def test_element_defaults():
    el = GUIElement(id="e1", window_id="w1", role="button", name="发送", bounds=(0, 0, 10, 10))
    assert el.confidence == 0.0
    assert el.calibrated is False
    assert el.source == []


def test_task_record_transitions():
    rec = TaskRecord(task_id="t1", app="trae")
    rec.transition("submitted", "ev1", "2026-11-17T12:00:00")
    rec.transition("running", "ev2", "2026-11-17T12:00:03")
    assert rec.state == "running"
    assert [t["state"] for t in rec.transitions] == ["submitted", "running"]


def test_action_result_verified_distinct_from_success():
    r = ActionResult(success=True, verified=False, before_snapshot_id="s1", after_snapshot_id="s2")
    assert r.success and not r.verified


def test_locator_chain_ordered():
    loc = Locator(semantic_id="trae.chat.composer", app_version="3.6.13",
                  chain=[{"cdp_selector": ".x"}, {"ocr_text": "y"}])
    assert list(loc.chain[0]) == ["cdp_selector"]