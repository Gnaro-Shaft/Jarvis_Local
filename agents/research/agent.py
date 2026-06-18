#!/usr/bin/env python3
"""Jarvis — Agent Recherche (web via SearXNG self-hosted).

Interroge un méta-moteur **SearXNG** (auto-hébergé) puis synthétise une réponse
sourcée avec le LLM local. Reste local-first : les requêtes passent par TON
SearXNG (pas d'appel direct à Google & co), conforme à l'esprit du projet.

Sécurité : LECTURE / ANALYSE uniquement (recherche web). Aucune action mutante.

Usage:
    python3 agents/research/agent.py "dernières nouvelles sur X"
    python3 agents/research/agent.py --n 8 "..."

Config (env):
    SEARXNG_URL      (http://localhost:8888)   instance SearXNG (ex. via .env : http://<ip-tailscale>:8888)
    RESEARCH_MODEL   (qwen3:32b)               modèle de synthèse
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)
from common import ollama_generate, clean_llm_output  # noqa: E402

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888").rstrip("/")
RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", "qwen3:32b")


def search(query: str, n: int = 6, timeout: int = 15) -> dict:
    """Recherche web via SearXNG (API JSON). Retourne {results:[...]} ou {error:...}."""
    url = f"{SEARXNG_URL}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        return {"error": f"SearXNG injoignable sur {SEARXNG_URL} ({e.reason}). "
                         f"Définis SEARXNG_URL (ex. dans .env)."}
    except (json.JSONDecodeError, ValueError):
        return {"error": f"Réponse SearXNG illisible (l'API JSON est-elle activée sur {SEARXNG_URL} ?)."}
    results = []
    for x in data.get("results", [])[:n]:
        results.append({
            "title": x.get("title", ""),
            "url": x.get("url", ""),
            "content": (x.get("content") or "").strip(),
        })
    return {"results": results}


def build_prompt(question: str, results: list[dict]) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['url']}\n{r['content']}" for i, r in enumerate(results)
    )
    return (
        "Tu es l'agent Recherche de Jarvis. Réponds en français à la question en "
        "t'appuyant UNIQUEMENT sur ces résultats de recherche web. Cite tes sources "
        "par [n] dans le texte. Sois factuel ; si les résultats ne suffisent pas ou se "
        "contredisent, dis-le.\n\n"
        f"# Résultats web (SearXNG)\n{ctx}\n\n# Question\n{question}\n\n# Réponse sourcée :"
    )


def prepare(question: str, n: int = 6, model: str = RESEARCH_MODEL) -> dict:
    """Recherche + construit le prompt (sans générer). Pour le streaming."""
    res = search(question, n=n)
    if "error" in res:
        return {"prompt": None, "model": model, "sources": [], "text": res["error"]}
    if not res["results"]:
        return {"prompt": None, "model": model, "sources": [], "text": "Aucun résultat web pertinent."}
    return {"prompt": build_prompt(question, res["results"]), "model": model,
            "sources": [r["url"] for r in res["results"] if r["url"]]}


def ask(question: str, n: int = 6, model: str = RESEARCH_MODEL) -> dict:
    p = prepare(question, n=n, model=model)
    if not p.get("prompt"):
        return {"answer": p.get("text", ""), "sources": p.get("sources", [])}
    return {"answer": clean_llm_output(ollama_generate(p["prompt"], model=model)),
            "sources": p["sources"]}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — agent Recherche (web via SearXNG)")
    p.add_argument("question", nargs="+")
    p.add_argument("--n", type=int, default=6, help="nombre de résultats (défaut 6)")
    p.add_argument("--model", default=RESEARCH_MODEL)
    a = p.parse_args(argv)
    out = ask(" ".join(a.question), n=a.n, model=a.model)
    print(f"\n❓ {' '.join(a.question)}\n")
    print(out["answer"])
    for i, u in enumerate(out.get("sources", []), 1):
        if i == 1:
            print("\n— Sources —")
        print(f"  [{i}] {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
