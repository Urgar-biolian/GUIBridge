"""CDP perception channel for Electron/Chromium targets (primary channel, see PROBE_REPORT F3)."""


class CDPChannel:
    def __init__(self, port: int):
        self.port = port

    async def connect(self, target_url: str) -> None:
        raise NotImplementedError("S1")

    async def attach_sessions(self) -> list[str]:
        raise NotImplementedError("S1")

    async def evaluate(self, expression: str, session_id: str | None = None):
        raise NotImplementedError("S1")

    async def insert_text(self, text: str) -> None:
        raise NotImplementedError("S1")

    async def scan_elements(self, session_id: str | None = None) -> list[dict]:
        raise NotImplementedError("S1")

    async def close(self) -> None:
        raise NotImplementedError("S1")