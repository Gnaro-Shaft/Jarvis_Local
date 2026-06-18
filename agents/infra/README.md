# Agent Infrastructure — Jarvis (prototype, lecture seule)

Surveille un serveur via **SSH** (santé système + Docker) et diagnostique en
langage naturel avec un LLM local.

```bash
python3 agents/infra/agent.py                  # snapshot santé + conteneurs
python3 agents/infra/agent.py --host homeserv01
python3 agents/infra/agent.py "le disque se remplit, pourquoi ?"   # diagnostic LLM
```

## Sécurité
**Lecture / analyse uniquement.** N'exécute que des commandes de lecture
(`uname`, `uptime`, `free`, `df`, `docker ps`, `systemctl --failed`, `ps`).
Aucune action mutante (restart/stop/suppression) — les commandes correctives
sont *proposées*, jamais exécutées (une couche de commandes validée viendra plus
tard, sur le modèle de `safe_fs`).

## Config (env)
| Variable | Défaut | Rôle |
|---|---|---|
| `JARVIS_REMOTE_HOST` | `""` (via `.env`) | hôte SSH à surveiller (ex. homeserv01) |
| `INFRA_MODEL` | `qwen3:32b` | modèle de diagnostic |

## Commandes correctives (validation requise)
Via `safe_cmd` : l'agent peut exécuter une commande corrective **après validation**.
```bash
python3 agents/infra/agent.py --run "docker restart mnemo-couchdb"   # commande directe
python3 agents/infra/agent.py --fix "mnemo-couchdb est unhealthy"    # l'agent propose UNE commande
# --yes : exécute sans prompt — sandbox/tests uniquement
```
- Classes : `read` (exécutée), `mutating` (validation `[y/N]`), `forbidden` (refusée).
- **Destructif interdit** (`rm`, `compose down`, `volume rm`, `prune`, `dd`, `reboot`…).
- **Confinement** : seuls les hôtes de `JARVIS_ALLOWED_HOSTS` (défaut `homeserv01:localhost`).

## Limites (prototype)
- Un seul hôte à la fois ; snapshot synchrone (SSH).
- Pas d'historique/alerting (un snapshot ponctuel).
- TODO : multi-hôtes, métriques dans le temps, couche de commandes correctives validées.
