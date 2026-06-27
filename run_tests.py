#!/usr/bin/env python3
"""Lance toutes les suites de tests de Jarvis (agents/test_*.py) et agrège le bilan.

    python3 run_tests.py          # tout
    python3 run_tests.py -v       # + sortie détaillée des suites en échec
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    tests = sorted(glob.glob(os.path.join(ROOT, "agents", "test_*.py")))
    if not tests:
        print("Aucune suite de tests trouvée.")
        return 1

    fails = []
    print(f"Lancement de {len(tests)} suites de tests\n" + "─" * 48)
    for t in tests:
        r = subprocess.run([sys.executable, t], capture_output=True, text=True)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        summary = lines[-1] if lines else "(pas de sortie)"
        status = "✅ OK  " if r.returncode == 0 else "❌ ÉCHEC"
        print(f"  {status}  {os.path.basename(t):22} {summary}")
        if r.returncode != 0:
            fails.append((t, r.stdout, r.stderr))

    print("─" * 48)
    if fails:
        print(f"❌ {len(fails)}/{len(tests)} suite(s) en échec")
        if verbose:
            for t, out, err in fails:
                print(f"\n===== {os.path.basename(t)} =====\n{out}\n{err}")
        else:
            print("   (relance avec -v pour le détail)")
        return 1
    print(f"✅ Toutes les suites passent ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
