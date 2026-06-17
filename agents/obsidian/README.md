# Agent Obsidian — Jarvis (prototype)

Boucle RAG **100% locale** qui réutilise **Mnemo** (le RAG existant) comme backbone
de connaissances, plutôt que de créer un 2ᵉ vector store.

```
question ──▶ Mnemo MCP (search_vault) ──▶ contexte ──▶ Ollama (qwen3:32b) ──▶ réponse sourcée
```

## Pourquoi Mnemo et pas la mémoire claude-flow
Mnemo utilise `bge-m3` (multilingue, 1024d, ~90% Hit@1) et règle le problème de
recall FR que l'embedding par défaut de claude-flow (`all-MiniLM-L6-v2`, anglais)
ne sait pas gérer. La vision du projet impose d'« exploiter le RAG existant ».

## Usage
```bash
python3 agents/obsidian/agent.py "ta question"
python3 agents/obsidian/agent.py --limit 6 --prefix "02 - Projets/Mnemo" --sources "..."
```

## Écriture : enrichir une note (validation requise)
L'agent rédige le contenu mis à jour (via Ollama, en s'appuyant sur le contexte
Mnemo), montre le **diff**, et n'applique qu'après validation `[y/N]` — l'ancienne
version est sauvegardée dans `Archive_IA` (via `safe_fs`).

```bash
python3 agents/obsidian/agent.py --enrich "/chemin/note.md" "ajoute une section Résumé"
python3 agents/obsidian/agent.py --enrich note.md --no-context "corrige les fautes"
# --yes : applique sans prompt — À ÉVITER sur le vrai vault (réserver aux tests/sandbox)
```
La sortie LLM est nettoyée (raisonnement `<think>…</think>` et fences retirés)
avant diff. Toute action reste confinée aux zones autorisées.

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `MNEMO_MCP_URL` | `http://100.100.77.23:8001/mcp` | serveur MCP Mnemo (homeserv01 via Tailscale) |
| `OLLAMA_URL` | `http://localhost:11434` | API Ollama locale |
| `OLLAMA_MODEL` | `qwen3:32b` | modèle de synthèse |

## Statut / limites (prototype)
- ✅ Retrieval + synthèse end-to-end validés (réponse FR sourcée, ~40s sur qwen3:32b)
- Lecture seule — aucune écriture, conforme aux règles de sécurité du projet
- Dépend de la joignabilité Tailscale de homeserv01 (MCP Mnemo)
- TODO : streaming de la réponse, cache, gestion d'erreur réseau plus fine,
  intégration au coordinateur multi-agents, sélection auto du modèle.
