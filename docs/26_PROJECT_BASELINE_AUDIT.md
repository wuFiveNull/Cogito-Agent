# Project Baseline Audit — 2026-06-19

## Verified baseline

- Application version: `0.16.0-dev`, sourced from `cogito_agent.version.APP_VERSION`.
- Test suite: 1433 passed, 4 skipped under the available Python 3.11 validation environment.
- Static checks: `ruff check src` clean; `mypy src` clean for 134 source files.
- Required release validation remains Python 3.12 and 3.13 on Windows, Linux, and macOS.
- Browser E2E scaffolding is available in `tests/browser/test_console_smoke.py`; it is optional and
  skips unless the `e2e` dependency group is installed.

## Stabilization findings resolved

- File logging now degrades to structured stdout when the configured home log directory is not
  writable, instead of preventing service startup.
- Removed the unsupported Django `yesno` filter from the Drift Jinja template.
- Restored the Dashboard migration status row.
- Replaced hard-coded API, Console, Doctor, backup, and status versions with one application
  version constant. Static asset cache keys remain content hashes.
- Added dedicated ignore rules for virtual environments and isolated pytest run directories.

## Architecture boundary findings

- Runtime kernel, governance, tracing, memory, skills, autonomy, workspace files, artifacts, and
  the Console MVP are present.
- A provider-neutral Model Router now provides deterministic constraint filtering, health-based
  fallback, circuit breaking, recovery probes, configured-provider factory wiring, and redacted
  route decision/fallback persistence in Trace and Audit.
- Context now records freshness, trust, evidence, stable references and exclusion reasons. Derived
  incremental session summaries and ResultComposer are implemented; adaptive budget allocation
  remains pending.
- Chat Workspace Phase 3 now has the three-column shell, paginated history, safe Markdown,
  Tool/Approval cards, stop/retry controls, audited rename/branch flows and Turn Inspector. The
  real-browser screenshot/accessibility gate remains pending because the in-app browser could not
  reach the otherwise healthy localhost validation server in this environment.
- Scheduler persists jobs but lacks leases, heartbeat, Cron/DST semantics, and duplicate-run
  protection.
- Subagent metadata remains process-local and cannot recover after restart.
- Task and Plugin lifecycle domains do not yet have persistent application-service boundaries.

## Immediate implementation order

1. Obtain hosted Python 3.12/3.13 cross-platform CI evidence for the v0.15 release gate.
2. Complete Chat Phase 3 and its real-browser, accessibility, and responsive checks.
3. Add multi-candidate provider configuration and per-provider credential resolution.
4. Continue with v0.17 Tasks/Knowledge/Automation only after the v0.16 exit gate passes.
