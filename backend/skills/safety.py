from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from backend.settings import settings

USER_AGENT = "CrawlerAgent/1.2 (+local)"
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
MIN_HOST_INTERVAL_SECONDS = 1.0

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
}


class SafetyError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    hostname: str
    port: int
    ip: str
    scheme: str

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        if self.port == default:
            return self.hostname
        return f"{self.hostname}:{self.port}"

    @property
    def curl_resolve(self) -> str:
        return f"{self.hostname}:{self.port}:{self.ip}"

    @property
    def pinned_url(self) -> str:
        parsed = urlparse(self.url)
        host = self.ip if ":" not in str(self.ip) else f"[{self.ip}]"
        default = 443 if self.scheme == "https" else 80
        netloc = host if self.port == default else f"{host}:{self.port}"
        return parsed._replace(netloc=netloc).geturl()



def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _is_blocked_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    return any(ip in network for network in _BLOCKED_NETWORKS)


def resolve_fetch_url(url: str, *, resolver=socket.getaddrinfo) -> ResolvedTarget:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SafetyError(f"protocol not allowed: {parsed.scheme or 'missing'}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise SafetyError("missing hostname")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise SafetyError(f"hostname not allowed: {host}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        ip_literal = None

    if ip_literal is not None:
        if _is_blocked_ip(ip_literal):
            raise SafetyError(f"ip not allowed: {host}")
        return ResolvedTarget(url=url, hostname=host, port=port, ip=str(ip_literal), scheme=parsed.scheme)

    try:
        infos = resolver(host, port)
    except OSError as exc:
        raise SafetyError(f"dns failed: {host}") from exc

    if not infos:
        raise SafetyError(f"dns returned no addresses: {host}")

    allowed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    blocked: list[str] = []
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise SafetyError(f"invalid resolved address: {addr}") from exc
        if _is_blocked_ip(ip):
            blocked.append(str(ip))
            continue
        allowed.append(ip)

    if not allowed:
        sample = blocked[0] if blocked else "none"
        raise SafetyError(f"resolved ip not allowed: {sample}")

    allowed.sort(key=lambda item: (item.version != 4, str(item)))
    return ResolvedTarget(url=url, hostname=host, port=port, ip=str(allowed[0]), scheme=parsed.scheme)


def validate_fetch_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    return resolve_fetch_url(url, resolver=resolver).url


_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def sandbox_download_dir(request_id: str, *, root: Path | None = None) -> Path:
    if not _REQUEST_ID_RE.match(request_id or ""):
        raise SafetyError("invalid request_id")
    base = (root or (settings.sqlite_path.parent / "downloads")).resolve()
    dest = (base / request_id).resolve()
    if dest != base and base not in dest.parents:
        raise SafetyError("download path escapes sandbox")
    dest.mkdir(parents=True, exist_ok=True)
    return dest

