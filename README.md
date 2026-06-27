# Jarvis Local

Assistant IA personnel **local-first, multi-agents**, inspiré de JARVIS.
Vision complète : note Obsidian `02 - Projets/Jarvis Local/` (vault dGnaro).

> **Local First** · l'assistant **propose**, l'utilisateur **décide** · **suppression interdite** (→ `Archive_IA`).

## Installation

**Prérequis**
- Python 3.10+ (aucune dépendance externe — stdlib uniquement)
- [Ollama](https://ollama.com) en local avec au moins un modèle :
  ```bash
  ollama pull qwen2.5:14b-instruct-q5_K_M   # web (rapide)
  ollama pull qwen3:32b qwen3-coder:30b     # raisonnement / code (optionnel)
  ```
- *(optionnel)* [Tailscale](https://tailscale.com) + accès SSH à un serveur pour l'agent Infra et l'accès distant
- *(optionnel)* [Mnemo](https://github.com/Gnaro-Shaft/mnemo) pour le RAG de l'agent Obsidian

**Démarrage**
```bash
git clone https://github.com/Gnaro-Shaft/Jarvis_Local.git
cd Jarvis_Local
./jarvis                 # chat interactif
# ou : python3 server.py   → http://localhost:8787 (interface web)
```

Configuration par variables d'environnement (modèles, hôtes, etc.) : voir [USAGE.md](USAGE.md).

## Architecture (prototype)

```
                 python3 jarvis.py "..."
                          │
                 ┌────────▼─────────┐
                 │   Coordinateur    │  jarvis.py
                 │ route + délègue   │  (règles + classifieur qwen3:4b)
                 └───┬──────────┬────┘
                     │          │
          ┌──────────▼──┐   ┌───▼───────────┐
          │   Obsidian   │   │      Dev       │
          │ RAG via Mnemo│   │ analyse de code│
          │  → qwen3:32b │   │ → qwen3-coder  │
          └──────────────┘   └────────────────┘
                  └──── agents/common.py (Ollama) ────┘

        écritures ──▶ agents/safe_fs.py  (fichiers : proposition → validation → application)
        commandes ──▶ agents/safe_cmd.py (shell/SSH : classification → validation → exécution)
```

- **Coordinateur** (`jarvis.py`) : comprend la demande, choisit l'agent + le modèle, délègue.
- **Agent Obsidian** (`agents/obsidian/`) : connaissances / vault, RAG via **Mnemo** (MCP HTTP), synthèse `qwen3:32b`.
- **Agent Dev** (`agents/dev/`) : analyse de code d'un projet, synthèse `qwen3-coder:30b`.
- **Agent Workspace** (`agents/workspace/`) : découvre les projets (local + serveur SSH), déduplique, gère le **projet actif** (contexte par défaut de l'agent Dev).
- **Agent Infrastructure** (`agents/infra/`) : surveille le serveur via SSH (santé + Docker) et diagnostique, **lecture seule**.
- **Agent Recherche** (`agents/research/`) : recherche web via **SearXNG** self-hosted → synthèse locale sourcée, **lecture seule** (local-first : pas d'appel direct aux moteurs publics).
- **Commun** (`agents/common.py`) : appel Ollama, nettoyage des sorties, état partagé (projet actif), **journal d'orchestration**.
- **Mémoire d'orchestration** : chaque interaction (question → agent → action → issue) est journalisée dans `.jarvis/journal.jsonl` ; consultable (`--history`) et interrogeable en langage naturel (`--recall`).

- **Écriture sécurisée** (`agents/safe_fs.py`) : création/modification/déplacement **soumis à validation** (aperçu diff → `[y/N]`), **suppression interdite** (seul retrait = archivage vers `Archive_IA/`), **confinement** aux zones autorisées, sauvegarde avant écrasement. Tests : `python3 agents/test_safe_fs.py` (13/13).

Tout est **local** (LLMs via Ollama sur le M5, Mnemo via Tailscale). Les écritures passent par `safe_fs`/`safe_cmd` avec validation.
- **Accès distant** (`server.py`) : petit serveur HTTP (stdlib) exposant Jarvis **en lecture** sur le tailnet (UI web + `/ask`, `/history`, `/recall`), jeton optionnel. Les écritures/commandes restent locales et interactives (pas d'action critique déclenchée à distance sans validation).

## Usage

**Le plus simple — le chat** (routage auto, raccourcis `/…`, validations interactives) :
```bash
./jarvis            # ouvre l'invite « jarvis› » — tape en langage naturel ; /aide pour les commandes
```
Voir [USAGE.md](USAGE.md) pour le mémo complet.

**En une ligne** :
```bash
python3 jarvis.py "qu'est-ce que je sais sur le RAG ?"        # → Obsidian
python3 jarvis.py "analyse l'agent dev et propose un fix"     # → Dev
python3 jarvis.py --agent dev --project /chemin "refacto ?"   # forcer l'agent
python3 jarvis.py --explain "..."                             # voir la décision de routage

# Projets (agent Workspace) :
python3 agents/workspace/agent.py            # catalogue local + serveur
python3 agents/workspace/agent.py --use v8   # projet actif → contexte Dev par défaut

# Infra (via coordinateur ou direct) :
python3 jarvis.py "comment vont les conteneurs docker du serveur ?"
python3 agents/infra/agent.py                # snapshot santé + Docker

# Recherche web (agent Research, via SearXNG) :
python3 jarvis.py "quelles sont les actualités récentes sur X ?"
python3 agents/research/agent.py "..."
python3 agents/infra/agent.py --run "docker restart mnemo-couchdb"   # commande validée
python3 agents/infra/agent.py --fix "couchdb est unhealthy"          # l'agent propose → tu valides

# Mémoire d'orchestration :
python3 jarvis.py --history 20                       # dernières interactions
python3 jarvis.py --recall "qu'as-tu fait sur le serveur cette semaine ?"

# Accès distant (Tailscale) — serveur HTTP, LECTURE SEULE :
JARVIS_BIND=<ip-tailscale-mac> JARVIS_TOKEN=<secret> python3 server.py
# puis depuis l'iPhone (Tailscale ON) : http://<ip-tailscale-mac>:8787/?token=<secret>

# Écriture (validation requise — diff puis [y/N]) :
python3 jarvis.py --write notes/idee.md "ajoute une section Résumé"   # → Obsidian
python3 jarvis.py --write src/util.py "ajoute slugify(s)"             # → Dev
```
Le coordinateur route aussi les écritures (note `.md`/vault → Obsidian, sinon → Dev).
Toute écriture passe par `safe_fs` : aperçu, validation, `Archive_IA`. Ne jamais
utiliser `--yes` sur le vrai vault.

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | API Ollama locale |
| `OLLAMA_MODEL` | `qwen3:32b` | modèle agent Obsidian |
| `DEV_MODEL` | `qwen3-coder:30b` | modèle agent Dev |
| `ROUTER_MODEL` | `qwen3:4b` | classifieur de routage |
| `MNEMO_MCP_URL` | `http://<ip-tailscale-serveur>:8001/mcp` | RAG Mnemo |

## Tests
```bash
python3 run_tests.py        # toutes les suites (agents/test_*.py)
python3 run_tests.py -v     # + détail des échecs
```
Couvre : sécurité fichiers (`safe_fs`) & commandes (`safe_cmd`), routage du
coordinateur, sélection de fichiers de l'agent Dev, journal/état partagés,
découverte de projets (Workspace). Déterministe, sans Ollama/SSH/réseau.

## État
Prototype fonctionnel : coordinateur + 2 agents, validés end-to-end, 100% local.
Voir la note de suivi pour la roadmap (garde-fous écriture/validation, agents
Workspace & Infra, mémoire d'orchestration, accès distant).
