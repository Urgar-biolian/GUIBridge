"""Managed launch: the only sanctioned way to give Trae a CDP port (PRD §3, docs/security.md).

Nothing here starts a real process: `popen` and `opener` are injected, so the contract that matters
is what would be handed to the OS — a random port, pinned to loopback, closed with the process.
"""

import json

import pytest
from launch import LaunchError, LaunchHandle, free_port, managed_launch

PORTS = [{"title": "Trae", "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/1"},
         {"title": "extension host", "type": "other", "url": "vscode-file://x"}]


class _FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(payload, seen=None):
    def _open(url, timeout=None):
        if seen is not None:
            seen.append((url, timeout))
        return _FakeResponse(payload)
    return _open


def test_a_free_port_is_one_we_can_actually_bind_on_loopback():
    from contextlib import closing
    import socket

    port = free_port()
    assert 0 < port < 65536
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", port))


def test_the_debugging_port_is_injected_with_a_loopback_binding():
    started = []
    handle = managed_launch("D:\\Program\\Trae\\Trae.exe", ("--user-data-dir", "tmp"),
                            port=49152, popen=lambda cmd, env=None: (started.append(cmd), _FakeProcess())[1],
                            opener=opener_for(PORTS))
    assert started == [["D:\\Program\\Trae\\Trae.exe", "--remote-debugging-port=49152",
                        "--remote-debugging-address=127.0.0.1", "--user-data-dir", "tmp"]]
    assert handle.port == 49152
    assert handle.base_url == "http://127.0.0.1:49152"


def test_the_session_port_is_injected_into_both_flags():
    commands = []

    def popen(cmd, env=None):
        commands.append(cmd)
        return _FakeProcess()

    handle = managed_launch("Trae.exe", popen=popen, opener=opener_for(PORTS))
    assert handle.port > 0
    assert commands[0][1] == f"--remote-debugging-port={handle.port}"
    assert commands[0][2] == "--remote-debugging-address=127.0.0.1"


def test_environment_reaches_the_launched_process():
    seen = {}

    def popen(cmd, env=None):
        seen["env"] = env
        return _FakeProcess()

    managed_launch("Trae.exe", env={"GUIBRIDGE": "1"}, popen=popen, opener=opener_for(PORTS))
    assert seen["env"] == {"GUIBRIDGE": "1"}


def test_targets_are_read_from_the_session_port_over_loopback_only():
    seen = []
    handle = LaunchHandle(_FakeProcess(), 49152, opener_for(PORTS, seen))
    assert handle.targets() == PORTS
    assert seen == [("http://127.0.0.1:49152/json/list", 3)]
    assert handle.page_target()["type"] == "page"


def test_a_session_without_a_page_target_is_an_error_not_a_fallback():
    handle = LaunchHandle(_FakeProcess(), 49152, opener_for([{"type": "other"}]))
    with pytest.raises(LaunchError):
        handle.page_target()


def test_wait_for_devtools_returns_as_soon_as_the_endpoint_answers():
    handle = LaunchHandle(_FakeProcess(), 49152, opener_for(PORTS))
    assert handle.wait_for_devtools(timeout=1.0) is handle


def test_wait_for_devtools_gives_up_rather_than_attaching_to_something_else():
    def refuse(url, timeout=None):
        raise OSError("connection refused")
    handle = LaunchHandle(_FakeProcess(), 49152, refuse)
    with pytest.raises(LaunchError) as exc:
        handle.wait_for_devtools(timeout=0.3)
    assert "did not answer" in str(exc.value)


def test_stopping_the_session_takes_the_port_with_it():
    process = _FakeProcess()
    LaunchHandle(process, 49152, opener_for(PORTS)).stop()
    assert process.terminated is True


def test_a_handle_without_a_process_or_port_is_refused():
    with pytest.raises(LaunchError):
        LaunchHandle(None, 49152)
    with pytest.raises(LaunchError):
        LaunchHandle(_FakeProcess(), 0)
