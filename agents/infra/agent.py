#!/usr/bin/env python3
"""Jarvis — Agent Infrastructure (prototype, lecture seule).

Surveille un serveur via SSH (santé système + Docker) et peut diagnostiquer en
langage naturel via un LLM local.

Sécurité : LECTURE / ANALYSE uniquement. Cet agent n'exécute QUE des commandes
de lecture (uptime, free, df, docker ps, systemctl --failed). Aucune action
mutante (restart, stop, suppression) — celles-ci relèveront d'une couche de
commandes validée, à part (cf. règles de sécurité du projet).

Usage:
    python3 agents/infra/agent.py                      # snapshot santé + Docker
    python3 agents/infra/agent.py --host homeserv01
    python3 agents/infra/agent.py "le disque se remplit, pourquoi ?"   # diagnostic LLM

Config (env):
    JARVIS_REMOTE_HOST  (vide ; ex. homeserv01) hôte SSH à surveiller
    INFRA_MODEL         (qwen3:32b)           modèle de diagnostic
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)
from common import ollama_generate, clean_llm_output, log_event  # noqa: E402
import safe_cmd  # noqa: E402

REMOTE_HOST = os.environ.get("JARVIS_REMOTE_HOST", "")  # ex. via .env : homeserv01
INFRA_MODEL = os.environ.get("INFRA_MODEL", "qwen3:32b")

# Commandes STRICTEMENT en lecture, exécutées en un seul aller SSH.
SNAPSHOT_CMD = r"""
echo '@@@uname';   uname -sr 2>/dev/null
echo '@@@uptime';  uptime 2>/dev/null
echo '@@@mem';     free -h 2>/dev/null | head -2
echo '@@@disk';    df -h / /data "$HOME" 2>/dev/null | sort -u
echo '@@@docker';  (docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null || echo 'docker indisponible')
echo '@@@failed';  (systemctl --failed --no-legend 2>/dev/null | head || true)
echo '@@@top';     (ps -eo pmem,pcpu,comm --sort=-pmem 2>/dev/null | head -6)
"""


def ssh_run(host: str, cmd: str, timeout: int = 15) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", host, cmd],
            capture_output=True, text=True, timeout=timeout + 10,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"erreur SSH : {e}"
    blob = (r.stderr or "") + (r.stdout or "")
    if "login.tailscale.com" in blob or "Tailscale SSH requires" in blob:
        m = re.search(r"https://login\.tailscale\.com/\S+", blob)
        url = m.group(0) if m else f"(lance `ssh {host}` dans un terminal pour obtenir le lien)"
        return False, (f"Tailscale SSH demande une ré-authentification → visite {url} "
                       f"puis réessaie (ou lance `ssh {host}` en interactif).")
    if r.returncode != 0 and not r.stdout:
        return False, f"SSH rc={r.returncode} : {r.stderr.strip()[:200]}"
    return True, r.stdout


_CACHE: dict[str, tuple[float, dict]] = {}      # host -> (timestamp, snapshot)
_CACHE_LOCK = threading.Lock()
CACHE_TTL = float(os.environ.get("JARVIS_INFRA_CACHE_TTL", "30"))  # secondes (0 = désactivé)


def invalidate_cache(host: str | None = None) -> None:
    """Vide le cache (après une action corrective, pour revoir l'état réel)."""
    with _CACHE_LOCK:
        _CACHE.pop(host, None) if host else _CACHE.clear()


def snapshot(host: str = REMOTE_HOST, force: bool = False) -> dict[str, str]:
    if not host:
        return {"_error": "Aucun serveur configuré — définis JARVIS_REMOTE_HOST (ex. dans .env)."}
    now = time.monotonic()
    if not force and CACHE_TTL > 0:
        with _CACHE_LOCK:
            hit = _CACHE.get(host)
            if hit and now - hit[0] < CACHE_TTL:
                return hit[1]
    ok, out = ssh_run(host, SNAPSHOT_CMD)
    if not ok:
        return {"_error": out}
    sections: dict[str, str] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("@@@"):
            cur = line[3:].strip()
            sections[cur] = ""
        elif cur is not None:
            sections[cur] += line + "\n"
    snap = {k: v.strip() for k, v in sections.items()}
    if CACHE_TTL > 0:
        with _CACHE_LOCK:
            _CACHE[host] = (now, snap)
    return snap


def _docker_summary(docker: str) -> str:
    if not docker or "indisponible" in docker:
        return "Docker indisponible"
    rows = [l for l in docker.splitlines() if l.strip()]
    up = sum(1 for l in rows if l.split("\t")[1:2] and l.split("\t")[1].lower().startswith("up"))
    return f"{len(rows)} conteneurs ({up} up)"


def print_status(host: str, snap: dict[str, str]) -> None:
    if "_error" in snap:
        print(f"⛔ {host} injoignable : {snap['_error']}")
        return
    print(f"\n🖥️  {host}  —  {snap.get('uname','?')}")
    print(f"   uptime/charge : {snap.get('uptime','?')}")
    mem = snap.get("mem", "").splitlines()
    if len(mem) >= 2:
        print(f"   mémoire : {mem[1]}")
    print(f"   Docker  : {_docker_summary(snap.get('docker',''))}")
    if snap.get("disk"):
        print("\n   Disque :")
        for l in snap["disk"].splitlines():
            print(f"     {l}")
    if snap.get("docker") and "indisponible" not in snap["docker"]:
        print("\n   Conteneurs :")
        for l in snap["docker"].splitlines():
            cols = l.split("\t")
            if len(cols) >= 2:
                print(f"     {cols[0][:22]:22} {cols[1]}")
    failed = snap.get("failed", "").strip()
    print(f"\n   Services en échec : {'aucun' if not failed else failed}")


def build_prompt(question: str, host: str, snap: dict[str, str]) -> str:
    ctx = "\n".join(f"## {k}\n{v}" for k, v in snap.items() if not k.startswith("_"))
    return (
        "Tu es l'agent Infrastructure de Jarvis. Tu diagnostiques l'état d'un "
        "serveur à partir du snapshot fourni (lecture seule). Réponds en français, "
        "de façon concrète et actionnable. Si tu suggères une commande corrective, "
        "présente-la comme une *proposition à valider* (ne l'exécute pas). Ne te base "
        "que sur le snapshot ; si une donnée manque, dis-le.\n\n"
        f"# Serveur : {host}\n# Snapshot\n{ctx}\n\n# Question\n{question}\n\n# Diagnostic :"
    )


def prepare(question: str, host: str = REMOTE_HOST, model: str = INFRA_MODEL) -> dict:
    """Prend le snapshot et construit le prompt (sans générer). Pour le streaming."""
    snap = snapshot(host)
    if "_error" in snap:
        return {"prompt": None, "model": model, "sources": [], "text": snap["_error"]}
    return {"prompt": build_prompt(question, host, snap), "model": model, "sources": []}


def ask(question: str, host: str = REMOTE_HOST, model: str = INFRA_MODEL) -> dict:
    snap = snapshot(host)
    if "_error" in snap:
        return {"error": snap["_error"]}
    answer = clean_llm_output(ollama_generate(build_prompt(question, host, snap), model=model))
    return {"answer": answer, "snapshot": snap}


def propose_fix(problem: str, host: str = REMOTE_HOST, model: str = INFRA_MODEL) -> str:
    """Demande au LLM UNE commande corrective (depuis le snapshot). 'NONE' si rien de sûr."""
    snap = snapshot(host)
    if "_error" in snap:
        return "NONE"
    ctx = "\n".join(f"## {k}\n{v}" for k, v in snap.items() if not k.startswith("_"))
    prompt = (
        "Tu es l'agent Infrastructure de Jarvis. À partir du snapshot serveur et du "
        "problème décrit, propose EXACTEMENT UNE commande shell corrective à exécuter "
        f"sur {host}. Réponds UNIQUEMENT par la commande (une seule ligne, sans backticks, "
        "sans explication). Préfère les commandes idempotentes (`docker compose up -d`, "
        "`docker restart`). N'utilise JAMAIS de commande destructive (rm, down -v, prune). "
        "Si aucune correction sûre n'est évidente, réponds: NONE.\n\n"
        f"# Snapshot\n{ctx}\n\n# Problème\n{problem}\n\n# Commande :"
    )
    return clean_llm_output(ollama_generate(prompt, model=model)).strip().splitlines()[0].strip()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — agent Infrastructure (monitoring SSH, lecture seule)")
    p.add_argument("question", nargs="*", help="question de diagnostic (sinon: snapshot)")
    p.add_argument("--host", default=REMOTE_HOST, help=f"hôte SSH (défaut {REMOTE_HOST})")
    p.add_argument("--model", default=INFRA_MODEL, help="modèle Ollama de diagnostic")
    p.add_argument("--run", metavar="CMD", default=None,
                   help="exécuter une commande corrective (validation via safe_cmd)")
    p.add_argument("--fix", metavar="PROBLÈME", default=None,
                   help="l'agent propose UNE commande corrective puis demande validation")
    p.add_argument("--yes", action="store_true", help="(run/fix) exécuter sans validation — sandbox/tests")
    a = p.parse_args(argv)

    # --- Action corrective directe ---
    if a.run:
        res = safe_cmd.confirm_and_run(safe_cmd.Command(a.host, a.run), assume_yes=a.yes)
        outcome = "refused/cancelled" if res is None else ("ok" if res["rc"] == 0 else "rc!=0")
        if res is not None:
            invalidate_cache(a.host)
        log_event("infra", "run", a.run, target=a.host, outcome=outcome)
        return 0

    # --- Correction proposée par l'agent (propose -> validation -> exécution) ---
    if a.fix:
        cmd = propose_fix(a.fix, host=a.host, model=a.model)
        if not cmd or cmd.upper() == "NONE":
            print("L'agent n'a pas de commande corrective sûre à proposer.")
            log_event("infra", "fix", a.fix, target=a.host, outcome="no_proposal")
            return 0
        print(f"💡 Commande proposée par l'agent pour : {a.fix}")
        res = safe_cmd.confirm_and_run(safe_cmd.Command(a.host, cmd), assume_yes=a.yes)
        outcome = "refused/cancelled" if res is None else ("ok" if res["rc"] == 0 else "rc!=0")
        if res is not None:
            invalidate_cache(a.host)
        log_event("infra", "fix", f"{a.fix} :: {cmd}", target=a.host, outcome=outcome)
        return 0

    if a.question:
        out = ask(" ".join(a.question), host=a.host, model=a.model)
        if "error" in out:
            print(f"⛔ {a.host} : {out['error']}", file=sys.stderr)
            return 1
        print(f"\n🖥️  {a.host} — diagnostic\n")
        print(out["answer"])
        return 0

    print_status(a.host, snapshot(a.host))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
