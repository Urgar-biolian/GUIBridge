"""Deterministic Trae simulation used before gate G1.

This is NOT a perception channel: it never touches a desktop. It replays the behaviours recorded in
probe/PROBE_REPORT.md (F5 mode menu leaves, F6 submit -> 「思考中」 -> read-back, F9 auto-approval
trigger, F10 approval popover) against a fixture DOM so the adapter, MCP surface and Dashboard can be
exercised while the live CDP channel is still missing. `ControlPlane` swaps it for
`perception.cdp` + `semantic.resolver` without any change to the adapter or tool layer.
"""

import json
from pathlib import Path

from adapters.trae import states
from adapters.trae.states import APPROVAL_OPTION_ROW, APPROVAL_POPOVER, RUNNING_TEXT

MODE_MENU = ".popup-menu"
# The four rows the approval popover offers on the probed build (docs/handoff-a-to-b.md, run
# 20261118T073742Z). Kept complete so a test can prove 完全访问 and 自定义 are never picked.
DEFAULT_APPROVAL_OPTIONS = (states.MANUAL_APPROVAL_LABEL, "自动审批", "完全访问", "自定义")


class Conflict(Exception):
    """More than one candidate matched: the caller must stop, not guess (PRD §8)."""

    code = "conflict"


def load_fixture(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class SimulatedTrae:
    """Channel-shaped object: selector in, element out, conversation text advances on each read."""

    name = "cdp-simulated"

    def __init__(self, fixture: dict):
        self.window = dict(fixture["window"])
        self.elements = {e["selector"]: dict(e) for e in fixture["elements"]}
        self.messages: list[str] = [fixture["conversation"]] if fixture.get("conversation") else []
        self.transient = ""
        # reply_plan steps are [text, reads_to_hold]; 思考中 persists across polls like the real DOM.
        self.reply_plan = [list(step) for step in fixture.get("reply_plan", [["思考中", 1]])]
        self.queue: list[list] = []
        self.composer_text = ""
        self.menu_open = fixture.get("menu_open", False)
        self.session_mode = fixture.get("session_mode", "Agent")
        self.approval_mode = fixture.get("approval_mode", "auto")
        # The popover is separate state from the mode: opening it is not switching (F10).
        self.approval_menu_open = False
        self.approval_options = list(fixture.get("approval_options") or DEFAULT_APPROVAL_OPTIONS)
        self.ide_mode = fixture.get("ide_mode", False)
        self.actions: list[dict] = []

    def available(self) -> bool:
        return True

    def window_identity(self, window_id: str) -> dict:
        if window_id != self.window["window_id"]:
            raise LookupError(f"no such window: {window_id}")
        return dict(self.window)

    def _trigger(self, label: str) -> dict:
        return {"selector": f"button[aria-label='{label}']", "role": "button", "name": label,
                "text": label, "disabled": False}

    def _option_row(self, name: str) -> dict:
        return {"selector": APPROVAL_OPTION_ROW, "role": "menuitem", "name": name, "text": name,
                "disabled": False}

    def _matches(self, selector: str) -> list[dict]:
        if selector == MODE_MENU:
            return [{"selector": MODE_MENU, "role": "menu", "name": "session modes", "text": "",
                     "children": ["Chat", "Ask", "Agent"]}] if self.menu_open else []
        if selector == APPROVAL_POPOVER:
            return [{"selector": APPROVAL_POPOVER, "role": "menu", "name": "approval modes", "text": "",
                     "children": list(self.approval_options)}] if self.approval_menu_open else []
        if selector == APPROVAL_OPTION_ROW:
            return [self._option_row(name) for name in self.approval_options] if self.approval_menu_open else []
        if selector == states.AUTO_APPROVAL_TRIGGER:
            return [self._trigger("自动审批")] if self.approval_mode == "auto" else []
        if selector == states.MANUAL_APPROVAL_TRIGGER:
            return [self._trigger("手动审批")] if self.approval_mode == "manual" else []
        if selector == states.APPROVAL_TRIGGER_CLASS:
            # One visible trigger carrying the current mode as its label (probe run 20261117T135355Z).
            return [self._trigger("自动审批" if self.approval_mode == "auto" else "手动审批")]
        element = self.elements.get(selector)
        if element is None:
            return []
        found = dict(element)
        if selector == ".chat-input-v2-send-button":
            found["disabled"] = not self.composer_text
        return [found]

    def find(self, window_id: str, selector: str) -> dict | None:
        matches = self._matches(selector)
        return matches[0] if matches else None

    def query(self, window_id: str, selector: str) -> list[dict]:
        return self._matches(selector)

    def scan(self, window_id: str, max_depth: int = 18) -> list[dict]:
        live = [dict(e) for e in self.elements.values()]
        for item in live:
            if item["selector"] == ".chat-input-v2-send-button":
                item["disabled"] = not self.composer_text
        if self.menu_open:
            live.append({"selector": MODE_MENU, "role": "menu", "name": "session modes", "text": ""})
        live.append(self._trigger("自动审批" if self.approval_mode == "auto" else "手动审批"))
        if self.approval_menu_open:
            live.append({"selector": APPROVAL_POPOVER, "role": "menu", "name": "approval modes", "text": ""})
            live.extend(self._option_row(name) for name in self.approval_options)
        return live

    def screenshot(self, window_id: str) -> str | None:
        return None

    def focus(self, window_id: str, selector: str) -> None:
        self._require(selector, "focus")
        self.actions.append({"action": "focus", "selector": selector})

    def insert_text(self, window_id: str, text: str) -> None:
        self.composer_text += text
        self.actions.append({"action": "insert_text", "text": text})

    def click(self, window_id: str, selector: str) -> None:
        self._require(selector, "click")
        self.actions.append({"action": "click", "selector": selector})
        if selector == ".icube-mode-tab-item-ide":
            self.ide_mode = True
        elif selector == ".v2-agent-entry-btn":
            self.menu_open = True
        elif selector == "[data-testid=ai-chat-create-new-session]":
            self.messages = []
            self.transient = ""
            self.queue = []
        elif selector == ".chat-input-v2-send-button":
            self._submit()
        elif selector in states.APPROVAL_TRIGGERS:
            # F10: the click opens the popover and changes no mode. Treating it as a toggle is what
            # made the pre-merge simulation report a switch that a real Trae never performed.
            self.approval_menu_open = not self.approval_menu_open

    def select(self, window_id: str, selector: str, value: str) -> None:
        self._require(selector, "select")
        if selector in states.APPROVAL_TRIGGERS:
            self._select_approval_option(selector, value)
            return
        menu = self._matches(MODE_MENU)
        if not menu:
            raise LookupError(f"no open menu to select {value!r} from")
        if value not in menu[0]["children"]:
            raise LookupError(f"menu has no leaf {value!r}")
        self.menu_open = False
        self.session_mode = value
        self.actions.append({"action": "select", "selector": selector, "value": value})

    def _select_approval_option(self, selector: str, value: str) -> None:
        """Opening the approval menu and choosing its manual row are one interaction, as in a dropdown.

        Keeping them together is what lets the switch stay a single gated action; the value is not
        caller-chosen, because 完全访问 is a human decision and never something this lane selects.
        """
        if not states.is_allowed_approval_target(value):
            raise LookupError(f"refusing to select the approval mode {value!r}; only "
                              f"{states.MANUAL_APPROVAL_LABEL!r} is switchable here")
        self.approval_menu_open = True
        self.actions.append({"action": "click", "selector": selector})
        offered = self._matches(APPROVAL_OPTION_ROW)
        if states.find_approval_option(offered, value) is None:
            # The menu stays open: closing it would hide what it offered from the after-snapshot.
            raise LookupError(f"approval popover offers no single {value!r} row: "
                              f"{[row['name'] for row in offered]}")
        self.actions.append({"action": "click", "selector": APPROVAL_OPTION_ROW, "name": value})
        self.approval_menu_open = False
        self.approval_mode = "manual"
        self.actions.append({"action": "select", "selector": selector, "value": value})

    def inner_text(self, window_id: str, selector: str) -> str:
        if selector != ".ai-chat-v2-ide-root":
            element = self.find(window_id, selector)
            return element.get("text", "") if element else ""
        if self.queue:
            step = self.queue[0]
            if step[0] in RUNNING_TEXT:
                self.transient = step[0] + "\n"
            else:
                self.messages.append(step[0] + "\n")
                self.transient = ""
            step[1] -= 1
            if step[1] <= 0:
                self.queue.pop(0)
        return "".join(self.messages) + self.transient

    def _require(self, selector: str, verb: str) -> None:
        # The triggers and the menus are state-driven surfaces, not fixture rows, so they are matched
        # by `_matches` alone; anything else has to be a registered element before it can be touched.
        dynamic = (MODE_MENU, APPROVAL_POPOVER, APPROVAL_OPTION_ROW) + states.APPROVAL_TRIGGERS
        if selector not in self.elements and selector not in dynamic:
            raise LookupError(f"cannot {verb} unregistered selector {selector!r}")
        if not self._matches(selector):
            raise LookupError(f"cannot {verb} absent selector {selector!r}")

    def _submit(self) -> None:
        if not self.composer_text:
            raise LookupError("send refused: composer empty")
        self.messages.append(f"USER: {self.composer_text}\n")
        self.actions.append({"action": "submit", "text": self.composer_text})
        self.composer_text = ""
        self.queue = [list(step) for step in self.reply_plan]


class RegistryResolver:
    """semantic_id -> live element, relocated from the registry chain on every call."""

    def __init__(self, channel: SimulatedTrae, registry: dict, window_id: str):
        self.channel = channel
        self.registry = registry
        self.window_id = window_id

    def resolve(self, window_id: str, semantic_id: str):
        from semantic.element import GUIElement
        locator = self.registry.get(semantic_id)
        if locator is None:
            raise LookupError(f"{semantic_id} is not registered")
        for strategy in locator.chain:
            selector = strategy.get("cdp_selector")
            if not selector:
                continue
            matches = self.channel.query(window_id, selector)
            if len(matches) > 1:
                raise Conflict(f"{semantic_id} matched {len(matches)} candidates; refusing to guess")
            if matches:
                found = matches[0]
                return GUIElement(id=f"{window_id}:{selector}", window_id=window_id,
                                  role=found.get("role", ""),
                                  name=found.get("name", semantic_id),
                                  bounds=tuple(found.get("rect", (0, 0, 0, 0))),
                                  actions=["click", "type", "select"], source=[self.channel.name],
                                  confidence=1.0, calibrated=False, semantic_id=semantic_id,
                                  evidence={"cdp_selector": selector,
                                            "process_name": self.channel.window_identity(window_id)["process_name"]})
        raise LookupError(f"{semantic_id}: no chain strategy matched a live element")
