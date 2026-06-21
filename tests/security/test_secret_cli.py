"""Tests for secrets CLI."""

from __future__ import annotations

import os
import tempfile

from cogito_agent.cli.secrets import (
    _delete_secret,
    _get_provider,
    _list_providers,
    _rotate_secret,
    _set_secret,
    _show_secret,
    _test_secret,
)


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
    return (
        db_path.replace(".db", "_secrets.db")
        if db_path and ".db" in db_path
        else db_path + "_secrets.db"
    )


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
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


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
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


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
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


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
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


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
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_delete_secret(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        provider = _get_provider(db_path)
        provider.set_secret("del_key", "del_val")
        ns = _make_ns(db_path, secret_name="del_key")
        _delete_secret(ns)
        captured = capsys.readouterr()
        assert "deleted" in captured.out.lower()
        assert provider.get_secret("del_key") is None
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_delete_secret_missing(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns = _make_ns(db_path, secret_name="nonexistent_delete")
        _delete_secret(ns)
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_rotate_secret(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        provider = _get_provider(db_path)
        provider.set_secret("rot_key", "old_val")
        ns = _make_ns(db_path, secret_name="rot_key", value="new_val")
        _rotate_secret(ns)
        captured = capsys.readouterr()
        assert "rotated" in captured.out.lower()
        sv = provider.get_secret("rot_key")
        assert sv is not None
        assert sv.value == "new_val"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_rotate_secret_missing(capsys):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns = _make_ns(db_path, secret_name="nonexistent_rotate", value="new")
        _rotate_secret(ns)
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_set_writes_audit_log():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        ns = _make_ns(db_path, secret_name="audit_test_key", value="audit_val")
        _set_secret(ns)
        from cogito_agent.storage import Database

        db = Database(db_path)
        db.initialize()
        cur = db.connection.execute(
            "SELECT action, resource FROM audit_logs WHERE resource = ?",
            ("secret:audit_test_key",),
        )
        rows = cur.fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "secret.set"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_delete_writes_audit_log():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        provider = _get_provider(db_path)
        provider.set_secret("audit_del_key", "val")
        ns = _make_ns(db_path, secret_name="audit_del_key")
        _delete_secret(ns)
        from cogito_agent.storage import Database

        db = Database(db_path)
        db.initialize()
        cur = db.connection.execute(
            "SELECT action, resource FROM audit_logs WHERE resource = ?",
            ("secret:audit_del_key",),
        )
        rows = cur.fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "secret.delete"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass


def test_rotate_writes_audit_log():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    sdb = _secrets_db_path(db_path)
    try:
        provider = _get_provider(db_path)
        provider.set_secret("audit_rot_key", "old")
        ns = _make_ns(db_path, secret_name="audit_rot_key", value="new")
        _rotate_secret(ns)
        from cogito_agent.storage import Database

        db = Database(db_path)
        db.initialize()
        cur = db.connection.execute(
            "SELECT action, resource FROM audit_logs WHERE resource = ?",
            ("secret:audit_rot_key",),
        )
        rows = cur.fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "secret.rotate"
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        try:
            os.unlink(sdb)
        except OSError:
            pass
