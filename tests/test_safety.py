import pytest

from backend.skills.safety import SafetyError, validate_fetch_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a",
        "javascript:alert(1)",
        "http://127.0.0.1/",
        "http://localhost/secret",
        "http://10.0.0.8/admin",
        "http://192.168.1.1/",
        "http://172.16.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(SafetyError):
        validate_fetch_url(url)


def test_rejects_hostname_that_resolves_to_loopback() -> None:
    def resolver(_host: str, *_args, **_kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 80))]

    with pytest.raises(SafetyError):
        validate_fetch_url("https://evil.example", resolver=resolver)


def test_allows_public_http_url() -> None:
    def resolver(_host: str, *_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 80))]

    assert validate_fetch_url("https://example.com/page", resolver=resolver) == "https://example.com/page"


def test_skips_poisoned_ipv6_if_public_ipv4_exists() -> None:
    from backend.skills.safety import resolve_fetch_url

    def resolver(_host: str, *_args, **_kwargs):
        return [
            (10, 1, 6, "", ("2001::1", 443, 0, 0)),
            (2, 1, 6, "", ("142.250.1.1", 443)),
        ]

    target = resolve_fetch_url("https://youtube.com/watch", resolver=resolver)
    assert target.ip == "142.250.1.1"


def test_rejects_when_all_resolved_ips_are_blocked() -> None:
    def resolver(_host: str, *_args, **_kwargs):
        return [(10, 1, 6, "", ("2001::1", 443, 0, 0))]

    with pytest.raises(SafetyError, match="resolved ip not allowed"):
        validate_fetch_url("https://youtube.com/watch", resolver=resolver)

