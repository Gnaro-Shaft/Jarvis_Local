#!/usr/bin/env python3
"""Jarvis — couche d'écriture sécurisée (proposition → validation → application).

Implémente les règles de sécurité de la vision Jarvis Local :
  - Lecture / analyse : libres (pas géré ici).
  - Création / modification / déplacement : possibles mais SOUMIS À VALIDATION.
  - Suppression : INTERDITE. Le seul retrait possible est l'archivage (déplacement
    vers `Archive_IA/` à la racine de la zone, jamais de perte de données).
  - Confinement : toute action est refusée hors des zones autorisées (workspaces).

Aucune fonction ici n'appelle `os.remove` / `os.unlink` / `rmtree`. Une
modification sauvegarde d'abord l'ancienne version dans `Archive_IA`.

Usage typique :
    acts = [safe_fs.create("…/note.md", contenu), safe_fs.archive("…/vieux.md")]
    safe_fs.confirm_and_apply(acts)          # affiche les diffs puis demande [y/N]
    safe_fs.confirm_and_apply(acts, assume_yes=True)   # non interactif (--yes)
"""
from __future__ import annotations

import difflib
import os
import shutil
import time
from dataclasses import dataclass

DEFAULT_WORKSPACES = {
    "obsidian": "/Users/dgnaro/dGnaro",
    "jarvis": "/Users/dgnaro/J_A_R_V_I_S",
    "downloads": "/Users/dgnaro/Downloads",
}
ARCHIVE_DIRNAME = "Archive_IA"
VALID_KINDS = {"create", "modify", "move", "archive"}


class SecurityError(Exception):
    """Action refusée par les règles de sécurité (hors zone, écrasement, etc.)."""


@dataclass
class Action:
    kind: str                 # create | modify | move | archive
    path: str                 # cible (ou source pour move/archive)
    dst: str | None = None    # destination (move)
    content: str | None = None  # contenu (create/modify)


# --------------------------------------------------------------------------- #
# Zones autorisées & confinement
# --------------------------------------------------------------------------- #
def workspaces() -> dict[str, str]:
    env = os.environ.get("JARVIS_WORKSPACES")
    if env:
        return {f"ws{i}": p for i, p in enumerate(env.split(os.pathsep)) if p}
    return dict(DEFAULT_WORKSPACES)


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def workspace_of(path: str) -> tuple[str, str] | None:
    """(nom, racine) de la zone contenant `path`, sinon None."""
    rp = _resolve(path)
    for name, root in workspaces().items():
        rr = _resolve(root)
        if rp == rr or rp.startswith(rr + os.sep):
            return name, rr
    return None


def _require_ws(path: str) -> tuple[str, str]:
    ws = workspace_of(path)
    if not ws:
        raise SecurityError(f"hors zone autorisée : {path}")
    return ws


# --------------------------------------------------------------------------- #
# Constructeurs d'actions
# --------------------------------------------------------------------------- #
def create(path: str, content: str) -> Action:
    return Action("create", path, content=content)


def modify(path: str, content: str) -> Action:
    return Action("modify", path, content=content)


def move(src: str, dst: str) -> Action:
    return Action("move", src, dst=dst)


def archive(path: str) -> Action:
    """Archivage = alternative à la suppression (jamais de delete)."""
    return Action("archive", path)


