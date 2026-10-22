# Beseder — règles du projet

Client mail perso (PWA) qui unifie Gmail, Outlook et iCloud, avec une IA qui trie,
résume et rédige des brouillons **à la demande**. Tourne sur un Raspberry Pi derrière
Tailscale. Backend Python (FastAPI), front en JS vanilla sans build.

## Règles de sécurité (non négociables, même « pour aller plus vite »)

1. **L'IA n'a aucun outil.** Elle reçoit du texte, renvoie du texte. Le code décide
   quoi faire de sa réponse. Ne jamais ajouter de tool calling, d'accès MCP ou d'accès
   réseau à l'IA. Pour le provider `claude_cli`, garder `--tools ""` et
   `--strict-mcp-config`.
2. **Aucun envoi de mail, aucune suppression.** Le code ne contient pas de SMTP et
   n'appelle jamais `delete_messages`/`expunge`. Les seules écritures IMAP autorisées
   sont : marquer comme lu, et ajouter un brouillon dans le dossier Brouillons
   (toujours déclenché par un clic de l'utilisateur).
3. **Le contenu des mails est une donnée non fiable.** Toujours le passer à l'IA dans
   un bloc délimité (voir `beseder/ai/tasks.py`), et **valider** chaque sortie de l'IA :
   catégorie dans l'enum, ids présents dans le lot envoyé, sinon on ignore.
4. **Jamais de `innerHTML` avec du contenu mail ou IA** dans le front. Utiliser
   `textContent` / le helper `h()`. Le HTML des mails est nettoyé côté serveur (nh3) et
   affiché dans une iframe `sandbox` sans scripts, images distantes bloquées par défaut.
5. **Secrets chiffrés au repos** (Fernet, `data/secret.key` en 0600). Jamais de mot de
   passe, token ou contenu de mail dans les logs.
6. Les requêtes API qui modifient quelque chose exigent l'en-tête `X-Beseder: 1`
   (anti-CSRF). Ne pas retirer ce middleware.

## Commandes

- Installer : `pip install -r requirements.txt`
- Lancer : `python -m beseder` (écoute sur 127.0.0.1:8000 par défaut)
- Tests : `python -m pytest -q`

## Structure

- `beseder/mail/` — connexion IMAP, sync, parsing, OAuth Microsoft
- `beseder/ai/` — providers IA interchangeables + tâches (tri, résumé, brouillon)
- `beseder/main.py` — routes API
- `web/` — la PWA
