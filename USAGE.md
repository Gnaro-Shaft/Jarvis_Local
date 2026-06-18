# Utiliser Jarvis

## La façon simple : le chat
```bash
cd ~/Jarvis_Local
./jarvis
```
Tu obtiens une invite `jarvis›`. Tape ta demande en langage naturel — Jarvis
choisit l'agent tout seul. Raccourcis disponibles :

| Commande | Effet |
|---|---|
| `<texte libre>` | poser une question (connaissances / code / infra, routage auto) |
| `/projet` | lister tes projets |
| `/use v8` | définir le projet actif (contexte de l'agent code) |
| `/ecrire <cible> \| <consigne>` | proposer une écriture (note ou fichier) → **validation** |
| `/infra` | état du serveur (santé + conteneurs) |
| `/fix <problème>` | l'agent infra propose une commande corrective → **validation** |
| `/historique [N]` | dernières interactions |
| `/rappel <question>` | résumé du journal en langage naturel |
| `/aide` · `/quitter` | aide · sortir |

> Les écritures et commandes affichent un **aperçu** puis demandent `y/N`.
> Rien n'est appliqué sans ton accord. Suppression impossible (→ `Archive_IA`).

## En une ligne (sans entrer dans le chat)
```bash
./jarvis "qu'est-ce que je sais sur le RAG ?"
./jarvis --history 20
./jarvis --recall "qu'as-tu fait sur le serveur ?"
```

## Confort : taper juste `jarvis`
Ajoute un alias dans `~/.zshrc` (ou `~/.bashrc`) :
```bash
alias jarvis='~/Jarvis_Local/jarvis'
```
Puis `source ~/.zshrc`. Tu pourras lancer `jarvis` depuis n'importe quel dossier.

## Depuis l'iPhone / à distance (lecture seule, Tailscale)
Sur le Mac :
```bash
JARVIS_BIND=<ip-tailscale-mac> JARVIS_TOKEN=monsecret python3 server.py
```
Sur l'iPhone (Tailscale activé), dans Safari :
`http://<ip-tailscale-mac>:8787/?token=monsecret`

## Prérequis
- **Ollama** lancé en local (modèles `qwen3:32b`, `qwen3-coder:30b`, `qwen3:4b`).
- **Tailscale** actif pour l'infra (`/infra`, `/fix`) et l'accès distant.
