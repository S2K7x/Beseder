# Connect your mailboxes

Beseder reads your mail over IMAP, the standard every mail provider supports. Instead of
your real password, you give it an **app password**: a separate password that only works
for mail and that you can revoke at any time without changing your main password.

You add mailboxes in the setup assistant or in **Settings › Mailboxes**.

![Adding a mailbox](images/setup-mailboxes.png)

## Gmail

1. Turn on **2-Step Verification**: [myaccount.google.com/signinoptions/twosv](https://myaccount.google.com/signinoptions/twosv).
   (App passwords don't exist without it.)
2. Open **App passwords**: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
3. Type `Beseder` and tap **Create**.
4. Copy the 16-letter password (spaces don't matter) and paste it in Beseder with your
   Gmail address.

If you use Google Workspace (work account) and don't see App passwords, your admin has
turned them off.

## iCloud

1. Sign in at [account.apple.com](https://account.apple.com).
2. Go to **Sign-In and Security › App-Specific Passwords** and tap **+**.
3. Name it `Beseder` and copy the password (it looks like `abcd-efgh-ijkl-mnop`).
4. Paste it in Beseder with your **@icloud.com** address (also works for @me.com and
   @mac.com).

## Outlook

Outlook.com, Hotmail and Live no longer accept app passwords: Beseder signs in the
official Microsoft way instead. It needs a free "app registration" on Microsoft Azure,
done **once** (about 5 minutes):

1. Go to [portal.azure.com](https://portal.azure.com) and sign in with your Microsoft account.
2. Search for **App registrations** and click **New registration**.
3. Name: `Beseder`. Under *Supported account types*, choose **Personal Microsoft accounts
   only** (or the option that includes both work and personal accounts if you also have a
   work mailbox). Leave *Redirect URI* empty. Click **Register**.
4. In the left menu, open **Authentication**, set **Allow public client flows** to
   **Yes**, and click **Save**.
5. Open **API permissions › Add a permission › APIs my organization uses**, search
   `Office 365 Exchange Online`, choose **Delegated permissions**, tick
   `IMAP.AccessAsUser.All`, and click **Add permissions**.
6. Go back to **Overview** and copy the **Application (client) ID**.

Then in Beseder:

1. Choose **Outlook**, enter your address and paste the client ID.
2. Tap **Sign in with Microsoft**. Beseder shows a short code.
3. Open [microsoft.com/devicelogin](https://microsoft.com/devicelogin) on any device, type
   the code and approve. Beseder finishes on its own.

You only do the Azure part once: Beseder remembers the client ID for your next Outlook
mailbox.

## Other providers (OVH, Proton Bridge, Fastmail, Yahoo…)

Choose **Other** and fill in:

- **IMAP server** and **port**: in your provider's help pages, usually
  `imap.yourprovider.com` and `993`.
- **Username**: usually your full address.
- **Password**: an app password if your provider offers them, otherwise your mailbox password.

## What Beseder does with your mailbox

- It syncs your **inbox** every 5 minutes (the last 30 days on the first sync).
- It marks an email as read when you open it, like any mail app.
- It saves a draft in your **Drafts** folder when you tap the save arrow.
- That's all: no sending, no deleting, no moving. Removing a mailbox from Beseder deletes
  nothing in the mailbox itself.

To revoke access at any time, delete the app password (Google, Apple) or remove Beseder
from [account.live.com/consent/Manage](https://account.live.com/consent/Manage) (Microsoft).
