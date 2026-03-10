# Task 1: DB Bootstrap, Schema Versioning, FTS5 Check, and Threading

**Type:** SEQUENTIAL (no dependencies — this is the foundation)
**Estimated scope:** Medium

## Context

We are migrating the `conversation-search-mcp` tool from an in-memory `bm25s` search
backend to SQLite FTS5. This task lays the DB foundation that all other tasks build on.

**Full spec:** `specs/fts5-migration.md` (read this first for complete context)
**Main source:** `conversation_search.py` (~1400 lines, single-file Python app)

## Objective

Implement the SQLite DB lifecycle: connection management, schema creation with versioning,
FTS5 availability check, and the threading model. This replaces the in-memory data
structures but does NOT yet rewrite `build()`, `search()`, or other methods — those are
separate tasks.

## Files to Modify

- `conversation_search.py` — primary changes
- `tests/test_fts5_index.py` — add/update tests

## What to Do

### 1. Schema version constant and creation function

Add a module-level constant `_SCHEMA_VERSION = 1` and a `_create_schema(conn)` function that:
- Creates the `sessions` table (see spec §Schema)
- Creates the `turns_fts` FTS5 virtual table (see spec §Schema)
- Sets `PRAGMA user_version = _SCHEMA_VERSION`

### 2. FTS5 availability check

Add `_check_fts5_available(conn)` that tries creating a temporary FTS5 table. If it fails,
raise `RuntimeError` with a clear message about FTS5 not being compiled in. Call this
before schema creation in `_open_db()`.

### 3. Schema version check in `_open_db()`

In `_open_db()`:
- Connect with `check_same_thread=False`
- Set WAL mode, `synchronous=NORMAL`, `cache_size=-8000`
- Read `PRAGMA user_version`
- If version != `_SCHEMA_VERSION`: drop `sessions` and `turns_fts` tables, then recreate
- Call `_create_schema(conn)`
- Return the connection

### 4. ConversationIndex class refactor (skeleton)

Update the `ConversationIndex.__init__` to use:
- `self._db_path: Path` (default `DB_PATH`)
- `self._conn: sqlite3.Connection | None = None`
- `self._lock = threading.Lock()`

Add `_get_connection()` that lazily opens the DB.

### 5. Threading model

Ensure the `threading.Lock` covers full DB operations, not just connection acquisition.
Every public method that touches the DB must use `with self._lock:` around the entire
operation (acquire → SQL → process → return).

**Clarification:** You ARE allowed to make minimal edits to existing methods (`build()`,
`search()`, `list_conversations()`, `read_turn()`, `read_conversation()`) to wrap their
bodies in `with self._lock:`. Do NOT rewrite their internal logic — just add the lock
wrapper. The full logic rewrites happen in Tasks 2 and 3.

### 6. Tests

Add to `tests/test_fts5_index.py`:
- **Schema creation test:** Verify tables exist and `user_version` is set correctly
- **Version mismatch rebuild test:** Create a DB with wrong `user_version`, open it,
  verify tables are dropped and recreated with correct version
- **FTS5 unavailability test:** Mock `sqlite3` to simulate FTS5 not being available,
  verify `RuntimeError` is raised with descriptive message
- **Lock coverage test:** Verify that concurrent build/search calls don't corrupt state
  (can use threading + a small test dataset)

## What NOT to Do

- Do NOT rewrite `build()` — that's Task 2
- Do NOT rewrite `search()` — that's Task 3
- Do NOT remove bm25s code yet — that's Task 5
- Do NOT update docs/README — that's Task 4
- Keep existing method signatures intact; only change internals

## Acceptance Criteria

- [ ] Opening the index creates the DB file at the expected path with correct `user_version`
- [ ] A DB with wrong `user_version` is automatically rebuilt (tables dropped + recreated)
- [ ] If FTS5 is unavailable, a clear `RuntimeError` is raised at startup (not a generic SQLite error)
- [ ] All existing tests still pass (the class interface is unchanged)
- [ ] New tests for schema versioning, FTS5 check, and threading pass
- [ ] `threading.Lock` covers full operations in all public DB methods
