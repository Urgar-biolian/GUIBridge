"""Managed launch: start Trae with a random, loopback-only CDP port (PRD §3, docs/security.md).

GUIBridge is the only process allowed to inject the debugging port, because the port has no
authentication; binding is pinned to 127.0.0.1 with `--remote-debugging-address`.
"""

import contextlib
import json
import socket
import subprocess
import time
import urllib.request

LOOPBACK = "127.0.0.1"


class LaunchError(Exception):
    pass


def free_port() -> int:
    with contextlib.closing(socket.socket()) as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


class LaunchHandle:
    def __init__(self, proc, port: int, opener=urllib.request.urlopen):
        if proc is None or port <= 0:
            raise LaunchError("managed launch requires a process and a positive port")
        self.proc = proc
        self.port = port
        self.opener = opener
        self.base_url = f"http://{LOOPBACK}:{port}"

    def targets(self) -> list[dict]:
        with self.opener(self.base_url + "/json/list", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def page_target(self) -> dict:
        for target in self.targets():
            if target.get("type") == "page":
                return target
        raise LaunchError("no page target exposed on the debugging port")

    def wait_for_devtools(self, timeout: float = 20.0) -> "LaunchHandle":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.page_target()
                return self
            except Exception:
                time.sleep(0.2)
        raise LaunchError(f"devtools endpoint {self.base_url} did not answer within {timeout}s")

    def stop(self) -> None:
        self.proc.terminate()


def managed_launch(exe: str, args: tuple[str, ...] = (), port: int | None = None, env: dict | None = None,
                   popen=subprocess.Popen, opener=urllib.request.urlopen) -> LaunchHandle:
    chosen = port or free_port()
    cmd = [exe, f"--remote-debugging-port={chosen}", f"--remote-debugging-address={LOOPBACK}", *args]
    return LaunchHandle(popen(cmd, env=env), chosen, opener)
