# v0.8 Console MVP Plan

## Status

- **Predecessor**: v0.7.0-rc1 (tagged, 755 tests, ruff/mypy clean)
- **Branch**: master
- **Nature**: Phase 1 (Foundation) ✅ + Phase 2 (Chat MVP) ✅ + Phase 3 (Memory Review MVP) ✅ + Phase 4 (Approval Queue MVP) ✅ + Phase 5 (Trace & Audit MVP) ✅ + Phase 6 (Autonomy Console MVP) ✅ + Phase 7 (Config & Doctor) ✅ — interactive chat, memory management, approval queue, trace/audit viewers, autonomy decision/outbox/feedback management, config viewer, doctor page
- **938 tests**, ruff clean, mypy clean (90 files)
- Chat page at `/console/chat`, send at `POST /console/chat/send`, stream at `POST /console/chat/stream`
- Memory page at `/console/memory`, actions at `/console/memory/candidates/{id}/accept|reject|edit`, `/console/memory/{id}/edit|archive|delete`
- Approval page at `/console/approval`, actions at `/console/approval/{id}/approve|reject`
- Trace page at `/console/traces`, detail at `/console/traces/{id}`
- Audit page at `/console/audit`, detail at `/console/audit/{id}`
- Autonomy dashboard at `/console/autonomy`, decisions at `/console/autonomy/decisions`, outbox at `/console/autonomy/outbox`, feedback at `/console/autonomy/feedback`

## Goal

Deliver a local Console (Web UI) for visibility and management of core Agent capabilities. Users interact with the Agent through a browser instead of only the CLI.

## Recommendation: Web UI (FastAPI + Jinja2 + htmx)

### Why Web over TUI

1. **Existing FastAPI infrastructure** — Cogito-Agent already has FastAPI with chat/stream, auth, and error schema. Adding Web UI leverages the existing API layer.
2. **Structured data display** — Trace tree, memory list, approval queue, audit log, and outbox are all table/tree views that render naturally in HTML but are painful in TUI.
3. **Long-term viability** — Web console can evolve into a proper dashboard. TUI is developer-only.
4. **htmx + Jinja2 avoids SPA complexity** — Server-rendered HTML with htmx for dynamic updates. No React/Vue build step. Keeps dependencies minimal.

### Comparison

| Criteria | Web UI (FastAPI+Jinja2+htmx) | TUI (Textual or similar) |
|---|---|---|
| Development speed | Fast (server-rendered, no build) | Medium |
| Trace tree display | Natural (nested HTML) | Complex |
| Memory review | Table + detail panel | Cramped |
| Feedback | Button clicks | Keyboard nav |
| Non-technical users | Accessible | Not accessible |
| API reuse | Direct (same process) | Needs new layer |
| Dependencies | htmx (7KB), Jinja2 (existing) | Textual + additional |
| Mobile | Basic responsive | Not mobile |

**Recommendation**: FastAPI + Jinja2 + htmx. This matches the project's existing tech stack and avoids introducing a frontend build pipeline.

---

## Required Pages

### 1. Dashboard (`GET /console/`)

- Summary stats: total memories, pending approvals, pending outbox, recent decisions
- Quick links to all sections
- Last N audit events
- System status (DB health, provider config)

### 2. Chat (`GET /console/chat`) ✅

- Input box with send button (htmx non-streaming)
- SSE streaming endpoint (`POST /console/chat/stream`)
- Session auto-created (`console-default`), workspace auto-created (`default`)
- Trace ID / request ID / state displayed after each turn
- Error banners with redacted messages
- No session selector (single console session)
- No workspace selector (single default workspace)

### 3. Memory Review (`GET /console/memory`)

- Pending candidate list (extracted, needs review)
- Accept / Reject / Edit actions
- Search existing memories
- Memory detail view

### 4. Approval Queue (`GET /console/approval`)

- Pending approval requests
- Approve / Reject buttons
- Detail view with capability, resource, actor
- Resume skill run after decision

### 5. Trace Inspector (`GET /console/traces`)

- List with filters (workspace, status, date range)
- Detail view with span tree (expandable)
- Per-span timings and attributes
- Replay button (if supported)

### 6. Audit Log Viewer (`GET /console/audit`)

- List with filters (actor, action, date range)
- Detail view with full details (redacted)
- Export button

### 7. Autonomy Decisions (`GET /console/autonomy/decisions`)

- List with filters (action, reason_code, workspace)
- Detail view with cost score breakdown
- Link to trace

### 8. Autonomy Outbox (`GET /console/autonomy/outbox`)

- List with status filter (pending/sent/failed)
- Mark as sent / failed buttons
- Detail view

### 9. Feedback (`POST /console/autonomy/feedback`)

- Form to record feedback on a decision
- Dropdown for value (useful/not_useful/too_many/wrong_time/irrelevant)
- Optional comment field

### 10. Config Viewer (`GET /console/config`)

- Read-only table of current config
- Section grouping (model, secrets, autonomy)
- No inline editing (MVP boundary)

### 11. Doctor (`GET /console/doctor`)

- Run `cogito doctor` checks from UI
- Display results: provider, secrets, DB, migrations
- Status badges (green/red/yellow)

---

## API Endpoint Draft

