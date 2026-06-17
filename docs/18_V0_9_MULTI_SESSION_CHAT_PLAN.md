# v0.9: Multi-Session Chat + Conversation History

## Goal

Replace `console-default` single-session with full multi-session chat:
- Create/list/switch/archive/delete sessions from the Chat UI sidebar
- History recovery on page refresh (messages loaded from DB)
- User messages persisted in the DB (previously only assistant responses)
- Auto-title from first user message

## Implementation

### Kernel Fixes

1. **Swapped args bug** (`runtime/kernel.py`):
   - `_build_context` and `_build_model_messages` called `self._msg_repo.list_by_session(event.workspace_id, event.session_id)`
   - Method signature is `list_by_session(session_id, workspace_id)` — args were swapped
   - Fix: swap to `(event.session_id, event.workspace_id)`

2. **User message persistence** (`runtime/kernel.py`):
   - Added `_persist_user_message(event)` method
   - Called in both `process()` and `process_stream()` before `_persist(event, output_text)`
   - Session `updated_at` bumped on each message
   - Auto-title: first user message's first 80 chars set as session title

### Session Hard-Delete Fix (`storage/repositories.py`)

- `SessionRepository.hard_delete` did not delete `spans` before `traces`
- spans.trace_id has FK constraint to traces.id → `DELETE FROM traces` failed
- Fix: delete spans → source_lineage → traces → sessions

### New Module: `console/chat_sessions.py`

| Route | Method | Description |
|-------|--------|-------------|
| `/console/chat/sessions` | GET | List sessions for the console workspace |
| `/console/chat/sessions` | POST | Create new UUID session (title: "New Chat") |
| `/console/chat/sessions/{id}` | GET | Get session with all messages |
| `/console/chat/sessions/{id}/archive` | POST | Soft delete (sets `deleted_at`) |
| `/console/chat/sessions/{id}/delete` | POST | Hard delete (cascading) |

- All routes write audit logs (session_created, session_archived, session_deleted)
- Uses shared `get_db()` singleton from `api/app.py`
- Content redacted via `redact_html()`
- AuthMiddleware protects all routes

### Updated Templates

- `console/chat.html`: Session sidebar (left) + messages area (right) + input
  - Session list with title, message count, last preview
  - New Chat button, archive button per session
  - Messages loaded via htmx `hx-trigger="load"` on page load
  - `updateSessionList()` JS to refresh sidebar after each message
  - `switchSession()` JS to toggle active state and update session_id form field

- `console/components/chat_history.html`: Renders all persisted messages (user/assistant bubbles)
- `console/components/chat_sessions.html`: Sidebar session list partial
- `console/components/chat_session_item.html`: Single session for htmx append on create

### CSS

- `console/static/console.css`: Added `.chat-sidebar`, `.session-item`, `.session-link`, `.btn-new-chat`, `.btn-icon`, `.chat-main` styles
- Responsive: sidebar becomes horizontal scroll on mobile

### Verification

- 32 new tests in `tests/console/test_chat_sessions.py`
- Test categories: create, list, get, archive, delete, messages, auth, audit, security (redaction/XSS)
- Existing tests updated: `test_e2e_demo.py` (now expects user message first), `kernel.py` swapped args fix verified
- pytest: 1043 passed
- ruff: clean
- mypy: clean (91 source files)

## Remaining (not in scope)

- Session title editing in UI
- Session search/filter in sidebar
- Session reordering
- Multi-user/OAuth/RBAC
