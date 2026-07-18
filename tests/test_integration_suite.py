"""Integration tests: real agents against the real dataset (needs OPENAI_API_KEY).

Run explicitly with ``pytest -m integration``. The repo dataset is copied to a
temp directory first, so the working tree is never mutated.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from jetai.agents.audit_context import run_audit_context_agent
from jetai.agents.build import DB_FILENAME, run_build_agent
from jetai.agents.checks import CHECK_SPECS, run_check_agent
from jetai.agents.config import AgentSettings
from jetai.agents.models import (
    AuditContext,
    BuildReport,
    DatasetProfile,
    Finding,
    FindingsReport,
)
from jetai.agents.profiling import run_profiling_agent
from jetai.agents.supervisor import run_supervisor
from jetai.agents.verifier import load_report, run_verifier_agent
from jetai.dataset import find_dataset_root
from jetai.evaluation import load_ground_truth, score_report
from jetai.preprocess import preprocess_dataset

_REPO = Path(__file__).parent.parent
_GROUND_TRUTH = _REPO / "eval" / "ground_truth.json"
_ALT_DATASET = Path(__file__).parent / "fixtures" / "alt_dataset"


def _configured() -> bool:
    try:
        AgentSettings()  # type: ignore[call-arg]
        return True
    except ValidationError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _configured(), reason="OPENAI_API_KEY not configured"),
]


@pytest.fixture(scope="module")
def settings() -> AgentSettings:
    return AgentSettings()  # type: ignore[call-arg]


@pytest.fixture(scope="module")
def dataset_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("dataset")
    shutil.copytree(_REPO / "data", target / "data")
    root = find_dataset_root(target / "data")
    preprocess_dataset(root)
    return root


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("run")


@pytest.fixture(scope="module")
def profile(settings: AgentSettings, dataset_root: Path, run_dir: Path) -> DatasetProfile:
    return run_profiling_agent(settings, dataset_root, run_dir)


@pytest.fixture(scope="module")
def audit_ctx(
    settings: AgentSettings, dataset_root: Path, profile: DatasetProfile, run_dir: Path
) -> AuditContext:
    return run_audit_context_agent(settings, dataset_root, profile, run_dir)


@pytest.fixture(scope="module")
def build_report(
    settings: AgentSettings,
    dataset_root: Path,
    profile: DatasetProfile,
    audit_ctx: AuditContext,
    run_dir: Path,
) -> BuildReport:
    return run_build_agent(settings, dataset_root, profile, audit_ctx, run_dir)


def test_profiler_describes_every_file(profile: DatasetProfile) -> None:
    assert profile.files
    undescribed = [f.path for f in profile.files if not f.description]
    assert not undescribed


def test_audit_context_extracts_thresholds(audit_ctx: AuditContext) -> None:
    assert audit_ctx.approval_threshold_eur == 10000
    assert audit_ctx.materiality_eur == 400000
    assert audit_ctx.fiscal_year_end.startswith("2025")


def test_build_produces_three_way_match(build_report: BuildReport, run_dir: Path) -> None:
    assert "three_way_match" in build_report.canonical_views_present
    with duckdb.connect(str(run_dir / DB_FILENAME), read_only=True) as conn:
        rows = conn.execute("SELECT count(*) FROM three_way_match").fetchone()
        receiptless = conn.execute(
            "SELECT count(*) FROM three_way_match WHERE receipt_count IS NULL"
        ).fetchone()
    assert rows is not None and 2000 <= rows[0] <= 3200
    assert receiptless is not None and receiptless[0] > 0


def test_checks_verifier_and_eval_scorecard(
    settings: AgentSettings,
    build_report: BuildReport,
    audit_ctx: AuditContext,
    run_dir: Path,
) -> None:
    for name in sorted(CHECK_SPECS):
        report = run_check_agent(settings, CHECK_SPECS[name], audit_ctx, run_dir)
        assert report.check == name
    final = run_verifier_agent(settings, audit_ctx, run_dir)
    assert final.confirmed

    card = score_report(final, load_ground_truth(_GROUND_TRUTH))
    by_id = {r.id: r for r in card.expected}
    assert by_id["F1"].caught, "the shell-vendor scheme must be caught"
    assert card.decoys_accused == 0, "the honest-twin decoys must survive verification"


def test_verifier_keeps_true_and_drops_unsupported(
    settings: AgentSettings,
    build_report: BuildReport,
    audit_ctx: AuditContext,
    run_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    planted_dir = tmp_path_factory.mktemp("planted-run")
    shutil.copy(run_dir / DB_FILENAME, planted_dir / DB_FILENAME)
    (planted_dir / "findings").mkdir()
    planted = FindingsReport(
        check="three_way_match",
        findings=[
            Finding(
                check="three_way_match",
                category="paid invoices without goods receipt",
                primary_entities=["209101"],
                evidence_sql=[
                    "SELECT vendor_id, count(*), sum(invoice_amount) FROM three_way_match "
                    "WHERE receipt_count IS NULL AND paid_amount IS NOT NULL "
                    "GROUP BY vendor_id ORDER BY 3 DESC"
                ],
                evidence_summary="Vendor 209101: five paid invoices, no goods receipts.",
                confidence="high",
            ),
            Finding(
                check="three_way_match",
                category="paid invoices without goods receipt",
                primary_entities=["209112"],
                evidence_sql=[],
                evidence_summary=(
                    "Vendor 209112 is newly created mid-year and therefore a shell vendor."
                ),
                confidence="low",
            ),
        ],
        checked_population="all vendor invoices",
    )
    (planted_dir / "findings" / "three_way_match.json").write_text(
        planted.model_dump_json(indent=2), encoding="utf-8"
    )

    final = run_verifier_agent(settings, audit_ctx, planted_dir)
    confirmed_entities = [
        e for item in final.confirmed for e in item.finding.primary_entities
    ]
    rejected_entities = [
        e for item in final.rejected for e in item.finding.primary_entities
    ]
    assert any("209101" in e for e in confirmed_entities)
    assert any("209112" in e for e in rejected_entities)
    assert not any("209112" in e for e in confirmed_entities)


def test_alt_dataset_generalization(
    settings: AgentSettings, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A different accounting software: English names, headers, ISO dates,
    decimal points. Profile -> build -> three_way_match must flag the planted
    paid-but-never-delivered invoice."""
    dataset = tmp_path_factory.mktemp("alt") / "alt_dataset"
    shutil.copytree(_ALT_DATASET, dataset)
    alt_run = tmp_path_factory.mktemp("alt-run")

    profile = run_profiling_agent(settings, dataset, alt_run)
    assert {f.path for f in profile.files} == {
        "ap_postings.csv",
        "goods_receipts.csv",
        "vendors.csv",
    }

    context = AuditContext(
        client="Alt Co", fiscal_year_end="2025-12-31", trivial_threshold_eur=1000
    )
    (alt_run / "audit_context.json").write_text(
        context.model_dump_json(indent=2), encoding="utf-8"
    )
    build = run_build_agent(settings, dataset, profile, context, alt_run)
    assert "three_way_match" in build.canonical_views_present

    report = run_check_agent(settings, CHECK_SPECS["three_way_match"], context, alt_run)
    mentioned = [e for f in report.findings for e in f.primary_entities]
    assert any("V9001" in e or "INV-2025-104" in e for e in mentioned)


def test_supervisor_end_to_end(
    settings: AgentSettings,
    dataset_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    e2e_run = tmp_path_factory.mktemp("e2e-run")
    summary = run_supervisor(settings, dataset_root, e2e_run)
    assert summary
    assert (e2e_run / "report.json").exists()

    card = score_report(load_report(e2e_run), load_ground_truth(_GROUND_TRUTH))
    by_id = {r.id: r for r in card.expected}
    assert by_id["F1"].caught
    assert card.decoys_accused == 0
