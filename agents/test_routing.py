#!/usr/bin/env python3
"""Tests du routage du coordinateur (jarvis) — uniquement la logique par mots-clés
(pas d'appel au classifieur LLM, qui nécessite Ollama)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis  # noqa: E402

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    # --- route() sur des cas tranchés par mots-clés (pas de LLM) ---
    cases = {
        "analyse le code de safe_cmd": "dev",
        "qu'est-ce que je sais sur le RAG dans mes notes": "obsidian",
        "comment vont les conteneurs docker du serveur": "infra",
        "quelles sont les actualités sur l'IA": "research",
        "cherche le prix du bitcoin en ligne": "research",
    }
    for q, expected in cases.items():
        got = jarvis.route(q, False)[0]
        check(got == expected, f"route '{q[:38]}' = {got} (attendu {expected})")

    # --- override par contexte ---
    check(jarvis.route("peu importe", True)[0] == "dev", "route: --project force dev")
    check(jarvis.route("regarde ~/proj/fichier.py", False)[0] == "dev", "route: chemin → dev")

    # --- normalisation insensible aux accents ---
    check(jarvis._norm("Récent ÉTÉ") == "recent ete", "_norm: minuscule + sans accents")
    check(jarvis._score("actualites du jour", jarvis.RESEARCH_KW) >= 1,
          "_score: 'actualites' (sans accent) matche 'actualité'")

    # --- pas de faux positif web sur des mots temporels génériques ---
    check(jarvis._score("résume les dernières décisions du projet", jarvis.RESEARCH_KW) == 0,
          "RESEARCH_KW: 'dernières/décisions' ne déclenche pas le web")

    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS routing ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
