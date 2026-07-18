"""Shared pydantic models: agent response formats and run artifacts.

Every artifact an agent writes to the run directory is one of these models,
so downstream consumers (supervisor, verifier, evaluation) parse structured
data instead of prose.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    """Deterministically detected shape of one source column."""

    name: str
    inferred_type: str = "text"  # "date" | "datetime" | "time" | "number" | "integer" | "text"
    date_format: str | None = None  # strptime format, e.g. "%d.%m.%Y"
    decimal_style: str | None = None  # "german" | "english"
    mixed: bool = False  # >=2 incompatible formats genuinely present
    ambiguous: bool = False  # data cannot discriminate; style is a documented default
    note: str | None = None


class FileProfile(BaseModel):
    """Profile of one source file: deterministic shape + LLM annotations."""

    path: str  # relative to the dataset root
    kind: str  # "table" | "document"
    rows: int = 0
    header_row: int = 0  # 0-based row index holding the real header
    encoding: str = "utf-8"
    delimiter: str | None = None
    columns: list[ColumnProfile] = Field(default_factory=list)
    sample_rows: list[list[str]] = Field(default_factory=list)
    description: str = ""  # one sentence, filled by the profiling agent
    candidate_keys: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    """The full profile artifact (``profile.json``)."""

    root: str
    files: list[FileProfile] = Field(default_factory=list)


class FileAnnotation(BaseModel):
    """LLM-supplied annotation for one profiled file."""

    path: str
    description: str
    candidate_keys: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)


class DatasetAnnotations(BaseModel):
    """Response format of the profiling agent's single LLM pass."""

    files: list[FileAnnotation] = Field(default_factory=list)


class AuditContext(BaseModel):
    """Thresholds and rules extracted from the audit working papers."""

    client: str = ""
    fiscal_year_end: str = ""  # ISO date, e.g. "2025-12-31"
    approval_threshold_eur: float | None = None
    materiality_eur: float | None = None
    trivial_threshold_eur: float | None = None
    special_rules: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)


class BuildAgentSummary(BaseModel):
    """Response format of the build agent: what it mapped, not what it claims works."""

    mapping: dict[str, str] = Field(
        default_factory=dict,
        description="canonical view.column -> source file/column it was mapped from",
    )
    unmapped: list[str] = Field(
        default_factory=list,
        description="canonical columns left NULL because no source column matched",
    )
    notes: list[str] = Field(default_factory=list)


class ViewCheck(BaseModel):
    """Deterministic verification result for one canonical view."""

    view: str
    present: bool
    row_count: int = 0
    error: str | None = None  # the view exists but cannot be queried
    null_defects: dict[str, int] = Field(
        default_factory=dict,
        description="required column -> NULL count (nonzero means casts/mapping lost values)",
    )
    date_range_defects: list[str] = Field(
        default_factory=list,
        description="date columns whose min/max fall outside the fiscal year +/- 1 year",
    )


class BuildReport(BaseModel):
    """The build artifact (``build_report.json``): agent mapping + deterministic checks."""

    canonical_views_present: list[str] = Field(default_factory=list)
    canonical_views_missing: list[str] = Field(default_factory=list)
    view_checks: list[ViewCheck] = Field(default_factory=list)
    link_coverage: dict[str, float] = Field(
        default_factory=dict,
        description="cross-view key link -> fraction of left-side keys found on the right",
    )
    mapping: dict[str, str] = Field(default_factory=dict)
    unmapped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    LOW_LINK_COVERAGE: ClassVar[float] = 0.2

    @property
    def defects(self) -> list[str]:
        """Human-readable list of deterministic defects found after the build."""
        problems: list[str] = []
        for check in self.view_checks:
            if not check.present:
                continue
            if check.error:
                problems.append(f"{check.view}: unqueryable ({check.error})")
                continue
            if check.row_count == 0:
                problems.append(f"{check.view}: present but empty")
            for column, nulls in check.null_defects.items():
                problems.append(f"{check.view}.{column}: {nulls} NULLs in required column")
            for defect in check.date_range_defects:
                problems.append(f"{check.view}: {defect}")
        for link, coverage in self.link_coverage.items():
            if coverage < self.LOW_LINK_COVERAGE:
                problems.append(
                    f"link {link}: only {coverage:.0%} of keys match — likely a column mis-mapping"
                )
        return problems


class Finding(BaseModel):
    """One suspicion raised by a check agent, with citable evidence."""

    check: str
    category: str
    primary_entities: list[str] = Field(
        default_factory=list,
        description="account/document/user identifiers actually accused",
    )
    amount_eur: float | None = None
    period: str | None = None
    evidence_sql: list[str] = Field(default_factory=list)
    evidence_summary: str = ""
    confidence: str = "medium"  # "low" | "medium" | "high"


class FindingsReport(BaseModel):
    """Response format and artifact of one check agent (``findings/<check>.json``)."""

    check: str = ""
    findings: list[Finding] = Field(default_factory=list)
    checked_population: str = ""
    limitations: list[str] = Field(default_factory=list)


class VerifiedFinding(BaseModel):
    """A finding after verifier scrutiny."""

    finding: Finding
    verifier_notes: str = ""


class RejectedFinding(BaseModel):
    """A finding the verifier could not support, with the innocent explanation."""

    finding: Finding
    reason: str


class FinalReport(BaseModel):
    """Response format of the verifier and the run's final artifact (``report.json``)."""

    confirmed: list[VerifiedFinding] = Field(default_factory=list)
    rejected: list[RejectedFinding] = Field(default_factory=list)
    tie_outs: list[str] = Field(default_factory=list)
    summary: str = ""
