"""Tool factories shared by the specialist agents.

Each factory binds a resource (DuckDB connection, dataset root, profile) into
a langchain tool. Results are deliberately compact: row-capped SQL output,
head-capped file reads — agents must aggregate and inspect, never dump.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from langchain_core.tools import BaseTool, tool

from jetai.agents.models import DatasetProfile

MAX_SQL_ROWS = 50
MAX_HEAD_LINES = 40


def _render_rows(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    header = " | ".join(columns)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in rows)
    return f"{header}\n{body}" if body else f"{header}\n(no rows)"


def make_execute_sql_tool(
    conn: duckdb.DuckDBPyConnection, *, max_rows: int = MAX_SQL_ROWS
) -> BaseTool:
    """SQL execution against the run's DuckDB; errors come back as text."""

    @tool
    def execute_sql(query: str) -> str:
        """Run one SQL statement against the audit database.

        Output is capped at a few dozen rows — use aggregation (GROUP BY,
        COUNT, SUM, LIMIT) instead of dumping tables.
        """
        try:
            cursor = conn.execute(query)
            if cursor.description is None:
                return "OK (statement executed, no result set)"
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(max_rows + 1)
        except duckdb.Error as error:
            return f"SQL error: {error}"
        truncated = len(rows) > max_rows
        text = _render_rows(columns, rows[:max_rows])
        if truncated:
            text += f"\n... output capped at {max_rows} rows; aggregate instead."
        return text

    return execute_sql


def make_schema_tool(conn: duckdb.DuckDBPyConnection) -> BaseTool:
    """The 'inspect before you query' tool: tables, columns, sample rows."""

    @tool
    def inspect_schema(table_name: str = "") -> str:
        """List tables/views with their columns. Pass a table name to also
        see its column types and 3 sample rows. Always inspect before querying."""
        try:
            if not table_name:
                rows = conn.execute(
                    "SELECT table_name, table_type FROM information_schema.tables "
                    "ORDER BY table_name"
                ).fetchall()
                lines = []
                for name, kind in rows:
                    columns = conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = ? ORDER BY ordinal_position",
                        [name],
                    ).fetchall()
                    lines.append(f"{name} ({kind}): {', '.join(c[0] for c in columns)}")
                return "\n".join(lines) or "(no tables yet)"
            columns = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            if not columns:
                return f"No table or view named {table_name!r}."
            cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
            names = [d[0] for d in cursor.description or []]
            sample = _render_rows(names, cursor.fetchall())
            types = ", ".join(f"{c[0]} {c[1]}" for c in columns)
            return f"{table_name}: {types}\nsample:\n{sample}"
        except duckdb.Error as error:
            return f"SQL error: {error}"

    return inspect_schema


def make_list_sources_tool(profile: DatasetProfile) -> BaseTool:
    """One line per profiled source file, so agents can pick without loading."""

    @tool
    def list_sources() -> str:
        """List every source file in the dataset: path, rows, one-line description."""
        lines = [
            f"{f.path} [{f.kind}, {f.rows} rows] {f.description}".strip() for f in profile.files
        ]
        return "\n".join(lines) or "(no files profiled)"

    return list_sources


def _resolve_inside(root: Path, relative_path: str) -> Path:
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes the dataset root: {relative_path}")
    return resolved


def make_read_head_tool(root: Path) -> BaseTool:
    """First lines of a source file, for schema inspection only."""

    @tool
    def read_head(relative_path: str, lines: int = 20) -> str:
        """Read the first lines of a source file (capped at 40) to inspect its
        header and value shapes. Never use this to read whole files."""
        try:
            path = _resolve_inside(root, relative_path)
            with path.open(encoding="utf-8", errors="replace") as handle:
                head = [next(handle, "") for _ in range(min(lines, MAX_HEAD_LINES))]
        except (OSError, ValueError) as error:
            return f"error: {error}"
        return "".join(head).rstrip("\n")

    return read_head


def make_read_markdown_tool(root: Path) -> BaseTool:
    """Full text of a converted markdown document (working papers are short)."""

    @tool
    def read_markdown(relative_path: str) -> str:
        """Read the full text of a converted .md document (working papers,
        statements). Only .md files are readable."""
        try:
            path = _resolve_inside(root, relative_path)
            if path.suffix.lower() != ".md":
                return f"error: {relative_path} is not a markdown document"
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            return f"error: {error}"

    return read_markdown
