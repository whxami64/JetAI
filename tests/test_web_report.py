"""Finding→source-file link resolution and evidence replay for the web UI."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from jetai.agents.build import DB_FILENAME
from jetai.agents.models import (
    BuildReport,
    FinalReport,
    Finding,
    VerifiedFinding,
)
from jetai.web.report import (
    evidence_rows,
    findings_table,
    render_findings_md,
    source_files_for_finding,
    views_for_finding,
)


def _finding(**overrides: object) -> Finding:
    base: dict = {
        "check": "three_way_match",
        "category": "shell vendor",
        "primary_entities": ["70011"],
        "amount_eur": 12500.0,
        "evidence_sql": ["SELECT * FROM three_way_match WHERE vendor_id = '70011'"],
        "evidence_summary": "Paid invoices without goods receipts.",
        "confidence": "high",
    }
    base.update(overrides)
    return Finding(**base)


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    (root / "Kreditoren").mkdir(parents=True)
    (root / "Kreditoren" / "Lieferantenbuchungen.csv").write_text("a;b\n")
    (root / "stale" / "Kreditoren").mkdir(parents=True)
    (root / "stale" / "Kreditoren" / "Lieferantenbuchungen.txt").write_text("raw")
    return root


def test_views_for_finding_unions_spec_and_sql() -> None:
    finding = _finding(evidence_sql=["SELECT * FROM master_data_changes"])
    views = views_for_finding(finding)
    assert {"three_way_match", "dim_vendor", "master_data_changes"} <= views


def test_source_files_resolved_with_stale_original(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    build = BuildReport(
        mapping={"three_way_match.invoice_no": "Kreditoren/Lieferantenbuchungen.csv:Belegnr"}
    )
    sources = source_files_for_finding(_finding(), build, root)
    labels = [label for label, _ in sources]
    assert "Kreditoren/Lieferantenbuchungen.csv" in labels
    assert "Lieferantenbuchungen.txt (original)" in labels


def test_source_files_degrade_to_empty(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    build = BuildReport(mapping={"gl_postings.amount": "Sachkontobuchungen.csv:Betrag"})
    finding = _finding(check="unknown_check", evidence_sql=[])
    assert source_files_for_finding(finding, build, root) == []


def test_render_findings_md_links_and_fallback(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    build = BuildReport(
        mapping={"three_way_match.invoice_no": "Kreditoren/Lieferantenbuchungen.csv:Belegnr"}
    )
    report = FinalReport(
        confirmed=[
            VerifiedFinding(finding=_finding(), verifier_notes="Re-ran SQL, holds."),
            VerifiedFinding(finding=_finding(check="unknown", evidence_sql=[])),
        ]
    )
    md = render_findings_md(report, build, root)
    assert "/gradio_api/file=" in md
    assert "(original)" in md
    assert "could not be resolved" in md
    assert "Re-ran SQL, holds." in md


def test_findings_table_rows() -> None:
    report = FinalReport(confirmed=[VerifiedFinding(finding=_finding())])
    rows = findings_table(report)
    assert rows == [["three_way_match", "shell vendor", "70011", "12,500.00", "", "high"]]


def test_evidence_rows_read_only(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / DB_FILENAME)) as conn:
        conn.execute("CREATE TABLE t AS SELECT 1 AS a, 'x' AS b")
    columns, rows = evidence_rows(tmp_path, "SELECT * FROM t")
    assert columns == ["a", "b"]
    assert rows == [(1, "x")]
    with pytest.raises(ValueError, match="read-only"):
        evidence_rows(tmp_path, "DROP TABLE t")
