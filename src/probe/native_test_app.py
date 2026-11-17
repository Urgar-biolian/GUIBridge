"""Phase 1 controlled Win32 target (skeleton).

Control IDs are fixed here so experiments stay reproducible.
The window is implemented in Phase 1; running this file now exits 2.
"""

from __future__ import annotations

import sys

APP_TITLE = "GUIBridge UIA Test Target"
BUTTON_ID = 1001
EDIT_ID = 1002
CHECKBOX_ID = 1003
STATUS_ID = 1004

CONTROLS = {
    "button": BUTTON_ID,
    "input": EDIT_ID,
    "checkbox": CHECKBOX_ID,
    "status": STATUS_ID,
}


def main() -> int:
    print("Phase 1 target not implemented yet. Planned controls:", CONTROLS)
    return 2


if __name__ == "__main__":
    sys.exit(main())
