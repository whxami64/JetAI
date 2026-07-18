"""Build agent: load discovered sources into DuckDB and produce the canonical views.

The canonical schema is the one choke point where dataset variation is
absorbed: view and column *names* are fixed here, the *sources* feeding them
are discovered by the agent from the profile. Exact SQL is the agent's call.
Afterwards the build is verified deterministically — the supervisor sees
measured results, never the agent's claims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from jetai.agents.config import AgentSettings
from jetai.agents.models import (
    AuditContext,
    BuildAgentSummary,
    BuildReport,
    DatasetProfile,
    ViewCheck,
)
from jetai.agents.runner import run_structured_agent
from jetai.agents.tools import (
    make_execute_sql_tool,
    make_list_sources_tool,
    make_read_head_tool,
    make_schema_tool,
)
from jetai.agents.tracing import JsonlTracer

DB_FILENAME = "audit.duckdb"


@dataclass(frozen=True)
class CanonicalColumn:
    name: str
    kind: str  # "text" | "date" | "number"
    required: bool = False  # NULLs in a required column are a recorded defect


# fmt: off
CANONICAL_SCHEMA: dict[str, tuple[CanonicalColumn, ...]] = {
    "dim_vendor": (
        CanonicalColumn("vendor_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("vat_id", "text"),
        CanonicalColumn("city", "text"), CanonicalColumn("country", "text"),
        CanonicalColumn("vendor_group", "text"),
    ),
    "dim_customer": (
        CanonicalColumn("customer_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("vat_id", "text"),
        CanonicalColumn("customer_group", "text"),
    ),
    "dim_account": (
        CanonicalColumn("account_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("account_type", "text"),
    ),
    "dim_asset": (
        CanonicalColumn("asset_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("asset_group", "text"),
        CanonicalColumn("asset_type", "text"), CanonicalColumn("status", "text"),
    ),
    "dim_user": (
        CanonicalColumn("user_id", "text", required=True),
        CanonicalColumn("department", "text"),
        CanonicalColumn("can_post", "text"), CanonicalColumn("can_approve", "text"),
        CanonicalColumn("can_run_payments", "text"),
        CanonicalColumn("can_create_vendor", "text"),
    ),
    "vendor_postings": (
        CanonicalColumn("vendor_id", "text", required=True),
        CanonicalColumn("posting_date", "date", required=True),
        CanonicalColumn("document_date", "date"),
        CanonicalColumn("document_number", "text"),
        CanonicalColumn("posting_type", "text"), CanonicalColumn("text", "text"),
        CanonicalColumn("amount", "number", required=True),
        CanonicalColumn("currency", "text"), CanonicalColumn("entry_id", "text"),
    ),
    "customer_postings": (
        CanonicalColumn("customer_id", "text", required=True),
        CanonicalColumn("posting_date", "date", required=True),
        CanonicalColumn("document_date", "date"),
        CanonicalColumn("document_number", "text"),
        CanonicalColumn("posting_type", "text"), CanonicalColumn("text", "text"),
        CanonicalColumn("amount", "number", required=True),
        CanonicalColumn("currency", "text"), CanonicalColumn("entry_id", "text"),
    ),
    "gl_postings": (
        CanonicalColumn("account", "text", required=True),
        CanonicalColumn("posting_date", "date", required=True),
        CanonicalColumn("document_date", "date"),
        CanonicalColumn("document_number", "text"),
        CanonicalColumn("posting_type", "text"), CanonicalColumn("text", "text"),
        CanonicalColumn("amount", "number", required=True),
        CanonicalColumn("currency", "text"),
        CanonicalColumn("counter_account", "text"),
        CanonicalColumn("user_id", "text"), CanonicalColumn("entry_id", "text"),
        CanonicalColumn("entry_date", "date"), CanonicalColumn("entry_time", "text"),
        CanonicalColumn("journal_line", "text"), CanonicalColumn("finalized", "text"),
    ),
    "asset_postings": (
        CanonicalColumn("asset_id", "text", required=True),
        CanonicalColumn("posting_date", "date"),
        CanonicalColumn("document_number", "text"),
        CanonicalColumn("posting_type", "text"), CanonicalColumn("text", "text"),
        CanonicalColumn("amount", "number", required=True),
        CanonicalColumn("asset_group", "text"),
    ),
    "goods_receipts": (
        CanonicalColumn("receipt_id", "text"),
        CanonicalColumn("receipt_date", "date", required=True),
        CanonicalColumn("invoice_number", "text"),
        CanonicalColumn("vendor_id", "text", required=True),
        CanonicalColumn("vendor_name", "text"),
        CanonicalColumn("amount", "number"), CanonicalColumn("note", "text"),
    ),
    "goods_issues": (
        CanonicalColumn("issue_id", "text"),
        CanonicalColumn("issue_date", "date", required=True),
        CanonicalColumn("invoice_number", "text"),
        CanonicalColumn("customer_id", "text", required=True),
        CanonicalColumn("customer_name", "text"),
        CanonicalColumn("amount", "number"), CanonicalColumn("note", "text"),
    ),
    "sales_invoices": (
        CanonicalColumn("invoice_number", "text", required=True),
        CanonicalColumn("customer_id", "text"),
        CanonicalColumn("customer_name", "text"),
        CanonicalColumn("invoice_date", "date"),
        CanonicalColumn("service_date", "date"),
        CanonicalColumn("amount", "number"), CanonicalColumn("kind", "text"),
        CanonicalColumn("note", "text"),
    ),
    "late_vendor_invoices": (
        CanonicalColumn("invoice_number", "text", required=True),
        CanonicalColumn("vendor_id", "text"),
        CanonicalColumn("vendor_name", "text"),
        CanonicalColumn("invoice_date", "date"),
        CanonicalColumn("service_date", "date"),
        CanonicalColumn("amount", "number"), CanonicalColumn("note", "text"),
    ),
    "next_period_postings": (
        CanonicalColumn("posting_date", "date", required=True),
        CanonicalColumn("document_number", "text"),
        CanonicalColumn("customer_id", "text"),
        CanonicalColumn("customer_name", "text"),
        CanonicalColumn("amount", "number"),
        CanonicalColumn("counter_account", "text"), CanonicalColumn("text", "text"),
    ),
    "approval_log": (
        CanonicalColumn("entry_id", "text", required=True),
        CanonicalColumn("journal_name", "text"),
        CanonicalColumn("creator", "text"), CanonicalColumn("entry_date", "date"),
        CanonicalColumn("entry_time", "text"),
        CanonicalColumn("approver", "text"),
        CanonicalColumn("approval_date", "date"),
        CanonicalColumn("approval_status", "text"),
        CanonicalColumn("total_abs_eur", "number"),
    ),
    "master_data_changes": (
        CanonicalColumn("change_date", "date", required=True),
        CanonicalColumn("account_type", "text"),
        CanonicalColumn("account_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("field", "text"),
        CanonicalColumn("old_value", "text"), CanonicalColumn("new_value", "text"),
        CanonicalColumn("changed_by", "text"),
        CanonicalColumn("approved_by", "text"), CanonicalColumn("approved", "text"),
    ),
    "open_items_ap": (
        CanonicalColumn("account_id", "text", required=True),
        CanonicalColumn("name", "text"),
        CanonicalColumn("balance", "number", required=True),
    ),
    "open_items_ar": (
        CanonicalColumn("account_id", "text", required=True),
        CanonicalColumn("name", "text"),
        CanonicalColumn("balance", "number", required=True),
    ),
    "trial_balance": (
        CanonicalColumn("account_id", "text", required=True),
        CanonicalColumn("name", "text"), CanonicalColumn("account_type", "text"),
        CanonicalColumn("closing_balance", "number"),
        CanonicalColumn("opening_balance", "number"),
        CanonicalColumn("debit", "number"), CanonicalColumn("credit", "number"),
        CanonicalColumn("year", "text"),
    ),
    "journal": (
        CanonicalColumn("source_ledger", "text", required=True),
        CanonicalColumn("account", "text"),
        CanonicalColumn("counter_account", "text"),
        CanonicalColumn("posting_date", "date", required=True),
        CanonicalColumn("document_date", "date"),
        CanonicalColumn("document_number", "text"), CanonicalColumn("text", "text"),
        CanonicalColumn("amount", "number", required=True),
        CanonicalColumn("currency", "text"),
        CanonicalColumn("user_id", "text"), CanonicalColumn("entry_id", "text"),
    ),
    "three_way_match": (
        CanonicalColumn("vendor_id", "text", required=True),
        CanonicalColumn("vendor_name", "text"),
        CanonicalColumn("invoice_number", "text", required=True),
        CanonicalColumn("invoice_date", "date"),
        CanonicalColumn("invoice_amount", "number"),
        CanonicalColumn("paid_amount", "number"),
        CanonicalColumn("payment_count", "number"),
        CanonicalColumn("receipt_amount", "number"),
        CanonicalColumn("receipt_count", "number"),
        CanonicalColumn("first_receipt_date", "date"),
    ),
}
# fmt: on


def _schema_spec() -> str:
    lines = []
    for view, columns in CANONICAL_SCHEMA.items():
        rendered = ", ".join(
            f"{c.name} {c.kind.upper()}{' NOT NULL' if c.required else ''}" for c in columns
        )
        lines.append(f"- {view}({rendered})")
    return "\n".join(lines)


_BRIEF = """You are the database builder for a journal-entry-testing audit. \
Load the profiled source files into DuckDB and produce the CANONICAL VIEWS below. \
Downstream check agents only ever see these views, so their names and column \
names must match exactly. Source files, layouts and column names vary by \
accounting software — map whatever the profile shows into the canonical shape.

