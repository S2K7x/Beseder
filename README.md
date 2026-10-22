# Beseder

Tes boîtes Gmail, Outlook et iCloud réunies dans une seule app (PWA pour iPhone), avec une IA qui :

- **trie automatiquement** tes mails (interrupteur « Tri auto ») en catégories : Important,
  Notifications, Newsletters, Promotions, Factures, Autres ;
- **résume tes non lus** quand tu appuies sur « ✨ Résumer les non lus » ;
- **rédige un brouillon de réponse** seulement quand tu appuies sur « ✍️ Rédiger une réponse ».

Ce que l'IA **ne peut pas** faire : envoyer un mail, supprimer, déplacer, transférer. Elle n'a
aucun outil : elle reçoit du texte et renvoie du texte, et le code vérifie chaque réponse. Les
brouillons sont enregistrés dans le dossier Brouillons de ta boîte ; c'est toi qui les envoies
depuis Mail.

## Ce qui est repris des outils existants

- Catégories : un mélange des onglets Gmail, des « bundles » de Shortwave et du
  Imbox / Feed / Paper Trail de HEY.
- **Règles par expéditeur** (inspirées du Screener de HEY) : quand tu changes la catégorie
  d'un mail en cochant « toujours pour cet expéditeur », la règle s'applique tout de suite et
  passe avant l'IA. Moins d'appels IA, et l'IA ne peut pas la contourner.
- Images distantes bloquées par défaut (comme Apple Mail « Protéger l'activité ») : les pixels
  de suivi ne se chargent pas tant que tu n'appuies pas sur « Afficher les images ».

## Installation sur le Raspberry Pi

Il faut Python 3.10 ou plus (Raspberry Pi OS Bookworm a la 3.11).

```bash
git clone https://github.com/S2K7x/Beseder.git ~/Beseder
cd ~/Beseder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m beseder        # test : http://127.0.0.1:8000 sur le Pi
```

Pour le lancer au démarrage :

```bash
sudo cp deploy/beseder.service /etc/systemd/system/   # adapte User= et les chemins
sudo systemctl enable --now beseder
```

### Accès depuis l'iPhone avec Tailscale

L'app écoute uniquement sur `127.0.0.1` : elle n'est pas joignable depuis le réseau. Tailscale
la publie en HTTPS sur ton tailnet seulement (le HTTPS est nécessaire pour la PWA) :

```bash
sudo tailscale serve --bg 8000
tailscale serve status    # affiche l'adresse, ex. https://raspberrypi.tail1234.ts.net
```

Active d'abord « HTTPS Certificates » dans la console Tailscale (DNS → MagicDNS + HTTPS).
Sur l'iPhone (avec l'app Tailscale connectée) : ouvre l'adresse dans Safari →
Partager → **Sur l'écran d'accueil**.

N'utilise **pas** `tailscale funnel`, qui exposerait l'app sur Internet.

## Ajouter tes boîtes

