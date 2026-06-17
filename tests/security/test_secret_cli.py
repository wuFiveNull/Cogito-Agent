"""Tests for secrets CLI."""
from __future__ import annotations

import os
import tempfile

from cogito_agent.cli.secrets import (
    _get_provider,
    _list_providers,
    _set_secret,
    _show_secret,
    _test_secret,
)
from cogito_agent.security import LocalSecretsProvider


def _make_ns(db_path: str, **kwargs):
    class NS:
        pass
    ns = NS()
    ns.db_path = db_path
    ns.secret_name = ""
    ns.value = ""
    ns.show_metadata = False
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


def _secrets_db_path(db_path: str) -> str:
    return db_path.replace(".db", "_secrets.db") if db_path and ".db" in db_path else db_path + "_secrets.db"


def test_list_empty(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns = _make_ns(db_path)
        _list_providers(ns)
        captured = capsys.readouterr()
        assert "No secrets" in captured.out
    finally:
        try: os.unlink(db_path)
        except: pass
        try: os.unlink(sdb)
        except: pass


def test_set_and_list(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns_set = _make_ns(db_path, secret_name="my_test_key", value="my_test_value")
        _set_secret(ns_set)
        captured = capsys.readouterr()
        assert "set" in captured.out.lower()

        ns_list = _make_ns(db_path)
        _list_providers(ns_list)
        captured = capsys.readouterr()
        assert "my_test_key" in captured.out
    finally:
        try: os.unlink(db_path)
        except: pass
        try: os.unlink(sdb)
        except: pass


def test_show_secret(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        # Set secret via the CLI provider so path matches
        provider = _get_provider(db_path)
        provider.set_secret("show_key", "show_val")
        ns = _make_ns(db_path, secret_name="show_key")
        _show_secret(ns)
        captured = capsys.readouterr()
        assert "show_key" in captured.out
        assert "[REDACTED]" in captured.out
        assert "show_val" not in captured.out
    finally:
        try: os.unlink(db_path)
        except: pass
        try: os.unlink(sdb)
        except: pass


def test_test_secret_available(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        provider = _get_provider(db_path)
        provider.set_secret("test_key_avail", "val")
        ns = _make_ns(db_path, secret_name="test_key_avail")
        _test_secret(ns)
        captured = capsys.readouterr()
        assert "available" in captured.out.lower()
        assert "not shown" in captured.out
    finally:
        try: os.unlink(db_path)
        except: pass
        try: os.unlink(sdb)
        except: pass


def test_test_secret_missing(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns = _make_ns(db_path, secret_name="nonexistent_key")
        _test_secret(ns)
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()
    finally:
        try: os.unlink(db_path)
        except: pass
        try: os.unlink(sdb)
        except: pass
