#!/usr/bin/env python3
"""Jarvis — Agent Obsidian (prototype).

Boucle RAG locale :
  1. Retrieval  -> Mnemo (RAG existant) via son serveur MCP en HTTP (search_vault)
  2. Synthèse   -> LLM local via Ollama (qwen3:32b par défaut)
  3. Réponse    -> en français, sourcée [Source N]

Principe (cf. vision Jarvis Local) : on RÉUTILISE Mnemo comme backbone de
connaissances (embeddings bge-m3 multilingue, 90% Hit@1) plutôt que de créer un
2e RAG. Lecture/analyse seulement -> aucune action critique, conforme aux règles
de sécurité du projet.

Usage:
    python3 agents/obsidian/agent.py "ma question"
    python3 agents/obsidian/agent.py --limit 6 --prefix "02 - Projets/Mnemo" "..."

Config (env, valeurs par défaut entre parenthèses) :
    MNEMO_MCP_URL   (http://localhost:8001/mcp)   serveur MCP Mnemo
    OLLAMA_URL      (http://localhost:11434)          API Ollama locale
    OLLAMA_MODEL    (qwen3:32b)                        modèle de synthèse
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)
from common import ollama_generate, clean_llm_output, format_history, USER_AGENT  # noqa: E402
import safe_fs  # noqa: E402

MNEMO_MCP_URL = os.environ.get("MNEMO_MCP_URL", "http://localhost:8001/mcp")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:32b")


class MnemoMCPError(RuntimeError):
    pass


class MnemoMCP:
    """Client MCP minimal (transport streamable HTTP + SSE) pour Mnemo."""

    def __init__(self, url: str = MNEMO_MCP_URL, timeout: int = 30):
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._id = 0

    def _post(self, payload: dict, notify: bool = False):
        self._id += 1
        payload = {"jsonrpc": "2.0", **payload}
        if not notify:
            payload["id"] = self._id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers
        )
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if notify:
            resp.read()
            return None
        # Parse la réponse : soit JSON pur, soit SSE (event: message / data: {...}).
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == payload["id"]:
                        return msg
            raise MnemoMCPError("aucune réponse SSE correspondante")
        return json.loads(resp.read())

    def connect(self):
        r = self._post(
            {
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "jarvis-obsidian-agent", "version": "0.1"},
                },
            }
        )
        if "error" in r:
            raise MnemoMCPError(f"initialize: {r['error']}")
        self._post({"method": "notifications/initialized"}, notify=True)
        return r["result"].get("serverInfo", {})

    def call(self, name: str, arguments: dict):
        r = self._post({"method": "tools/call", "params": {"name": name, "arguments": arguments}})
        if "error" in r:
            raise MnemoMCPError(f"{name}: {r['error']}")
        content = r["result"].get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"raw": text}

    def search_vault(self, query: str, limit: int = 5, path_prefix: str | None = None):
        args = {"query": query, "limit": limit}
        if path_prefix:
            args["path_prefix"] = path_prefix
        return self.call("search_vault", args)


def build_prompt(question: str, hits: list[dict], convo: str = "") -> str:
    ctx = "\n\n".join(
        f"[Source {i+1}] {h.get('path','?')} > {h.get('section','')} "
        f"(score {h.get('score', 0):.2f})\n{h.get('content_preview','').strip()}"
        for i, h in enumerate(hits)
    )
    return (
        "Tu es l'agent Obsidian de Jarvis. Réponds en français, de façon concise et "
        "structurée, UNIQUEMENT à partir du contexte fourni. Cite tes sources entre "
        "crochets [Source N]. Si le contexte ne suffit pas, dis-le clairement.\n\n"
        f"# Contexte (extraits du vault Obsidian via Mnemo)\n{ctx}\n\n"
        f"{convo}# Question\n{question}\n\n# Réponse sourcée :"
    )


def build_enrich_prompt(path: str, current: str, instruction: str, context: str) -> str:
    ctx = f"\n# Contexte (extraits du vault via Mnemo, pour t'appuyer sur des faits)\n{context}\n" if context else ""
    base = current if current.strip() else "(nouvelle note, vide)"
    return (
        "Tu es l'agent Obsidian de Jarvis. Tu édites une note Markdown.\n"
        "Renvoie UNIQUEMENT le contenu Markdown COMPLET de la note mise à jour — "
        "aucun commentaire, aucun bloc de code englobant. Préserve TOUT le contenu "
        "et le frontmatter existants ; applique seulement la consigne. N'invente pas "
        "de faits ; si tu utilises le contexte, reste fidèle.\n"
        f"{ctx}\n"
        f"# Note actuelle ({os.path.basename(path)})\n{base}\n\n"
        f"# Consigne\n{instruction}\n\n"
        "# Note mise à jour (Markdown complet) :"
    )


def enrich(note_path: str, instruction: str, use_context: bool = True,
           limit: int = 4, model: str = OLLAMA_MODEL) -> tuple[safe_fs.Action, list[dict]]:
    """Propose une édition de note (NE l'applique PAS — validation via safe_fs)."""
    note_path = os.path.abspath(os.path.expanduser(note_path))
    current = ""
    if os.path.exists(note_path):
        with open(note_path, "r", encoding="utf-8", errors="replace") as f:
            current = f.read()
    context, hits = "", []
    if use_context:
        try:
            mnemo = MnemoMCP()
            mnemo.connect()
            hits = mnemo.search_vault(
                f"{instruction} {os.path.basename(note_path)}", limit=limit
            ).get("results", [])
            context = "\n".join(
                f"- {h.get('path')}: {h.get('content_preview', '')[:300]}" for h in hits
            )
        except Exception:
            context, hits = "", []  # contexte best-effort, ne bloque pas l'édition
    new_content = clean_llm_output(
        ollama_generate(build_enrich_prompt(note_path, current, instruction, context), model=model)
    )
    action = safe_fs.modify(note_path, new_content) if current else safe_fs.create(note_path, new_content)
    return action, hits


def prepare(question: str, limit: int = 5, prefix: str | None = None,
            model: str = OLLAMA_MODEL, history: list | None = None) -> dict:
    """Récupère le contexte et construit le prompt (sans générer). Pour le streaming."""
    mnemo = MnemoMCP()
    mnemo.connect()
    hits = mnemo.search_vault(question, limit=limit, path_prefix=prefix).get("results", [])
    if not hits:
        return {"prompt": None, "model": model, "sources": [],
                "text": "Aucun passage pertinent trouvé dans le vault."}
    return {"prompt": build_prompt(question, hits, format_history(history)), "model": model,
            "sources": [h.get("path") for h in hits]}


def ask(question: str, limit: int = 5, prefix: str | None = None) -> dict:
    mnemo = MnemoMCP()
    mnemo.connect()
    res = mnemo.search_vault(question, limit=limit, path_prefix=prefix)
    hits = res.get("results", [])
    if not hits:
        return {"answer": "Aucun passage pertinent trouvé dans le vault.", "hits": []}
    answer = ollama_generate(build_prompt(question, hits), model=OLLAMA_MODEL)
    return {"answer": answer, "hits": hits}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Jarvis — agent Obsidian (RAG via Mnemo + Ollama)")
    p.add_argument("question", nargs="+", help="la question en langage naturel")
    p.add_argument("--limit", type=int, default=5, help="nb de passages récupérés (défaut 5)")
    p.add_argument("--prefix", default=None, help="restreindre à un sous-dossier du vault")
    p.add_argument("--sources", action="store_true", help="afficher les sources détaillées")
    p.add_argument("--enrich", metavar="NOTE", default=None,
                   help="mode écriture : enrichir/éditer la note NOTE (la question = la consigne)")
    p.add_argument("--no-context", action="store_true", help="(enrich) ne pas chercher de contexte Mnemo")
    p.add_argument("--model", default=OLLAMA_MODEL, help="modèle Ollama de synthèse")
    p.add_argument("--yes", action="store_true",
                   help="(enrich) appliquer sans validation interactive — À ÉVITER sur le vrai vault")
    a = p.parse_args(argv)
    question = " ".join(a.question)

    # --- Mode écriture : proposition -> validation -> application (safe_fs) ---
    if a.enrich:
        action, hits = enrich(a.enrich, question, use_context=not a.no_context,
                              limit=a.limit, model=a.model)
        if hits:
            print("Contexte Mnemo utilisé :")
            for h in hits:
                print(f"  - {h.get('path')} ({h.get('score', 0):.2f})")
        safe_fs.confirm_and_apply([action], assume_yes=a.yes)
        return 0

    out = ask(question, limit=a.limit, prefix=a.prefix)
    print(f"\n❓ {question}\n")
    print(out["answer"])
    if out["hits"]:
        print("\n— Sources —")
        for i, h in enumerate(out["hits"], 1):
            print(f"  [{i}] {h.get('path')} ({h.get('score', 0):.2f})")
        if a.sources:
            for i, h in enumerate(out["hits"], 1):
                print(f"\n[{i}] {h.get('path')} > {h.get('section','')}\n{h.get('content_preview','').strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
