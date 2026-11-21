"""Dependency license audit (offline, reproducible).

Reads only local metadata: pip dist-info, conda-meta, cargo metadata --offline,
node_modules package.json. No network, no installs, no live application access.

    python -X utf8 tools/license_audit.py

Writes var/experiments/license_audit_<ts>.json (gitignored) and prints markdown
tables for docs/research/license-audit.md. Resolution order per package:
License-Expression -> License -> trove classifier -> conda-meta -> LICENSE file.
"""

from __future__ import annotations

import datetime
import importlib.metadata as md
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "var" / "experiments"
CONDA_META = pathlib.Path(sys.base_prefix) / "conda-meta"
PERMISSIVE = re.compile(
    r"(?i)(MIT|BSD|Apache|ISC|PSF|Python|Unlicense|HPND|TCL|ZPL|Zope|"
    r"Historical|Unicode|Public Domain|CC0|3-Clause)"
)
NAME = r'"([A-Za-z0-9_.\-]+)'


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def conda_license(name: str) -> tuple[str, str, str] | None:
    if not CONDA_META.is_dir():
        return None
    for p in CONDA_META.glob("*.json"):
        if norm(p.name.split("-")[0]) != norm(name):
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        lic = j.get("license")
        if lic:
            return lic, f"conda-meta/{p.name}", j.get("version", "")
    return None


def license_file(dist: md.Distribution) -> tuple[str, str] | None:
    for f in dist.files or []:
        if re.search(r"(?i)(license|copying)(\.|$|/)", str(f)):
            try:
                text = (pathlib.Path(dist.locate_file(f))).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            first = next((l.strip() for l in text.splitlines() if l.strip()), "")
            if first:
                return first[:60], f"file:{f}"
    return None


def resolve(name: str) -> dict:
    try:
        dist = md.distribution(name)
    except Exception:
        got = conda_license(name)
        return {"name": name, "version": got[2] if got else None,
                "license": got[0] if got else "UNRESOLVED",
                "source": got[1] if got else "not-installed", "installed": False}
    lic = dist.metadata.get("License-Expression")
    src = "License-Expression"
    if not lic:
        lic = (dist.metadata.get("License") or "").split("\n")[0].strip()[:60]
        src = "License"
    if not lic:
        cls = [c.split("::")[-1].strip() for c in (dist.metadata.get_all("Classifier") or [])
               if c.startswith("License")]
        lic, src = (cls[0], "classifier") if cls else ("", "")
    if not lic or lic.upper() in ("UNKNOWN", "NONE"):
        got = conda_license(name) or license_file(dist)
        if got:
            lic, src = got[0], got[1]
    return {"name": norm(name), "version": dist.version, "license": lic or "UNRESOLVED",
            "source": src or "none", "installed": True,
            "path": str(getattr(dist, "_path", ""))}


def declared() -> tuple[list[str], dict[str, list[str]]]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    main = re.search(r"^dependencies = \[(.*?)\]", text, re.S | re.M)
    roots = re.findall(NAME, main.group(1)) if main else []
    extras: dict[str, list[str]] = {}
    opt = re.search(r"\[project\.optional-dependencies\](.*?)(^\[|\Z)", text, re.S | re.M)
    if opt:
        for key, body in re.findall(r"^(\w+) = \[(.*?)\]", opt.group(1), re.S | re.M):
            extras[key] = re.findall(NAME, body)
    return roots, extras


def closure(roots: list[str]) -> dict[str, dict]:
    from packaging.requirements import Requirement

    seen: dict[str, dict] = {}
    queue = [(norm(r), "declared") for r in roots]
    while queue:
        name, parent = queue.pop(0)
        if name in seen:
            continue
        rec = resolve(name)
        rec["via"] = parent
        seen[name] = rec
        if not rec["installed"]:
            continue
        try:
            dist = md.distribution(name)
        except Exception:
            continue
        for raw in dist.requires or []:
            try:
                req = Requirement(raw)
            except Exception:
                continue
            if req.marker and not req.marker.evaluate({"extra": ""}):
                continue
            queue.append((norm(req.name), name))
    return seen


def cargo() -> list[dict]:
    crate = ROOT / "src" / "probe" / "gbmirror"
    if not (crate / "Cargo.toml").exists():
        return []
    proc = subprocess.run(
        ["cargo", "metadata", "--offline", "--filter-platform", "x86_64-pc-windows-msvc",
         "--format-version", "1"],
        cwd=crate, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return [{"error": proc.stderr.strip()[:300]}]
    meta = json.loads(proc.stdout)
    return [{"name": p["name"], "version": p["version"],
             "license": p.get("license") or p.get("license_file") or "UNRESOLVED",
             "source": "cargo metadata"} for p in meta["packages"]]


def npm() -> list[dict]:
    out = []
    for manifest in sorted(ROOT.glob("apps/*/package.json")) + sorted(ROOT.glob("examples/*/package.json")):
        tree = manifest.parent / "node_modules"
        direct = json.loads(manifest.read_text(encoding="utf-8"))
        out.append({"manifest": str(manifest.relative_to(ROOT)),
                    "dependencies": direct.get("dependencies", {}),
                    "devDependencies": direct.get("devDependencies", {}),
                    "license": direct.get("license", "UNDECLARED")})
        if not tree.is_dir():
            continue
        for p in sorted(tree.glob("*/package.json")) + sorted(tree.glob("@*/*/package.json")):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"name": j.get("name"), "version": j.get("version"),
                        "license": j.get("license", "UNRESOLVED"), "source": str(p.relative_to(ROOT))})
    return out


def table(rows: list[dict], cols: list[str]) -> str:
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def main() -> int:
    roots, extras = declared()
    py = closure(roots + [r for v in extras.values() for r in v])
    crates = cargo()
    nodes = npm()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {"generated_utc": stamp, "python": py, "extras": extras,
               "cargo": crates, "npm": nodes,
               "python_executable": sys.executable, "base_prefix": sys.base_prefix}
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"license_audit_{stamp}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"raw record: {out.relative_to(ROOT)}")
    print(f"python closure: {len(py)} packages; extras: {extras}")
    print("\n### Python\n")
    print(table(sorted(py.values(), key=lambda r: r["name"]),
                ["name", "version", "license", "source", "via"]))
    print("\n### Rust\n")
    print(table(sorted(crates, key=lambda r: r.get("name", "")), ["name", "version", "license"]))
    print("\n### npm\n")
    print(table([n for n in nodes if "name" in n], ["name", "version", "license"]))
    print("\n### tallies\n")
    for label, rows in (("python", list(py.values())), ("cargo", crates),
                        ("npm", [n for n in nodes if "name" in n])):
        print(label, dict(Counter(r.get("license", "?") for r in rows)))
    flagged = [r for r in list(py.values()) + crates + [n for n in nodes if "name" in n]
               if not r.get("installed", True) or not PERMISSIVE.match(str(r.get("license", "")))]
    print("\n### flagged (unresolved / not installed / non-permissive prefix)\n")
    print(table(flagged, ["name", "version", "license", "source"]) if flagged else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())