def _archive_dest(path: str) -> str:
    name, root = _require_ws(path)
    rel = os.path.relpath(_resolve(path), root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(root, ARCHIVE_DIRNAME, f"{rel}.{stamp}")


# --------------------------------------------------------------------------- #
# Aperçu (diff lisible) — affiché avant toute validation
# --------------------------------------------------------------------------- #
def preview(action: Action) -> str:
    a = action
    if a.kind == "create":
        body = (a.content or "")
        head = "\n".join(body.splitlines()[:30])
        more = "" if body.count("\n") < 30 else "\n  …"
        return f"🆕 CRÉER  {a.path}  ({len(body.splitlines())} lignes)\n  " + head.replace("\n", "\n  ") + more
    if a.kind == "modify":
        old = ""
        if os.path.exists(a.path):
            with open(a.path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
        diff = difflib.unified_diff(
            old.splitlines(), (a.content or "").splitlines(),
            fromfile=f"a/{os.path.basename(a.path)}", tofile=f"b/{os.path.basename(a.path)}",
            lineterm="",
        )
        d = "\n".join(diff) or "(aucun changement)"
        return f"✏️  MODIFIER  {a.path}  (ancienne version → {ARCHIVE_DIRNAME})\n{d}"
    if a.kind == "move":
        return f"📦 DÉPLACER  {a.path}  →  {a.dst}"
    if a.kind == "archive":
        return f"🗄️  ARCHIVER  {a.path}  →  {_archive_dest(a.path)}  (PAS de suppression)"
    raise SecurityError(f"type d'action inconnu : {a.kind}")


# --------------------------------------------------------------------------- #
# Application (après validation)
# --------------------------------------------------------------------------- #
def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def apply(action: Action) -> str:
    a = action
    if a.kind not in VALID_KINDS:
        raise SecurityError(f"type d'action inconnu : {a.kind}")

    if a.kind == "create":
        _require_ws(a.path)
        if os.path.exists(a.path):
            raise SecurityError(f"existe déjà (utiliser 'modify') : {a.path}")
        _ensure_parent(a.path)
        with open(a.path, "w", encoding="utf-8") as f:
            f.write(a.content or "")
        return f"créé : {a.path}"

    if a.kind == "modify":
        _require_ws(a.path)
        if not os.path.exists(a.path):
            raise SecurityError(f"introuvable (utiliser 'create') : {a.path}")
        backup = _archive_dest(a.path)          # sauvegarde avant écrasement
        _ensure_parent(backup)
        shutil.copy2(a.path, backup)
        with open(a.path, "w", encoding="utf-8") as f:
            f.write(a.content or "")
        return f"modifié : {a.path}  (sauvegarde {backup})"

    if a.kind == "move":
        _require_ws(a.path)
        _require_ws(a.dst or "")
        if not os.path.exists(a.path):
            raise SecurityError(f"source introuvable : {a.path}")
        if os.path.exists(a.dst):
            raise SecurityError(f"destination existe déjà : {a.dst}")
        _ensure_parent(a.dst)
        shutil.move(a.path, a.dst)
        return f"déplacé : {a.path} → {a.dst}"

    # archive : seul "retrait" autorisé (jamais de delete)
    _require_ws(a.path)
    if not os.path.exists(a.path):
        raise SecurityError(f"introuvable : {a.path}")
    dst = _archive_dest(a.path)
    _ensure_parent(dst)
    shutil.move(a.path, dst)
    return f"archivé : {a.path} → {dst}"


# --------------------------------------------------------------------------- #
# Boucle de validation
# --------------------------------------------------------------------------- #
def confirm_and_apply(actions: list[Action], assume_yes: bool = False, input_fn=input) -> list[str]:
    """Affiche les aperçus, demande validation, applique. Retourne les résultats."""
    if not actions:
        print("Aucune action proposée.")
        return []
    print("\n=== Actions proposées (validation requise) ===")
    for i, a in enumerate(actions, 1):
        print(f"\n[{i}/{len(actions)}] " + preview(a))
    if not assume_yes:
        try:
            ans = input_fn("\nAppliquer ces actions ? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "o", "yes", "oui"):
            print("⛔ Annulé — aucune modification effectuée.")
            return []
    results = []
    for a in actions:
        try:
            results.append("✅ " + apply(a))
        except SecurityError as e:
            results.append(f"⛔ refusé : {e}")
    print("\n=== Résultat ===")
    for r in results:
        print("  " + r)
    return results
