#!/usr/bin/env python3
"""Tests de l'agent Dev : tokenisation, scoring, sélection de fichiers pertinents."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

AGENTS = os.path.dirname(os.path.abspath(__file__))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dev = _load(os.path.join(AGENTS, "dev", "agent.py"), "dev_agent")
results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    # --- _tokenize ---
    toks = dev._tokenize("Où est l'authentification (auth) ?")
    check("authentification" in toks and "auth" in toks, "tokenize: garde les mots utiles")
    check("le" not in toks and "est" not in toks, "tokenize: retire les mots vides")
    check("auth" in dev._tokenize("AUTH"), "tokenize: insensible à la casse")

    # --- _score : nom de fichier pondéré + contenu ---
    s_name = dev._score("auth.py", "x", {"auth"})
    s_content = dev._score("x.py", "auth auth", {"auth"})
    check(s_name > 0 and s_content > 0, "score: matche nom et contenu")
    check(s_name >= s_content, "score: le nom de fichier pèse plus que le contenu")

    # --- collect_project : le fichier pertinent passe en tête ---
    proj = tempfile.mkdtemp(prefix="jarvis-dev-")
    with open(os.path.join(proj, "alpha.py"), "w") as f:
        f.write("def login():\n    # gestion de l'authentification\n    return True\n")
    with open(os.path.join(proj, "beta.py"), "w") as f:
        f.write("def addition(a, b):\n    return a + b\n")
    with open(os.path.join(proj, "README.md"), "w") as f:
        f.write("# Projet de démonstration\n")

    tree, files = dev.collect_project(proj, 50000, "authentification login")
    rels = [r for r, _ in files]
    check(rels and rels[0] == "alpha.py", f"collect: fichier pertinent en tête ({rels[:2]})")
    check(set(tree) >= {"alpha.py", "beta.py", "README.md"}, "collect: arborescence complète")

    # --- budget respecté ---
    _, small = dev.collect_project(proj, 20, "authentification")
    total = sum(len(c) for _, c in small)
    check(total <= 20 + dev.PER_FILE_CAP, "collect: budget approximativement respecté")

    # --- sans question : README d'abord ---
    _, files2 = dev.collect_project(proj, 50000, None)
    check(files2[0][0] == "README.md", "collect: sans question, README en tête")

    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS dev ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