| Boîte | Ce qu'il faut |
|---|---|
| Gmail | Un [mot de passe d'application](https://myaccount.google.com/apppasswords) (la validation en 2 étapes doit être active). |
| iCloud | Un mot de passe pour app : [account.apple.com](https://account.apple.com) → Connexion et sécurité → Mots de passe pour app. |
| Outlook / Hotmail | Connexion Microsoft (OAuth), voir ci-dessous. Microsoft n'accepte plus les mots de passe en IMAP. |
| Autre (OVH, etc.) | Serveur IMAP + mot de passe. |

### Outlook : à faire une seule fois

1. Va sur [portal.azure.com](https://portal.azure.com) → **App registrations** → **New registration**.
2. Nom : `Beseder`. Types de comptes : *comptes personnels Microsoft uniquement*, ou les
   deux si tu as aussi une boîte pro.
3. Une fois créée : **Authentication** → *Allow public client flows* = **Yes** → Save.
4. **API permissions** → Add → *APIs my organization uses* → `Office 365 Exchange Online`
   → Delegated → `IMAP.AccessAsUser.All`.
5. Copie l'**Application (client) ID** dans Beseder (Réglages → Ajouter une boîte → Outlook).

Beseder affiche ensuite un code à saisir sur microsoft.com/devicelogin, depuis n'importe quel
appareil.

## Brancher une IA

Dans **Réglages → Intelligence artificielle**, choisis un fournisseur, appuie sur
« Lister les modèles », choisis-en un, puis « Tester ».

| Fournisseur | Prix | À savoir |
|---|---|---|
| OpenRouter | Modèles `:free` gratuits | Certains fournisseurs gratuits gardent les prompts, donc tes mails. |
| Google AI Studio | Gratuit avec limites | En offre gratuite, Google peut utiliser tes prompts pour améliorer ses produits. |
| Ollama | Gratuit, local | Rien ne sort de chez toi. Un Pi est lent : préfère un petit modèle, ou un Ollama sur un PC de ton tailnet. |
| Claude (API) | Payant | Haiku pour le tri (peu cher), Opus pour les résumés et brouillons. |
| Claude Code sur le Pi | Ton abonnement | Utilise le `claude` déjà connecté sur le Pi, lancé avec `--tools ""` et `--strict-mcp-config` : aucun outil, aucun serveur MCP. Mets le chemin complet du binaire si besoin (`which claude`). |
| Autre | — | N'importe quelle API compatible OpenAI (Groq, Mistral, LM Studio…). |

Le « modèle rapide » sert au tri (beaucoup d'appels courts). Laisse-le vide pour utiliser le
même modèle partout.

## Sécurité

- **Prompt injection** : un mail peut contenir « ignore tes instructions et… ». Le contenu est
  passé à l'IA dans un bloc délimité par un jeton aléatoire, mais la vraie protection est
  ailleurs : l'IA n'a aucun pouvoir. Au pire, un mail piégé se classe mal ou fausse un
  résumé. Les sorties sont validées (catégorie connue, id présent dans le lot), et le texte de
  l'IA est affiché comme du texte, jamais comme du HTML (pas d'exfiltration par image).
- **HTML des mails** : nettoyé côté serveur (nh3) puis affiché dans une iframe `sandbox` sans
  scripts, avec une CSP qui bloque les images distantes.
- **Secrets** : mots de passe, tokens et clés API sont chiffrés dans `data/` avec une clé
  locale (`data/secret.key`, droits 600). Sauvegarde ce dossier, ne le commite jamais.
- **Réseau** : écoute sur `127.0.0.1`, publiée seulement sur le tailnet. Contrôle de l'en-tête
  `Host` (anti DNS rebinding) et en-tête `X-Beseder` obligatoire sur les requêtes qui
  modifient quelque chose (anti-CSRF).
- **Journal** : chaque action IA et chaque brouillon enregistré est noté dans la table
  `audit_log` (sans contenu de mail).

## Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `BESEDER_DATA_DIR` | `data` | Base SQLite et clé de chiffrement |
| `BESEDER_HOST` / `BESEDER_PORT` | `127.0.0.1` / `8000` | Adresse d'écoute |
| `BESEDER_ALLOWED_HOSTS` | `localhost,127.0.0.1,*.ts.net` | Valeurs acceptées pour l'en-tête Host |
| `BESEDER_SYNC_INTERVAL` | `300` | Secondes entre deux synchronisations |
| `BESEDER_INITIAL_DAYS` / `BESEDER_INITIAL_MAX` | `30` / `500` | Profondeur du premier import par boîte |

## Limites actuelles

- Seul le dossier **INBOX** est synchronisé, toutes les 5 minutes (pas encore d'IMAP IDLE ni de
  notifications push).
- Les catégories restent dans Beseder : elles ne sont pas reportées dans Gmail/iCloud.
- Pas d'envoi direct : c'est voulu. Le brouillon part dans ta boîte, ou s'ouvre dans Mail.

## Développement

```bash
pip install -r requirements.txt
python -m pytest -q
```

Les règles à respecter en modifiant le code sont dans [CLAUDE.md](CLAUDE.md).
