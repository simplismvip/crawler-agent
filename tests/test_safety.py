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
