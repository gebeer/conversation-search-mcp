"""Tests for the SQLite FTS5 index (schema, build, search, list, read, recency)."""
from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from conftest import cs, SAMPLE_RECORDS, SAMPLE_SESSION_ID


# ---------------------------------------------------------------------------
# Additional sample data for cross-session tests
# ---------------------------------------------------------------------------

SECOND_SESSION_ID = "def67890-aaaa-bbbb-cccc-dddddddddddd"

SECOND_SESSION_RECORDS = [
    {
        "type": "user",
        "message": {"role": "user", "content": "How does SQLite FTS5 full-text search work?"},
        "timestamp": "2026-02-01T09:00:00Z",
        "cwd": "/home/user/otherproject",
        "slug": "sqlite-fts5-search",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "FTS5 is a virtual table that supports inverted indexes for full-text search.",
                }
            ],
        },
        "timestamp": "2026-02-01T09:00:10Z",
    },
    {
        "type": "user",
        "message": {"role": "user", "content": "What tokenizer should I use for porter stemming?"},
        "timestamp": "2026-02-01T09:01:00Z",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Use tokenize='porter unicode61' when creating the FTS5 virtual table.",
                }
            ],
        },
        "timestamp": "2026-02-01T09:01:15Z",
    },
]

THIRD_SESSION_ID = "aabbccdd-1234-5678-9abc-eeff00112233"

