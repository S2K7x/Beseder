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
| *Login rejected by …* | Most providers need an **app password**, not your usual one ([guide](mailboxes.md)). Orange needs its separate mail app password. |
| Gmail worked, then *Login rejected* | Changing your Google password revokes app passwords. Create a new one. |
| GMX, Zoho, Yandex, Orange: *Login rejected* | IMAP access must be turned on in the provider's settings first ([guide](mailboxes.md)). |
| *Cannot reach … (timed out)* | Wrong server name or port, or the Pi has no internet. Known providers are filled in for you; check **Advanced server settings** if you changed them. |
| *Microsoft session expired, reconnect the account* | Remove the Outlook mailbox in Settings and add it again. |
| Outlook: *AADSTS7000218* or "client_secret" | In Azure › Authentication, set **Allow public client flows** to **Yes**. |
| Outlook: *AADSTS700016* (app not found) | The client ID is wrong, or the app isn't set to accept personal Microsoft accounts. |
| Azure: "creating applications outside of a directory has been deprecated" | You need a directory first: create a free Azure account ([guide](mailboxes.md#outlook)). |

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

## Notifications don't arrive

- On iPhone: Beseder must be opened from its Home Screen icon (not Safari), on iOS 16.4+.
  Then Settings › Notifications › **Turn on for this device**.
- Tap **Send a test**. If it says no device received it, turn notifications off and on
  again on that device.
- Check that notifications for Beseder are allowed in the phone's settings.
- "Important emails only" needs auto-triage on: without an AI, choose **Every new email**.
- The Pi must be able to reach the internet (Apple's and Google's push services).

## New mail takes a few minutes to show up

Beseder keeps a live connection to each inbox (IMAP IDLE) and shows new mail within
seconds. A few providers don't support it: Beseder then checks every 5 minutes. The logs
say "has no IMAP IDLE" for those mailboxes.

## Gmail: no Undo after archiving

Undo looks for the email in "All Mail". In Gmail on the web, open Settings › Labels and tick
**Show in IMAP** for All Mail. Archiving itself works either way.

## Archive or Move says the server can't move messages

Your provider doesn't support the IMAP MOVE command. Archive the email from your usual mail
app instead.

## Emails aren't being sorted

- Is **Auto-triage** on? It's the switch in the **Categories** card.
- Is an AI connected? A red message in the Categories card shows the last AI error.
- Sorting runs after each sync (every 5 minutes). Tap the refresh button to sync now.

## Follow-ups stay empty

- **To reply** needs auto-triage: the AI marks emails that expect an answer while sorting
  them. Emails sorted before this feature existed aren't marked; new ones will be.
- **Waiting for a reply** needs your Sent folder. Beseder finds it on its own; if your
  provider names it oddly, the logs say "Sent folder sync failed". Only emails you sent that
  ask something (a question mark, "let me know"…) and are 2 to 30 days old show up.

## The morning brief doesn't arrive

- Check Settings › Assistant › Morning brief is on and Settings › Notifications is on for
  your device (tap **Send a test**).
- It only runs if you have unread mail and an AI connected, once a day. If Beseder was off
  at that time, it waits for the next day rather than briefing you hours late.

## Unsubscribe says "refused" or "could not reach"

Beseder only unsubscribes in one tap through public `https` links (see
[security](security.md#unsubscribing-is-locked-down)). If the sender's server refuses,
open the email and use the unsubscribe link at the bottom of the message, or mark the sender
with the tag button so their mail goes to Promotions.

## Search doesn't find an old email

The search box looks in your inbox first. Tap **Search all mail on the server** below the
results (or open **Folders**) to search everything your provider keeps. On Gmail, pick
**All mail**: it contains every archived email. Some providers only search whole words.

## A snoozed email still shows in my phone's mail app

That's expected: snooze only exists in Beseder, so it never moves anything on your mail
server. The email comes back on top of Beseder's inbox at the time you picked. To bring it
back sooner, tap the **Snoozed** chip above the list, then **Back to inbox now**.

## Two different emails are grouped as one conversation (or the reverse)

Beseder groups by the reply headers mail apps add, not by subject. A few apps leave them
out: their replies then show as separate emails. Archive and Undo always act on what you
see grouped.

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
