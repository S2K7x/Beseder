"""Microsoft OAuth (Outlook / Hotmail / Live) with the device code flow.

Outlook.com no longer accepts passwords over IMAP: an OAuth token is required.
The device code flow needs no public server: the app shows a code, and you
enter it at microsoft.com/devicelogin from any device.
"""

import time
import uuid
from dataclasses import dataclass

import httpx

SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"


def _base(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


@dataclass
class PendingFlow:
    client_id: str
    tenant: str
    device_code: str
    email: str
    name: str
    expires_at: float
    interval: int


class MicrosoftOAuth:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=30)
        self.pending: dict[str, PendingFlow] = {}
        # account_id -> (access_token, expires_at)
        self._access: dict[int, tuple[str, float]] = {}

    def start(self, client_id: str, tenant: str, email: str, name: str) -> dict:
        r = self.http.post(f"{_base(tenant)}/devicecode", data={"client_id": client_id, "scope": SCOPE})
        data = r.json()
        if r.status_code != 200:
            raise ValueError(data.get("error_description") or data.get("error") or "Microsoft error")
        flow_id = uuid.uuid4().hex
        self.pending[flow_id] = PendingFlow(
            client_id=client_id,
            tenant=tenant,
            device_code=data["device_code"],
            email=email,
            name=name,
            expires_at=time.time() + int(data.get("expires_in", 900)),
            interval=int(data.get("interval", 5)),
        )
        return {
            "flow_id": flow_id,
            "user_code": data["user_code"],
            "verification_uri": data.get("verification_uri", "https://microsoft.com/devicelogin"),
            "interval": int(data.get("interval", 5)),
        }

    def poll(self, flow_id: str) -> tuple[str, dict | None, PendingFlow | None]:
        """Returns ("pending"|"done"|"error", tokens|message, flow)."""
        flow = self.pending.get(flow_id)
        if not flow:
            return "error", {"message": "Unknown or expired sign-in flow"}, None
        if time.time() > flow.expires_at:
            self.pending.pop(flow_id, None)
            return "error", {"message": "The code expired, please start again"}, None
        r = self.http.post(
            f"{_base(flow.tenant)}/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": flow.client_id,
                "device_code": flow.device_code,
            },
        )
        data = r.json()
        if r.status_code == 200:
            self.pending.pop(flow_id, None)
            return "done", data, flow
        err = data.get("error")
        if err in ("authorization_pending", "slow_down"):
            return "pending", None, flow
        self.pending.pop(flow_id, None)
        return "error", {"message": data.get("error_description") or err or "Microsoft error"}, None

    def access_token(self, account_id: int, secret: dict, save_secret) -> str:
        """Returns a valid access token, refreshing it when needed.

        Microsoft rotates refresh tokens: the new one is stored through save_secret.
        """
        cached = self._access.get(account_id)
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        r = self.http.post(
            f"{_base(secret.get('tenant', 'common'))}/token",
            data={
                "grant_type": "refresh_token",
                "client_id": secret["client_id"],
                "refresh_token": secret["refresh_token"],
                "scope": SCOPE,
            },
        )
        data = r.json()
        if r.status_code != 200:
            raise PermissionError(
                "Microsoft session expired, reconnect the account: "
                + (data.get("error_description") or data.get("error") or "")
            )
        if data.get("refresh_token") and data["refresh_token"] != secret["refresh_token"]:
            save_secret({**secret, "refresh_token": data["refresh_token"]})
        token = data["access_token"]
        self._access[account_id] = (token, time.time() + int(data.get("expires_in", 3600)))
        return token