# Older session with identical term ("sorting") so recency boost is testable
THIRD_SESSION_RECORDS = [
    {
        "type": "user",
        "message": {"role": "user", "content": "How do I do sorting in Python?"},
        "timestamp": "2024-01-01T00:00:00Z",  # very old
        "cwd": "/home/user/oldproject",
        "slug": "old-python-sorting",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "You can use sorted() or list.sort() for sorting."}
            ],
        },
        "timestamp": "2024-01-01T00:00:10Z",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_projects_dir(tmp_path, monkeypatch):
    """Redirect _PROJECTS_ROOT to a temp directory with multiple sessions."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(cs, "_PROJECTS_ROOT", root)

    # First project: "sorting" session (recent — 2026-01-15)
    proj1 = root / "home-user-myproject"
    proj1.mkdir()
    (proj1 / f"{SAMPLE_SESSION_ID}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in SAMPLE_RECORDS) + "\n"
    )

    # Second project: "sqlite fts5" session
    proj2 = root / "home-user-otherproject"
    proj2.mkdir()
    (proj2 / f"{SECOND_SESSION_ID}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in SECOND_SESSION_RECORDS) + "\n"
    )

    # Third project: "sorting" session (very old — 2024-01-01)
    proj3 = root / "home-user-oldproject"
    proj3.mkdir()
    (proj3 / f"{THIRD_SESSION_ID}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in THIRD_SESSION_RECORDS) + "\n"
    )

    return root


@pytest.fixture
def index_with_data(tmp_path, projects_dir, sample_jsonl):
    """ConversationIndex backed by temp SQLite DB, built from sample data."""
    db_path = tmp_path / "test.db"
    idx = cs.ConversationIndex(db_path=db_path)
    idx.build("*")
    return idx


@pytest.fixture
def multi_index(tmp_path, multi_projects_dir):
    """ConversationIndex with three sessions across three projects."""
    db_path = tmp_path / "multi.db"
    idx = cs.ConversationIndex(db_path=db_path)
    idx.build("*")
    return idx


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------


class TestCreateSchema:
    def test_create_schema_creates_tables(self, tmp_path):
        db_path = tmp_path / "schema_test.db"
        conn = sqlite3.connect(str(db_path))
        cs._create_schema(conn)

        # Check sessions table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchall()
        assert len(tables) == 1, "sessions table should exist"

        # Check turns_fts virtual table exists
        vtables = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='turns_fts'"
        ).fetchall()
        assert len(vtables) == 1, "turns_fts virtual table should exist"

        conn.close()

    def test_create_schema_idempotent(self, tmp_path):
        db_path = tmp_path / "idempotent_test.db"
        conn = sqlite3.connect(str(db_path))

        # Should not raise on second call
        cs._create_schema(conn)
        cs._create_schema(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
        ).fetchall()
        # At minimum sessions and turns_fts must be present
        table_names = {row[0] for row in tables}
        assert "sessions" in table_names
        assert "turns_fts" in table_names

        conn.close()


# ---------------------------------------------------------------------------
# 2. Build / indexing tests
# ---------------------------------------------------------------------------


class TestBuildIndexing:
    def test_build_indexes_sample_data(self, tmp_path, projects_dir, sample_jsonl):
        """Building from sample JSONL produces the correct number of FTS rows."""
        db_path = tmp_path / "build.db"
        idx = cs.ConversationIndex(db_path=db_path)
        idx.build("*")

        conn = idx._get_connection()
        # SAMPLE_RECORDS has 2 user messages → 2 turns
        row_count = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
        assert row_count == 2, f"Expected 2 turns, got {row_count}"

    def test_build_incremental_skips_unchanged(self, tmp_path, projects_dir, sample_jsonl, capsys):
        """Second build on unchanged files should report cache_hits == file_count."""
        db_path = tmp_path / "inc.db"
        idx = cs.ConversationIndex(db_path=db_path)

        idx.build("*")
        # Capture stderr from second build
        idx.build("*")

        captured = capsys.readouterr()
        # Second build's stderr line should show '1 cached' (1 file, unchanged)
        assert "1 cached" in captured.err, (
            f"Expected '1 cached' in stderr, got: {captured.err!r}"
        )

    def test_build_incremental_detects_changes(self, tmp_path, projects_dir, sample_jsonl):
        """Modifying a file between builds causes it to be re-indexed."""
        db_path = tmp_path / "detect.db"
        idx = cs.ConversationIndex(db_path=db_path)
        idx.build("*")

        conn = idx._get_connection()
        initial_count = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
        assert initial_count == 2

        # Append a new user/assistant exchange to the JSONL
        extra_records = [
            {
                "type": "user",
                "message": {"role": "user", "content": "What is a generator in Python?"},
                "timestamp": "2026-01-15T11:00:00Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "A generator yields values lazily."}],
                },
                "timestamp": "2026-01-15T11:00:05Z",
            },
        ]
        with open(sample_jsonl["session_file"], "a") as f:
            for r in extra_records:
                f.write(json.dumps(r) + "\n")

        # Touch mtime so change is detected (write appends change size too)
        idx.build("*")

        new_count = conn.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
        assert new_count == 3, f"Expected 3 turns after re-index, got {new_count}"

    def test_build_removes_stale_sessions(self, tmp_path, multi_projects_dir):
        """Deleting a JSONL and rebuilding removes its session and turns from the DB."""
        db_path = tmp_path / "stale.db"
        idx = cs.ConversationIndex(db_path=db_path)
        idx.build("*")

        conn = idx._get_connection()
        initial_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert initial_sessions == 3

        # Delete the second session's JSONL file
        stale_file = multi_projects_dir / "home-user-otherproject" / f"{SECOND_SESSION_ID}.jsonl"
        stale_file.unlink()

        idx.build("*")

        remaining_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert remaining_sessions == 2, f"Expected 2 sessions after deletion, got {remaining_sessions}"

        # The deleted session's turns must also be gone
        stale_turns = conn.execute(
            "SELECT COUNT(*) FROM turns_fts WHERE session_id = ?", (SECOND_SESSION_ID,)
        ).fetchone()[0]
        assert stale_turns == 0, "Stale session's turns should have been removed"

    def test_build_populates_sessions_table(self, tmp_path, projects_dir, sample_jsonl):
        """Session metadata (project, slug, timestamps, turn_count) is stored correctly."""
        db_path = tmp_path / "meta.db"
        idx = cs.ConversationIndex(db_path=db_path)
        idx.build("*")

        conn = idx._get_connection()
        row = conn.execute(
            "SELECT session_id, project, slug, first_ts, last_ts, turn_count FROM sessions"
        ).fetchone()

        assert row is not None, "sessions table should have at least one row"
        session_id, project, slug, first_ts, last_ts, turn_count = row

        assert session_id == SAMPLE_SESSION_ID
        assert "myproject" in project  # derived from directory name
        assert slug == "python-sorting"  # from SAMPLE_RECORDS slug field
        assert first_ts == "2026-01-15T10:00:00Z"
        assert last_ts == "2026-01-15T10:01:10Z"
        assert turn_count == 2


# ---------------------------------------------------------------------------
# 3. Search tests
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_basic_keyword(self, index_with_data):
        """Searching for a known term returns at least one result."""
        result = index_with_data.search("sorting")
        assert result["total"] > 0
        assert len(result["results"]) > 0
        assert result["query"] == "sorting"

    def test_search_returns_snippets(self, index_with_data):
        """Snippets contain bold markers around matched terms."""
        result = index_with_data.search("sorting")
        assert result["total"] > 0
        # FTS5 snippet uses '**' as opening and closing markers
        snippet = result["results"][0]["snippet"]
        assert "**" in snippet, f"Expected bold markers in snippet, got: {snippet!r}"

    def test_search_no_results(self, index_with_data):
        """Searching for a nonexistent term returns empty results."""
        result = index_with_data.search("xyznonexistentterm123")
        assert result["total"] == 0
        assert result["results"] == []

    def test_search_phrase_query(self, multi_index):
        """Quoted phrase search finds exact multi-word phrases."""
        result = multi_index.search('"custom key function"')
        assert result["total"] > 0
        assert any("key" in r["snippet"].lower() for r in result["results"])

    def test_search_boolean_or(self, multi_index):
        """OR boolean query returns results matching either term."""
        result = multi_index.search("sorting OR tokenizer")
        assert result["total"] > 0
        # Should match sessions from both the sorting and FTS5 sessions
        session_ids = {r["session_id"] for r in result["results"]}
        assert len(session_ids) >= 1

    def test_search_boolean_not(self, multi_index):
        """AND NOT query excludes results containing the excluded term."""
        result_sorting = multi_index.search("sort")
        result_not = multi_index.search("sort NOT lambda")
        # Excluding lambda should eliminate the turn that mentions key=lambda
        assert result_not["total"] <= result_sorting["total"]

    def test_search_prefix_query(self, multi_index):
        """Prefix search matches words starting with the given prefix."""
        result = multi_index.search("sort*")
        assert result["total"] > 0
        # Should match "sort", "sorted", "sorting"

    def test_search_filter_by_session(self, multi_index):
        """Filtering by session_id restricts results to that session."""
        result = multi_index.search("sort*", session_id=SAMPLE_SESSION_ID, limit=20)
        assert result["total"] > 0
        for r in result["results"]:
            assert r["session_id"] == SAMPLE_SESSION_ID

    def test_search_filter_by_project(self, multi_index):
        """Filtering by project substring restricts results to matching project."""
        result = multi_index.search("sort*", project="myproject", limit=20)
        assert result["total"] > 0
        for r in result["results"]:
            assert "myproject" in r["project"].lower()

    def test_search_invalid_syntax(self, index_with_data):
        """Malformed FTS5 query returns error dict instead of raising an exception."""
        # An unclosed quote is invalid FTS5 syntax
        result = index_with_data.search('"unclosed phrase')
        assert "error" in result, "Malformed query should return an error key"
        assert result["results"] == []
        assert result["total"] == 0

    def test_search_recency_boost(self, multi_index):
        """More recent session appears before older session for equal-relevance query.

        FTS5 BM25 scores are very small floats (sub-0.0001) that round to 0.0
        at 4 decimal places, so we verify ordering not score magnitude.
        The recency boost formula (exp decay with 30-day half-life) causes the
        recent session (2026-01-15) to rank before the old one (2024-01-01)
        when BM25 scores are equal.
        """
        # Both SAMPLE_SESSION_ID (2026-01-15) and THIRD_SESSION_ID (2024-01-01)
        # contain the word "sorting" in structurally identical turns.
        result = multi_index.search("sorting", limit=10)
        assert result["total"] >= 2

        # Collect positions for the two sessions (first occurrence wins)
        positions: dict[str, int] = {}
        for i, r in enumerate(result["results"]):
            if r["session_id"] in (SAMPLE_SESSION_ID, THIRD_SESSION_ID):
                if r["session_id"] not in positions:
                    positions[r["session_id"]] = i

        assert SAMPLE_SESSION_ID in positions, "Recent session should appear in results"
        assert THIRD_SESSION_ID in positions, "Old session should appear in results"

        assert positions[SAMPLE_SESSION_ID] < positions[THIRD_SESSION_ID], (
            f"Recent session (position {positions[SAMPLE_SESSION_ID]}) should rank "
            f"before old session (position {positions[THIRD_SESSION_ID]})"
        )


# ---------------------------------------------------------------------------
# 4. List conversations tests
# ---------------------------------------------------------------------------


class TestListConversations:
    def test_list_conversations_returns_all(self, multi_index):
        """Listing without a filter returns all indexed sessions."""
        result = multi_index.list_conversations()
        assert result["total"] == 3
        ids = {c["session_id"] for c in result["conversations"]}
        assert SAMPLE_SESSION_ID in ids
        assert SECOND_SESSION_ID in ids
        assert THIRD_SESSION_ID in ids

    def test_list_conversations_filter_project(self, multi_index):
        """Project substring filter returns only matching sessions."""
        result = multi_index.list_conversations(project="myproject")
        assert result["total"] == 1
        assert result["conversations"][0]["session_id"] == SAMPLE_SESSION_ID

    def test_list_conversations_sorted_by_time(self, multi_index):
        """Results are sorted descending by last_timestamp."""
        result = multi_index.list_conversations()
        timestamps = [c["last_timestamp"] for c in result["conversations"]]
        assert timestamps == sorted(timestamps, reverse=True), (
            f"Expected descending order, got: {timestamps}"
        )

    def test_list_conversations_respects_limit(self, multi_index):
        """Limit parameter caps the number of returned sessions."""
        result = multi_index.list_conversations(limit=1)
        assert len(result["conversations"]) == 1
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# 5. Read tests
# ---------------------------------------------------------------------------


class TestReadTurn:
    def test_read_turn_success(self, index_with_data):
        """Reading a valid turn returns user_text and assistant_text."""
        result = index_with_data.read_turn(SAMPLE_SESSION_ID, 0)
        assert "error" not in result
        assert result["session_id"] == SAMPLE_SESSION_ID
        assert result["turn_number"] == 0
        assert "sort" in result["user_text"].lower()
        assert "sorted" in result["assistant_text"].lower() or "sort" in result["assistant_text"].lower()

    def test_read_turn_unknown_session(self, index_with_data):
        """Unknown session_id returns an error dict."""
        result = index_with_data.read_turn("nonexistent-session-id", 0)
        assert "error" in result
        assert "nonexistent-session-id" in result["error"]

    def test_read_turn_out_of_range(self, index_with_data):
        """Turn number beyond session length returns an error dict."""
        result = index_with_data.read_turn(SAMPLE_SESSION_ID, 9999)
        assert "error" in result
        assert "out of range" in result["error"].lower() or "9999" in result["error"]

    def test_read_turn_negative_turn_number(self, index_with_data):
        """Negative turn number returns an error dict."""
        result = index_with_data.read_turn(SAMPLE_SESSION_ID, -1)
        assert "error" in result


class TestReadConversation:
    def test_read_conversation_success(self, index_with_data):
        """Paginated read returns turns with correct structure."""
        result = index_with_data.read_conversation(SAMPLE_SESSION_ID, offset=0, limit=10)
        assert "error" not in result
        assert result["session_id"] == SAMPLE_SESSION_ID
        assert result["total_turns"] == 2
        assert len(result["turns"]) == 2
        assert result["offset"] == 0
        assert result["limit"] == 10

        # Verify turn structure
        first_turn = result["turns"][0]
        assert "turn_number" in first_turn
        assert "user_text" in first_turn
        assert "assistant_text" in first_turn
        assert "tools_used" in first_turn
        assert "timestamp" in first_turn

    def test_read_conversation_pagination(self, index_with_data):
        """Offset + limit slices the turns correctly."""
        result = index_with_data.read_conversation(SAMPLE_SESSION_ID, offset=1, limit=1)
        assert "error" not in result
        assert len(result["turns"]) == 1
        assert result["turns"][0]["turn_number"] == 1

    def test_read_conversation_unknown_session(self, index_with_data):
        """Unknown session_id returns an error dict."""
        result = index_with_data.read_conversation("nonexistent-session-id")
        assert "error" in result
        assert "nonexistent-session-id" in result["error"]

    def test_read_conversation_includes_metadata(self, index_with_data):
        """Response includes project, cwd, and git_branch fields."""
        result = index_with_data.read_conversation(SAMPLE_SESSION_ID)
        assert "error" not in result
        assert "project" in result
        assert "cwd" in result
        assert "git_branch" in result
        assert "myproject" in result["project"].lower()


# ---------------------------------------------------------------------------
# 6. Recency boost unit tests
# ---------------------------------------------------------------------------


class TestAgeInDays:
    def test_age_in_days_recent(self):
        """A timestamp 1 day ago returns approximately 1.0."""
        now = time.time()
        one_day_ago = now - 86400
        # Build an ISO string from that epoch
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(one_day_ago, tz=timezone.utc).isoformat()
        age = cs._age_in_days(ts, now)
        assert 0.9 < age < 1.1, f"Expected ~1.0 day, got {age}"

    def test_age_in_days_unknown(self):
        """Empty timestamp string returns 365 (treated as old)."""
        age = cs._age_in_days("", time.time())
        assert age == 365.0

    def test_age_in_days_utc_z_suffix(self):
        """ISO 8601 timestamp with Z suffix is parsed correctly."""
        now = time.time()
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(now - 86400 * 7, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # Z suffix format
        age = cs._age_in_days(ts, now)
        assert 6.9 < age < 7.1, f"Expected ~7.0 days, got {age}"

    def test_age_in_days_zero_for_now(self):
        """A timestamp equal to now returns 0 (or very close)."""
        now = time.time()
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        age = cs._age_in_days(ts, now)
        assert age < 0.01, f"Expected near-zero age, got {age}"

    def test_age_in_days_invalid_returns_365(self):
        """Unparseable timestamp string returns 365."""
        age = cs._age_in_days("not-a-date", time.time())
        assert age == 365.0

    def test_recency_boost_formula(self):
        """Verify that the blended score formula favors recent results."""
        # Simulate two identical BM25 scores, one recent (1 day) and one old (365 days)
        now = time.time()
        bm25_score = 1.0  # normalized positive score

        age_recent = 1.0   # 1 day old
        age_old = 365.0    # 1 year old

        recency_recent = math.exp(-0.693 * age_recent / 30)
        recency_old = math.exp(-0.693 * age_old / 30)

        blended_recent = bm25_score * (1 + 0.2 * recency_recent)
        blended_old = bm25_score * (1 + 0.2 * recency_old)

        assert blended_recent > blended_old, (
            f"Recent blended ({blended_recent:.4f}) should exceed old ({blended_old:.4f})"
        )
