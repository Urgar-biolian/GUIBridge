"""GUIBridge's tool surface is frozen to `packages/mcp/server.py` (docs/framework.md 契约冻结清单 #2),
which puts this package in the same import slot as the official MCP SDK's top-level `mcp`.

Left alone, `import mcp` from `packages/` hides the SDK completely and the server module cannot start.
This package resolves the clash by name:

* `mcp.server` is this project's tool surface, and it is given a `__path__` that points at the SDK's
  `mcp/server/` directory, so `mcp.server.mcpserver` and the rest of that subtree still import.
* every other `mcp.*` name (`mcp.types`, `mcp.shared.*`, `mcp.client.*`) is served from the installed
  SDK by the meta-path finder below.

Consequence to remember: `from mcp.server import <anything SDK-side>` is impossible in this project —
import SDK server symbols by their full submodule path.
"""

import sys
from importlib.machinery import PathFinder
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SELF = Path(__file__).resolve().parent


def _sdk_root() -> Path:
    for entry in sys.path:
        candidate = (Path(entry) / "mcp").resolve()
        if candidate != _SELF and (candidate / "server").is_dir():
            return candidate
    raise ImportError("the official mcp SDK is not installed; run `python -m pip install -e \".[dev,ocr]\"`")


class _SdkSubmoduleFinder:
    """Answer `mcp.*` import requests from the SDK's tree, leaving `mcp.server*` to this package."""

    def __init__(self, root: Path):
        self.root = root

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("mcp."):
            return None
        tail = fullname.split(".")[1:]
        if tail[0] == "server":
            return None
        return PathFinder.find_spec(fullname, [str(self.root.joinpath(*tail[:-1]))])


def _load_surface(root: Path):
    name = f"{__name__}.server"
    if name in sys.modules:
        return sys.modules[name]
    spec = spec_from_file_location(name, _SELF / "server.py")
    surface = module_from_spec(spec)
    surface.__path__ = [str(root / "server")]
    sys.modules[name] = surface
    spec.loader.exec_module(surface)
    return surface


def _install() -> None:
    if any(isinstance(finder, _SdkSubmoduleFinder) for finder in sys.meta_path):
        return
    root = _sdk_root()
    sys.meta_path.insert(0, _SdkSubmoduleFinder(root))
    _load_surface(root)


_install()
