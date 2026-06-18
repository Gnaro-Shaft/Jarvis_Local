# Agent Workspace — Jarvis (prototype)

Découvre les projets **en local et sur le serveur** (SSH via Tailscale),
déduplique les copies local↔serveur, et gère le **projet actif**.

```
python3 agents/workspace/agent.py                 # catalogue (local + serveur)
python3 agents/workspace/agent.py --local-only    # rapide, sans le serveur
python3 agents/workspace/agent.py --use v8        # définir le projet actif
python3 agents/workspace/agent.py --active        # afficher le projet actif
```

## Projet actif
Persisté dans `.jarvis/state.json`. Le coordinateur (`jarvis.py`) l'utilise comme
**contexte par défaut de l'agent Dev** : une question/écriture de code sans
`--project` cible automatiquement le projet actif.

## Découverte
- **Projet = racine de dépôt** (`.git`) ou dossier contenant un marqueur
  (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`…).
- Le scan serveur ne remonte que les **racines de repo** (pas les sous-paquets d'un monorepo).
- Dédup par nom : un projet présent des deux côtés est marqué « copie ».

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `JARVIS_PROJECT_ROOTS` | `~` (home) | racines locales (séparées par `:`) |
| `JARVIS_REMOTE_HOST` | `""` (via `.env`) | hôte SSH, ex. homeserv01 (`""` = pas de serveur) |
| `JARVIS_REMOTE_ROOTS` | `$HOME:$HOME/projects:/data` | racines distantes |

## Limites (prototype)
- Dédup par nom seulement (ne compare pas les contenus local/serveur).
- Scan serveur synchrone (SSH) — utiliser `--local-only` pour aller vite.
- TODO : détection de divergence local/serveur (git status, mtime), choix du
  côté (local/serveur) pour le projet actif.