CANONICAL VIEWS (create every one whose source data exists; skip a view only \
when the dataset has no source for it):
{schema}

Semantics:
- journal = UNION ALL of all posting ledgers (GL, vendor, customer, asset) on \
the common column set, source_ledger naming the origin.
- three_way_match: one row per vendor INVOICE (not payment), LEFT JOINed with \
aggregated payments for the same vendor/document and aggregated goods receipts \
for the same invoice/vendor. Purely factual: NULL receipt columns simply mean \
no receipt exists. No judgment here.
- dim_user comes from a rights/permissions matrix if one exists; map its right \
columns onto can_post / can_approve / can_run_payments / can_create_vendor.

PROFILE OF THE SOURCE FILES (detected facts, not guesses — trust these formats):
{digest}

Fiscal year end: {fiscal_year_end}

Method:
1. Load each relevant file with read_csv: pass delim, header=true, \
skip=<header_row from the profile> (the row index given IS the number of lines \
to skip before the header), and all_varchar=true. Build raw tables first.
2. Create typed base tables: cast dates with try_strptime(col, '<detected format>') \
and numbers per the detected decimal style (german: replace('.','') then \
replace(',','.') then TRY_CAST; english: strip ',' then TRY_CAST). For columns \
flagged !mixed, combine try_strptime attempts with COALESCE.
3. Create the canonical views on top. Missing source columns: emit NULL and \
list them in `unmapped`.
4. Verify your own work with quick counts before answering.

