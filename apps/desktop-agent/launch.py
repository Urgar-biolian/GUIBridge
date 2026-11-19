"""Managed launch: start Trae with a random, loopback-only CDP port (PRD §3, docs/security.md).

GUIBridge is the only process allowed to inject the debugging port, because the port has no
authentication; binding is pinned to 127.0.0.1 with `--remote-debugging-address`.

Merged surface. `managed_launch`/`LaunchHandle` are the plane's entry and the only ones that add the
loopback flag; A lane's exe discovery and `launch_trae` CLI wrapper sit on top of it so a fresh
launch cannot take the path that omits the address.
"""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import time
import urllib.request

LOOPBACK = "127.0.0.1"
DEFAULT_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Trae\Trae.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Trae CN\Trae CN.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Trae\Trae.exe"),
]


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


def find_trae_exe(exe: str | None = None) -> str:
    if exe:
        return exe
    for candidate in DEFAULT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("Trae.exe not found; pass --exe explicitly")


def launch_trae(project_path: str, exe: str | None = None, port: int | None = None,
                popen=subprocess.Popen) -> dict:
    """Open a project in a freshly launched Trae and report the port it is debuggable on."""
    binary = find_trae_exe(exe)
    handle = managed_launch(binary, (project_path,), port, popen=popen)
    return {"pid": handle.proc.pid, "port": handle.port, "exe": binary, "handle": handle}


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Trae with a loopback CDP port")
    parser.add_argument("project_path")
    parser.add_argument("--exe")
    parser.add_argument("--port", type=int)
    parser.add_argument("--wait", action="store_true", help="block until the DevTools endpoint answers")
    cli = parser.parse_args()
    result = launch_trae(cli.project_path, cli.exe, cli.port)
    if cli.wait:
        result["handle"].wait_for_devtools()
    del result["handle"]
    print(json.dumps(result))


if __name__ == "__main__":
    main()
