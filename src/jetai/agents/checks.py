"""Check agents: one generic runner + declarative specs.

Adding a check is adding a :class:`CheckSpec`. Briefs are generic audit logic
— they describe *what kind* of pattern to find, never which record to find.

``required_views`` are the minimum for the check to be meaningful at all;
``optional_views`` enrich it. The runner tells the agent which optional
evidence exists so a missing source degrades the check instead of killing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from jetai.agents.build import DB_FILENAME
from jetai.agents.config import AgentSettings
from jetai.agents.models import AuditContext, DatasetProfile, FindingsReport
from jetai.agents.runner import run_structured_agent
from jetai.agents.tools import (
    make_execute_sql_tool,
    make_list_sources_tool,
    make_read_markdown_tool,
    make_schema_tool,
)
from jetai.agents.tracing import JsonlTracer

FINDINGS_DIRNAME = "findings"


@dataclass(frozen=True)
class CheckSpec:
    name: str
    required_views: tuple[str, ...]
    brief: str
    optional_views: tuple[str, ...] = field(default=())


CHECK_SPECS: dict[str, CheckSpec] = {
    spec.name: spec
    for spec in (
        CheckSpec(
            name="three_way_match",
            required_views=("vendor_postings", "dim_vendor"),
            optional_views=(
                "three_way_match",
                "goods_receipts",
                "master_data_changes",
                "dim_user",
                "gl_postings",
            ),
            brief="""Perform a payment/invoice/receipt match on the vendor side.

FULL MODE (when the `three_way_match` view exists — one row per invoice with \
aggregated payments and goods receipts; NULL receipt columns mean no receipt \
exists): look for invoices that were PAID but have no goods receipt at all \
(services or goods never evidenced as delivered), especially round amounts and \
vaguely described services; and for material mismatches between invoice, \
payment and receipt amounts.

DEGRADED MODE (no goods-receipt data in this dataset): fall back to a two-way \
match on `vendor_postings` — payments without a matching invoice, duplicate \
payments for one document, round-amount invoices with vague service texts, new \
vendors receiving unusually fast or large payments — and look for SUBSTITUTE \
delivery evidence: posting texts referencing deliveries, machine-generated \
origin markers that distinguish interface postings from manual ones, and \
open-item aging. State explicitly in the findings that receipt data was \
unavailable and the evidence level is reduced.

In both modes, cross-check suspicious vendors' master data where available: \
when was the vendor created (`master_data_changes`), who created and who \
approved it, and which users booked and paid the postings (`gl_postings`, \
`dim_user` rights). A new vendor + no delivery evidence + one user doing \
create/book/pay is the classic shell-vendor pattern. Aggregate by vendor \
before drilling into single invoices.""",
        ),
        CheckSpec(
            name="cutoff",
            required_views=("gl_postings",),
            optional_views=(
                "late_vendor_invoices",
                "late_customer_invoices",
                "next_period_postings",
                "goods_receipts",
                "goods_issues",
                "sales_invoices",
                "customer_postings",
            ),
            brief="""Test period cut-off around the fiscal year end — BOTH directions.

Expense side (understated liabilities → overstated profit):
- next-period vendor invoices (`late_vendor_invoices`) whose service date lies \
in the audit year: was a matching accrual/provision posted in the audit year \
(`gl_postings`)?
- goods received before year end (`goods_receipts`) with the invoice still \
open and no accrual.

Revenue side (premature or shifted revenue):
- goods issued/delivered near year end (`goods_issues`) invoiced only in the \
next period (`late_customer_invoices`, `sales_invoices`) or vice versa: \
revenue invoiced in the audit year for deliveries that happened after \
year end;
- invoices whose service date and invoice date fall in different fiscal years;
- bill-and-hold or similar arrangements: revenue recognized while goods never \
left the premises — check source documents for such agreements.

Also probe `next_period_postings` for items economically belonging to the \
audit year. Distinguish carefully: legitimate accruals for unbilled year-end \
work DO exist — the anomaly is the specific items with no accrual, not \
year-end accruals in general.""",
        ),
        CheckSpec(
            name="account_classification",
            required_views=("dim_asset", "gl_postings"),
            optional_views=("asset_postings", "dim_account", "vendor_postings"),
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
            optional_views=("vendor_postings", "dim_vendor", "approval_log"),
            brief="""Test for payments split to stay under an approval threshold.
Look for:
- multiple same-day payments to the SAME payee, each individually below the \
approval threshold (see audit context), that together exceed it — classic \
threshold splitting. Group payments by payee and date, sum, and compare \
against the threshold;
- if the audit context has NO explicit payment threshold, derive candidate \
thresholds from the data: clusters of same-payee same-day payments just under \
a round number (e.g. many payments at 9,x00 under 10,000) are the signature \
regardless of the documented limit;
- collective/batch document numbers or sequential documents are corroborating \
evidence. A single payment just under a threshold is not a finding; the \
pattern of several the same day is.""",
        ),
        CheckSpec(
            name="four_eyes",
            required_views=("approval_log",),
            optional_views=("master_data_changes", "dim_user", "journal"),
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
        CheckSpec(
            name="journal_anomalies",
            required_views=("journal",),
            optional_views=("gl_postings", "approval_log", "dim_account", "trial_balance"),
            brief="""Test the journal against the audit context's OWN risk criteria.

The audit context's `special_rules` list contains the selection criteria and \
control rules the auditors documented for THIS engagement. Go through them one \
by one, decide which are testable against the canonical views, and run each \
testable rule as a query (examples of typically testable rules: postings \
outside business hours or on weekends, postings after a lock/closing date, \
long lags between posting date and entry date, round amounts above a \
threshold, postings by specific user groups, rarely-used accounts, missing or \
unusual posting texts, revenue posted directly against cash/bank, accounts \
singled out for full review).

Report one finding per rule that produces exceptions, naming the rule, the \
exception count, the total amount and the most material examples. Note the \
rules you could NOT test and why in `limitations`. Do not invent rules that \
are not in the audit context.""",
        ),
    )
}


def _existing_views(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }


def run_check_agent(
    settings: AgentSettings,
    spec: CheckSpec,
    context: AuditContext,
    run_dir: Path,
    root: Path,
    profile: DatasetProfile,
) -> FindingsReport:
    """Run one check agent read-only and write ``findings/<name>.json``."""
    db_path = run_dir / DB_FILENAME
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent=f"check:{spec.name}")
    with duckdb.connect(str(db_path), read_only=True) as conn:
        existing = _existing_views(conn)
        available = [v for v in spec.optional_views if v in existing]
        missing = [v for v in spec.optional_views if v not in existing]
        brief = f"""You are an audit check agent. Work primarily on the canonical \
DuckDB views (inspect_schema first; the database is read-only). You may also \
consult the dataset's source documents (list_sources, read_markdown) when a \
finding needs documentary context — agreements, working papers, protocols.

CHECK: {spec.name}
{spec.brief}

OPTIONAL EVIDENCE AVAILABLE IN THIS DATASET: {", ".join(available) or "(none)"}
OPTIONAL EVIDENCE MISSING IN THIS DATASET: {", ".join(missing) or "(none)"} — \
adapt to what exists instead of giving up; note reduced evidence in findings.

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
        report = run_structured_agent(
            settings=settings,
            name=f"check:{spec.name}",
            brief=brief,
            tools=[
                make_execute_sql_tool(conn),
                make_schema_tool(conn),
                make_list_sources_tool(profile),
                make_read_markdown_tool(root),
            ],
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
