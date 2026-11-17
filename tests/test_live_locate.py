"""Live read-only locate test against a running Trae with --remote-debugging-port.

Never inserts text, never clicks, never switches mode. Requires:
  GUIBRIDGE_CDP_PORT (default 9222) and Trae open in IDE mode with a chat panel.
"""

import asyncio
import os

import pytest

from perception.cdp import CDPChannel, elements_from_dom, list_targets

PORT = int(os.environ.get("GUIBRIDGE_CDP_PORT", "9222"))


@pytest.mark.live
def test_live_locate_chat_controls():
    asyncio.run(_locate())


async def _locate():
    try:
        targets = list_targets(PORT)
    except Exception as e:
        pytest.skip(f"CDP unreachable on {PORT}: {e}")
    page = next((t for t in targets if t.type == "page" and "trae" in (t.title + t.url).lower()), None)
    if page is None:
        pytest.skip("no Trae page target on debug port")

    ch = CDPChannel(PORT)
    await ch.connect(page.ws_url)
    try:
        await ch.attach_sessions()
        sid = next((s for s, info in ch.sessions.items()
                    if info.get("type") == "page"), None)

        composer_raw = await ch.query_selector(".chat-input-v2-input-box-editable", sid)
        assert composer_raw is not None, "composer not found (open the chat panel)"
        composer = elements_from_dom([composer_raw], "live")[0]
        assert composer.role == "textbox"
        assert "type" in composer.actions

        send_raw = await ch.query_selector(".chat-input-v2-send-button", sid)
        assert send_raw is not None
        send = elements_from_dom([send_raw], "live")[0]
        assert send.evidence["cdp"]["disabled"] is True, "composer must stay empty in read-only test"

        approval_raw = await ch.query_selector("[class*=permissionModeTrigger]", sid)
        assert approval_raw is not None

        mode_raw = await ch.query_selector(".v2-agent-entry-btn", sid)
        assert mode_raw is not None
    finally:
        await ch.close()