# Task 3: Search Query Engine — FTS5 MATCH, Filtering, Ranking, Fallback

**Type:** SEQUENTIAL (blocks on: Task 2 — search tests need build() to populate data)
**Estimated scope:** Large

## Context

We are migrating the `conversation-search-mcp` tool from an in-memory `bm25s` search
backend to SQLite FTS5. This task rewrites `search()` to use FTS5 MATCH queries with
SQL-level filtering, recency-blended ranking, query fallback for code-like searches,
and `[[`/`]]` snippet markers.

**Full spec:** `specs/fts5-migration.md` (read this first for complete context)
**Main source:** `conversation_search.py` (~1400 lines, single-file Python app)

## Objective

Rewrite `ConversationIndex.search()` with:
1. SQL-level filtering (session_id, project) — no Python post-filter
2. Accurate total count via separate COUNT query
3. BM25 + recency-blended ranking with proper re-sort before limit
4. `[[`/`]]` snippet markers
5. Try-raw-then-fallback query error handling
6. `literal:` prefix for deterministic code-like searches

## Files to Modify

- `conversation_search.py` — rewrite search method + add helpers
- `tests/test_fts5_index.py` — add/update tests

## What to Do

### 1. Rewrite `search()` method

See spec §Search for the complete pseudocode. Key changes from current implementation:

**SQL-level filtering:**
```python
conditions = ["turns_fts MATCH ?"]
params = [query]
if session_id:
    conditions.append("session_id = ?")
    params.append(session_id)
if project:
    conditions.append("project LIKE ?")
    params.append(f"%{project}%")
where = " AND ".join(conditions)
```

**Accurate total count:**
```python
count_sql = f"SELECT COUNT(*) FROM turns_fts WHERE {where}"
total = conn.execute(count_sql, params_without_limit).fetchone()[0]
```

**Snippet markers:** Use `snippet(turns_fts, 0, '[[', ']]', '...', 24)` — NOT `**`.

**Recency re-sort:** After computing blended scores, `results.sort(key=lambda r: -r["score"])`
MUST happen BEFORE `results[:limit]` truncation. This is not optional.

### 2. Query fallback helper `_execute_fts_query()`

Implement the try-raw-then-fallback strategy (spec §Error Handling):
1. Execute raw query
2. On any `sqlite3.OperationalError` from the MATCH query (not just errors containing
   "fts5" — FTS5 parse failures can surface as generic syntax errors, unterminated-string
   errors, etc.): extract tokens with `_extract_search_tokens()`, retry as quoted phrase
3. On second failure: return structured error response:
   `{"results": [], "query": query, "total": 0, "error": f"Query failed: {e}"}`

**Important:** Catch `OperationalError` broadly from the FTS5 MATCH execution, but
do NOT catch errors from non-MATCH SQL (e.g., COUNT queries, connection issues).
The simplest approach: wrap only the MATCH execute call in try/except, not the
entire method.

```python
def _extract_search_tokens(query: str) -> list[str]:
    """Strip punctuation/operators, keep alphanumeric + underscore."""
    import re
    return re.findall(r'\w+', query)
```

### 3. `literal:` prefix support

Before any FTS5 processing:
```python
if query.startswith("literal:"):
    raw = query[len("literal:"):]
    tokens = _extract_search_tokens(raw)
    query = '"' + " ".join(tokens) + '"' if tokens else raw
```

### 4. Recency boost helper

```python
def _age_in_days(ts: str, now: float) -> float:
    """Convert ISO 8601 timestamp to age in days."""
    # Parse ts, compute (now - ts_epoch) / 86400
```

Recency formula: `blended = bm25_score * (1 + 0.2 * recency)` where
`recency = math.exp(-0.693 * age_days / 30)` (30-day half-life, 20% weight).

### 5. Tests

Add to `tests/test_fts5_index.py`:

- **Basic search:** Index test data, search for a keyword, verify results returned
- **SQL-level session_id filter:** Search with session_id filter, verify only matching
  session's turns returned (no Python post-filter)
- **SQL-level project filter:** Same for project filter
- **Accurate total count:** Search with filters, verify `total` matches actual count
  (not just `len(results)`)
- **Recency ranking:** Index two turns with same content but different timestamps,
  verify recent turn ranks higher. **Important:** use significantly different timestamps
  (e.g., 1 day ago vs 60 days ago) so recency boost is large enough to be observable.
  Do NOT rely on insertion order.
- **Snippet markers:** Verify snippets contain `[[` and `]]`, not `**`
- **Query fallback — code-like query:** Search for `key=lambda` or `std::vector` — should
  not raise an error, should return results if matching content exists
- **Query fallback — unclosed quote:** Search for `"unclosed` — should not raise,
  should return structured error or fallback results
- **Unrecoverable query:** Search for something that fails both raw and fallback,
  verify response includes `"error"` key with descriptive message
- **literal: prefix:** Search for `literal:conversation_search.py` — should tokenize
  and search, not break
- **Boolean query:** Search for `heartbeat AND NOT clawd` — verify FTS5 boolean works
- **Phrase query:** Search for `"systemd timer"` — verify exact phrase matching
- **Prefix query:** Search for `buffer*` — verify prefix matching
- **Empty results:** Search for nonexistent term, verify `{"results": [], "total": 0}`

## What NOT to Do

- Do NOT modify `build()` — that's Task 2
- Do NOT remove bm25s imports — that's Task 5
- Do NOT update docs — that's Task 4
- Do NOT change the method signature of `search()` — keep it API-compatible

## Acceptance Criteria

- [ ] `session_id` and `project` filters are in SQL WHERE, not Python post-filter
- [ ] `total` reflects full filtered match count, not just page size
- [ ] Code-like queries (punctuation, operators) don't crash — fallback works
- [ ] `literal:` prefix tokenizes and searches as quoted phrase
- [ ] Recency boost affects final ordering (re-sort happens before truncation)
- [ ] Snippets use `[[`/`]]` markers
- [ ] FTS5 boolean, phrase, and prefix queries work correctly
- [ ] All new tests pass; existing tests still pass
- [ ] All DB operations are within `with self._lock:` blocks
