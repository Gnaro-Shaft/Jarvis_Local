# Agent Recherche — Jarvis (web via SearXNG)

Recherche sur le web en restant **local-first** : les requêtes passent par un
méta-moteur **SearXNG auto-hébergé** (pas d'appel direct à Google & co), puis le
LLM local synthétise une réponse **sourcée** (URLs citées).

```
question ──▶ SearXNG (API JSON) ──▶ top résultats ──▶ LLM local ──▶ réponse + sources
```

```bash
python3 agents/research/agent.py "dernières nouvelles sur X"
python3 agents/research/agent.py --n 8 "..."
# via le coordinateur (routage auto sur les mots « web / actualité / récent / … ») :
./jarvis "quelles sont les actualités récentes sur Y ?"
```

## Sécurité / vie privée
- **Lecture seule** (recherche). Aucune action mutante.
- Les requêtes transitent par **ton** SearXNG (anonymisées, self-hosted) — conforme
  à l'esprit local-first du projet. (SearXNG interroge ensuite des moteurs publics.)

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `SEARXNG_URL` | `http://localhost:8888` | instance SearXNG (ex. `.env` : `http://<ip-tailscale>:8888`) |
| `RESEARCH_MODEL` | `qwen3:32b` | modèle de synthèse |

Prérequis : SearXNG joignable avec l'**API JSON activée** (`search.formats: [html, json]`).
