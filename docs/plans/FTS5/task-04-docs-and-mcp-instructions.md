# Task 4: Documentation and MCP Instructions Update

**Type:** SEQUENTIAL (blocks on: Task 3 — docs describe search behavior implemented there;
both tasks edit `conversation_search.py`, so parallel execution would cause merge conflicts)
**Estimated scope:** Small

## Context

We are migrating the `conversation-search-mcp` tool from an in-memory `bm25s` search
backend to SQLite FTS5. This task updates all user-facing documentation to reflect the
new search behavior.

**Full spec:** `specs/fts5-migration.md` (read this first for complete context)
**Main source:** `conversation_search.py` (~1400 lines, single-file Python app)

## Objective

Update all user-facing text — MCP server instructions, tool docstrings, README, and
specs — to accurately describe FTS5 behavior. Remove stale bm25s references.

## Files to Modify

- `conversation_search.py` — MCP server instructions string, tool docstrings
- `README.md` — user-facing documentation
- `specs/conversation-search-mcp.md` — original spec (add migration note)

## What to Do

### 1. MCP server instructions string

Find the server instructions string in `conversation_search.py` (used by FastMCP for
the `instructions` parameter). Update to document:

- FTS5 query syntax: implicit AND, phrases (`"..."`), boolean (`AND`, `OR`, `NOT`),
  prefix (`term*`), grouping (`(a OR b) AND c`)
- `literal:` prefix for code-like searches
- Snippet format: `[[match]]` markers in context windows
- Recency boost: recent conversations score slightly higher
- Remove any mention of "increase limit for better filtering" — filters are now in SQL

### 2. Tool docstrings

Update the `search_conversations` tool description/docstring to mention:
- Implicit AND (all terms must match by default)
- OR is explicit
- FTS5 syntax support
- `literal:` prefix

### 3. README.md

Update the README to reflect:
- SQLite FTS5 backend (not bm25s)
- Persistent on-disk index (`~/.cache/conversation-search/index.db`)
- No `bm25s` dependency
- FTS5 query syntax examples
- Improved startup time (warm start from persistent DB)
- Lower memory footprint

Remove:
- Any mention of bm25s
- "250 MB in-memory index" or similar
- "rebuild on every start" language

### 4. Remove stale guidance

Search for and remove/update any text that:
- References `bm25s`, `BM25`, or in-memory indexing as current behavior
- Tells users to "raise limit" to compensate for post-retrieval filtering
- Describes snippets as "first 300 characters" or using `**` bold markers
- Describes the backend as keyword-only or implicit OR

## What NOT to Do

- Do NOT modify any Python logic/implementation — only strings and docs
- Do NOT create new documentation files beyond what's listed above
- Keep changes minimal and accurate

## Acceptance Criteria

- [ ] No user-facing text mentions bm25s as the current backend
- [ ] No text describes snippets as "first 300 chars" or using `**` markers
- [ ] No text advises raising `limit` for filtering workarounds
- [ ] MCP instructions document FTS5 query syntax, `literal:` prefix, `[[`/`]]` snippets
- [ ] README describes SQLite FTS5, persistent indexing, and lower memory footprint
- [ ] Tool docstrings mention implicit AND and FTS5 syntax
