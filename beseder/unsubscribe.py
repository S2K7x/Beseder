"""One-click unsubscribe (RFC 8058), always on a user click.

The link comes from a stranger's email, so the request is locked down: https only, the
server must resolve to public addresses (nothing on the Pi's network or Tailscale), the
connection goes to the address that was checked, no redirects, no cookies, 10 s timeout.
"""

import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

import certifi
import httpcore

TIMEOUT = 10


class UnsubscribeError(Exception):
    pass


async def public_address(host: str, port: int) -> str:
    """Resolves host and returns one of its addresses, only if all of them are public."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise UnsubscribeError(f"Cannot find {host}")
    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise UnsubscribeError(f"Cannot find {host}")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise UnsubscribeError("This unsubscribe link points to a private network: refused")
    return sorted(addrs)[0]


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Connects to the address that was checked, whatever DNS says a second later. TLS still
    checks the certificate against the link's host name."""

    def __init__(self, ip: str):
        self.ip = ip
        self.inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self.inner.connect_tcp(self.ip, port, timeout=timeout, local_address=local_address,
                                            socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


async def one_click(url: str) -> int:
    """POSTs "List-Unsubscribe=One-Click" to the link. Returns the HTTP status."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise UnsubscribeError("Only https unsubscribe links are supported")
    port = parts.port or 443
    ip = await public_address(parts.hostname, port)
    ctx = ssl.create_default_context(cafile=certifi.where())
    async with httpcore.AsyncConnectionPool(ssl_context=ctx, network_backend=_PinnedBackend(ip)) as pool:
        try:
            r = await pool.request(
                "POST", url,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Beseder"},
                content=b"List-Unsubscribe=One-Click",
                extensions={"timeout": {"connect": TIMEOUT, "read": TIMEOUT, "write": TIMEOUT, "pool": TIMEOUT}},
            )
        except httpcore.TimeoutException:
            raise UnsubscribeError("The sender's server did not answer")
        except (httpcore.NetworkError, httpcore.ProtocolError, ssl.SSLError) as e:
            raise UnsubscribeError(f"Could not reach the sender's server ({type(e).__name__})")
    if r.status >= 400:
        raise UnsubscribeError(f"The sender's server refused ({r.status})")
    return r.status
