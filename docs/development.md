# Development

## Run without Docker

You need Python 3.10 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m beseder        # http://127.0.0.1:8000
.venv/bin/python -m pytest -q      # tests
```

To start it at boot without Docker, copy `deploy/beseder.service` to
`/etc/systemd/system/`, adjust `User=` and the paths, then
`sudo systemctl enable --now beseder`.

## Testing against a real mail server

`tests/test_integration_imap.py` syncs, marks as read and saves drafts against a real IMAP
server. It is skipped unless you point it at one. A throwaway Dovecot works:

```bash
docker run -d --name qa-imap -e USER_PASSWORD=qa-pass -p 127.0.0.1:31993:31993 \
  -v "$PWD/tests/dovecot.conf:/etc/dovecot/dovecot.conf:ro" dovecot/dovecot
BESEDER_TEST_IMAP=127.0.0.1:31993 python -m pytest -q tests/test_integration_imap.py
```

(`tests/dovecot.conf` is the image's default config with `listen = *`, for machines without
IPv6.) GitHub Actions runs the whole suite, this server included, plus a Docker build, on
every push: see `.github/workflows/tests.yml`.

## Configuration

All settings are environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `BESEDER_DATA_DIR` | `data` (`/data` in Docker) | SQLite database and encryption key |
| `BESEDER_HOST` / `BESEDER_PORT` | `127.0.0.1` / `8000` (`0.0.0.0` in Docker) | Listen address |
| `BESEDER_ALLOWED_HOSTS` | `localhost,127.0.0.1,*.ts.net` | Accepted values for the Host header |
| `BESEDER_SYNC_INTERVAL` | `300` | Seconds between two syncs |
| `BESEDER_INITIAL_DAYS` / `BESEDER_INITIAL_MAX` | `30` / `500` | Depth of the first import per mailbox |
| `BESEDER_IDLE` | `1` | `0` turns off instant mail (IMAP IDLE) and keeps the periodic sync only |
| `BESEDER_MAX_MESSAGE_BYTES` | `10485760` | Above this size, only headers are imported |

## Code layout

| Path | What's there |
|---|---|
| `beseder/main.py` | HTTP API and PWA serving |
| `beseder/service.py` | AI config, triage, follow-ups, morning brief, AI search, periodic sync |
| `beseder/mail/` | IMAP sync (inbox and Sent, read only), parsing and sanitizing, Microsoft OAuth |
| `beseder/mail/threads.py` | Conversation keys from References / In-Reply-To |
| `beseder/ai/providers.py` | Pluggable AI providers |
| `beseder/ai/tasks.py` | Prompts and output validation for triage, briefs, drafts and search |
| `beseder/unsubscribe.py` | One-click unsubscribe (RFC 8058) with its network guard |
| `beseder/push.py` | Web Push (VAPID, aes128gcm) |
| `web/` | The PWA: vanilla JS, no build step |
| `tests/` | Pytest suite (fake IMAP server, fake AI provider) |

## Rules

The security rules every change must follow are in [CLAUDE.md](../CLAUDE.md). The short
version: the AI never gets tools, the code never sends or deletes mail, AI output is always
validated, and message or AI content never goes through `innerHTML`.
