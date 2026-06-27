#!/usr/bin/env python3
"""Jarvis — Coordinateur central (prototype).

Point d'entrée unique. Comprend la demande, choisit l'agent adapté (et donc le
modèle), délègue, et renvoie la réponse. Version starter du « Coordinateur » de
la vision Jarvis Local.

Routage :
  1. Override explicite (--agent) ou présence de --project  -> direct.
  2. Règles rapides par mots-clés (code/dev vs connaissances/vault).
  3. Si ambigu -> classifieur LLM léger local (qwen3:4b) qui tranche.

Agents disponibles :
  - obsidian : connaissances / vault Obsidian (RAG via Mnemo)
  - dev      : analyse de code d'un projet

Usage:
    python3 jarvis.py "ma question"
    python3 jarvis.py --agent dev --project /chemin "refacto X ?"
    python3 jarvis.py --explain "qu'est-ce que je sais sur le RAG ?"
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(ROOT, "agents")
sys.path.insert(0, AGENTS_DIR)
from common import (  # noqa: E402
    ollama_generate, clean_llm_output, get_active_project, set_active_project,
    log_event, read_events,
)
import safe_fs  # noqa: E402

ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "qwen3:4b")

# Signaux de routage (mots-clés, minuscules, sans accents gérés à la volée).
DEV_KW = [
    "code", "coder", "fichier", "fonction", "classe", "méthode", "refactor",
    "refacto", "bug", "erreur", "exception", "stacktrace", "script", "module",
    "repo", "dépôt", "git", "api", "endpoint", "test", "compile", "build",
    "python", "javascript", "typescript", "react", "node", "css", "html",
    "architecture du code", "implémente", "implementation", "débogue", "debug",
]
KNOW_KW = [
    "vault", "note", "notes", "obsidian", "connaissance", "connaissances",
    "formation", "concept", "daily", "session", "résume mes", "qu'est-ce que je sais",
    "ce que je sais", "mon vault", "mes notes", "documentation", "moc", "savoir",
]
INFRA_KW = [
    "serveur", "server", "docker", "conteneur", "container", "homeserv", "infra",
    "infrastructure", "systemd", "tailscale", "uptime", "ram serveur", "disque serveur",
    "self-hosted", "self-hébergé", "ssh", "healthy", "unhealthy", "conteneurs",
]
RESEARCH_KW = [
    "web", "internet", "en ligne", "sur le net", "actualité", "actualités", "news",
    "météo", "google", "cherche sur", "recherche web", "prix de", "cours de",
    "quoi de neuf", "en 2026",
]


def _norm(s: str) -> str:
    """minuscule + sans accents (pour matcher même si l'utilisateur tape sans accents)."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                    if unicodedata.category(c) != "Mn")


def _score(text: str, keywords: list[str]) -> int:
    t = _norm(text)
    return sum(1 for kw in keywords if _norm(kw) in t)


def _has_path(text: str) -> bool:
    return bool(re.search(r"(^|\s)(/|\./|~/)[\w./-]+", text))


def classify_llm(question: str) -> str:
    """Tranche les cas ambigus via un LLM local. Retourne l'un des 4 agents."""
    prompt = (
        "Tu es le routeur de Jarvis. Choisis L'UNIQUE agent le plus adapté à la demande :\n"
        "- obsidian : chercher dans les NOTES personnelles / vault Obsidian / connaissances de l'utilisateur.\n"
        "- dev : analyser ou écrire du CODE, un projet logiciel, des fichiers source.\n"
        "- infra : état d'un SERVEUR, conteneurs Docker, services, SSH, auto-hébergement.\n"
        "- research : information À JOUR sur le WEB (actualités, faits récents, recherche internet).\n"
        "Réponds par UN SEUL mot : obsidian, dev, infra ou research.\n\n"
        f"Demande : {question}\nAgent :"
    )
    out = clean_llm_output(ollama_generate(prompt, model=ROUTER_MODEL, temperature=0.0)).lower()
    for agent in ("research", "infra", "obsidian", "dev"):
        if agent in out:
            return agent
    return "obsidian"  # défaut prudent (lecture seule)


def route(question: str, project_given: bool) -> tuple[str, str]:
    """Retourne (agent, raison)."""
    if project_given:
        return "dev", "projet fourni (--project)"
    if _has_path(question):
        return "dev", "chemin de fichier détecté dans la question"
    dev = _score(question, DEV_KW)
    know = _score(question, KNOW_KW)
    infra = _score(question, INFRA_KW)
    research = _score(question, RESEARCH_KW)
    top = max(dev, know, infra, research)
    if top == 0:
        return classify_llm(question), f"ambigu -> classifieur {ROUTER_MODEL}"
    if research == top:
        return "research", f"signaux web ({research})"
    if infra == top:
        return "infra", f"signaux infra ({infra})"
    if dev > know:
        return "dev", f"signaux code ({dev}) > connaissances ({know})"
    if know > dev:
        return "obsidian", f"signaux connaissances ({know}) > code ({dev})"
    return classify_llm(question), f"ambigu (dev={dev}, know={know}) -> classifieur {ROUTER_MODEL}"


def route_write(target: str) -> tuple[str, str]:
    """Choisit l'agent pour une écriture selon la cible."""
    ws = safe_fs.workspace_of(target)
    if ws and ws[0] == "obsidian":
        return "obsidian", "cible dans le vault Obsidian"
    if target.lower().endswith((".md", ".markdown")):
        return "obsidian", "cible Markdown (note)"
    return "dev", "cible = fichier de code"


_LOADED: dict = {}


def _load(path: str, name: str):
    """Charge un module d'agent, mémoïsé : chargé une fois puis réutilisé
    (évite la ré-exécution à chaque requête et fait persister les caches internes,
    ex. le cache snapshot de l'agent infra)."""
    if name in _LOADED:
        return _LOADED[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LOADED[name] = mod
    return mod


REPL_HELP = """\
Commandes :
  <texte libre>            poser une question (routage auto : connaissances / code / infra / web)
  /projet                  lister les projets (local)
  /use <nom>               définir le projet actif (contexte de l'agent code)
  /ecrire <cible> | <consigne>   proposer une écriture (note ou fichier) → validation
  /infra                   état du serveur (santé + conteneurs)
  /fix <problème>          l'agent infra propose une commande corrective → validation
  /historique [N]          dernières interactions journalisées
  /rappel <question>       résumé du journal en langage naturel
  /oubli                   effacer le contexte de conversation (questions de suivi)
  /aide                    cette aide
  /quitter                 sortir
(Les questions de suivi marchent : « et la suite ? », « détaille le point 2 ».)
"""


def _repl_projects(line: str) -> None:
    ws = _load(os.path.join(AGENTS_DIR, "workspace", "agent.py"), "workspace_agent")
    if line.startswith("/use"):
        name = line[len("/use"):].strip()
        if not name:
            print("usage : /use <nom>")
            return
        items = {e["name"].lower(): e for e in ws.catalog(local_only=True)}
        e = items.get(name.lower())
        if not e:
            print(f"projet introuvable : {name}")
            return
        set_active_project({"name": e["name"], "local": e.get("local"), "remote": e.get("remote")})
        print(f"✅ projet actif : {e['name']}" + (f"  ({e['local']})" if e.get("local") else ""))
    else:
        ws.print_catalog(ws.catalog(local_only=True))


def _repl_write(line: str) -> None:
    rest = line.split(" ", 1)[1].strip() if " " in line else ""
    if "|" in rest:
        target, instr = (s.strip() for s in rest.split("|", 1))
    else:
        target = rest
        instr = input("consigne : ").strip()
    if not target or not instr:
        print("usage : /ecrire <cible> | <consigne>")
        return
    agent = route_write(target)[0]
    active = get_active_project() or {}
    if agent == "obsidian":
        mod = _load(os.path.join(AGENTS_DIR, "obsidian", "agent.py"), "obsidian_agent")
        action, _ = mod.enrich(target, instr)
    else:
        mod = _load(os.path.join(AGENTS_DIR, "dev", "agent.py"), "dev_agent")
        action = mod.propose_write(target, instr, project=active.get("local") or ROOT)
    results = safe_fs.confirm_and_apply([action])
    log_event(agent, "write", instr, target=target, outcome="applied" if results else "cancelled")


def _repl_infra(status: bool, problem: str = "") -> None:
    mod = _load(os.path.join(AGENTS_DIR, "infra", "agent.py"), "infra_agent")
    if status:
        mod.print_status(mod.REMOTE_HOST, mod.snapshot())
        return
    cmd = mod.propose_fix(problem, host=mod.REMOTE_HOST)
    if not cmd or cmd.upper() == "NONE":
        print("Aucune commande corrective sûre proposée.")
        log_event("infra", "fix", problem, target=mod.REMOTE_HOST, outcome="no_proposal")
        return
    print(f"💡 Proposition pour : {problem}")
    res = mod.safe_cmd.confirm_and_run(mod.safe_cmd.Command(mod.REMOTE_HOST, cmd))
    outcome = "refused/cancelled" if res is None else ("ok" if res["rc"] == 0 else "rc!=0")
    if res is not None:
        mod.invalidate_cache(mod.REMOTE_HOST)
    log_event("infra", "fix", f"{problem} :: {cmd}", target=mod.REMOTE_HOST, outcome=outcome)


def _repl_handle(line: str, history: list) -> None:
    low = line.lower()
    if low in ("/aide", "/help", "?"):
        print(REPL_HELP)
    elif low in ("/oubli", "/reset", "/clear"):
        history.clear()
        print("🧹 Contexte de conversation effacé.")
    elif low.startswith("/projet") or low.startswith("/use"):
        _repl_projects(line)
    elif low.startswith("/ecrire") or low.startswith("/write"):
        _repl_write(line)
    elif low.startswith("/infra"):
        _repl_infra(status=True)
    elif low.startswith("/fix"):
        _repl_infra(status=False, problem=line.split(" ", 1)[1].strip() if " " in line else "")
    elif low.startswith("/historique") or low.startswith("/history"):
        parts = line.split()
        _print_history(int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20)
    elif low.startswith("/rappel") or low.startswith("/recall"):
        q = line.split(" ", 1)[1].strip() if " " in line else ""
        print(recall(q) if q else "usage : /rappel <question>")
    elif line.startswith("/"):
        print("commande inconnue — /aide")
    else:
        res = answer(line, history=history)
        print(f"\n🧭 {res['agent']} — {res['reason']}")
        if res.get("note"):
            print(res["note"])
        print("\n" + res["text"])
        for i, src in enumerate(res.get("sources", []), 1):
            if i == 1:
                print("\n— Sources —")
            print(f"  [{i}] {src}")
        history.append({"q": line, "a": res["text"]})


def repl() -> int:
    active = get_active_project() or {}
    history: list = []          # mémoire conversationnelle de la session
    print("🤖 Jarvis — chat local. Tape ta demande, ou /aide. (/quitter pour sortir)")
    if active.get("name"):
        print(f"   projet actif : {active['name']}")
    while True:
        try:
            line = input("\njarvis› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("/quitter", "/quit", "/exit", "quit", "exit"):
            break
        try:
            _repl_handle(line, history)
        except Exception as e:
            print(f"⛔ erreur : {e}")
    print("À bientôt.")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — coordinateur central (prototype)")
    p.add_argument("question", nargs="*")
    p.add_argument("--agent", choices=["auto", "obsidian", "dev", "infra", "research"], default="auto")
    p.add_argument("--history", type=int, nargs="?", const=20, default=None,
                   help="afficher les N dernières interactions journalisées (défaut 20)")
    p.add_argument("--recall", default=None,
                   help="question en langage naturel sur l'historique de Jarvis")
    p.add_argument("--project", default=None, help="(agent dev) racine du projet")
    p.add_argument("--limit", type=int, default=5, help="(agent obsidian) nb de passages")
    p.add_argument("--prefix", default=None, help="(agent obsidian) sous-dossier du vault")
    p.add_argument("--explain", action="store_true", help="affiche la décision de routage")
    p.add_argument("--write", metavar="CIBLE", default=None,
                   help="mode écriture : la question = la consigne, CIBLE = note ou fichier à produire/éditer")
    p.add_argument("--no-context", action="store_true", help="(écriture note) sans contexte Mnemo")
    p.add_argument("--model", default=None, help="forcer le modèle Ollama")
    p.add_argument("--yes", action="store_true", help="(écriture) appliquer sans validation — sandbox/tests")
    a = p.parse_args(argv)

    # --- Mémoire d'orchestration : consultation ---
    if a.history is not None:
        return _print_history(a.history)
    if a.recall:
        return _recall(a.recall, a.model)

    question = " ".join(a.question)
    if not question and not a.write:
        return repl()        # aucun argument → chat interactif
    if not question and a.write:
        p.error("--write requiert une consigne")

    # Projet actif (agent Workspace) → contexte par défaut de l'agent Dev.
    active = get_active_project() or {}
    active_local = active.get("local")
    dev_project = a.project or active_local or ROOT

    # --- Mode écriture : routage puis délégation à la capacité d'action de l'agent ---
    if a.write:
        if a.agent != "auto":
            agent, reason = a.agent, "forcé (--agent)"
        else:
            agent, reason = route_write(a.write)
        print(f"🧭 Coordinateur (écriture) → agent **{agent}**  ({reason})")
        if agent == "obsidian":
            mod = _load(os.path.join(AGENTS_DIR, "obsidian", "agent.py"), "obsidian_agent")
            kw = {"use_context": not a.no_context, "limit": a.limit}
            if a.model:
                kw["model"] = a.model
            action, hits = mod.enrich(a.write, question, **kw)
            for h in hits:
                print(f"  contexte: {h.get('path')} ({h.get('score', 0):.2f})")
        else:
            mod = _load(os.path.join(AGENTS_DIR, "dev", "agent.py"), "dev_agent")
            kw = {"project": dev_project}
            if a.model:
                kw["model"] = a.model
            action = mod.propose_write(a.write, question, **kw)
        results = safe_fs.confirm_and_apply([action], assume_yes=a.yes)
        log_event(agent, "write", question, target=a.write,
                  outcome="applied" if results else "cancelled")
        return 0

    res = answer(question, agent_override=(None if a.agent == "auto" else a.agent),
                 limit=a.limit, prefix=a.prefix, project=a.project)
    if a.explain or a.agent == "auto":
        print(f"🧭 Coordinateur → agent **{res['agent']}**  ({res['reason']})")
    if res.get("note"):
        print(res["note"])
    print(f"\n❓ {question}\n")
    print(res["text"])
    for i, src in enumerate(res.get("sources", []), 1):
        if i == 1:
            print("\n— Sources —")
        print(f"  [{i}] {src}")
    return res["rc"]


def _run_infra(question: str) -> int:
    mod = _load(os.path.join(AGENTS_DIR, "infra", "agent.py"), "infra_agent")
    out = mod.ask(question)
    if "error" in out:
        print(f"⛔ infra : {out['error']}", file=sys.stderr)
        return 1
    print(f"\n❓ {question}\n")
    print(out["answer"])
    return 0


def prepare_answer(question: str, agent_override: str | None = None, limit: int = 5,
                   prefix: str | None = None, project: str | None = None,
                   history: list | None = None) -> dict:
    """Routage + récupération du contexte SANS génération (pour le streaming).
    `history` = [{q, a}, …] pour les questions de suivi.
    Retourne {agent, reason, prompt, model, sources, note, text?, logtarget}."""
    active = get_active_project() or {}
    active_local = active.get("local")
    if agent_override:
        agent, reason = agent_override, "forcé (--agent)"
    else:
        # Question de suivi : router en tenant compte du tour précédent.
        route_q = question if not history else f"{history[-1].get('q', '')} {question}".strip()
        agent, reason = route(route_q, project_given=project is not None)

    if agent == "infra":
        mod = _load(os.path.join(AGENTS_DIR, "infra", "agent.py"), "infra_agent")
        p = mod.prepare(question, history=history)
        note, logtarget = None, None
    elif agent == "research":
        mod = _load(os.path.join(AGENTS_DIR, "research", "agent.py"), "research_agent")
        p = mod.prepare(question, history=history)
        note, logtarget = None, None
    elif agent == "dev":
        proj = project or active_local or ROOT
        mod = _load(os.path.join(AGENTS_DIR, "dev", "agent.py"), "dev_agent")
        p = mod.prepare(question, proj, history=history)
        note = f"📁 {p.get('project', proj)}" + (f" ({p['n_files']} fichiers)" if p.get("n_files") else "")
        logtarget = proj
    else:
        mod = _load(os.path.join(AGENTS_DIR, "obsidian", "agent.py"), "obsidian_agent")
        p = mod.prepare(question, limit=limit, prefix=prefix, history=history)
        note, logtarget = None, None
    return {"agent": agent, "reason": reason, "prompt": p.get("prompt"), "model": p.get("model"),
            "sources": p.get("sources", []), "text": p.get("text"), "note": note, "logtarget": logtarget}


def answer(question: str, agent_override: str | None = None, limit: int = 5,
           prefix: str | None = None, project: str | None = None, history: list | None = None) -> dict:
    """Routage + génération LECTURE (sans print). Réutilisé par CLI/REPL.
    Retourne {agent, reason, text, sources, rc, note}."""
    prep = prepare_answer(question, agent_override, limit, prefix, project, history)
    if prep.get("prompt"):
        text, rc = clean_llm_output(ollama_generate(prep["prompt"], model=prep["model"])), 0
    else:
        text = prep.get("text") or ""
        rc = 0 if text else 1
    log_event(prep["agent"], "read", question, target=prep.get("logtarget"),
              outcome="ok" if rc == 0 else "error")
    return {"agent": prep["agent"], "reason": prep["reason"], "text": text,
            "sources": prep.get("sources", []), "rc": rc, "note": prep.get("note")}


def _print_history(n: int) -> int:
    evs = read_events(limit=n)
    if not evs:
        print("Journal vide.")
        return 0
    print(f"\n{'QUAND':19} {'AGENT':9} {'MODE':7} {'ISSUE':9} REQUÊTE")
    for e in evs:
        print(f"{e.get('ts',''):19} {e.get('agent',''):9} {e.get('mode',''):7} "
              f"{e.get('outcome',''):9} {e.get('request','')[:60]}")
    return 0


def recall(question: str, model: str | None = None) -> str:
    """Synthèse LLM du journal d'orchestration. Réutilisé par la CLI et le serveur."""
    evs = read_events(limit=200)
    if not evs:
        return "Journal vide — rien à rappeler."
    lines = [
        f"{e.get('ts','')} [{e.get('agent','')}/{e.get('mode','')}/{e.get('outcome','')}] "
        f"{e.get('request','')}" + (f" -> {e['target']}" if e.get("target") else "")
        for e in evs
    ]
    prompt = (
        "Voici le journal des actions de l'assistant Jarvis. Réponds en français à la "
        "question, en t'appuyant UNIQUEMENT sur ce journal. Sois concret (dates, agents, "
        "actions). Si l'info n'y est pas, dis-le.\n\n"
        "# Journal\n" + "\n".join(lines) + f"\n\n# Question\n{question}\n\n# Réponse :"
    )
    return clean_llm_output(ollama_generate(prompt, model=model or "qwen3:4b"))


def _recall(question: str, model: str | None) -> int:
    print(recall(question, model))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
