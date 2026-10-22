# Beseder

[![Tests](https://github.com/S2K7x/Beseder/actions/workflows/tests.yml/badge.svg)](https://github.com/S2K7x/Beseder/actions/workflows/tests.yml)

**All your mailboxes in one calm inbox, with your own AI assistant.**
Gmail, Outlook, iCloud, Yahoo and many more together, on your phone and your computer,
running on your own Raspberry Pi.

![Beseder on desktop](docs/images/desktop.png)

- **Sorts your mail** into Important, Notifications, Newsletters, Promotions, Receipts and Other.
- **Instant and notified**: new mail shows up within seconds, with a notification for the important ones.
- **Conversations**: replies are grouped, with your own answers in the timeline.
- **All your mail, not just the inbox**: browse Archive, All Mail, Sent or any folder and
  search years of mail on the server (Gmail's search syntax works too), or see everything
  from one sender.
- **Archive, move, snooze, select several**: process your inbox fast, with an Undo and
  keyboard shortcuts. The trash is never one tap away.
- **Briefs you**: one tap, or every morning with a notification, the AI tells you what matters.
- **Follow-ups**: what's waiting for your answer, and who hasn't answered you yet.
- **Drafts replies in your style**, only when you ask. You read it and send it yourself.
- **Sorting rules in plain words** ("emails from my kids' school are important"), one-tap
  unsubscribe, and a search that understands questions ("how much was my last power bill?").
- **Never acts alone**: the AI cannot send, delete, move or forward anything. Only you can.
- **Free to run**: use a free AI (OpenRouter, Google), a local one (Ollama) or your Claude subscription.

## Quick start (5 minutes)

You need a computer that stays on (a Raspberry Pi is perfect) with
[Docker](https://docs.docker.com/engine/install/) installed.

```bash
git clone https://github.com/S2K7x/Beseder.git
cd Beseder
docker compose up -d
```

Open **http://localhost:8000** on that machine: a setup assistant walks you through
everything (your name, your mailboxes, your AI).

To use it from your iPhone, follow the [install guide](docs/install.md): it takes one
more command with Tailscale.

## Guides

| I want to… | Read |
|---|---|
| Install Beseder on a Raspberry Pi, step by step | [docs/install.md](docs/install.md) |
| Connect Gmail, Outlook, iCloud, Yahoo, Orange, Free… | [docs/mailboxes.md](docs/mailboxes.md) |
| Choose and connect an AI | [docs/ai.md](docs/ai.md) |
| Understand how Beseder keeps my mail safe | [docs/security.md](docs/security.md) |
| Fix a problem | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Change the code | [docs/development.md](docs/development.md) |

## Keyboard shortcuts

`j` / `k` next / previous email · `e` archive · `s` snooze · `r` reply · `x` select ·
`/` search · `Esc` cancel

## Everyday commands

Run them in the `Beseder` folder.

| What | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` |
| Update to the latest version | `git pull && docker compose up -d --build` |
| See what's happening | `docker compose logs -f` |
| Back up your data | `docker compose cp beseder:/data ./beseder-backup` |

Your settings and mail live in a Docker volume: updating or restarting never loses them.