Answer with: mapping (canonical view.column -> source file/column), unmapped, \
and notes on anything a check agent should know."""


def _table_digest(profile: DatasetProfile) -> str:
    lines = []
    for file in profile.files:
        if file.kind != "table":
            continue
        lines.append(
            f"## {file.path} [{file.rows} rows, delim={file.delimiter!r}, "
            f"header_row={file.header_row}, encoding={file.encoding}]"
        )
        if file.description:
            lines.append(f"about: {file.description}")
        rendered = []
        for column in file.columns:
            fmt = column.date_format or column.decimal_style or ""
            flags = "".join(
                flag
                for flag, on in (("!mixed", column.mixed), ("?ambiguous", column.ambiguous))
                if on
            )
            rendered.append(
                f"{column.name}({column.inferred_type}{' ' + fmt if fmt else ''}{flags})"
            )
        lines.append("columns: " + ", ".join(rendered))
        if file.quality_notes:
            lines.append("notes: " + "; ".join(file.quality_notes))
    return "\n".join(lines)


def _fiscal_window(context: AuditContext) -> tuple[date, date] | None:
    try:
        year = int(context.fiscal_year_end[:4])
    except (ValueError, IndexError):
        return None
    return date(year - 1, 1, 1), date(year + 1, 12, 31)


def verify_build(db_path: Path, context: AuditContext) -> list[ViewCheck]:
    """Deterministic post-build verification; never trusts the agent's claims."""
    checks: list[ViewCheck] = []
    window = _fiscal_window(context)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        existing = {
            row[0]
            for row in conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
        }
        for view, columns in CANONICAL_SCHEMA.items():
            if view not in existing:
                checks.append(ViewCheck(view=view, present=False))
                continue
            check = ViewCheck(view=view, present=True)
            check.row_count = conn.execute(f'SELECT count(*) FROM "{view}"').fetchone()[0]  # type: ignore[index]
            actual = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                    [view],
                ).fetchall()
            }
            for column in columns:
                if column.name not in actual:
                    if column.required:
                        check.null_defects[column.name] = check.row_count
                    continue
                if column.required and check.row_count:
                    nulls = conn.execute(
                        f'SELECT count(*) FROM "{view}" WHERE "{column.name}" IS NULL'
                    ).fetchone()[0]  # type: ignore[index]
                    if nulls:
                        check.null_defects[column.name] = nulls
                if column.kind == "date" and window and check.row_count:
                    low, high = conn.execute(
                        f'SELECT min("{column.name}"), max("{column.name}") '
                        f'FROM "{view}" WHERE "{column.name}" IS NOT NULL'
                    ).fetchone() or (None, None)
                    for bound in (low, high):
                        if bound is None:
                            continue
                        value = bound if isinstance(bound, date) else None
                        if value is not None and not (window[0] <= value <= window[1]):
                            check.date_range_defects.append(
                                f"{column.name} value {value} outside {window[0]}..{window[1]}"
                                " (possible day/month swap)"
                            )
                            break
            checks.append(check)
    return checks


