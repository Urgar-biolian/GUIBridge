"""UIA perception channel: native Win32/WPF/WinForms; Electron exposes frame-level tree only."""


class UIAChannel:
    def list_windows(self, process_names: list[str]) -> list[dict]:
        raise NotImplementedError("S1")

    def inspect_window(self, window_id: str, max_depth: int = 18, max_nodes: int = 20000) -> list[dict]:
        raise NotImplementedError("S1")