```text
# Console pages (server-rendered HTML)
GET    /console/                        → Dashboard
GET    /console/chat                    → Chat page
POST   /console/chat/send               → Send message, returns SSE stream
GET    /console/memory                  → Memory review list
POST   /console/memory/<id>/accept      → Accept candidate
POST   /console/memory/<id>/reject      → Reject candidate
GET    /console/approval                → Approval queue
POST   /console/approval/<id>/approve   → Approve request
POST   /console/approval/<id>/reject    → Reject request
GET    /console/traces                  → Trace list
GET    /console/traces/<id>             → Trace detail (spans)
GET    /console/audit                   → Audit log list
GET    /console/audit/<id>              → Audit log detail
GET    /console/autonomy/decisions      → Decision list
GET    /console/autonomy/decisions/<id> → Decision detail
GET    /console/autonomy/outbox         → Outbox list
POST   /console/autonomy/feedback       → Record feedback
GET    /console/config                  → Config viewer
GET    /console/doctor                  → Doctor status
POST   /console/doctor/run              → Run doctor checks

# Data API (JSON, for htmx or direct fetch)
GET    /api/v1/status                   → System status JSON
GET    /api/v1/traces                   → Trace list JSON
GET    /api/v1/traces/<id>              → Trace detail JSON
GET    /api/v1/audit                    → Audit log JSON
GET    /api/v1/autonomy/decisions       → Decisions JSON
GET    /api/v1/autonomy/outbox          → Outbox JSON
```

---

## Data Model (HTML Templates)

### Template Variables (common to all pages)

```json
{
  "workspace_id": "string",
  "session_id": "string",
  "stats": {
    "memory_candidates": 3,
    "pending_approvals": 1,
    "pending_outbox": 5,
    "decisions_today": 12
  },
  "flash": [{"level": "info|warn|error", "message": "..."}]
}
```

### Template structure

```
templates/
  console/
    base.html              ← Base layout (nav, sidebar, header)
    dashboard.html
    chat.html
    memory/
      list.html
      detail.html
    approval/
      list.html
    traces/
      list.html
      detail.html          ← Span tree with expand/collapse
    audit/
      list.html
      detail.html
    autonomy/
      decisions/
        list.html
        detail.html
      outbox/
        list.html
    config.html
    doctor.html
  components/
    stat_card.html
    flash_message.html
    pagination.html
    trace_tree.html
    status_badge.html
```

---

## Security & Redaction

- All console pages must go through the same optional Bearer auth as API endpoints
- All decision reason/details pass through `RedactionHelper.redact()` before rendering
- Audit details are redacted at the storage layer (already done via `AuditLogger`)
- Config page must not display secret values (`api_key`, `secret_ref` resolved values)
- Outbox body rendered through `_redact()` before display
- No raw secret values in any HTML output
- No CSRF protection needed for MVP (single-user, same-origin only). Add if multi-user later.

---

## Implementation Order (actual)

1. ✅ **Phase 1: Foundation** — FastAPI static file serving + Jinja2 setup, base template, dashboard page, `/api/v1/status` endpoint
2. ✅ **Phase 2: Chat** — Chat page with htmx send + SSE streaming integration
3. ✅ **Phase 3: Memory Review** — Memory review list with accept/reject, edit/archive/delete
4. ✅ **Phase 4: Approval** — Approval queue with approve/reject
5. ✅ **Phase 5: Trace & Audit** — Trace list/detail with span tree viewer + Audit list/detail with filters and redacted details
6. ✅ **Phase 6: Autonomy** — Decisions list/detail, Outbox list, Feedback form, dashboard, filters
7. ✅ **Phase 7: Config & Doctor** — Config viewer (read-only, section-grouped, redacted secrets), Doctor page (system health check, section-grouped results, overall status badge, JSON API)
8. 🚧 **Phase 8: Polish** — Navigation, responsive layout, loading states, error pages

---

## Testing Plan

| Test type | Scope |
|---|---|
| Unit tests | Template rendering helpers, data formatting, redaction utilities |
| Integration tests | Page loads return 200, forms submit correctly, auth blocks unauthenticated requests |
| E2E tests | Full flow: emit autonomy event → view decision → record feedback |
| Secret redaction tests | All pages check that secret-like values in output are redacted |
| Accessibility | Basic: semantic HTML, readable contrast, keyboard nav support |

---

## What Not to Build (v0.8 MVP)

- Multi-user / OAuth / RBAC
- Cloud deployment / Docker compose
- Telegram / Feishu real send
- Plugin marketplace
- Complex charts / dashboards (single stat cards only)
- Inline config editing
- Websocket-based real-time updates (polling or htmx trigger OK)
- Mobile app

---

## v0.8.0 Acceptance Checklist

```text
[x] Dashboard loads with stats
[x] Chat page sends message and displays response
[x] Memory review shows candidates
[x] Memory accept works
[x] Memory reject works
[x] Memory edit works
[x] Memory archive works
[x] Memory delete works
[x] Approval queue shows pending items
[x] Approval approve works
[x] Approval reject works
[x] Trace list shows traces
[x] Trace detail shows span tree
[x] Audit list shows entries
[x] Audit detail shows redacted details
[x] Autonomy dashboard shows stats
[x] Autonomy decisions list works
[x] Autonomy decisions shows cost breakdown
[x] Autonomy outbox list works
[x] Feedback form records feedback
[x] Feedback filters work
[x] Decision/outbox/feedback detail pages work
[x] All autonomy pages respect auth
[x] Config page shows keys (redacted secrets)
[x] Doctor page shows system status
[x] All pages respect auth (when COGITO_API_KEY is set)
[x] No secret leakage in any HTML output
[x] pytest passes
[x] ruff check src/ passes
[x] mypy src/ passes
[x] Existing CLI tests still pass
```