def run_build_agent(
    settings: AgentSettings,
    root: Path,
    profile: DatasetProfile,
    context: AuditContext,
    run_dir: Path,
) -> BuildReport:
    """Run the build agent read-write, verify deterministically, write the report."""
    db_path = run_dir / DB_FILENAME
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent="build")
    conn = duckdb.connect(str(db_path))
    try:
        # DuckDB resolves relative paths against the process CWD, so give the
        # agent absolute paths via a working-directory hint instead.
        conn.execute(f"SET file_search_path = '{root.as_posix()}'")
        summary = run_structured_agent(
            settings=settings,
            name="build",
            brief=_BRIEF.format(
                schema=_schema_spec(),
                digest=_table_digest(profile),
                fiscal_year_end=context.fiscal_year_end or "unknown",
            ),
            tools=[
                make_execute_sql_tool(conn),
                make_schema_tool(conn),
                make_list_sources_tool(profile),
                make_read_head_tool(root),
            ],
            response_format=BuildAgentSummary,
            tracer=tracer,
        )
    finally:
        conn.close()

    checks = verify_build(db_path, context)
    report = BuildReport(
        canonical_views_present=[c.view for c in checks if c.present],
        canonical_views_missing=[c.view for c in checks if not c.present],
        view_checks=checks,
        mapping=summary.mapping,
        unmapped=summary.unmapped,
        notes=summary.notes,
    )
    (run_dir / "build_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def load_build_report(run_dir: Path) -> BuildReport:
    return BuildReport.model_validate(
        json.loads((run_dir / "build_report.json").read_text(encoding="utf-8"))
    )
