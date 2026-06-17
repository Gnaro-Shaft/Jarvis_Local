#!/usr/bin/env python3
"""Tests de la couche de commandes sécurisées (safe_cmd)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safe_cmd  # noqa: E402

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    results.append((bool(cond), label))


def main() -> int:
    # 1. Classification
    cases = {
        "docker ps": "read",
        "docker compose ps": "read",
        "df -h /": "read",
        "systemctl status nginx": "read",
        "docker compose up -d couchdb": "mutating",
        "docker restart mnemo-couchdb": "mutating",
        "systemctl restart docker": "mutating",
        "rm -rf /data": "forbidden",
        "docker compose down -v": "forbidden",
        "docker volume rm x": "forbidden",
        "docker system prune -f": "forbidden",
        "dd if=/dev/zero of=/dev/sda": "forbidden",
        "sudo reboot": "forbidden",
    }
    for cmd, expected in cases.items():
        got = safe_cmd.classify(cmd)
        check(got == expected, f"classify '{cmd}' = {got} (attendu {expected})")

    # 2. Forbidden -> run() lève SecurityError
    try:
        safe_cmd.run(safe_cmd.Command("localhost", "rm -rf /tmp/whatever"))
        check(False, "run(destructif) devrait lever")
    except safe_cmd.SecurityError:
        check(True, "run(destructif) refusé (SecurityError)")

    # 3. Confinement hôte
    try:
        safe_cmd.run(safe_cmd.Command("evil-host", "docker ps"))
        check(False, "hôte non autorisé devrait lever")
    except safe_cmd.SecurityError:
        check(True, "hôte non autorisé refusé")

    # 4. Exécution d'une commande read locale (sans validation)
    res = safe_cmd.confirm_and_run(safe_cmd.Command("localhost", "echo jarvis-ok"), assume_yes=False)
    check(res is not None and res["rc"] == 0 and "jarvis-ok" in res["out"], "read local exécuté sans validation")

    # 5. Mutante refusée à la validation (réponse 'n') -> pas d'exécution
    res = safe_cmd.confirm_and_run(
        safe_cmd.Command("localhost", "touch /tmp/jarvis_should_not_exist_$$"),
        assume_yes=False, input_fn=lambda _="": "n",
    )
    check(res is None, "mutante refusée à la validation = non exécutée")

    # 6. Mutante validée (assume_yes) -> exécutée (commande inoffensive)
    res = safe_cmd.confirm_and_run(safe_cmd.Command("localhost", "true"), assume_yes=True)
    check(res is not None and res["rc"] == 0, "mutante validée exécutée")

    # 7. Garde-fou : pas de pattern destructif manqué (échantillon)
    for danger in ["rm -fr ~", "docker rm -f c", "git clean -fdx"]:
        check(safe_cmd.classify(danger) == "forbidden", f"destructif détecté : '{danger}'")

    ok = sum(1 for c, _ in results if c)
    print("\n================ TESTS safe_cmd ================")
    for c, label in results:
        print(f"  {'✅' if c else '❌'} {label}")
    print(f"\n{ok}/{len(results)} OK")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
