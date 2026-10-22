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
docker run -d --name qa-imap -e USER_PASSWORD=qa-pass -p 127.0.0.1:31993:31993 dovecot/dovecot
BESEDER_TEST_IMAP=127.0.0.1:31993 python -m pytest -q tests/test_integration_imap.py
```

(If the container exits with "Address family not supported", your machine has no IPv6:
add `listen = *` to Dovecot's config.)

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
| `beseder/service.py` | AI config, triage, periodic sync |
| `beseder/mail/` | IMAP sync, message parsing and sanitizing, Microsoft OAuth |
| `beseder/ai/providers.py` | Pluggable AI providers |
| `beseder/ai/tasks.py` | Prompts and output validation for triage, briefs and drafts |
| `web/` | The PWA: vanilla JS, no build step |
| `tests/` | Pytest suite (fake IMAP server, fake AI provider) |

## Rules

The security rules every change must follow are in [CLAUDE.md](../CLAUDE.md). The short
version: the AI never gets tools, the code never sends or deletes mail, AI output is always
validated, and message or AI content never goes through `innerHTML`.
