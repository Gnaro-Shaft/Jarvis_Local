#!/usr/bin/env python3
"""Tests des briques partagées (common) : nettoyage LLM, journal, état."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    # --- clean_llm_output ---
    check(common.clean_llm_output("<think>raisonnement</think>\nRéponse") == "Réponse\n",
          "clean: retire le bloc <think>")
    check(common.clean_llm_output("```python\ncode\n```") == "code\n",
          "clean: retire les fences ```")
    check(common.clean_llm_output("texte simple") == "texte simple\n",
          "clean: laisse le texte normal")

    # --- journal (isolé dans un fichier temporaire) ---
    tmp = tempfile.mkdtemp(prefix="jarvis-test-")
    common.journal_path = lambda: os.path.join(tmp, "journal.jsonl")
    common.log_event("dev", "read", "q1", outcome="ok")
    common.log_event("infra", "run", "q2", outcome="ok", target="srv")
    evs = common.read_events()
    check(len(evs) == 2, "journal: 2 entrées enregistrées")
    check(evs[0]["agent"] == "dev" and evs[1]["mode"] == "run", "journal: ordre + contenu")
    check(len(common.read_events(limit=1)) == 1, "journal: --limit")
    fil = common.read_events(agent="infra")
    check(len(fil) == 1 and fil[0]["target"] == "srv", "journal: filtre par agent")

    # --- état (projet actif) isolé ---
    common.state_path = lambda: os.path.join(tmp, "state.json")
    check(common.get_active_project() is None, "état: aucun projet actif au départ")
    common.set_active_project({"name": "v8", "local": "/x/v8"})
    got = common.get_active_project()
    check(got and got["name"] == "v8" and got["local"] == "/x/v8", "état: set puis get")

    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS common ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
