# Cogito-Agent

Local-first personal Agent runtime with long-term memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior.

## Quick Start

```bash
pip install -e ".[dev]"
cogito migrate          # creates ~/.cogito/cogito.db
cogito chat             # start interactive chat
cogito replay list      # list recent traces
cogito replay show <id> # inspect a trace
cogito maintenance usage          # usage report
cogito maintenance consolidate    # deduplicate memories
cogito maintenance cleanup_traces # purge old traces
```

## Requirements

- Python 3.12+

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```
