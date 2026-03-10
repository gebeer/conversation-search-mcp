# Task 2: Incremental Build with Pattern-Scoped Stale Deletion

**Type:** SEQUENTIAL (blocks on: Task 1 — needs DB bootstrap + schema)
**Estimated scope:** Large

## Context

We are migrating the `conversation-search-mcp` tool from an in-memory `bm25s` search
backend to SQLite FTS5. This task rewrites the `build()` method to write to SQLite
instead of in-memory arrays, with safe stale deletion for persistent storage.

**Full spec:** `specs/fts5-migration.md` (read this first for complete context)
**Main source:** `conversation_search.py` (~1400 lines, single-file Python app)

## Objective

Rewrite `ConversationIndex.build()` to:
1. Discover JSONL files matching the glob pattern
2. Incrementally index new/changed files into SQLite (sessions + turns_fts tables)
3. Safely delete stale rows scoped to the current pattern only
4. Rewrite `list_conversations()` to query the sessions table
5. Update `read_turn()` and `read_conversation()` to get file_path from sessions table

## Files to Modify

- `conversation_search.py` — rewrite build/list/read methods
- `tests/test_fts5_index.py` — add/update tests

## What to Do

### 1. Rewrite `build(pattern)`

Replace the in-memory indexing with SQLite writes. The method should:

```
with self._lock:
    conn = self._get_connection()
    # 1. Glob for JSONL files matching pattern
    # 2. Load existing sessions from DB: {file_path: (session_id, mtime, size)}
    # 3. For each discovered file:
    #    a. Check mtime + size against DB cache
    #    b. If unchanged: add to seen_paths, skip
    #    c. If changed or new:
    #       - Parse JSONL (reuse existing _parse_conversation logic)
    #       - DELETE old rows: turns_fts WHERE session_id = ?, sessions WHERE session_id = ?
    #       - INSERT new rows into sessions and turns_fts
    #       - Add to seen_paths
    # 4. Pattern-scoped stale deletion (see below)
    # 5. conn.commit()
    # 6. PRAGMA optimize
```

### 2. Pattern-scoped stale deletion (CRITICAL)

This is the most important correctness requirement. With a persistent DB, the old
"delete everything not seen" approach would destroy data from other patterns.

**Rule:** Only delete a stored session if:
- Its `file_path` falls within the current glob pattern's scope, AND
- Its `file_path` is not in `seen_paths`

Implementation approach:
- The current codebase uses `_PROJECTS_ROOT.glob(pattern)` to discover project directories,
  then finds JSONL files within those directories
- For each stored session NOT in `seen_paths`, derive its parent directory path relative
  to `_PROJECTS_ROOT`, then check if that relative directory would be matched by the
  current glob pattern
- Only delete if the stored session's directory falls within the current pattern's scope
  AND the file is not in `seen_paths`
- Rows from directories outside the current pattern's scope are never touched

### 3. Rewrite `list_conversations()`

Query the `sessions` table directly instead of in-memory dict:
```python
SELECT session_id, project, slug, summary, cwd, git_branch,
       first_ts, last_ts, turn_count
FROM sessions
WHERE project LIKE ? (if filtered)
ORDER BY last_ts DESC
LIMIT ?
```

**Note:** Keep the existing method signature. Do NOT add pagination/offset — that's
not in the current API or the agreed spec.

### 4. Update `read_turn()` and `read_conversation()`

Get `file_path` from the `sessions` table instead of `self._session_files`:
```python
row = conn.execute("SELECT file_path FROM sessions WHERE session_id = ?", (sid,)).fetchone()
```
Then re-parse the JSONL file as before (full-fidelity reads unchanged).

### 5. Tests

Add to `tests/test_fts5_index.py`:
- **Basic build test:** Index a set of test JSONL files, verify sessions and turns are in DB
- **Incremental build test:** Build, modify one file, rebuild — verify only changed file is reparsed
- **Pattern-scoped deletion (critical regression test):**
  - Build with pattern `dir_a/*`
  - Build with pattern `dir_b/*`
  - Verify dir_a sessions still exist after dir_b build
- **File deletion cleanup:** Delete a JSONL file, rebuild — verify its sessions/turns are removed
- **Directory deletion cleanup:** Delete an entire project directory, rebuild — verify cleanup
- **list_conversations test:** Verify project filtering, sort order (by last_ts DESC), limit
- **read_turn/read_conversation:** Verify file_path lookup from DB works correctly

## What NOT to Do

- Do NOT rewrite `search()` — that's Task 3
- Do NOT remove bm25s imports yet — that's Task 5
- Do NOT update docs — that's Task 4
- Keep the existing `_parse_conversation` logic; just change where results are stored

## Acceptance Criteria

- [ ] `build()` writes sessions and turns to SQLite instead of in-memory arrays
- [ ] Incremental builds skip unchanged files (mtime+size cache in sessions table)
- [ ] Building with pattern A then pattern B does NOT delete pattern A's data
- [ ] Deleting a file in the current pattern removes its sessions + turns on rebuild
- [ ] `list_conversations()` queries the sessions table with filtering and pagination
- [ ] `read_turn()` and `read_conversation()` look up file_path from sessions table
- [ ] All new tests pass; existing tests still pass
- [ ] All DB operations are within `with self._lock:` blocks
