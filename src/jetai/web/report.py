"""Report rendering for the web UI: findings tables, source-file links, evidence.

Findings carry no file paths — only canonical view names inside their evidence
SQL. The chain back to the uploaded files goes through the build report's
``mapping`` (``"view.column" -> "source file/column"`` free text), matched
against the actual dataset tree, including the archived originals in
``stale/``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb

from jetai.agents.build import CANONICAL_SCHEMA, DB_FILENAME
from jetai.agents.checks import CHECK_SPECS
from jetai.agents.models import BuildReport, FinalReport, Finding
from jetai.dataset import STALE_DIRNAME

_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|create|drop|alter|copy|attach|export|install|load)\b",
    re.IGNORECASE,
)


def findings_table(report: FinalReport) -> list[list[str]]:
    """Confirmed findings as rows for a dataframe component."""
    return [
        [
            v.finding.check,
            v.finding.category,
            ", ".join(v.finding.primary_entities),
            f"{v.finding.amount_eur:,.2f}" if v.finding.amount_eur is not None else "",
            v.finding.period or "",
            v.finding.confidence,
        ]
        for v in report.confirmed
    ]


def views_for_finding(finding: Finding) -> set[str]:
    """Canonical views a finding rests on: its check's views + views in its SQL."""
    views: set[str] = set()
    spec = CHECK_SPECS.get(finding.check)
    if spec is not None:
        views.update(spec.required_views)
        views.update(spec.optional_views)
    sql = " ".join(finding.evidence_sql)
    for view in CANONICAL_SCHEMA:
        if re.search(rf"\b{re.escape(view)}\b", sql):
            views.add(view)
    return views


def _dataset_files(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*")) if p.is_file()]


def source_files_for_finding(
    finding: Finding, build_report: BuildReport, root: Path
) -> list[tuple[str, Path]]:
    """Best-effort ``(label, absolute path)`` list of the files behind a finding.

    Mapping values are LLM free text, so files are matched by name or stem
    substring; converted files get their archived original attached.
    """
    views = views_for_finding(finding)
    mapping_text = " ".join(
        value for key, value in build_report.mapping.items() if key.split(".", 1)[0] in views
    )
    if not mapping_text:
        return []

    files = _dataset_files(root)
    matched: dict[Path, str] = {}
    for path in files:
        if STALE_DIRNAME in path.relative_to(root).parts:
            continue
        if path.name in mapping_text or (len(path.stem) > 3 and path.stem in mapping_text):
            matched[path] = str(path.relative_to(root))
    results: list[tuple[str, Path]] = []
    for path, label in sorted(matched.items()):
        results.append((label, path))
        # A converted file's original was archived under stale/<relative path>
        # with the same stem but its source extension.
        stale_parent = root / STALE_DIRNAME / path.relative_to(root).parent
        if stale_parent.is_dir():
            for original in sorted(stale_parent.iterdir()):
                if original.is_file() and path.stem.startswith(original.stem):
                    results.append((f"{original.name} (original)", original))
    return results


def _file_link(label: str, path: Path) -> str:
    return f"[{label}](/gradio_api/file={path.resolve()})"


def render_findings_md(report: FinalReport, build_report: BuildReport, root: Path) -> str:
    """Confirmed findings with source-file links, as one Markdown document."""
    if not report.confirmed:
        return "No confirmed findings."
    sections: list[str] = []
    for index, verified in enumerate(report.confirmed, start=1):
        finding = verified.finding
        amount = f" — EUR {finding.amount_eur:,.2f}" if finding.amount_eur is not None else ""
        lines = [
            f"### {index}. [{finding.check}] {finding.category}{amount}",
            "",
            finding.evidence_summary,
            "",
            f"**Entities:** {', '.join(finding.primary_entities) or '—'}  ",
            f"**Period:** {finding.period or '—'}  ",
            f"**Confidence:** {finding.confidence}",
        ]
        if verified.verifier_notes:
            lines += ["", f"**Verifier notes:** {verified.verifier_notes}"]
        try:
            sources = source_files_for_finding(finding, build_report, root)
        except OSError:
            sources = []
        if sources:
            links = " · ".join(_file_link(label, path) for label, path in sources)
            lines += ["", f"**Source files:** {links}"]
        else:
            lines += ["", "**Source files:** could not be resolved for this finding."]
        sections.append("\n".join(lines))
    return "\n\n---\n\n".join(sections)


def evidence_rows(
    run_dir: Path, sql: str, limit: int = 50
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Re-run one evidence SQL statement read-only; returns (columns, rows)."""
    if _WRITE_SQL.search(sql):
        raise ValueError("Only read-only SELECT statements can be replayed.")
    with duckdb.connect(str(run_dir / DB_FILENAME), read_only=True) as conn:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(limit)
    return columns, rows
