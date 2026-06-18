# Agent Développement — Jarvis (prototype)

Analyse un projet de code et répond à des questions techniques avec un LLM coder
local (Ollama), en **lecture seule**.

```
question + projet ──▶ collecte fichiers (sous budget) ──▶ qwen3-coder:30b ──▶ réponse (cite les fichiers)
```

## Sécurité
Lecture / analyse uniquement. L'agent **ne crée, ne modifie, ni ne supprime**
aucun fichier — il *propose* du code en sortie texte ; l'application reste soumise
à validation (cf. règles de sécurité du projet).

## Usage
```bash
python3 agents/dev/agent.py "explique l'architecture"          # défaut: ce repo
python3 agents/dev/agent.py --project /chemin/projet "..."
python3 agents/dev/agent.py --model coder-32k "refacto X ?"
```

## Écriture : produire / éditer un fichier (validation requise)
L'agent rédige le contenu complet du fichier cible (modèle coder, avec le projet
en contexte), montre le **diff**, et n'applique qu'après validation `[y/N]` —
l'ancienne version (si modif) est sauvegardée dans `Archive_IA` (via `safe_fs`).

```bash
python3 agents/dev/agent.py --write src/util.py "ajoute une fonction slugify(s)"
python3 agents/dev/agent.py --project /chemin --write /chemin/calc.py "crée add(a,b)"
# --yes : applique sans prompt — réserver aux tests/sandbox
```
Sortie LLM nettoyée (raisonnement `<think>` + fences retirés). Confinement aux
zones autorisées comme toute écriture.

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | API Ollama locale |
| `DEV_MODEL` | `qwen3-coder:30b` | modèle coder |
| `DEV_CTX_BUDGET` | `48000` | budget de contexte (caractères) |

## Limites (prototype)
- Contexte = les fichiers **les plus pertinents pour la question** (scoring lexical :
  correspondances nom de fichier ×5 + contenu, plafonné), sous budget. L'arborescence
  complète est toujours fournie. → plus rapide et plus précis sur les gros projets.
- Limite : scoring lexical (pas de stemming/embeddings) — « routage » ≠ « route ».
- Ignore `node_modules`, `.git`, `dist`, `venv`, etc.
- TODO : sélection de fichiers pertinents par la question, application de patchs
  *après validation*, intégration au coordinateur.
