# Beseder

Your Gmail, Outlook and iCloud mailboxes in one app (a PWA for iPhone and desktop), with
an AI that:

- **sorts your mail automatically** (the "Auto-triage" switch) into Important,
  Notifications, Newsletters, Promotions, Receipts and Other;
- **briefs you on your unread mail** when you tap "Summarize unread";
- **drafts a reply** only when you tap "Reply with AI" or the ✨ button in the reply box.

What the AI **cannot** do: send, delete, move or forward anything. It has no tools: it
gets text and returns text, and the code checks every answer. Drafts are saved to your
mailbox's Drafts folder and you send them yourself from your mail app.

## The interface

- **Desktop**: three columns. Your messages as cards on the left, the open email (or
  your daily brief) in the middle, and on the right the AI brief, the categories with
  the auto-triage switch, and your mailboxes.
- **Phone**: one column with a bottom tab bar: Inbox, Important, Brief, Settings.
- Light and dark mode follow your system.

## Borrowed from existing tools

- Categories: a mix of Gmail tabs, Shortwave bundles and HEY's Imbox / Feed / Paper Trail.
- **Sender rules** (inspired by HEY's Screener): pick a category on an email and tap the
  tag button to always file that sender there. Rules run before the AI, so it cannot
  override them, and they save AI calls.
- Remote images blocked by default (like Apple Mail's Protect Mail Activity): tracking
  pixels do not load until you tap the image button.

## Install on the Raspberry Pi

You need Python 3.10 or newer (Raspberry Pi OS Bookworm ships 3.11).

```bash
git clone https://github.com/S2K7x/Beseder.git ~/Beseder
cd ~/Beseder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m beseder        # try it: http://127.0.0.1:8000 on the Pi
```

To start it at boot:

```bash
sudo cp deploy/beseder.service /etc/systemd/system/   # adjust User= and the paths
sudo systemctl enable --now beseder
```

### Reach it from your iPhone with Tailscale

The app only listens on `127.0.0.1`: nothing on your network can reach it. Tailscale
publishes it over HTTPS to your tailnet only (a PWA needs HTTPS):

```bash
sudo tailscale serve --bg 8000
tailscale serve status    # shows the address, e.g. https://raspberrypi.tail1234.ts.net
```

First turn on "HTTPS Certificates" in the Tailscale admin console (DNS → MagicDNS +
HTTPS). On the iPhone (with the Tailscale app connected), open the address in Safari →
Share → **Add to Home Screen**.

Do **not** use `tailscale funnel`, which would expose the app to the whole internet.

## Add your mailboxes

| Mailbox | What you need |
|---|---|
| Gmail | An [app password](https://myaccount.google.com/apppasswords) (2-Step Verification must be on). |
| iCloud | An app-specific password: [account.apple.com](https://account.apple.com) → Sign-In and Security → App-Specific Passwords. |
| Outlook / Hotmail | Microsoft sign-in (OAuth), see below. Microsoft no longer accepts passwords over IMAP. |
| Other (OVH, etc.) | IMAP server + password. |

### Outlook: one-time setup

1. Go to [portal.azure.com](https://portal.azure.com) → **App registrations** → **New registration**.
2. Name: `Beseder`. Supported account types: *personal Microsoft accounts only*, or both
   if you also have a work mailbox.
3. Once created: **Authentication** → *Allow public client flows* = **Yes** → Save.
4. **API permissions** → Add → *APIs my organization uses* → `Office 365 Exchange Online`
   → Delegated → `IMAP.AccessAsUser.All`.
5. Paste the **Application (client) ID** in Beseder (Settings → Add a mailbox → Outlook).

Beseder then shows a code to enter at microsoft.com/devicelogin, from any device.

## Connect an AI

In **Settings → AI provider**, pick a provider, tap "List models", choose one, then "Test".

| Provider | Price | Good to know |
|---|---|---|
| OpenRouter | `:free` models cost nothing | Some free providers keep prompts, so your emails. |
| Google AI Studio | Free with limits | On the free tier, Google may use your prompts to improve its products. |
| Ollama | Free, local | Nothing leaves your home. A Pi is slow: use a small model, or an Ollama on a PC in your tailnet. |
| Claude (API) | Paid | Haiku for triage (cheap), Opus for briefs and drafts. Refusal fallback is on. |
| Claude Code on the Pi | Your subscription | Uses the `claude` already signed in on the Pi, run with `--tools ""` and `--strict-mcp-config`: no tools, no MCP servers. Use the full path if needed (`which claude`). |
| Other | — | Any OpenAI-compatible API (Groq, Mistral, LM Studio…). |

The "fast model" is used for triage (many short calls). Leave it empty to use the same
model everywhere. In **Profile** you can set your name (greeting and draft signature) and
the language of the brief; drafts always follow the language of the email you reply to.

## Security

- **Prompt injection**: an email can say "ignore your instructions and…". Content goes
  to the AI inside a block delimited by a random token, but the real protection is that
  the AI has no power. At worst, a booby-trapped email gets misfiled or skews a brief.
  Outputs are validated (known category, id present in the batch), and AI text is shown
  as text, never as HTML (no exfiltration through images).
- **Email HTML**: sanitized on the server (nh3), then shown in a `sandbox` iframe without
  scripts, with a CSP that blocks remote images.
- **Secrets**: passwords, tokens and API keys are encrypted in `data/` with a local key
  (`data/secret.key`, mode 600). Back up that folder, never commit it.
- **Network**: listens on `127.0.0.1`, published only to the tailnet. The `Host` header
  is checked (anti DNS rebinding) and requests that change anything need an
  `X-Beseder` header (anti-CSRF).
- **Log**: every AI action and every saved draft goes to the `audit_log` table (never any
  message content).

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `BESEDER_DATA_DIR` | `data` | SQLite database and encryption key |
| `BESEDER_HOST` / `BESEDER_PORT` | `127.0.0.1` / `8000` | Listen address |
| `BESEDER_ALLOWED_HOSTS` | `localhost,127.0.0.1,*.ts.net` | Accepted values for the Host header |
| `BESEDER_SYNC_INTERVAL` | `300` | Seconds between two syncs |
| `BESEDER_INITIAL_DAYS` / `BESEDER_INITIAL_MAX` | `30` / `500` | Depth of the first import per mailbox |

## Current limits

- Only the **INBOX** folder is synced, every 5 minutes (no IMAP IDLE or push notifications yet).
- Categories live in Beseder: they are not mirrored to Gmail or iCloud.
- No direct sending: on purpose. The draft goes to your mailbox, or opens in your mail app.

## Development

```bash
pip install -r requirements.txt
python -m pytest -q
```

The rules to follow when changing the code are in [CLAUDE.md](CLAUDE.md).
