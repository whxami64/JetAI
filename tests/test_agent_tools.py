"""Agent tool factories: SQL capping, error passthrough, path safety."""

from __future__ import annotations

from pathlib import Path

import duckdb

from jetai.agents.models import DatasetProfile, FileProfile
from jetai.agents.tools import (
    make_execute_sql_tool,
    make_list_sources_tool,
    make_read_head_tool,
    make_read_markdown_tool,
    make_schema_tool,
)


def test_execute_sql_caps_rows() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE t AS SELECT range AS n FROM range(100)")
    tool = make_execute_sql_tool(conn, max_rows=10)

    output = tool.invoke({"query": "SELECT * FROM t ORDER BY n"})
    assert "capped at 10 rows" in output
    assert len(output.splitlines()) == 12  # header + 10 rows + cap notice


def test_execute_sql_is_safe_under_parallel_tool_calls() -> None:
    """langgraph runs parallel tool calls on threads sharing one connection."""
    from concurrent.futures import ThreadPoolExecutor

    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE t AS SELECT range AS n FROM range(500)")
    tool = make_execute_sql_tool(conn, max_rows=10)

    def query(_: int) -> str:
        return tool.invoke({"query": "SELECT n FROM t ORDER BY n"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(query, range(80)))
    assert all(out.splitlines()[1] == "0" for out in outputs)


def test_execute_sql_returns_errors_as_text() -> None:
    tool = make_execute_sql_tool(duckdb.connect(":memory:"))
    output = tool.invoke({"query": "SELECT * FROM missing_table"})
    assert output.startswith("SQL error:")


def test_schema_tool_lists_and_samples() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE accounts AS SELECT '100' AS account_id, 'Kasse' AS name")
    tool = make_schema_tool(conn)

    listing = tool.invoke({})
    assert "accounts" in listing and "account_id" in listing

    detail = tool.invoke({"table_name": "accounts"})
    assert "Kasse" in detail

    assert "No table or view" in tool.invoke({"table_name": "nope"})


def test_list_sources_tool_renders_profile() -> None:
    profile = DatasetProfile(
        root="/x",
        files=[FileProfile(path="a/b.csv", kind="table", rows=42, description="Vendors.")],
    )
    output = make_list_sources_tool(profile).invoke({})
    assert "a/b.csv" in output and "42 rows" in output and "Vendors." in output


def test_read_head_caps_lines_and_blocks_escapes(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
    tool = make_read_head_tool(tmp_path)

    output = tool.invoke({"relative_path": "data.csv", "lines": 99})
    assert len(output.splitlines()) == 40  # hard cap

    assert "error" in tool.invoke({"relative_path": "../secret.txt"})


def test_read_markdown_only_reads_markdown(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("# Threshold 10.000 EUR", encoding="utf-8")
    (tmp_path / "raw.csv").write_text("a;b", encoding="utf-8")
    tool = make_read_markdown_tool(tmp_path)

    assert "Threshold" in tool.invoke({"relative_path": "paper.md"})
    assert "error" in tool.invoke({"relative_path": "raw.csv"})
