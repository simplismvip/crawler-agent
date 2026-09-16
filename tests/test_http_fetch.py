from __future__ import annotations

from backend.skills.http_fetch import ResolvedTarget, pinned_getaddrinfo, resolve_fetch_url


def test_resolve_fetch_url_exposes_pin_tuple() -> None:
    def resolver(_host: str, *_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    target = resolve_fetch_url("https://example.com/page", resolver=resolver)
    assert isinstance(target, ResolvedTarget)
    assert target.hostname == "example.com"
    assert target.ip == "93.184.216.34"
    assert target.port == 443
    assert target.curl_resolve == "example.com:443:93.184.216.34"
    assert target.host_header == "example.com"
    assert "93.184.216.34" in target.pinned_url
    assert "example.com" in target.url


def test_pinned_getaddrinfo_forces_validated_ip() -> None:
    import socket

    target = ResolvedTarget(
        url="https://example.com/page",
        hostname="example.com",
        port=443,
        ip="93.184.216.34",
        scheme="https",
    )
    with pinned_getaddrinfo(target):
        infos = socket.getaddrinfo("example.com", 443)
    assert infos[0][4][0] == "93.184.216.34"

