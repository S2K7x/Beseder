"""Mail providers Beseder knows how to connect to, with the steps shown to the user.

Server names and setup steps were checked against each provider's help pages (October 2026).
The front end gets this list from /api/mail/providers, so there is one source of truth.
"""

DOCS = "https://github.com/S2K7x/Beseder/blob/HEAD/docs/mailboxes.md"

# Order matters: the first four are shown as big buttons, the rest in "More providers".
PROVIDERS: dict[str, dict] = {
    "gmail": {
        "label": "Gmail", "mark": "G", "host": "imap.gmail.com", "port": 993,
        "domains": ["gmail.com", "googlemail.com"],
        "password_label": "App password", "placeholder": "abcd efgh ijkl mnop", "strip_spaces": True,
        "steps": [
            {"t": "Turn on 2-Step Verification on your Google account.",
             "url": "https://myaccount.google.com/signinoptions/twosv", "label": "Open Google security"},
            {"t": "Create an app password named “Beseder”.",
             "url": "https://myaccount.google.com/apppasswords", "label": "Open App passwords"},
            {"t": "Copy the 16-letter password and paste it below. Spaces don't matter."},
        ],
    },
    "outlook": {
        "label": "Outlook", "mark": "O", "host": "outlook.office365.com", "port": 993, "auth": "oauth",
        "domains": ["outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr", "hotmail.co.uk",
                    "live.com", "live.fr", "msn.com"],
        "steps": [
            {"t": "Once only: create a free Microsoft app ID (about 10 minutes, a free Azure account is needed).",
             "url": f"{DOCS}#outlook", "label": "Follow the guide"},
            {"t": "Paste its Application (client) ID below."},
            {"t": "Tap Sign in with Microsoft and type the code it shows on microsoft.com/devicelogin."},
        ],
    },
    "icloud": {
        "label": "iCloud", "mark": "i", "host": "imap.mail.me.com", "port": 993,
        "domains": ["icloud.com", "me.com", "mac.com"],
        # Apple: the username is usually the name before @, sometimes the full address.
        "username": "local_then_full",
        "password_label": "App-specific password", "placeholder": "abcd-efgh-ijkl-mnop",
        "steps": [
            {"t": "Sign in to your Apple Account (two-factor authentication must be on).",
             "url": "https://account.apple.com", "label": "Open Apple Account"},
            {"t": "Go to Sign-In and Security › App-Specific Passwords, tap +, name it “Beseder”."},
            {"t": "Paste the password below with your iCloud address."},
        ],
    },
    "yahoo": {
        "label": "Yahoo", "mark": "Y", "host": "imap.mail.yahoo.com", "port": 993,
        "domains": ["yahoo.com", "yahoo.fr", "yahoo.co.uk", "yahoo.de", "yahoo.es", "yahoo.it",
                    "ymail.com", "rocketmail.com"],
        "password_label": "App password", "placeholder": "abcdefghijklmnop", "strip_spaces": True,
        "steps": [
            {"t": "Open Yahoo Account security.", "url": "https://login.yahoo.com/account/security",
             "label": "Open Yahoo security"},
            {"t": "Tap Generate app password, name it “Beseder”."},
            {"t": "Paste the password below with your Yahoo address."},
        ],
    },
    "aol": {
        "label": "AOL", "mark": "A", "host": "imap.aol.com", "port": 993,
        "domains": ["aol.com", "aol.fr", "aol.co.uk", "aim.com"],
        "password_label": "App password", "strip_spaces": True,
        "steps": [
            {"t": "Open AOL Account security.", "url": "https://login.aol.com/account/security",
             "label": "Open AOL security"},
            {"t": "Tap Generate app password, name it “Beseder”."},
            {"t": "Paste the password below with your AOL address."},
        ],
    },
    "fastmail": {
        "label": "Fastmail", "mark": "F", "host": "imap.fastmail.com", "port": 993,
        "domains": ["fastmail.com", "fastmail.fm"],
        "password_label": "App password",
        "steps": [
            {"t": "In Fastmail, open Settings › Privacy & Security › Manage app passwords and access.",
             "url": "https://app.fastmail.com/settings/security", "label": "Open Fastmail settings"},
            {"t": "Create a new app password with access to Mail (IMAP)."},
            {"t": "Paste it below with your Fastmail address."},
        ],
    },
    "zoho": {
        "label": "Zoho Mail", "mark": "Z", "host": "imap.zoho.com", "port": 993,
        "domains": ["zoho.com", "zohomail.com", "zohomail.eu", "zoho.eu"],
        "domain_hosts": {"zohomail.eu": "imap.zoho.eu", "zoho.eu": "imap.zoho.eu"},
        "password_label": "App-specific password",
        "steps": [
            {"t": "In Zoho Mail settings, make sure IMAP access is enabled (Mail Accounts › IMAP).",
             "url": "https://mail.zoho.com", "label": "Open Zoho Mail"},
            {"t": "Create an app-specific password under Security › App Passwords.",
             "url": "https://accounts.zoho.com/home#security", "label": "Open App Passwords"},
            {"t": "Paste it below. Accounts hosted in Europe use the server imap.zoho.eu (see Server settings)."},
        ],
    },
    "gmx": {
        "label": "GMX", "mark": "X", "host": "imap.gmx.net", "port": 993,
        "domains": ["gmx.net", "gmx.de", "gmx.fr", "gmx.at", "gmx.ch", "gmx.com", "gmx.us", "gmx.co.uk"],
        "domain_hosts": {"gmx.com": "imap.gmx.com", "gmx.us": "imap.gmx.com", "gmx.co.uk": "imap.gmx.com"},
        "password_label": "Password",
        "steps": [
            {"t": "In GMX webmail, open Settings › POP3 & IMAP and allow access via IMAP."},
            {"t": "Enter your GMX address and password below (or an app password if you use 2FA)."},
        ],
    },
    "yandex": {
        "label": "Yandex", "mark": "Я", "host": "imap.yandex.com", "port": 993,
        "domains": ["yandex.com", "yandex.ru", "ya.ru"],
        "password_label": "App password",
        "steps": [
            {"t": "In Yandex Mail settings › Email clients, turn on IMAP and “App passwords and OAuth tokens”."},
            {"t": "Create an app password of type Mail in Yandex ID.", "url": "https://id.yandex.com/security",
             "label": "Open App passwords"},
            {"t": "Paste it below (it is shown only once)."},
        ],
    },
    "orange": {
        "label": "Orange", "mark": "Or", "host": "imap.orange.fr", "port": 993,
        "domains": ["orange.fr", "wanadoo.fr"],
        "password_label": "Mail app password",
        "steps": [
            {"t": "In Orange Mail, open Settings › Security and turn on POP or IMAP access (off by default)."},
            {"t": "In your Espace client › Connexion et sécurité, create the password for mail apps (POP/IMAP/SMTP)."},
            {"t": "Paste that password below with your Orange address."},
        ],
    },
    "free": {
        "label": "Free", "mark": "Fr", "host": "imap.free.fr", "port": 993,
        "domains": ["free.fr"],
        "password_label": "Password",
        "steps": [{"t": "Nothing to turn on: enter your full Free address and your usual password."}],
    },
    "sfr": {
        "label": "SFR", "mark": "S", "host": "imap.sfr.fr", "port": 993,
        "domains": ["sfr.fr", "neuf.fr", "club-internet.fr", "cegetel.net"],
        "password_label": "Password",
        "steps": [{"t": "Enter your full SFR address and your mailbox password."}],
    },
    "laposte": {
        "label": "La Poste", "mark": "LP", "host": "imap.laposte.net", "port": 993,
        "domains": ["laposte.net"],
        "password_label": "Password",
        "steps": [{"t": "Nothing to turn on: enter your laposte.net address and your usual password."}],
    },
    "bbox": {
        "label": "Bouygues (Bbox)", "mark": "B", "host": "imap.bbox.fr", "port": 993,
        "domains": ["bbox.fr"],
        "password_label": "Password",
        "steps": [{"t": "Enter your full bbox.fr address and your mailbox password."}],
    },
    "imap": {
        "label": "Other (IMAP)", "mark": "@", "host": "", "port": 993,
        "domains": [],
        "password_label": "Password",
        "steps": [
            {"t": "Find your provider's IMAP server in its help pages. It often looks like imap.yourprovider.com."},
            {"t": "Port 993 uses SSL. Port 143 uses STARTTLS. Both are encrypted."},
            {"t": "If your provider offers app passwords, use one instead of your main password."},
        ],
    },
}

POPULAR = ["gmail", "outlook", "icloud", "yahoo"]


def host_for(kind: str, email: str) -> str:
    p = PROVIDERS[kind]
    domain = email.rsplit("@", 1)[-1].lower()
    return p.get("domain_hosts", {}).get(domain, p["host"])


def usernames_for(kind: str, email: str, username: str = "") -> list[str]:
    """Usernames to try, in order."""
    if username:
        return [username]
    email = email.strip()
    if PROVIDERS[kind].get("username") == "local_then_full" and "@" in email:
        return [email.split("@", 1)[0], email]
    return [email]


def detect(email: str) -> str | None:
    domain = email.rsplit("@", 1)[-1].lower()
    for key, p in PROVIDERS.items():
        if domain in p["domains"]:
            return key
    return None


def public_list() -> list[dict]:
    return [{"key": k, "popular": k in POPULAR, "auth": p.get("auth", "password"), **p} for k, p in PROVIDERS.items()]
