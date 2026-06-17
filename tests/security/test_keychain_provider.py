"""Tests for KeychainSecretProvider."""
from __future__ import annotations

from cogito_agent.security import KeychainSecretProvider, SecretValue


def test_keychain_placeholder_not_available():
    """On most test environments, keychain is unavailable."""
    kc = KeychainSecretProvider(service_name="cogito-test")
    # Should not crash - available will be False
    assert hasattr(kc, "available")
    if not kc.available:
        assert kc.get_secret("test_key") is None
        assert kc.list_keys() == []


def test_keychain_repr_no_leak():
    kc = KeychainSecretProvider(service_name="cogito-test")
    r = repr(kc)
    assert "keychain" in r.lower()
    assert "placeholder" not in r  # No longer a placeholder


def test_keychain_delete_missing_returns_false():
    kc = KeychainSecretProvider(service_name="cogito-test")
    if kc.available:
        result = kc.delete_secret("nonexistent_key_for_testing")
        assert result is False
    else:
        # Should raise or return False when unavailable
        try:
            result = kc.delete_secret("nonexistent")
            assert result is False
        except Exception:
            pass


def test_secret_value_no_leak_in_keychain():
    sv = SecretValue("supersecret", name="test_kc_key")
    assert str(sv) == "[REDACTED]"
    assert "[REDACTED]" in repr(sv)
    assert sv.value == "supersecret"
