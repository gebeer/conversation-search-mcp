# FTS5 Migration — Task Plan

Migration of `conversation-search-mcp` from in-memory `bm25s` to SQLite FTS5.

**Spec:** `specs/fts5-migration.md` (revised 2026-03-10 after peer review with Codex/GPT-5.4)

## Dependency Graph

```
Task 1: DB Bootstrap
  │
  └──► Task 2: Incremental Build (blocks on T1)
         │
         └──► Task 3: Search Query Engine (blocks on T2)
                │
                ├──► Task 4: Docs & MCP Instructions (blocks on T3)
                │
                └──► Task 5: Cleanup & Integration (blocks on T3+T4)
```

All tasks are strictly sequential. Task 4 was originally parallel but both T3 and T4
edit `conversation_search.py`, and T4's docs describe behavior implemented in T3.

## Task Summary

| Task | Title | Type | Blocks On | Size |
|------|-------|------|-----------|------|
| 1 | [DB Bootstrap, Schema, Threading](task-01-db-bootstrap.md) | SEQUENTIAL (foundation) | — | Medium |
| 2 | [Incremental Build + Stale Deletion](task-02-incremental-build.md) | SEQUENTIAL | Task 1 | Large |
| 3 | [Search Query Engine](task-03-search-query-engine.md) | SEQUENTIAL | Task 2 | Large |
| 4 | [Docs & MCP Instructions](task-04-docs-and-mcp-instructions.md) | SEQUENTIAL | Task 3 | Small |
| 5 | [Cleanup & Integration](task-05-cleanup-and-integration.md) | SEQUENTIAL (final) | Tasks 3, 4 | Small-Medium |

## Execution Strategy

**Phase 1:** Task 1 (foundation — everything depends on this)
**Phase 2:** Task 2 (incremental build + stale deletion)
**Phase 3:** Task 3 (search engine rewrite)
**Phase 4:** Task 4 (docs update — needs final search behavior from T3)
**Phase 5:** Task 5 (cleanup sweep + integration verification)

Each task is self-contained: a subagent receives the full spec (`specs/fts5-migration.md`)
plus its task document and can execute without further context.

## Review Notes

Spec was peer-reviewed by Codex (GPT-5.4) on 2026-03-10. Key revisions from review:
- Pattern-scoped stale deletion (prevents data loss with persistent DB)
- SQL-level filtering instead of Python post-filter
- Query fallback strategy for code-like searches
- `[[`/`]]` snippet markers instead of markdown bold
- Schema versioning with `PRAGMA user_version`
- Threading model: lock covers full operations
- FTS5 availability check at startup
- Accurate total count via separate COUNT query

Task decomposition was also reviewed by Codex. Fixes applied:
- Removed `--reindex` CLI flag from Task 5 (scope creep, contradicted own "no new features" rule)
- Removed `OFFSET`/pagination from Task 2 (not in current API or spec)
- Clarified pattern-scoping to use `_PROJECTS_ROOT`-relative directory matching
- Made Task 4 sequential after Task 3 (both edit `conversation_search.py`, avoid merge conflicts)
- Clarified Task 1 allows minimal lock-wrapper edits to existing methods
- Broadened FTS5 error catching in Task 3 (not just errors containing "fts5")
- Specified structured error response for unrecoverable query failures
- Tightened Task 5 scope (integration sweep, not archaeology)
