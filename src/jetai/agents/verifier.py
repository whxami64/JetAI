"""Verifier agent: re-probe every finding before it reaches the report.

Reads the check agents' findings files verbatim (structured, never supervisor
paraphrase), re-runs the cited evidence, actively looks for innocent
explanations, merges duplicates across checks, and produces the final report.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from jetai.agents.build import DB_FILENAME
from jetai.agents.checks import load_findings
from jetai.agents.config import AgentSettings
from jetai.agents.models import AuditContext, FinalReport
from jetai.agents.runner import run_structured_agent
from jetai.agents.tools import make_execute_sql_tool, make_schema_tool
from jetai.agents.tracing import JsonlTracer

_BRIEF = """You are the verification agent of a journal-entry-testing audit. \
The check agents raised the findings below. Your job is to decide, per finding, \
whether the evidence truly supports an accusation — an unsupported accusation \
is worse than a miss.

For every finding:
1. Re-run or probe the cited evidence_sql against the database (read-only) and \
confirm the numbers.
2. Actively look for the innocent explanation before confirming: proper \
four-eyes approvals, real goods receipts/deliveries, documented investment \
requests, disclosed related parties, revenue-neutral corrections, documented \
rebates. A pattern that LOOKS suspicious but has proper documentation and \
controls is CLEAN — reject it with the reason.
3. Merge duplicates: the same scheme surfacing in several checks becomes ONE \
confirmed finding (keep the union of primary_entities and the strongest \
evidence).
4. Check amounts against the trivial threshold in the audit context; drop \
immaterial isolated findings.
5. Where possible, tie confirmed totals out against independent sources in the \
database (open items, trial balance) and record those tie_outs.

AUDIT CONTEXT:
{context}

FINDINGS (verbatim from the check agents):
{findings}

Answer with confirmed findings (with your verifier notes), rejected findings
(with reasons), tie_outs, and a short overall summary."""


def render_report_md(report: FinalReport) -> str:
    lines = ["# Audit findings report", "", report.summary, ""]
    lines.append("## Confirmed findings")
    if not report.confirmed:
        lines.append("(none)")
    for item in report.confirmed:
        finding = item.finding
        amount = f" — EUR {finding.amount_eur:,.2f}" if finding.amount_eur else ""
        lines += [
            f"### [{finding.check}] {finding.category}{amount}",
            f"Entities: {', '.join(finding.primary_entities) or '-'}",
            f"Period: {finding.period or '-'} · Confidence: {finding.confidence}",
            "",
            finding.evidence_summary,
            "",
        ]
        if item.verifier_notes:
            lines += [f"*Verifier:* {item.verifier_notes}", ""]
        if finding.evidence_sql:
            lines += ["```sql", *finding.evidence_sql, "```", ""]
    lines.append("## Rejected findings")
    if not report.rejected:
        lines.append("(none)")
    for rejected in report.rejected:
        lines.append(
            f"- [{rejected.finding.check}] {rejected.finding.category} "
            f"({', '.join(rejected.finding.primary_entities) or '-'}): {rejected.reason}"
        )
    if report.tie_outs:
        lines += ["", "## Tie-outs", *[f"- {t}" for t in report.tie_outs]]
    return "\n".join(lines) + "\n"


def run_verifier_agent(
    settings: AgentSettings, context: AuditContext, run_dir: Path
) -> FinalReport:
    """Verify all findings and write ``report.json`` + ``report.md``."""
    findings = load_findings(run_dir)
    if not findings:
        raise FileNotFoundError(f"No findings files under {run_dir}/findings; run checks first.")
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent="verifier")
    findings_blob = "\n\n".join(report.model_dump_json(indent=2) for report in findings)
    with duckdb.connect(str(run_dir / DB_FILENAME), read_only=True) as conn:
        report = run_structured_agent(
            settings=settings,
            name="verifier",
            brief=_BRIEF.format(context=context.model_dump_json(indent=2), findings=findings_blob),
            tools=[make_execute_sql_tool(conn), make_schema_tool(conn)],
            response_format=FinalReport,
            tracer=tracer,
            recursion_limit=50,
        )
    (run_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")
    return report


def load_report(run_dir: Path) -> FinalReport:
    return FinalReport.model_validate(
        json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    )
