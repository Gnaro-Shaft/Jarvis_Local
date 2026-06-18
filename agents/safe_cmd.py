#!/usr/bin/env python3
"""Jarvis — couche de commandes sécurisées (proposition → validation → exécution).

Analogue de `safe_fs`, mais pour les commandes shell (locales ou distantes via
SSH). Sert aux actions correctives d'infrastructure (`docker compose up -d`,
`docker restart`, …) proposées par un agent.

Règles de sécurité (cf. vision Jarvis Local) :
  - Une commande est classée : `read` (lecture, faible risque), `mutating`
    (modifie l'état → VALIDATION REQUISE), ou `forbidden` (destructif → REFUSÉ).
  - **Destructif interdit** : `rm`, `docker rm/volume rm/prune`, `compose down`,
    `mkfs`, `dd`, `shutdown`/`reboot`, `drop database`, fork-bomb… → `SecurityError`.
    (cohérent avec « suppression interdite »).
  - **Confinement** : seuls les hôtes autorisés (`JARVIS_ALLOWED_HOSTS`) sont joignables.
  - Aucune commande mutante n'est exécutée sans validation `[y/N]` (sauf assume_yes).
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

ALLOWED_HOSTS = {"localhost", "local"}
ALLOWED_HOSTS |= {h for h in os.environ.get("JARVIS_ALLOWED_HOSTS", "").split(":") if h}
if os.environ.get("JARVIS_REMOTE_HOST"):  # l'hôte distant configuré est autorisé d'office
    ALLOWED_HOSTS.add(os.environ["JARVIS_REMOTE_HOST"])

# Destructif → toujours refusé. (rm/find -delete/dd… interdits même "simples".)
FORBIDDEN = [
    r"(?:^|[\s;&|])(rm|rmdir|unlink|shred)\s",
    r"(?:^|\s)-delete(?:\s|$)|-exec\s+(?:rm|sh|bash|python)",
    r"docker\s+(rm|kill)\b",
    r"docker\s+(volume|image|system|container|network)\s+(rm|prune)",
    r"docker\s+compose\s+down",
    r"\bmkfs\b|(?:^|\s)dd\s|>\s*/dev/[sh]d",
    r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b",
    r"\bdrop\s+database\b|\btruncate\s+table\b",
    r":\(\)\s*\{.*\};|\bgit\s+clean\b",
    r"\b(chown|chmod)\s+-R\s+/\s|\bmv\s+\S+\s+/dev/null",
]
# Opérateurs shell qui peuvent chaîner/rediriger → interdit le classement "read"
# (une lecture qui contient `>`, `|`, `;`, etc. doit passer par la validation).
_SHELL_OPS = re.compile(r">>|[;|&`>]|\$\(")
# Lecture / inspection → faible risque (validation non requise), SI aucun opérateur shell.
READ = [
    r"^\s*docker\s+(ps|images|inspect|logs|stats|top|version|info|compose\s+(ps|config|logs))\b",
    r"^\s*(ls|cat|head|tail|less|df|du|free|uptime|ps|top|stat|hostname|whoami|pwd|env|printenv|id|uname)\b",
    r"^\s*systemctl\s+(status|list-units|is-active|is-enabled)\b|^\s*journalctl\b",
    r"^\s*git\s+(status|log|diff|show|branch|remote)\b",
    r"^\s*(grep|find|echo|date|which|command)\b",
]


class SecurityError(Exception):
    """Commande refusée par les règles de sécurité."""


@dataclass
class Command:
    host: str          # "homeserv01" | "localhost"
    command: str


def classify(command: str) -> str:
    c = command.strip()
    for pat in FORBIDDEN:
        if re.search(pat, c):
            return "forbidden"
    if not _SHELL_OPS.search(c):          # pas de redirection/chaînage → éligible "read"
        for pat in READ:
            if re.match(pat, c):
                return "read"
    return "mutating"


def _check_host(host: str) -> None:
    if host not in ALLOWED_HOSTS:
        raise SecurityError(f"hôte non autorisé : {host} (autorisés : {sorted(ALLOWED_HOSTS)})")


def is_local(host: str) -> bool:
    return host in ("localhost", "local", "")


def preview(cmd: Command) -> str:
    kind = classify(cmd.command)
    icon = {"read": "👁️ ", "mutating": "⚙️ ", "forbidden": "⛔"}[kind]
    where = "local" if is_local(cmd.host) else f"ssh {cmd.host}"
    return f"{icon} [{kind}] ({where})  $ {cmd.command}"


def run(cmd: Command, timeout: int = 60) -> dict:
    """Exécute (après classification/confinement). Lève SecurityError si interdit."""
    kind = classify(cmd.command)
    if kind == "forbidden":
        raise SecurityError(f"commande destructive refusée : {cmd.command}")
    _check_host(cmd.host)
    if is_local(cmd.host):
        argv = ["bash", "-lc", cmd.command]
    else:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", cmd.host, cmd.command]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"rc": r.returncode, "out": r.stdout, "err": r.stderr}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "out": "", "err": f"timeout après {timeout}s"}


def confirm_and_run(cmd: Command, assume_yes: bool = False, input_fn=input) -> dict | None:
    """Aperçu → validation (si mutante) → exécution. Retourne le résultat ou None."""
    kind = classify(cmd.command)
    print("\n=== Commande proposée ===")
    print(preview(cmd))
    if kind == "forbidden":
        print("⛔ Refusée (destructive) — aucune exécution.")
        return None
    if kind == "mutating" and not assume_yes:
        try:
            ans = input_fn("\nExécuter cette commande ? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "o", "yes", "oui"):
            print("⛔ Annulé — aucune exécution.")
            return None
    res = run(cmd)
    print(f"\n=== Résultat (rc={res['rc']}) ===")
    if res["out"]:
        print(res["out"].rstrip())
    if res["err"]:
        print("[stderr] " + res["err"].rstrip())
    return res
