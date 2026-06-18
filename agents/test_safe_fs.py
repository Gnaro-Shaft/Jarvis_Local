#!/usr/bin/env python3
"""Tests de la couche d'écriture sécurisée (safe_fs)."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safe_fs  # noqa: E402

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    ws = tempfile.mkdtemp(prefix="jarvis-safefs-")
    os.environ["JARVIS_WORKSPACES"] = ws
    j = lambda *p: os.path.join(ws, *p)

    # 1. create
    safe_fs.confirm_and_apply([safe_fs.create(j("note.md"), "v1\nligne2\n")], assume_yes=True)
    check(os.path.exists(j("note.md")), "create : fichier écrit")
    check(open(j("note.md")).read() == "v1\nligne2\n", "create : contenu correct")

    # 2. create refusé si existe déjà
    try:
        safe_fs.apply(safe_fs.create(j("note.md"), "x"))
        check(False, "create existant : devrait lever")
    except safe_fs.SecurityError:
        check(True, "create existant : refusé (→ modify)")

    # 3. modify + sauvegarde de l'ancienne version dans Archive_IA
    safe_fs.confirm_and_apply([safe_fs.modify(j("note.md"), "v2 modifié\n")], assume_yes=True)
    check(open(j("note.md")).read() == "v2 modifié\n", "modify : nouveau contenu")
    arch = j(safe_fs.ARCHIVE_DIRNAME)
    backups = [r for _, _, fs in os.walk(arch) for r in fs] if os.path.isdir(arch) else []
    check(any("note.md" in b for b in backups), "modify : ancienne version sauvegardée dans Archive_IA")

    # 4. move
    safe_fs.confirm_and_apply([safe_fs.move(j("note.md"), j("sub", "note.md"))], assume_yes=True)
    check(not os.path.exists(j("note.md")) and os.path.exists(j("sub", "note.md")), "move : déplacé")

    # 5. archive = seul retrait (pas de delete) → original parti, copie dans Archive_IA
    safe_fs.confirm_and_apply([safe_fs.archive(j("sub", "note.md"))], assume_yes=True)
    check(not os.path.exists(j("sub", "note.md")), "archive : retiré de l'emplacement")
    all_arch = [os.path.join(d, f) for d, _, fs in os.walk(arch) for f in fs]
    check(len(all_arch) >= 2, "archive : données conservées dans Archive_IA (rien perdu)")

    # 6. confinement : action hors zone refusée
    for act in (safe_fs.create("/etc/evil.txt", "x"), safe_fs.archive("/etc/hosts")):
        try:
            safe_fs.apply(act)
            check(False, f"confinement : {act.kind} hors zone devrait être refusé")
        except safe_fs.SecurityError:
            check(True, f"confinement : {act.kind} hors zone refusé")

    # 7. validation refusée (assume_yes=False, réponse 'n') → aucune action
    before = set(os.listdir(ws))
    safe_fs.confirm_and_apply([safe_fs.create(j("ne_pas_creer.md"), "x")],
                              assume_yes=False, input_fn=lambda _="": "n")
    check(not os.path.exists(j("ne_pas_creer.md")), "validation refusée : rien n'est appliqué")
    check(set(os.listdir(ws)) == before, "validation refusée : workspace inchangé")

    # 8. garantie : aucun APPEL de suppression dans le module (forme `xxx(`).
    #    On ignore les mentions en docstring/commentaire en exigeant la parenthèse.
    src = open(safe_fs.__file__).read()
    check(not any(x in src for x in ("os.remove(", "os.unlink(", "rmtree(")),
          "garantie : aucun appel de suppression dans safe_fs")

    # --- bilan ---
    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS safe_fs ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK   (workspace de test : {ws})")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
