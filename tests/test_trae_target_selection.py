"""Target selection for the Trae CDP adapter with a floating-chat page present.

Trae CN exposes a floatingButton.html page before the workbench page, so picking the
first page containing "trae" connects to the floating button and every locator misses.
The adapter must prefer the workbench page and only fall back when none exists."""

import asyncio

import adapters.trae.cdp_direct as cdp
from perception.cdp import CDPTarget


def _adapter(monkeypatch, pages):
    monkeypatch.setattr(cdp, "list_targets", lambda port: pages)
    return cdp.CdpTraeAdapter(port=0, store=None)


def test_target_prefers_workbench_over_floating_chat(monkeypatch):
    pages = [
        CDPTarget("page", "", "file:///D:/Trae%20CN/resources/app/out/vs/platform/"
                  "iCubeFloatingChat/electron-main/media/floatingButton.html", "ws://floating"),
        CDPTarget("page", "guibridge-demo-workspace - TRAE CN",
                  "vscode-file://vscode-app/d:/Trae%20CN/resources/app/out/vs/code/"
                  "electron-browser/workbench/workbench.html", "ws://workbench"),
    ]
    assert asyncio.run(_adapter(monkeypatch, pages)._target()) is pages[1]


def test_target_without_workbench_keeps_first_trae_page(monkeypatch):
    pages = [CDPTarget("page", "Agui - TRAE", "vscode-file://vscode-app/other.html", "ws://one")]
    assert asyncio.run(_adapter(monkeypatch, pages)._target()) is pages[0]

