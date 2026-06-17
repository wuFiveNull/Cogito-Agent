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

## Streaming Config Enforcement

`model.streaming_enabled` (default `"true"`) now controls whether `StreamGenerator` uses `stream_chat()`:

| streaming_enabled | adapter.supports_streaming | Behavior |
|---|---|---|
| `true` | `True` | Per-token delta events via `stream_chat()` |
| `true` | `False` | Single delta via `chat()` fallback |
| `false` | `True` | Forces `chat()` fallback (no streaming) |
| `false` | `False` | Single delta via `chat()` (no change) |

The flag is read per-request in the API `chat_stream` endpoint and passed through `process_stream()` → `_stream_generate_reply()` → `StreamGenerator`.

## Max Retries Config

`model.max_retries` (default `"2"`) controls the number of retry attempts for model calls:

- Read from config per-request in the API streaming endpoint.
- Passed to `_stream_generate_reply()` and `StreamGenerator`.
- Non-stream `/chat` also uses `_retry_with_backoff()` with configurable max_retries.
- Exponential backoff (2^attempt * 0.5s base).
- The existing `RuntimeKernel._retry_with_backoff()` is used for both model calls and tool dispatch.

## Streaming Retry Strategy

When streaming is active, the retry logic in `_stream_generate_reply()` follows this strategy:

| Phase | Failure | Behavior |
|---|---|---|
| Before first delta | `stream_chat()` raises | Retry up to `max_retries` times, re-create `StreamGenerator` each attempt |
| After first delta | Iterator fails mid-stream | **No retry** — emit SSE error event. No token replay. |
| All retries exhausted | All attempts failed | Emit normalized `PROVIDER_*` error via SSE error event |

- If the adapter's `supports_streaming` is `False` and `streaming_enabled` is `False`, the non-stream `chat()` path is used, which has its own retry via `_retry_with_backoff()`.
- After-first-delta failures produce an error event with the unified `ProviderError` schema.
- Errors are normalized via `normalize_provider_error()` which classifies exceptions into `PROVIDER_*` codes without leaking raw secret or traceback.

## Provider CLI

### `cogito provider list`

Shows all registered providers with type, secret requirement, and configured status.

### `cogito provider show <provider>`

Shows provider metadata:
- Name, configured status, secret requirement, secret availability
- Default base_url (redacted) and default model
- Streaming support

### `cogito provider doctor`

Runs the same checks as `cogito doctor` for the current provider, including secret_ref resolution.

### `cogito provider test <provider>`

Tests provider configuration:
- Checks secret availability (no value shown)
- Checks base_url configuration
- With `--live`: executes a real network request to verify reachability
- **Default: no network request** (use `--live` explicitly, which may incur API costs)
- Normalizes errors using `PROVIDER_*` codes:
  - `PROVIDER_NOT_CONFIGURED`, `PROVIDER_SECRET_MISSING`, `PROVIDER_UNREACHABLE`
  - `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_AUTH_FAILED`
  - `PROVIDER_MODEL_UNAVAILABLE`, `PROVIDER_UNKNOWN_ERROR`

## Config secret_ref (Implemented)

The config system supports:

```json
{
  "model.provider": "openai",
  "model.model": "gpt-4o-mini",
  "model.secret_ref": "openai_api_key",
  "model.timeout_seconds": "60",
  "model.max_retries": "2",
  "model.streaming_enabled": "true"
}
```

- `model.secret_ref` references a key in the SecretProvider (via `LocalSecretsProvider`).
- `build_model_adapter_from_config()` resolves `secret_ref` first, falls back to `api_key_env`.
- `cogito doctor` now shows `secret_ref` availability status.
- `cogito config set model.secret_ref <name>` fully supported.
- Legacy `model.api_key_env` env-var-based config still works as fallback.
- Priority: `secret_ref` > `api_key_env`.
- `cogito export` excludes secret values.

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

## ProviderError Normalization

The `cogito_agent.models.provider_errors` module provides:

- `ProviderErrorCode` (StrEnum): `NOT_CONFIGURED`, `SECRET_MISSING`, `UNREACHABLE`, `TIMEOUT`, `RATE_LIMITED`, `AUTH_FAILED`, `MODEL_UNAVAILABLE`, `UNKNOWN_ERROR`
- `ProviderError(Exception)`: with `.code`, `.provider`, `.retryable`, `.safe_message`, `.to_dict()`
- `normalize_provider_error(exc, provider)`: classifies any exception into a `ProviderError` with safe message
- `safe_provider_error_message(code, provider, detail)`: returns redacted error message

All provider errors in `process_stream()`, `_generate_reply()`, and the retry logic pass through `normalize_provider_error()`, ensuring:
- No raw Python traceback in user-facing output
- No API key, Bearer token, or URL credential in error messages (via `RedactionHelper`)
- Consistent `PROVIDER_*` codes across CLI, API, SSE, trace, and audit

## Known Limitations

1. **LocalSecretsProvider is NOT encrypted.** Values are plaintext in SQLite. Not suitable for production without OS-level encryption.
2. **KeychainSecretProvider is a placeholder.** No real OS keychain integration.
3. **Provider config timeout/retry not fully wired to adapter.** `config_manager` reads `timeout_seconds` but `OpenAICompatibleAdapter` compatibility is partial. `max_retries` is passed to `RuntimeKernel._retry_with_backoff()` for model calls.
4. **No provider test for `openai-compatible` with `--live`.** The health check endpoint may differ by provider.
5. **No encrypted secret store in production.** For real deployment, use env-var-based `EnvSecretProvider` with external secret management.

## Next Priorities

1. Implement `KeychainSecretProvider` using OS keychain APIs.
2. Add per-provider health check endpoints for `--live` tests.
3. Integrate timeout/retry config into `OpenAICompatibleAdapter` constructor.
