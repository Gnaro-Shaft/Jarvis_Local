#!/usr/bin/env python3
"""Jarvis — Agent Workspace (prototype).

Découvre les projets (local + serveur via SSH), déduplique les copies
local↔serveur, et gère le « projet actif » (cf. vision Jarvis Local).

Le projet actif est persisté dans `.jarvis/state.json` et sert de contexte par
défaut au coordinateur (`jarvis.py`) pour l'agent Dev.

Usage:
    python3 agents/workspace/agent.py                 # liste le catalogue
    python3 agents/workspace/agent.py --local-only    # sans le serveur (rapide)
    python3 agents/workspace/agent.py --use v8        # définit le projet actif
    python3 agents/workspace/agent.py --active        # affiche le projet actif

Config (env):
    JARVIS_PROJECT_ROOTS   (~ = home)          racines locales (os.pathsep)
    JARVIS_REMOTE_HOST     (vide ; ex. homeserv01)  hôte SSH du serveur ("" = off)
    JARVIS_REMOTE_ROOTS    ($HOME:$HOME/projects:/data)   racines distantes
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)
from common import get_active_project, set_active_project  # noqa: E402

LOCAL_ROOTS = os.environ.get("JARVIS_PROJECT_ROOTS", os.path.expanduser("~")).split(os.pathsep)
REMOTE_HOST = os.environ.get("JARVIS_REMOTE_HOST", "")  # ex. via .env : homeserv01
REMOTE_ROOTS = os.environ.get("JARVIS_REMOTE_ROOTS", "$HOME:$HOME/projects:/data").split(":")

# marqueur de fichier -> type de projet
MARKER_TYPE = {
    "pyproject.toml": "python", "requirements.txt": "python", "setup.py": "python",
    "package.json": "node", "Cargo.toml": "rust", "go.mod": "go",
    ".git": "git",  # fallback faible
}
IGNORE = {"node_modules", ".git", "Archive_IA", "Templates"}


def detect_type(path: str) -> str | None:
    """Type du projet d'après ses marqueurs ; None si ce n'est pas un projet."""
    try:
        entries = set(os.listdir(path))
    except OSError:
        return None
    for marker in ("pyproject.toml", "setup.py", "requirements.txt"):
        if marker in entries:
            return "python"
    if "package.json" in entries:
        return "node"
    if "Cargo.toml" in entries:
        return "rust"
    if "go.mod" in entries:
        return "go"
    if ".git" in entries:
        return "git"
    return None


def scan_local() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for root in LOCAL_ROOTS:
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            if entry in IGNORE or entry.startswith("."):
                continue
            p = os.path.join(root, entry)
            if not os.path.isdir(p):
                continue
            t = detect_type(p)
            if t is None:
                continue
            found[entry.lower()] = {"name": entry, "local": p, "type": t}
    return found


def scan_remote(timeout: int = 12) -> dict[str, dict]:
    if not REMOTE_HOST:
        return {}
    roots = " ".join(f'"{r}"' for r in REMOTE_ROOTS)
    # Un projet = une RACINE de dépôt (.git). On détecte le type via les marqueurs
    # présents à cette racine — évite de remonter les sous-paquets d'un monorepo.
    remote_cmd = (
        f'for root in {roots}; do [ -d "$root" ] && '
        f'find "$root" -maxdepth 4 -name .git -type d -not -path "*/node_modules/*" 2>/dev/null; '
        f'done | sed "s:/.git$::" | sort -u | while read d; do '
        f'if [ -f "$d/pyproject.toml" ] || [ -f "$d/setup.py" ] || [ -f "$d/requirements.txt" ]; then t=python; '
        f'elif [ -f "$d/package.json" ]; then t=node; '
        f'elif [ -f "$d/Cargo.toml" ]; then t=rust; '
        f'elif [ -f "$d/go.mod" ]; then t=go; else t=git; fi; '
        f'echo "$d|$t"; done'
    )
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", REMOTE_HOST, remote_cmd],
            capture_output=True, text=True, timeout=timeout + 8,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    found: dict[str, dict] = {}
    for line in out.splitlines():
        if "|" not in line:
            continue
        path, t = line.rsplit("|", 1)
        name = os.path.basename(path)
        if name in IGNORE or not name:
            continue
        found[name.lower()] = {"name": name, "remote": path, "type": t}
    return found


def catalog(local_only: bool = False) -> list[dict]:
    loc = scan_local()
    rem = {} if local_only else scan_remote()
    merged: dict[str, dict] = {}
    for key, e in loc.items():
        merged[key] = dict(e)
    for key, e in rem.items():
        if key in merged:
            merged[key]["remote"] = e["remote"]
            if merged[key]["type"] == "git" and e["type"] != "git":
                merged[key]["type"] = e["type"]
        else:
            merged[key] = dict(e)
    return [merged[k] for k in sorted(merged)]


def print_catalog(items: list[dict]) -> None:
    active = get_active_project() or {}
    aname = active.get("name")
    print(f"\n{'':2}{'PROJET':24} {'TYPE':8} {'LOCAL':6} {'SERVEUR':8}")
    print("  " + "-" * 50)
    for e in items:
        mark = "→" if e["name"] == aname else " "
        loc = "✓" if e.get("local") else "·"
        rem = "✓ copie" if e.get("local") and e.get("remote") else ("✓" if e.get("remote") else "·")
        print(f"{mark} {e['name'][:24]:24} {e['type']:8} {loc:6} {rem:8}")
    print(f"\n{len(items)} projets" + (f"  ·  actif : {aname}" if aname else "  ·  aucun projet actif"))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — agent Workspace (découverte projets + projet actif)")
    p.add_argument("--local-only", action="store_true", help="ne pas interroger le serveur")
    p.add_argument("--use", metavar="NOM", default=None, help="définir le projet actif")
    p.add_argument("--active", action="store_true", help="afficher le projet actif")
    a = p.parse_args(argv)

    if a.active:
        act = get_active_project()
        print(act if act else "Aucun projet actif.")
        return 0

    if a.use:
        items = {e["name"].lower(): e for e in catalog(local_only=a.local_only)}
        e = items.get(a.use.lower())
        if not e:
            print(f"⛔ projet introuvable : {a.use}", file=sys.stderr)
            return 1
        set_active_project({"name": e["name"], "local": e.get("local"), "remote": e.get("remote")})
        print(f"✅ projet actif : {e['name']}")
        if e.get("local"):
            print(f"   local   : {e['local']}")
        if e.get("remote"):
            print(f"   serveur : {REMOTE_HOST}:{e['remote']}")
        return 0

    print_catalog(catalog(local_only=a.local_only))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
