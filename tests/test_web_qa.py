"""Q&A tool behavior over a fabricated run directory (no API calls)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from jetai.agents.build import DB_FILENAME
from jetai.agents.models import FinalReport, Finding, RejectedFinding, VerifiedFinding
from jetai.web.qa import build_qa_tools


def _fake_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = [
        {
            "ts": "t",
            "agent": "supervisor",
            "event": "tool_start",
            "tool": "run_check",
            "input": "{'check_name': 'cutoff'}",
        },
        {
            "ts": "t",
            "agent": "check:cutoff",
            "event": "tool_start",
            "tool": "execute_sql",
            "input": "SELECT * FROM gl_postings",
        },
        {
            "ts": "t",
            "agent": "check:cutoff",
            "event": "llm_end",
            "completion": "done",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    ]
    with (run_dir / "traces.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    report = FinalReport(
        confirmed=[
            VerifiedFinding(
                finding=Finding(
                    check="cutoff",
                    category="missing accrual",
                    primary_entities=["RE-2026-001"],
                    amount_eur=9000.0,
                ),
                verifier_notes="Accrual absent in gl_postings.",
            )
        ],
        rejected=[
            RejectedFinding(
                finding=Finding(check="four_eyes", category="self approval"),
                reason="Approval log shows a second user.",
            )
        ],
        summary="One confirmed finding.",
    )
    (run_dir / "report.json").write_text(report.model_dump_json(indent=2))
    (run_dir / "report.md").write_text("# Audit findings report\n")
    with duckdb.connect(str(run_dir / DB_FILENAME)) as conn:
        conn.execute("CREATE TABLE gl_postings AS SELECT 1 AS doc_no")
    return run_dir


def _tools(run_dir: Path, conn: duckdb.DuckDBPyConnection) -> dict:
    return {t.name: t for t in build_qa_tools(run_dir, conn)}


def test_qa_tools_read_traces_and_artifacts(tmp_path: Path) -> None:
    run_dir = _fake_run_dir(tmp_path)
    with duckdb.connect(str(run_dir / DB_FILENAME), read_only=True) as conn:
        tools = _tools(run_dir, conn)

        summary = tools["summarize_run"].invoke({})
        assert "check:cutoff" in summary and "execute_sql" in summary

        filtered = tools["read_trace_events"].invoke({"agent": "check:cutoff"})
        assert filtered.startswith("2 matching events")
        assert "gl_postings" in filtered

        by_event = tools["read_trace_events"].invoke({"event": "llm_end"})
        assert by_event.startswith("1 matching events")

        findings = tools["list_findings"].invoke({})
        assert "confirmed #1: [cutoff]" in findings
        assert "rejected #1: [four_eyes]" in findings

        artifact = tools["read_artifact"].invoke({"name": "report.md"})
        assert artifact.startswith("# Audit findings report")
        assert "unknown artifact" in tools["read_artifact"].invoke({"name": "../evil"})
        assert "not produced" in tools["read_artifact"].invoke({"name": "profile.json"})

        rows = tools["execute_sql"].invoke({"query": "SELECT * FROM gl_postings"})
        assert "doc_no" in rows
