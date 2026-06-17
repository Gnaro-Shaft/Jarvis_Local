#!/usr/bin/env python3
"""Jarvis — Agent Développement (prototype).

Analyse un projet de code et répond à des questions techniques (architecture,
fonctionnement, pistes d'amélioration, génération/refacto proposée) avec un LLM
coder local via Ollama.

Sécurité (cf. vision Jarvis Local) : LECTURE / ANALYSE uniquement. L'agent ne
crée, ne modifie, ni ne supprime aucun fichier — il *propose* du code en sortie
texte ; toute application reste soumise à la validation de l'utilisateur.

Usage:
    python3 agents/dev/agent.py --project /chemin/projet "ta question"
    python3 agents/dev/agent.py "explique l'architecture"        # défaut: ce repo

Config (env):
    OLLAMA_URL        (http://localhost:11434)
    DEV_MODEL         (qwen3-coder:30b)     modèle coder de synthèse
    DEV_CTX_BUDGET    (48000)               budget de contexte en caractères
"""
from __future__ import annotations

import argparse
import os
import sys

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)
from common import ollama_generate, clean_llm_output  # noqa: E402
import safe_fs  # noqa: E402

DEV_MODEL = os.environ.get("DEV_MODEL", "qwen3-coder:30b")
CTX_BUDGET = int(os.environ.get("DEV_CTX_BUDGET", "48000"))
REPO_ROOT = os.path.dirname(AGENTS_DIR)

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", "target", ".claude", ".claude-flow", ".swarm", ".obsidian",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".idea", ".vscode",
}
CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".yaml", ".yml",
    ".toml", ".sh", ".rs", ".go", ".java", ".rb", ".css", ".html", ".sql", ".env.example",
}
PER_FILE_CAP = 6000  # caractères max lus par fichier


def collect_project(root: str, budget: int) -> tuple[list[str], list[tuple[str, str]]]:
    """Retourne (arbre des fichiers, [(chemin_relatif, contenu)]) sous budget."""
    tree: list[str] = []
    files: list[tuple[str, str]] = []
    spent = 0
    # README d'abord (haute valeur), puis le reste trié.
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in CODE_EXT or fn.lower().startswith("readme"):
                paths.append(os.path.join(dirpath, fn))
    paths.sort(key=lambda p: (0 if os.path.basename(p).lower().startswith("readme") else 1, p))

    for full in paths:
        rel = os.path.relpath(full, root)
        tree.append(rel)
        if spent >= budget:
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(PER_FILE_CAP + 1)
        except OSError:
            continue
        truncated = len(content) > PER_FILE_CAP
        content = content[:PER_FILE_CAP]
        if spent + len(content) > budget:
            content = content[: budget - spent]
            truncated = True
        if truncated:
            content += "\n... [tronqué]"
        files.append((rel, content))
        spent += len(content)
    return tree, files


def build_prompt(question: str, project: str, tree: list[str], files: list[tuple[str, str]]) -> str:
    tree_str = "\n".join(f"  {p}" for p in tree)
    files_str = "\n\n".join(f"=== {rel} ===\n{content}" for rel, content in files)
    return (
        "Tu es l'agent Développement de Jarvis. Tu analyses un projet de code et "
        "réponds en français, de façon précise et concrète, en t'appuyant sur le "
        "code fourni (cite les fichiers concernés). Si tu proposes du code, présente-le "
        "comme une *proposition* (l'utilisateur validera) et n'invente pas de fichiers "
        "absents. Si l'info manque dans le contexte, dis-le.\n\n"
        f"# Projet analysé : {project}\n\n"
        f"# Arborescence (fichiers pertinents)\n{tree_str}\n\n"
        f"# Contenu des fichiers\n{files_str}\n\n"
        f"# Question\n{question}\n\n# Réponse :"
    )


