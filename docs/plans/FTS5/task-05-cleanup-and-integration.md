# Task 5: Cleanup and Integration Verification

**Type:** SEQUENTIAL (blocks on: Tasks 2, 3, 4 — all implementation must be complete)
**Estimated scope:** Small-Medium

## Context

We are migrating the `conversation-search-mcp` tool from an in-memory `bm25s` search
backend to SQLite FTS5. This is the final task: remove any remaining bm25s vestiges,
update PEP 723 dependencies, and verify the complete integration works end-to-end.

**Full spec:** `specs/fts5-migration.md` (read this first for complete context)
**Main source:** `conversation_search.py` (~1400 lines, single-file Python app)

**Note:** By the time this task runs, Tasks 1-4 will have already rewritten the core
methods. Some bm25s code may already be gone. This task is a sweep to catch anything
remaining and verify the whole thing works together.

## Objective

1. Remove any remaining bm25s code/imports/references
2. Update PEP 723 dependencies
3. Run integration tests that exercise the complete flow
4. Clean up dead code and migration artifacts

## Files to Modify

- `conversation_search.py` — remove remaining bm25s code, update dependencies
- `tests/test_fts5_index.py` — add integration tests
- `tests/conftest.py` — update fixtures if needed

## What to Do

### 1. Remove remaining bm25s code

Search `conversation_search.py` for and remove (if still present):
- `import bm25s` or `from bm25s import ...`
- Any `bm25s.BM25` instantiation or usage
- `self._retriever`, `self._corpus`, `self._conversations`, `self._session_files`,
  `self._file_cache` — any in-memory data structures replaced by SQLite
- Any helper functions that only served bm25s
- Any fallback code paths that check for bm25s availability

If these are already gone from prior tasks, confirm and move on.

### 2. Update PEP 723 inline metadata

Ensure the dependencies in the script's PEP 723 block do NOT include `bm25s`:

```python
dependencies = ["mcp", "uvicorn", "watchdog"]
```

### 3. Integration tests

Add to `tests/test_fts5_index.py`:

- **End-to-end test:** Create test JSONL files → build index → search → verify results
  → read_turn → verify full content → list_conversations → verify listing.
  This should exercise the complete flow in one test.
- **Warm restart test:** Build index → create new ConversationIndex instance pointing at
  same DB → verify search works without rebuild (persistence verification)
- **No bm25s import test:** Verify `bm25s` is not imported anywhere:
  ```python
  import ast, inspect
  source = inspect.getsource(conversation_search)
  tree = ast.parse(source)
  # check no Import/ImportFrom nodes reference bm25s
  ```

### 4. Final cleanup

- Remove any TODO/FIXME comments related to the migration
- Remove any dead code paths that were kept for backward compatibility
- Ensure no orphaned test fixtures reference bm25s

## What NOT to Do

- Do NOT change the public API (method signatures stay the same)
- Do NOT add new features (no `--reindex` flag, no pagination, nothing not in the spec)
- Do NOT modify the daemon architecture
- Do NOT add daemon watcher tests here — daemon tests belong in `tests/test_daemon_lifecycle.py`

## Acceptance Criteria

- [ ] `bm25s` is not imported or referenced anywhere in `conversation_search.py`
- [ ] PEP 723 dependencies list does not include `bm25s`
- [ ] End-to-end integration test passes (build → search → read → list)
- [ ] Warm restart test passes (persistence verified)
- [ ] No dead code from bm25s era remains
- [ ] All tests pass (existing + new)
