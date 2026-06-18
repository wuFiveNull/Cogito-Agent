# v0.11.0-dev: Autonomy Delivery & Local Production Hardening

**Status:** Released (2026-06-18)  
**Tests:** 1097 passing (27 new), ruff clean, mypy clean (95 source files)

---

## Features

### 1. Autonomy Dispatcher (`OutboxDispatcher`)

New `src/cogito_agent/autonomy/dispatcher.py`:

- Periodic scan of pending/retrying outbox messages
- Delivery states: `pending` → `delivering` → `sent | failed` → `retrying` → `dead_letter`
- Exponential backoff: `delay = min(30 * 2^(attempt-1), 3600)` seconds
- Max retries: 5 (configurable via `MAX_RETRIES`)
- Migration v7 adds columns: `delivery_attempts`, `last_error`, `next_retry_at`, `delivered_at`, `read_at`, `dismissed_at`, `failed_at`, `updated_at`
- Each delivery attempt writes a trace span (`SpanKind.autonomous`) and audit log
- Payload redacted via `RedactionHelper` in audit logs
- `retry_message()` API to reset failed messages to `pending`
- `run_forever()` for blocking daemon loop
- Governance check via `PolicyEngine` (operation: `notification.send`) — respects policy deny

### 2. DeliveryAdapter Abstraction

New `src/cogito_agent/autonomy/delivery.py`:

- `DeliveryAdapter` Protocol — `deliver(message, db) → DeliveryResult`
- `DeliveryResult` Pydantic model: `message_id`, `status`, `delivered_at`, `error`, `trace_id`
- `LocalInboxDeliveryAdapter` — writes to `notifications` table
- `ConsoleNotificationAdapter` — writes to `inbox_items` table for Web Console

### 3. Web Console Inbox Page

New `src/cogito_agent/console/inbox_views.py` + templates:

- `/console/inbox` — inbox list with status/priority/source/retries columns
- Filter bar: status dropdown, search input, time range
- Stat cards: total/pending/sent/retrying/failed/dead_letter/skipped
- Row actions: Retry (failed/dead_letter), Mark Read (sent), Dismiss, Feedback dropdown
- `/console/inbox/{id}` — detail with full metadata, trace link, raw JSON toggle, feedback form
- Feedback values: useful / not_useful / too_many / wrong_time / irrelevant
- All content redacted + HTML-escaped; AuthMiddleware protects all routes

### 4. Secret Store Hardening

Added to `src/cogito_agent/security/`:

- **`LocalEncryptedSecretProvider`** — Fernet-encrypted SQLite (requires `cryptography`). Key file auto-generated on first use. Values encrypted at rest.
- **`DevSqliteSecretProvider`** — Wraps `LocalSecretsProvider`, emits `UserWarning` on every instantiation. For dev/test only.
- **`get_provider_from_config()`** updated — `secrets.backend` accepts `env`, `local`, `keychain`, `local_encrypted`, `dev_sqlite` (new default).
- Doctor page now shows security risk level per backend:
  - `env` / `local_encrypted` / `keychain` → low risk
  - `local` / `dev_sqlite` → HIGH risk (plaintext)
- `cryptography` is optional — if missing, `LocalEncryptedSecretProvider` raises `ImportError` on construction.

### 5. Backup/Restore/Export CLI

New `src/cogito_agent/cli/backup.py`:

- `cogito backup create --out <path> [--include-secrets]` — ZIP backup including DB, config, skills, audit logs, traces, workspace metadata
- `cogito backup restore <path> [--dry-run]` — restore with preflight validation
- `cogito export data [--out]` — workspace data export (legacy format)
- `cogito export memories [--out]` — JSON export of all memories
- `cogito export traces [--out]` — JSON export of all traces
- Secrets excluded by default; `--include-secrets` flag required to include them
- All operations write audit logs

---

## Files Changed

| File | Change |
|------|--------|
| `src/cogito_agent/security/secrets.py` | Added `LocalEncryptedSecretProvider`, `DevSqliteSecretProvider` |
| `src/cogito_agent/security/__init__.py` | Exports new providers, updated `get_provider_from_config` |
| `src/cogito_agent/autonomy/delivery.py` | **New** — DeliveryAdapter protocol + implementations |
| `src/cogito_agent/autonomy/dispatcher.py` | **New** — OutboxDispatcher with retry/backoff/dead-letter |
| `src/cogito_agent/storage/database.py` | Migration v7 for new columns |
| `src/cogito_agent/cli/__init__.py` | Added backup/restore/export subcommands |
| `src/cogito_agent/cli/backup.py` | **New** — Backup/restore/export implementation |
| `src/cogito_agent/console/inbox_views.py` | **New** — Inbox page views |
| `src/cogito_agent/console/router.py` | Register inbox router |
| `src/cogito_agent/console/utils.py` | Added "Inbox" to menu |
| `src/cogito_agent/console/doctor_views.py` | Security risk check, encrypted provider check |
| `src/cogito_agent/console/templates/console/inbox.html` | **New** — Inbox list template |
| `src/cogito_agent/console/templates/console/inbox_detail.html` | **New** — Inbox detail template |
| `tests/test_v0_11_delivery_hardening.py` | **New** — 27 tests covering all features |

---

## Verification

```bash
pytest tests/ -q    # 1097 passed, 1 pre-existing failure
ruff check src/     # clean
mypy src/           # clean, 95 files
```

---

## Design Decisions

1. **Dispatcher uses `operation="send"` for policy check** — matches existing `NotificationGate._governance_check()` so the default `MVP_MATRIX` rule `allow_with_audit` applies.
2. **DevSqliteSecretProvider is now the default** — it emits a warning on every use, making the security tradeoff explicit. Users must consciously switch to `local_encrypted` or `keychain`.
3. **Backup secrets are opt-in** — the `--include-secrets` flag is required to include API keys/tokens in backups. This prevents accidental secret leakage.
4. **Inbox consolidates outbox_messages + inbox_items** — the Web Console shows both in a unified view, sorted by creation time.
5. **`cryptography` remains optional** — it's only needed for `LocalEncryptedSecretProvider`. The test suite skips related tests gracefully.
