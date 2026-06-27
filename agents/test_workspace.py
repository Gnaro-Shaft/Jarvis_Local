#!/usr/bin/env python3
"""Tests de l'agent Workspace : détection de type + découverte locale (sans serveur)."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

AGENTS = os.path.dirname(os.path.abspath(__file__))

# Isoler AVANT de charger le module (LOCAL_ROOTS/REMOTE_HOST lus à l'import).
_ROOT = tempfile.mkdtemp(prefix="jarvis-ws-")
os.environ["JARVIS_PROJECT_ROOTS"] = _ROOT
os.environ["JARVIS_REMOTE_HOST"] = ""  # pas de serveur pendant les tests


def _mkproj(name: str, *files: str) -> str:
    d = os.path.join(_ROOT, name)
    os.makedirs(d, exist_ok=True)
    for f in files:
        p = os.path.join(d, f)
        os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(f) else None
        open(p, "w").close()
    return d


py = _mkproj("mon_py", "requirements.txt")
node = _mkproj("mon_node", "package.json")
gitp = _mkproj("mon_git", ".git/HEAD")
_mkproj("pas_un_projet", "notes.txt")

spec = importlib.util.spec_from_file_location("ws", os.path.join(AGENTS, "workspace", "agent.py"))
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    # --- detect_type ---
    check(ws.detect_type(py) == "python", "detect_type: requirements.txt → python")
    check(ws.detect_type(node) == "node", "detect_type: package.json → node")
    check(ws.detect_type(gitp) == "git", "detect_type: .git → git")
    check(ws.detect_type(os.path.join(_ROOT, "pas_un_projet")) is None,
          "detect_type: dossier sans marqueur → None")

    # --- scan_local ---
    found = ws.scan_local()
    names = {e["name"] for e in found.values()}
    check({"mon_py", "mon_node", "mon_git"} <= names, "scan_local: trouve les projets")
    check("pas_un_projet" not in names, "scan_local: ignore les non-projets")

    # --- catalog local-only (pas de SSH) ---
    cat = ws.catalog(local_only=True)
    check(any(e["name"] == "mon_node" and e["type"] == "node" for e in cat),
          "catalog: type correct")
    check(all(not e.get("remote") for e in cat), "catalog: aucun 'remote' sans serveur")

    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS workspace ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
