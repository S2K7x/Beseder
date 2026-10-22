# Beseder: project rules

A personal mail client (PWA) that brings Gmail, Outlook, iCloud, Yahoo and other IMAP mailboxes together, with an AI
that sorts, briefs and drafts replies **on demand**. Runs on a Raspberry Pi behind
Tailscale. Python backend (FastAPI), vanilla JS front end with no build step.
Everything (UI, API messages, prompts, docs, comments) is in English.

## Security rules (non-negotiable, even "to go faster")

1. **The AI has no tools.** It gets text and returns text. The code decides what to do
   with its answer. Never add tool calling, MCP access or network access for the AI.
   For the `claude_cli` provider, keep `--tools ""` and `--strict-mcp-config`.
2. **No sending, no deleting.** The code has no SMTP and never calls
   `delete_messages`/`expunge`. The only allowed IMAP writes are: mark as read, and
   append a draft to the Drafts folder (always triggered by a user click).
3. **Message content is untrusted data.** Always pass it to the AI inside a delimited
   block (see `beseder/ai/tasks.py`), and **validate** every AI output: category in the
   enum, ids present in the batch that was sent, otherwise ignore it.
4. **Never `innerHTML` with message or AI content** in the front end. Use `textContent`
   or the `h()` / `put()` helpers. Message HTML is sanitized server-side (nh3) and shown
   in a `sandbox` iframe without scripts, with remote images blocked by default.
5. **Secrets encrypted at rest** (Fernet, `data/secret.key` with mode 0600). Never log
   passwords, tokens or message content.
6. API requests that change anything require the `X-Beseder: 1` header (anti-CSRF).
   Do not remove that middleware.

## Commands

- Install: `pip install -r requirements-dev.txt`
- Run: `python -m beseder` (listens on 127.0.0.1:8000 by default)
- Tests: `python -m pytest -q`
- Docker: `docker compose up -d` (image in `Dockerfile`, data in the `beseder-data` volume)
- User docs live in `docs/`: keep them in sync when a setup step or a screen changes.

## Layout

- `beseder/mail/`: IMAP connection, sync, parsing, Microsoft OAuth
- `beseder/mail/providers.py`: every supported mail provider (server, steps shown to the user).
  Adding a provider = one entry there + a section in `docs/mailboxes.md`.
- `beseder/ai/`: pluggable AI providers + tasks (triage, brief, draft)
- `beseder/main.py`: API routes
- `web/`: the PWA (three columns on desktop, bottom tab bar on phones)
- The first-run setup assistant is in `web/app.js` (`renderWelcome`); it reuses the guided
  mailbox and AI setup also shown in Settings.
