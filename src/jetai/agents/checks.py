"""Check agents: one generic runner + declarative specs.

Adding a check is adding a :class:`CheckSpec`. Briefs are generic audit logic
— they describe *what kind* of pattern to find, never which record to find.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

from jetai.agents.build import DB_FILENAME
from jetai.agents.config import AgentSettings
from jetai.agents.models import AuditContext, FindingsReport
from jetai.agents.runner import run_structured_agent
from jetai.agents.tools import make_execute_sql_tool, make_schema_tool
from jetai.agents.tracing import JsonlTracer

FINDINGS_DIRNAME = "findings"


@dataclass(frozen=True)
class CheckSpec:
    name: str
    required_views: tuple[str, ...]
    brief: str


CHECK_SPECS: dict[str, CheckSpec] = {
    spec.name: spec
    for spec in (
        CheckSpec(
            name="three_way_match",
            required_views=("three_way_match", "dim_vendor"),
            brief="""Perform a three-way match on the vendor invoices \
(view `three_way_match`: one row per invoice with aggregated payments and \
goods receipts; NULL receipt columns mean no receipt exists).
Look for:
- invoices that were PAID but have no goods receipt at all (services or goods \
never evidenced as delivered), especially round amounts and vaguely described \
services;
- material mismatches between invoice, payment and receipt amounts;
- for suspicious vendors, cross-check the vendor's master data: when was the \
vendor created (`master_data_changes`), who created and who approved it, and \
which users booked and paid the postings (`vendor_postings`, `gl_postings`, \
`dim_user` rights). A new vendor + no receipts + one user doing create/book/pay \
is the classic shell-vendor pattern.
Aggregate by vendor before drilling into single invoices.""",
        ),
        CheckSpec(
            name="cutoff",
            required_views=("gl_postings",),
            brief="""Test period cut-off around the fiscal year end.
Look for:
- next-period vendor invoices (`late_vendor_invoices`) whose service date lies \
in the audit year: was a matching accrual/provision posted in the audit year \
(`gl_postings`)? Invoiced-in-January December costs without an accrual \
overstate profit;
- goods received before year end (`goods_receipts`) with the invoice still \
open and no accrual;
- next-period postings (`next_period_postings`) that economically belong to \
the audit year;
- distinguish carefully: legitimate accruals for unbilled year-end work DO \
exist — the anomaly is the specific items with no accrual, not year-end \
accruals in general.""",
        ),
        CheckSpec(
            name="account_classification",
            required_views=("dim_asset", "gl_postings"),
            brief="""Test whether expense-like items were capitalized as assets.
Look for:
- asset records (`dim_asset`, `asset_postings`) whose NAMES read like repairs \
or maintenance (repair/replacement/overhaul wording in the dataset's language) \
rather than acquisitions of new assets;
- their acquisition postings going to balance-sheet asset accounts instead of \
a repair/maintenance expense account (use account NAMES and types from \
`dim_account` to identify both sides — never assume specific account numbers);
- genuinely new machines/equipment with proper investment documentation are \
NOT findings. Capitalized repairs overstate profit and assets.""",
        ),
        CheckSpec(
            name="split_payments",
            required_views=("journal",),
            brief="""Test for payments split to stay under the approval threshold.
Look for:
- multiple same-day payments to the SAME payee, each individually below the \
approval threshold (see audit context), that together exceed it — classic \
threshold splitting. Group payments by payee and date, sum, and compare \
against the threshold;
- collective/batch document numbers or sequential documents are corroborating \
evidence. A single payment just under the threshold is not a finding; the \
pattern of several the same day is.""",
        ),
        CheckSpec(
            name="four_eyes",
            required_views=("approval_log", "master_data_changes"),
            brief="""Test the four-eyes principle and segregation of duties.
Look for:
- journal batches (`approval_log`) where the creator and the approver are the \
same user, or approvals that are missing entirely;
- master data changes (`master_data_changes`) — especially vendor creations \
and bank data changes — where changed_by equals approved_by or approval is \
missing;
- users (`dim_user`) whose combined rights break segregation of duties \
(e.g. one user able to create vendors AND post AND run payments), and whether \
those users actually exercised the combination (`journal`).""",
        ),
    )
}


def run_check_agent(
    settings: AgentSettings,
    spec: CheckSpec,
    context: AuditContext,
    run_dir: Path,
) -> FindingsReport:
    """Run one check agent read-only and write ``findings/<name>.json``."""
    db_path = run_dir / DB_FILENAME
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent=f"check:{spec.name}")
    brief = f"""You are an audit check agent. Work exclusively on the canonical \
DuckDB views (inspect_schema first; the database is read-only).

CHECK: {spec.name}
{spec.brief}

AUDIT CONTEXT:
{context.model_dump_json(indent=2)}

Rules for findings:
- cite the exact SQL you ran as evidence_sql and summarize the result;
- name the accused accounts/documents/users in primary_entities (bare \
identifiers, e.g. an account number or user id);
- report facts and patterns with amounts and periods; note the checked \
population and any limitations;
- ignore amounts below the trivial threshold unless they are part of a \
pattern; do not pad the report — no finding is a valid result."""
    with duckdb.connect(str(db_path), read_only=True) as conn:
        report = run_structured_agent(
            settings=settings,
            name=f"check:{spec.name}",
            brief=brief,
            tools=[make_execute_sql_tool(conn), make_schema_tool(conn)],
            response_format=FindingsReport,
            tracer=tracer,
        )
    report.check = spec.name
    for finding in report.findings:
        finding.check = spec.name
    findings_dir = run_dir / FINDINGS_DIRNAME
    findings_dir.mkdir(exist_ok=True)
    (findings_dir / f"{spec.name}.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    return report


def load_findings(run_dir: Path) -> list[FindingsReport]:
    findings_dir = run_dir / FINDINGS_DIRNAME
    if not findings_dir.is_dir():
        return []
    return [
        FindingsReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(findings_dir.glob("*.json"))
    ]
