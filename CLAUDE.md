# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
pip install -e ".[dev]"            # Install package with dev dependencies
pip install -e ".[vector]"         # Include sentence-transformers for dense embeddings
pytest                             # Run all tests
pytest tests/path/to/test_file.py  # Run a specific test file
pytest -k "test_name_pattern"      # Run tests matching pattern
ruff check src/                    # Lint source
ruff check src/ --fix              # Lint and auto-fix
mypy src/                          # Type check (strict mode enabled)
cogito-tui                         # Launch the TUI
python -m build --wheel            # Build wheel package
```

## Architecture Overview

**Runtime Kernel** (`src/cogito_agent/runtime/`) — Central orchestration engine. `RuntimeKernel.process()` / `process_stream()` is the single entry point for all agent interactions. Manages turn state machine, model calls, tool execution, persistence, tracing, and budget enforcement. Uses **ports/adapter (hexagonal) pattern** — `ports.py` defines SPI boundaries via Protocol classes.

**Ports** (`runtime/ports.py`): `RuntimePersistencePort`, `RuntimeTracePort`, `RuntimeAuditPort`, `RuntimeCapabilityExecutorPort`, `RuntimePolicyPort`, `RuntimeCapabilityCatalogPort`, `RuntimeArtifactWriterPort`. Concrete adapters implement these in `storage/`, `trace/`, `governance/`, `execution/`.

**Application Layer** (`src/cogito_agent/application/`) — Channel-neutral business logic: `ChatApplicationService`, `SessionApplicationService`, `WorkspaceApplicationService`, `MemoryApplicationService`, `ApprovalApplicationService`, `InboxApplicationService`, `BackupApplicationService`, `MCPApplicationService`, `RunApplicationService`, `DriftApplicationService`, `AutonomyApplicationService`. Each accepts ports via constructor injection. Used by both CLI and web UI.

**Composition Root** — `application/runtime_factory.py` (`build_runtime_kernel()`) wires all components together. `storage/database.py` (`Database.create_runtime_services()`) provides SQLite-backed adapters.

**Storage** (`src/cogito_agent/storage/`) — SQLite with versioned migrations (0001–0024, both `.sql` files and inline migrations). `Database` class manages connections with WAL mode, foreign keys. Repository pattern in `repositories.py` (no ORM). Adapter pattern in `runtime_persistence.py`, `subagent_persistence.py`, `context_sink.py`.

**Memory System** (`src/cogito_agent/memory/`, `src/cogito_agent/retrieval/`, `src/cogito_agent/embedding/`) — Hybrid retrieval: sparse (BM25/FTS5 via `MarkdownChunkIndex`) + dense (embedding provider via `DenseRetrievalService`) + fusion scoring (recency, confidence, pinned boost) in `retrieval/gate.py`. Memory lifecycle: candidates → accept → active → archive.

**Governance** (`src/cogito_agent/governance/`, `src/cogito_agent/execution/`) — `PolicyEngine` evaluates static policy matrix. `GovernedCapabilityExecutor` wraps all capability calls with policy checks, guardians (Network, Path, Shell, SecretEgress), approval flow, audit, and tracing. Every capability invocation goes through this executor.

**Model Abstraction** (`src/cogito_agent/models/`) — `ModelAdapter` Protocol (SPI) allows pluggable providers. `OpenAICompatibleAdapter` is the primary implementation. `ModelRouter` selects candidates by capability (vision, chat), role, modality, and health.

**Console** (`src/cogito_agent/console/`) — Web UI via FastAPI + Jinja2 templates + htmx. Sub-routers in `router.py` for approval, audit, autonomy, backup, chat, config, doctor, drift, inbox, MCP, memory, runs, traces, workspace files. Templates in `console/templates/`.

**CLI** (`src/cogito_agent/cli/`) — 65KB argparse entry point in `__init__.py`. Subcommands: chat, config, memory, skill, approval, traces, audit, export, backup, daemon, provider, replay, maintenance, diagnostics, secrets, migrate, doctor.

**Proactive Behavior** (`src/cogito_agent/autonomy/`, `src/cogito_agent/runtime/drift.py`) — `DriftRuntime` runs a background tick loop selecting low/medium-risk skills (memory consolidation, trace review, inbox digest, daily brief, task extraction) respecting quiet hours and daily budget. `ThreadPoolExecutor` for concurrent execution.

## CLI Entry Points

- `cogito` → `cli:run_cli` (main CLI)
- `cogito-console` → `api.app:run_api` (FastAPI web server)
- `cogito-daemon` → `cli.daemon:main` (daemon mode)
- `cogito-demo` → `cli.e2e_demo:run_e2e_demo` (end-to-end demo)

## Key Design Rules

- `runtime` must not import concrete model providers, tool implementations, or storage drivers
- `capability` must not bypass `governance` (policy/approval)
- `memory` must not directly call models
- `api` must not write storage except through application services
- Trace/audit/redaction is applied at every boundary (CLI, API, autonomy, drift)
- All dynamic content in Console is HTML-escaped and redacted

## TUI Architecture

The TUI at ``src/cogito_agent/tui/`` replaces the old argparse CLI with a Textual-based
full-screen terminal interface inspired by Google's gemini-cli (React+Ink).

**Entry point**: ``cogito-tui`` (``cogito_agent.tui.app:main``)

**Key constraints**:
- **No direct DB access** — TUI never imports ``*Repository`` or calls
  ``db.connection.execute()``. All data flows through Application Services
  (``ChatApplicationService``, ``SessionApplicationService``, etc.)
- **Extend services, not the TUI** — if a method is missing on a service,
  add it to the service module, not to the TUI
- **Single Database instance** — created once in ``app.main()``, injected into all
  services, closed on ``App.on_exit()``

**Component structure**:
- ``app.py`` — ``CogitoTUI(TextualApp)`` with reactive state, service init, dialog mgmt
- ``screens/chat_screen.py`` — Main layout: message list + composer + footer
- ``widgets/message_item.py`` — Type-dispatch message rendering (gemini-cli HistoryItemDisplay pattern)
- ``widgets/dialog_manager.py`` — Priority-ordered modal dialog selection
- ``widgets/messages/factory.py`` — Decorator-based message type registry (``@register("type")``)
- ``themes/manager.py`` — Wraps Textual ``theme`` / ``register_theme()``

**DIALOG_PRIORITY** (first match wins): auth > theme > settings > model > session > memory > confirm > help
