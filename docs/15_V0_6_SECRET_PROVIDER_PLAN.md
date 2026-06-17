# v0.6 Secret Store + Provider Hardening — Candidate

## Status

- **Current commit:** (current HEAD)
- **Status:** v0.6 secret/provider hardening candidate, **not released**.
- **No GitHub tag or release.**

## SecretProvider Design

```
SecretProvider (Protocol)
├── get_secret(key) -> SecretValue | None
├── list_keys() -> list[str]
├── set_secret(key, value)
├── delete_secret(key) -> bool
└── rotate_secret(key, new_value) -> bool
```

### SecretValue

Wraps raw secret strings to prevent accidental leakage:

- `str(sv)` → `"[REDACTED]"`
- `repr(sv)` → `"SecretValue(name=..., value=[REDACTED])"`
- `sv.value` → actual secret string (for API calls only)
- `len(sv)` → length of secret
- `bool(sv)` → whether value is non-empty

### EnvSecretProvider

- Reads secrets from environment variables with configurable prefix (default `COGITO_`).
- All keys normalized to uppercase (cross-platform).
- `get_secret("MY_KEY")` → reads `COGITO_MY_KEY` env var.
- No encryption — relies on OS environment access control.
- Suitable for development and deployment where env vars are managed externally.

### LocalSecretsProvider

- Stores secrets in a local SQLite database (`~/.cogito/secrets.db`).
- **NOT encrypted at rest** — values stored as plaintext. Clearly documented as insufficient for production-grade security.
- Tracks `created_at`, `updated_at`, `last_used_at` for each secret.
- CLI shows only metadata (name, timestamps), never the value.

### KeychainSecretProvider

- **Placeholder only.** Always returns `None`.
- Not implemented. When implemented will use:
  - macOS: Keychain
  - Windows: Credential Manager
  - Linux: libsecret / GNOME Keyring

## CLI: `cogito secrets`

| Command | Description |
|---------|-------------|
| `cogito secrets list` | List all secrets (names + status + created date) |
| `cogito secrets show <name>` | Show secret metadata (never value) |
| `cogito secrets set <name>` | Set secret from stdin or secure prompt |
| `cogito secrets delete <name>` | Delete a secret (writes audit) |
| `cogito secrets rotate <name>` | Rotate secret value (writes audit) |
| `cogito secrets test <name>` | Verify secret is available (no value shown) |

- `set` reads from `--value` flag **or** `getpass` secure prompt if `--value` is omitted.
- `list` shows name, status (available/missing), created date.
- `show` shows name, status, `[REDACTED]` for value, optional metadata flags.
- All mutations (`set`/`delete`/`rotate`) write audit log entries via `AuditLogger`.
- Output is NOT redacted by `RedactionHelper` since no secret values are ever displayed. (Redaction applied at caller layer as needed.)

## Provider Hardening

Not fully implemented in v0.6.0. The framework is in place:

- `EnvSecretProvider` and `LocalSecretsProvider` ready for provider secret storage.
- Provider doctor CLI planned (`cogito provider doctor`, `cogito provider test`).
- Secret ref support planned (config `model.secret_ref`).

## Config secret_ref Design

The config system will support:

```json
{
  "model.provider": "openai",
  "model.model": "gpt-4o-mini",
  "model.secret_ref": "openai_api_key",
  "model.timeout_seconds": 60,
  "model.max_retries": 2,
  "model.streaming_enabled": true
}
```

- `model.secret_ref` references a key in the SecretProvider (not a direct value).
- `cogito doctor` resolves `secret_ref` to check availability without revealing the value.
- Legacy `model.api_key_env` env-var-based config still works as fallback.
- `cogito export` excludes secret values; may include `secret_ref` metadata (redacted by default).

## Redaction Guarantees

The existing `RedactionHelper` (in `trace/redaction.py`) handles:

- Bearer tokens: `Bearer [REDACTED]`
- API keys: `sk-*` → `[REDACTED_API_KEY]`
- Auth headers: `Authorization: [REDACTED]`
- Cookie headers: `Cookie: [REDACTED]`
- URL credentials: `https://[REDACTED]@`
- Query params: `token=`, `api_key=`, `access_token=` → `=[REDACTED]`
- Dynamic env-based secrets: matched from `EnvSecretProvider` at runtime

The `SecretValue` class adds a **second layer** of protection: if any code path accidentally calls `str()` or `repr()` on a secret value, it shows `[REDACTED]` instead of the raw string.

## Known Limitations

1. **LocalSecretsProvider is NOT encrypted.** Values are plaintext in SQLite. Not suitable for production without OS-level encryption.
2. **KeychainSecretProvider is a placeholder.** No real OS keychain integration.
3. **Provider doctor CLI not implemented.** `cogito provider doctor` and `cogito provider test` are not yet available.
4. **Config `secret_ref` not implemented.** The config system still uses env-var-based API key loading. Migration path is designed but not coded.
5. **Provider timeout/retry config not unified.** The `OpenAICompatibleAdapter` has `timeout_sec` but no retry config from settings.
6. **No `cogito config set model.secret_ref` support.** Secret ref is described in design docs only.

## Next Priorities

1. Implement `cogito provider doctor` and `cogito provider test` CLIs.
2. Wire `model.secret_ref` in config manager → adapter initialization.
3. Add `cogito config set model.secret_ref` support.
4. Integrate timeout/retry/streaming flags from config to provider adapters.
5. Implement `KeychainSecretProvider` using OS keychain APIs.
