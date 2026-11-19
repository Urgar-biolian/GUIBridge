"""F10's approval-popover sequence, pinned without a desktop.

PROBE_REPORT F10 measured that Trae's permission-mode trigger does not toggle: a click — even a
trusted one — only opens a Vue popover, and the mode moves when the row named exactly 手动审批 inside
it is chosen. `adapters.trae.states` carries the selectors and the three scripts the sequence sends,
so the direct CDP adapter, the control plane's channel and the live demo cannot drift apart again.

These cover the branch outcomes the sequence can produce. Which one a real Trae returns stays a live
measurement (tests/test_live_trae.py, gated on GUIBRIDGE_LIVE); nothing here asserts that a desktop
was touched.
"""

import asyncio

from adapters.trae import states
from adapters.trae.cdp_direct import CdpTraeAdapter

TRIGGER_SCRIPT = states.approval_trigger_point_js()
OPTION_SCRIPT = states.approval_option_click_js()
LABEL_SCRIPT = states.approval_label_js()


class _FakePage:
    """Answers the three scripts the sequence sends, and records the trusted clicks it receives.

    The popover opens only for `click_at`, which is the whole F10 finding: an untrusted (JS) click on
    the trigger leaves `popover_open` false, and every later read says so.
    """

    def __init__(self, label: str = "自动审批", *, absent: bool = False, rows: tuple[str, ...] = (),
                 option_result: str | None = None, final_label: str = "手动审批",
                 opens_on_click: bool = True):
        self.label = label
        self.absent = absent
        self.rows = rows
        self.option_result = option_result
        self.final_label = final_label
        self.opens_on_click = opens_on_click
        self.clicks: list[tuple[float, float]] = []
        self.scripts: list[str] = []
        self.popover_open = False

    async def evaluate_json(self, expression: str, session_id: str | None = None):
        self.scripts.append(expression)
        if expression == TRIGGER_SCRIPT:
            if self.absent:
                return {"status": "absent", "label": None}
            return {"status": "found", "label": self.label, "x": 300.0, "y": 860.0}
        if expression == OPTION_SCRIPT:
            if not self.popover_open:
                return "no_menu"
            if self.option_result:
                return self.option_result
            matches = [name for name in self.rows if name == states.MANUAL_APPROVAL_LABEL]
            return "clicked" if len(matches) == 1 else ("ambiguous_option" if matches else "no_option")
        if expression == LABEL_SCRIPT:
            return self.final_label
        raise AssertionError(f"unexpected script sent to the page: {expression[:80]}")

    async def click_at(self, x: float, y: float, session_id: str | None = None) -> None:
        self.clicks.append((x, y))
        self.popover_open = self.opens_on_click


def _run(page: _FakePage) -> tuple[str, _FakePage]:
    adapter = CdpTraeAdapter(port=0, store=None)
    return asyncio.run(adapter._force_manual_approval(page)), page


def test_a_trigger_that_already_reads_manual_is_left_alone():
    outcome, page = _run(_FakePage(label="手动审批"))
    assert outcome == "manual"
    assert page.clicks == [] and page.scripts == [TRIGGER_SCRIPT]


def test_a_missing_trigger_is_reported_as_absent_not_as_manual():
    outcome, page = _run(_FakePage(absent=True))
    assert outcome == "absent"
    assert page.clicks == []


def test_the_switch_opens_the_popover_with_a_trusted_click_then_picks_the_manual_row():
    outcome, page = _run(_FakePage(rows=(states.MANUAL_APPROVAL_LABEL, "自动审批", "完全访问")))
    assert outcome == "manual"
    assert page.clicks == [(300.0, 860.0)], "only the trigger gets a mouse event; the row is clicked in-page"
    assert page.scripts == [TRIGGER_SCRIPT, OPTION_SCRIPT, LABEL_SCRIPT]


def test_a_popover_that_never_opens_stays_unverified():
    outcome, page = _run(_FakePage(rows=(states.MANUAL_APPROVAL_LABEL,), opens_on_click=False))
    assert outcome == "unverified:no_menu"
    assert LABEL_SCRIPT not in page.scripts, "nothing is claimed as switched when no row was clicked"


def test_a_popover_without_a_manual_row_says_so_rather_than_picking_another():
    outcome, page = _run(_FakePage(rows=("自动审批", "完全访问")))
    assert outcome == "unverified:no_option"
    assert page.final_label == "手动审批" and LABEL_SCRIPT not in page.scripts


def test_two_manual_rows_are_a_conflict_not_a_lucky_click():
    outcome, _ = _run(_FakePage(rows=(states.MANUAL_APPROVAL_LABEL, states.MANUAL_APPROVAL_LABEL)))
    assert outcome == "unverified:ambiguous_option"


def test_a_row_click_that_does_not_move_the_label_is_not_reported_as_manual():
    outcome, _ = _run(_FakePage(rows=(states.MANUAL_APPROVAL_LABEL,), final_label="自动审批"))
    assert outcome == "unverified:自动审批"


def test_full_access_is_never_a_value_this_lane_will_select():
    assert states.is_allowed_approval_target(states.MANUAL_APPROVAL_LABEL) is True
    for value in ("完全访问", "自动审批", "auto", "", None):
        assert states.is_allowed_approval_target(value) is False


def test_the_option_match_is_exact_and_ambiguous_rows_are_refused():
    assert states.find_approval_option([{"name": "自动审批"}, {"name": "手动审批"}])["name"] == "手动审批"
    assert states.find_approval_option([{"name": "手动审批开关"}]) is None
    assert states.find_approval_option([{"name": "手动审批"}, {"name": "手动审批"}]) is None
    assert states.find_approval_option([]) is None


def test_the_popover_selectors_stay_in_code_because_locators_yaml_is_frozen():
    """`locators.yaml` needs a two-person approve to gain the popover; the constants are pinned here."""
    assert (states.APPROVAL_POPOVER, states.APPROVAL_OPTION_ROW, states.APPROVAL_OPTION_NAME) == (
        "[class*=permissionModePopover]", "[class*=permissionModeItem-]", "[class*=permissionModeItemName]")
    assert "permissionModeTrigger" in TRIGGER_SCRIPT and "permissionModePopover" in OPTION_SCRIPT
    # The row is found through its name element's exact text, and the click lands on the wrapping row.
    assert "permissionModeItemName" in OPTION_SCRIPT and states.MANUAL_APPROVAL_LABEL in OPTION_SCRIPT
    assert "row.click()" in OPTION_SCRIPT and "getBoundingClientRect" in OPTION_SCRIPT
