"""Managed Trae launch: inject a loopback-only random debug port and open the project.

Prefer attaching to an already running instance whose port you control; this helper is for
fresh launches only. Never binds non-loopback addresses.
"""

from __future__ import annotations

import os
import socket
import subprocess

DEFAULT_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Trae\Trae.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Trae CN\Trae CN.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Trae\Trae.exe"),
]


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_trae_exe(exe: str | None = None) -> str:
    if exe:
        return exe
    for candidate in DEFAULT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError("Trae.exe not found; pass --exe explicitly")


def launch_trae(project_path: str, exe: str | None = None, port: int | None = None) -> dict:
    port = port or free_loopback_port()
    binary = find_trae_exe(exe)
    proc = subprocess.Popen([binary, f"--remote-debugging-port={port}", project_path],
                            cwd=project_path)
    return {"pid": proc.pid, "port": port, "exe": binary}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Launch Trae with a loopback CDP port")
    parser.add_argument("project_path")
    parser.add_argument("--exe")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    print(json.dumps(launch_trae(args.project_path, args.exe, args.port)))
