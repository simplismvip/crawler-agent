from __future__ import annotations

import contextlib
import socket
from collections.abc import Iterator

from backend.skills.safety import ResolvedTarget, resolve_fetch_url

__all__ = ["ResolvedTarget", "resolve_fetch_url", "pinned_getaddrinfo", "curl_cffi_available"]


def curl_cffi_available() -> bool:
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


@contextlib.contextmanager
def pinned_getaddrinfo(target: ResolvedTarget) -> Iterator[None]:
    original = socket.getaddrinfo

    def wrapped(host: str, port, *args, **kwargs):
        if host == target.hostname or host == target.ip:
            family = socket.AF_INET6 if ":" in target.ip else socket.AF_INET
            port_num = int(port) if port else target.port
            return [(family, socket.SOCK_STREAM, 6, "", (target.ip, port_num))]
        return original(host, port, *args, **kwargs)

    socket.getaddrinfo = wrapped  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.getaddrinfo = original  # type: ignore[method-assign]