def prepare(question: str, project: str = REPO_ROOT, model: str = DEV_MODEL) -> dict:
    """Collecte le projet et construit le prompt (sans générer). Pour le streaming."""
    project = os.path.abspath(project)
    if not os.path.isdir(project):
        return {"prompt": None, "model": model, "sources": [], "text": f"projet introuvable : {project}"}
    tree, files = collect_project(project, CTX_BUDGET)
    if not files:
        return {"prompt": None, "model": model, "sources": [], "text": f"aucun fichier analysable dans {project}"}
    return {"prompt": build_prompt(question, project, tree, files), "model": model,
            "sources": [], "project": project, "n_files": len(files)}


def ask(question: str, project: str, model: str = DEV_MODEL) -> dict:
    project = os.path.abspath(project)
    if not os.path.isdir(project):
        return {"error": f"projet introuvable : {project}"}
    tree, files = collect_project(project, CTX_BUDGET)
    if not files:
        return {"error": f"aucun fichier de code analysable dans {project}"}
    prompt = build_prompt(question, project, tree, files)
    answer = ollama_generate(prompt, model=model)
    return {"answer": answer, "n_files": len(files), "n_listed": len(tree), "project": project}


def build_write_prompt(target: str, current: str, instruction: str,
                       project: str, tree: list[str], files: list[tuple[str, str]]) -> str:
    tree_str = "\n".join(f"  {p}" for p in tree) or "  (projet vide)"
    files_str = "\n\n".join(f"=== {rel} ===\n{content}" for rel, content in files)
    if files_str:
        files_str = f"\n# Contexte du projet (fichiers existants)\n{files_str}\n"
    base = current if current.strip() else "(fichier inexistant — à créer)"
    return (
        "Tu es l'agent Développement de Jarvis. Tu produis le contenu d'UN fichier.\n"
        "Renvoie UNIQUEMENT le contenu COMPLET du fichier cible — aucun commentaire "
        "hors-code, aucun bloc de code englobant (pas de ```). Respecte les conventions "
        "du projet. Si le fichier existe, préserve ce qui n'est pas concerné par la consigne.\n"
        f"# Projet : {project}\n# Arborescence\n{tree_str}\n{files_str}\n"
        f"# Fichier cible : {os.path.relpath(target, project) if target.startswith(project) else target}\n"
        f"# Contenu actuel\n{base}\n\n"
        f"# Consigne\n{instruction}\n\n# Contenu du fichier :"
    )


def propose_write(target: str, instruction: str, project: str = REPO_ROOT,
                  model: str = DEV_MODEL) -> safe_fs.Action:
    """Propose l'écriture d'un fichier (NE l'applique PAS — validation via safe_fs)."""
    target = os.path.abspath(os.path.expanduser(target))
    project = os.path.abspath(project)
    current = ""
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            current = f.read()
    tree, files = collect_project(project, CTX_BUDGET) if os.path.isdir(project) else ([], [])
    new = clean_llm_output(
        ollama_generate(build_write_prompt(target, current, instruction, project, tree, files), model=model)
    )
    return safe_fs.modify(target, new) if current else safe_fs.create(target, new)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — agent Développement (analyse de code, lecture seule)")
    p.add_argument("question", nargs="+", help="la question / tâche")
    p.add_argument("--project", default=REPO_ROOT, help="racine du projet (défaut: ce repo)")
    p.add_argument("--model", default=DEV_MODEL, help=f"modèle Ollama (défaut {DEV_MODEL})")
    p.add_argument("--write", metavar="FICHIER", default=None,
                   help="mode écriture : produire/éditer le FICHIER (la question = la consigne)")
    p.add_argument("--yes", action="store_true",
                   help="(write) appliquer sans validation interactive — À ÉVITER hors sandbox")
    a = p.parse_args(argv)
    question = " ".join(a.question)

    # --- Mode écriture : proposition -> validation -> application (safe_fs) ---
    if a.write:
        action = propose_write(a.write, question, a.project, model=a.model)
        safe_fs.confirm_and_apply([action], assume_yes=a.yes)
        return 0

    out = ask(question, a.project, model=a.model)
    if "error" in out:
        print(f"⛔ {out['error']}", file=sys.stderr)
        return 1
    print(f"\n📁 {out['project']}  ({out['n_files']} fichiers lus / {out['n_listed']} listés, modèle {a.model})")
    print(f"❓ {question}\n")
    print(out["answer"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
