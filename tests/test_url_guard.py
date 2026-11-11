from unittest.mock import patch

import pytest

from app.services.url_guard import URLPolicyError, validate_target_url


def test_url_guard_allows_exact_allowlisted_host() -> None:
    with patch("app.services.url_guard._resolved_addresses", return_value=("93.184.216.34",)):
        result = validate_target_url(
            "https://qa.example.com/path?q=1#section",
            allowed_hosts=("qa.example.com",),
        )
    assert result == "https://qa.example.com/path?q=1"


def test_url_guard_rejects_unlisted_host() -> None:
    with pytest.raises(URLPolicyError, match="not in ALLOWED_TARGET_HOSTS"):
        validate_target_url("https://other.example.com", allowed_hosts=("qa.example.com",))


def test_url_guard_rejects_credentials_and_non_http_protocols() -> None:
    with pytest.raises(URLPolicyError, match="Credentials"):
        validate_target_url("https://user:pass@qa.example.com", allowed_hosts=("qa.example.com",))
    with pytest.raises(URLPolicyError, match="Only HTTP"):
        validate_target_url("file:///etc/passwd", allowed_hosts=("qa.example.com",))


def test_url_guard_blocks_private_resolution_by_default() -> None:
    with patch("app.services.url_guard._resolved_addresses", return_value=("10.0.0.5",)):
        with pytest.raises(URLPolicyError, match="non-public IP"):
            validate_target_url("https://qa.example.com", allowed_hosts=("qa.example.com",))


def test_url_guard_allows_private_targets_only_when_explicitly_enabled() -> None:
    result = validate_target_url(
        "http://127.0.0.1:8000/demo",
        allowed_hosts=("127.0.0.1",),
        allow_loopback_targets=True,
    )
    assert result == "http://127.0.0.1:8000/demo"


def test_wildcard_allowlist_matches_subdomains() -> None:
    with patch("app.services.url_guard._resolved_addresses", return_value=("93.184.216.34",)):
        assert validate_target_url(
            "https://staging.example.com", allowed_hosts=("*.example.com",)
        ) == "https://staging.example.com/"


def test_redact_sensitive_url_parameters() -> None:
    from app.services.url_guard import redact_sensitive_url

    cleaned = redact_sensitive_url("https://qa.example.com/report?token=secret&view=full&api_key=abc#top")
    assert "secret" not in cleaned
    assert "abc" not in cleaned
    assert "view=full" in cleaned
    assert "%5BREDACTED%5D" in cleaned


def test_private_network_targets_require_separate_explicit_opt_in() -> None:
    with patch("app.services.url_guard._resolved_addresses", return_value=("10.10.2.3",)):
        with pytest.raises(URLPolicyError, match="address range is disabled"):
            validate_target_url("https://staging.example.com", allowed_hosts=("staging.example.com",))
        assert validate_target_url(
            "https://staging.example.com", allowed_hosts=("staging.example.com",), allow_private_targets=True
        ) == "https://staging.example.com/"


def test_invalid_port_is_reported_as_url_policy_error() -> None:
    with pytest.raises(URLPolicyError, match="Invalid port"):
        validate_target_url("https://qa.example.com:99999", allowed_hosts=("qa.example.com",))
