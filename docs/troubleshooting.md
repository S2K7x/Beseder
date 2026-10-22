# Troubleshooting

Start by looking at the logs, they usually say what's wrong:

```bash
docker compose logs --tail 50
```

## The page doesn't open

- **Is it running?** `docker compose ps` should show `beseder` as `healthy`. If not,
  `docker compose up -d` and check the logs.
- **On the Pi itself**, open `http://localhost:8000`.
- **From your phone**, Tailscale must be on (on the phone *and* the Pi) and
  `tailscale serve status` must show port 8000.

## "Invalid host header" or error 400 when opening the page

Beseder only accepts the addresses it expects: `localhost`, `127.0.0.1` and your
`*.ts.net` Tailscale address. If you use another address (for example a custom domain),
add it in a `.env` file next to `docker-compose.yml`:

```
BESEDER_ALLOWED_HOSTS=localhost,127.0.0.1,*.ts.net,mail.example.com
```

then run `docker compose up -d`.

## A mailbox won't connect

| Message | What to do |
|---|---|
| *Login rejected. Use an app password.* | You used your normal password, or mistyped the app password. Create a new one ([guide](mailboxes.md)). |
| *Cannot reach … (timed out)* | Wrong server name or port, or the Pi has no internet. Gmail, iCloud and Outlook servers are filled in for you. |
| *Microsoft session expired, reconnect the account* | Remove the Outlook mailbox in Settings and add it again. |
| Outlook: *AADSTS…* errors | Check the Azure steps, especially **Allow public client flows = Yes** and the account type. |

A mailbox with a problem shows the error in red in the **Mailboxes** card.

## The AI test fails

| Message | What to do |
|---|---|
| *401* or *key rejected* | The key is wrong or was deleted. Create a new one. |
| *429* or *rate limit* | Free tiers have limits. Wait a bit, or pick another model. |
| *No model found* | Ollama: download one first with `ollama pull llama3.2`. |
| Ollama: *connection refused* | In Docker, Ollama must listen with `OLLAMA_HOST=0.0.0.0` ([guide](ai.md#ollama)). |
| *Command not found: claude* | Rebuild with `WITH_CLAUDE_CLI=true` ([guide](ai.md#claude-code)). |
| Claude Code: *not logged in* | Run `docker compose exec -it beseder claude` and sign in. |

## Emails aren't being sorted

- Is **Auto-triage** on? It's the switch in the **Categories** card.
- Is an AI connected? A red message in the Categories card shows the last AI error.
- Sorting runs after each sync (every 5 minutes). Tap the refresh button to sync now.

## I changed a category but the AI keeps changing it back

It won't: a category you set by hand is never overwritten. To file *all* emails from a
sender, pick the category and tap the **tag** button next to "Reply with AI".

## Start over

To restart the setup assistant: **Settings › Help › Run setup again**.

To erase everything (mailboxes, settings, synced mail) and start fresh:

```bash
docker compose down -v
docker compose up -d
```

This deletes nothing in your actual mailboxes.
