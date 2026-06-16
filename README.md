# Cogito-Agent

Local-first personal Agent runtime with long-term memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior.

## Quick Start

```bash
pip install -e ".[dev]"
cogito migrate              # creates ~/.cogito/cogito.db
cogito chat                 # start interactive chat (uses config model provider)
cogito config show          # view current config
cogito config set model.provider openai
cogito doctor               # check system health

cogito replay list          # list recent traces
cogito replay show <id>     # inspect a trace
cogito traces list          # list all traces with filtering
cogito traces show <id>     # show full trace detail
cogito audit list           # list audit logs
cogito audit show <id>      # show audit log detail
cogito usage summary --last 7d

cogito maintenance usage          # usage report
cogito maintenance consolidate    # deduplicate memories
cogito maintenance cleanup_traces # purge old traces

cogito export --workspace default --out export.json
cogito daemon once               # run one tick cycle
cogito daemon status             # check daemon status
cogito schedule list             # list scheduled jobs
cogito schedule maintenance consolidate --daily 03:00

# API authentication (optional)
export COGITO_API_KEY=your-secret-key
cogito-demo             # start API server with auth
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
