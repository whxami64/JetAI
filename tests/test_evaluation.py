"""Deterministic scoring against a fabricated final report."""

from __future__ import annotations

from jetai.agents.models import FinalReport, Finding, VerifiedFinding
from jetai.evaluation import (
    Decoy,
    ExpectedFinding,
    GroundTruth,
    load_ground_truth,
    score_report,
)

_TRUTH = GroundTruth(
    expected=[
        ExpectedFinding(
            id="F1",
            check_any=["three_way_match", "four_eyes"],
            must_mention_any=["209101", "MV-U05"],
        ),
        ExpectedFinding(id="F2", check_any=["account_classification"], must_mention_any=["040000"]),
        ExpectedFinding(
            id="F4", check_any=["split_payments"], must_mention_any=["200007"], core=False
        ),
    ],
    decoys=[Decoy(id="D3", entities=["209112"])],
)


def _confirmed(check: str, entities: list[str]) -> VerifiedFinding:
    return VerifiedFinding(finding=Finding(check=check, category="x", primary_entities=entities))


def test_catch_miss_decoy_and_precision() -> None:
    report = FinalReport(
        confirmed=[
            # catches F1: allowed check, entity contains the ground-truth id
            _confirmed("three_way_match", ["vendor 209101 (Ratio Consulting)"]),
            # accuses decoy D3
            _confirmed("three_way_match", ["209112"]),
            # right entity, wrong check: must NOT catch F2
            _confirmed("cutoff", ["040000"]),
        ]
    )
    card = score_report(report, _TRUTH)

    by_id = {r.id: r for r in card.expected}
    assert by_id["F1"].caught
    assert not by_id["F2"].caught
    assert not by_id["F4"].caught
    assert card.core_recall == 0.5  # F1 of {F1, F2}
    assert card.bonus_caught == 0
    assert card.decoys_accused == 1
    assert card.precision == 1 / 3  # only the F1 finding matched an expectation
    assert card.confirmed_findings == 3


def test_merged_check_names_still_match() -> None:
    report = FinalReport(confirmed=[_confirmed("four_eyes / three_way_match", ["209101"])])
    card = score_report(report, _TRUTH)
    assert {r.id: r.caught for r in card.expected}["F1"]


def test_rejected_findings_do_not_score() -> None:
    report = FinalReport(confirmed=[])
    card = score_report(report, _TRUTH)
    assert card.core_recall == 0.0
    assert card.decoys_accused == 0
    assert card.precision == 0.0


def test_repo_ground_truth_parses() -> None:
    truth = load_ground_truth()
    assert {e.id for e in truth.expected} == {"F1", "F2", "F3", "F4"}
    assert len(truth.decoys) == 7
