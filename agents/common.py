#!/usr/bin/env python3
"""Briques partagées entre les agents Jarvis."""
from __future__ import annotations

import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# --- État partagé de Jarvis (ex. projet actif) : J_A_R_V_I_S/.jarvis/state.json --
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def state_path() -> str:
    return os.path.join(_REPO_ROOT, ".jarvis", "state.json")


def load_state() -> dict:
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(state_path()), exist_ok=True)
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def journal_path() -> str:
    return os.path.join(_REPO_ROOT, ".jarvis", "journal.jsonl")


def log_event(agent: str, mode: str, request: str,
              outcome: str = "ok", target: str | None = None, detail: str | None = None) -> None:
    """Journalise une interaction de Jarvis (append-only JSONL)."""
    from datetime import datetime
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "agent": agent, "mode": mode, "request": request,
        "target": target, "outcome": outcome, "detail": detail,
    }
    os.makedirs(os.path.dirname(journal_path()), exist_ok=True)
    with open(journal_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_events(limit: int | None = None, agent: str | None = None,
                since: str | None = None) -> list[dict]:
    """Lit le journal (plus ancien -> plus récent), filtré, tronqué aux `limit` derniers."""
    events: list[dict] = []
    try:
        with open(journal_path(), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if agent and e.get("agent") != agent:
                    continue
                if since and e.get("ts", "") < since:
                    continue
                events.append(e)
    except OSError:
        return []
    return events[-limit:] if limit else events


def get_active_project() -> dict | None:
    """Retourne le projet actif {name, local?, remote?} ou None."""
    return load_state().get("active_project")


def set_active_project(project: dict) -> None:
    state = load_state()
    state["active_project"] = project
    save_state(state)


def ollama_generate(
    prompt: str,
    model: str,
    url: str = OLLAMA_URL,
    temperature: float = 0.2,
    think: bool = False,
    timeout: int = 600,
) -> str:
    """Appel synchrone à Ollama (/api/generate). `think=False` => pas de CoT (qwen3).

    Deux leviers anti-latence (variables d'env) :
      - JARVIS_MODEL : force UN seul modèle pour tous les agents → pas de
        rechargement quand on change d'agent (un gros modèle = ~44 Go RAM, un seul
        tient à la fois sur 64 Go).
      - JARVIS_KEEP_ALIVE (défaut 30m) : garde le modèle chargé entre les requêtes.
    """
    model = os.environ.get("JARVIS_MODEL") or model
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "keep_alive": os.environ.get("JARVIS_KEEP_ALIVE", "30m"),
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        f"{url}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"].strip()


def ollama_stream(prompt: str, model: str, url: str = OLLAMA_URL,
                  temperature: float = 0.2, think: bool = False, timeout: int = 600):
    """Comme ollama_generate mais en flux : yield les morceaux de texte au fil de l'eau."""
    model = os.environ.get("JARVIS_MODEL") or model
    payload = {
        "model": model, "prompt": prompt, "stream": True, "think": think,
        "keep_alive": os.environ.get("JARVIS_KEEP_ALIVE", "30m"),
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        f"{url}/api/generate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = obj.get("response", "")
            if chunk:
                yield chunk
            if obj.get("done"):
                break


def clean_llm_output(text: str) -> str:
    """Nettoie une sortie LLM destinée à un fichier (note ou code) :
    retire le raisonnement `<think>…</think>` (qwen3 en émet parfois malgré
    think=False) et un éventuel bloc de code englobant (```lang … ```)."""
    t = text.strip()
    if "</think>" in t:
        t = t.rsplit("</think>", 1)[1].strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t + "\n"
