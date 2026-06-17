from __future__ import annotations

import getpass
import sys
from typing import Any

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.security import (
    LocalSecretsProvider,
    SecretProvider,
)
from cogito_agent.storage import Database
from cogito_agent.trace.redaction import RedactionHelper


def _get_provider(db_path: str) -> SecretProvider:
    if not db_path or db_path == ":memory:":
        return LocalSecretsProvider()
    sdb = db_path.replace(".db", "_secrets.db") if ".db" in db_path else db_path + "_secrets.db"
    return LocalSecretsProvider(sdb)


def _redact(s: str) -> str:
    return RedactionHelper().redact(s)


def _list_providers(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    keys = provider.list_keys()
    if not keys:
        print("  No secrets configured.")
        return
    print(f"  Secrets ({len(keys)}):")
    for key in keys:
        sv = provider.get_secret(key)
        status = "available" if sv is not None else "missing"
        meta = ""
        if hasattr(provider, "metadata"):
            try:
                m = provider.metadata(key)
                if m:
                    created = str(m.get("created_at", ""))[:10]
                    meta = f"  created={created}"
            except Exception:
                pass
        print(f"    {key}  [{status}]{meta}")


def _show_secret(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    key = ns.secret_name
    sv = provider.get_secret(key)
    if sv is None:
        print(f"  Secret '{key}' not found.")
        return
    meta = ""
    if hasattr(provider, "metadata"):
        try:
            m = provider.metadata(key)
            if m:
                meta = (
                    f"  created={m.get('created_at','')[:19]}"
                    f"  updated={m.get('updated_at','')[:19]}"
                    f"  last_used={m.get('last_used_at','')[:19] or 'never'}"
                )
        except Exception:
            pass
    print(f"  Name:    {key}")
    print("  Status:  available")
    print("  Value:   [REDACTED]")
    if ns.show_metadata and meta:
        print(f"  {meta}")


def _audit_log(db_path: str, action: str, key: str) -> None:
    try:
        db = Database(db_path)
        db.initialize()
        audit = AuditLogger(db)
        audit.log(
            actor_id="cli", action=action,
            resource=f"secret:{key}",
            workspace_id="*",
            decision="allow", reason="user requested",
            redact_details=False,
        )
    except Exception:
        pass


def _read_secret_value(key: str, ns: Any) -> str:
    if hasattr(ns, "stdin") and ns.stdin:
        return sys.stdin.read().strip()
    try:
        if ns.value:
            return str(ns.value)
    except AttributeError:
        pass
    return getpass.getpass(f"  Enter secret value for '{key}': ")


def _set_secret(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    key = ns.secret_name
    value = _read_secret_value(key, ns)
    provider.set_secret(key, value)
    _audit_log(ns.db_path, "secret.set", key)
    print(f"  Secret '{key}' set.")


def _delete_secret(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    key = ns.secret_name
    if provider.delete_secret(key):
        _audit_log(ns.db_path, "secret.delete", key)
        print(f"  Secret '{key}' deleted.")
    else:
        print(f"  Secret '{key}' not found.")


def _rotate_secret(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    key = ns.secret_name
    new_value = _read_secret_value(key, ns)
    if provider.rotate_secret(key, new_value):
        _audit_log(ns.db_path, "secret.rotate", key)
        print(f"  Secret '{key}' rotated.")
    else:
        print(f"  Secret '{key}' not found.")


def _test_secret(args: Any) -> None:
    ns = args
    provider = _get_provider(ns.db_path)
    key = ns.secret_name
    sv = provider.get_secret(key)
    if sv is not None:
        print(f"  Secret '{key}': available (value not shown)")
    else:
        print(f"  Secret '{key}': not found")
