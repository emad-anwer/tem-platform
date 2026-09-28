from __future__ import annotations

import pytest

from app.core.pipeline.validation import (
    TargetKind,
    normalize_app_store_url,
    normalize_cidr,
    normalize_domain,
    normalize_ip,
    normalize_keyword,
    normalize_target,
)


class TestNormalizeDomain:
    def test_lowercases_and_strips_trailing_dot(self):
        assert normalize_domain("Admin.Example.COM.") == "admin.example.com"

    def test_rejects_wildcard(self):
        with pytest.raises(ValueError, match="wildcard"):
            normalize_domain("*.example.com")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            normalize_domain("   ")

    def test_rejects_single_label(self):
        with pytest.raises(ValueError, match="two labels"):
            normalize_domain("localhost")

    def test_converts_unicode_to_punycode(self):
        assert normalize_domain("müller.example.com") == "xn--mller-kva.example.com"

    def test_rejects_label_over_63_chars(self):
        long_label = "a" * 64
        with pytest.raises(ValueError):
            normalize_domain(f"{long_label}.example.com")

    def test_rejects_overall_length_over_253(self):
        long_domain = ".".join(["a" * 50] * 6) + ".com"
        with pytest.raises(ValueError, match="maximum length"):
            normalize_domain(long_domain)


class TestNormalizeIp:
    def test_ipv4_canonical_form(self):
        assert normalize_ip("192.168.001.001", version=4) == "192.168.1.1"

    def test_rejects_version_mismatch(self):
        with pytest.raises(ValueError, match="IPv4"):
            normalize_ip("2001:db8::1", version=4)

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            normalize_ip("not-an-ip", version=4)

    def test_ipv6_canonical_form(self):
        assert normalize_ip("2001:0DB8::1", version=6) == "2001:db8::1"


class TestNormalizeCidr:
    def test_normalizes_host_bits(self):
        assert normalize_cidr("192.168.1.5/24") == "192.168.1.0/24"

    def test_rejects_invalid_cidr(self):
        with pytest.raises(ValueError):
            normalize_cidr("not-a-cidr")


class TestNormalizeKeyword:
    def test_collapses_whitespace_and_casefolds(self):
        assert normalize_keyword("  Acme   Corp  ") == "acme corp"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            normalize_keyword("   ")


class TestNormalizeAppStoreUrl:
    def test_lowercases_host_and_strips_trailing_slash(self):
        result = normalize_app_store_url("HTTPS://Apps.Apple.COM/us/app/acme/id123/")
        assert result == "https://apps.apple.com/us/app/acme/id123"

    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValueError, match="http"):
            normalize_app_store_url("ftp://apps.apple.com/id123")

    def test_rejects_missing_host(self):
        with pytest.raises(ValueError, match="host"):
            normalize_app_store_url("https:///id123")


class TestNormalizeTargetDispatch:
    @pytest.mark.parametrize(
        ("kind", "value", "expected"),
        [
            (TargetKind.DOMAIN, "Example.COM", "example.com"),
            (TargetKind.HOSTNAME, "Lab-Nginx", "lab-nginx"),
            (TargetKind.IPV4, "10.0.0.1", "10.0.0.1"),
            (TargetKind.IPV6, "::1", "::1"),
            (TargetKind.CIDR, "10.0.0.0/8", "10.0.0.0/8"),
            (TargetKind.KEYWORD, "  Acme  ", "acme"),
            (TargetKind.BRAND_NAME, "  Acme  ", "acme"),
            (
                TargetKind.APP_STORE_URL,
                "https://APPS.apple.com/id123/",
                "https://apps.apple.com/id123",
            ),
        ],
    )
    def test_dispatches_to_correct_normalizer(self, kind, value, expected):
        assert normalize_target(kind, value) == expected


def test_hostname_kind_accepts_single_label_where_domain_still_rejects():
    """ADR-0004 §5: the two kinds are deliberately different floors."""
    assert normalize_target(TargetKind.HOSTNAME, "lab-nginx") == "lab-nginx"
    with pytest.raises(ValueError):
        normalize_target(TargetKind.DOMAIN, "lab-nginx")
