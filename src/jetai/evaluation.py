"""Deterministic scoring of a run's final report against the ground truth.

The ground truth lives in ``eval/ground_truth.json`` — outside ``src`` on
purpose, so agents can never see it. Because agent outputs are structured
(``primary_entities`` on every finding), scoring needs no LLM judge: an
expected finding is *caught* when a confirmed finding from an allowed check
names one of its entities; a decoy is *accused* when any confirmed finding
names one of the decoy's entities.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from jetai.agents.models import FinalReport

DEFAULT_GROUND_TRUTH = Path("eval/ground_truth.json")


class ExpectedFinding(BaseModel):
    id: str
    title: str = ""
    check_any: list[str]
    must_mention_any: list[str]
    core: bool = True


class Decoy(BaseModel):
    id: str
    entities: list[str]


class GroundTruth(BaseModel):
    expected: list[ExpectedFinding]
    decoys: list[Decoy] = Field(default_factory=list)


class ExpectedResult(BaseModel):
    id: str
    title: str = ""
    core: bool = True
    caught: bool = False
    matched_entities: list[str] = Field(default_factory=list)


class DecoyResult(BaseModel):
    id: str
    accused: bool = False
    matched_entities: list[str] = Field(default_factory=list)


class Scorecard(BaseModel):
    expected: list[ExpectedResult]
    decoys: list[DecoyResult]
    confirmed_findings: int = 0
    core_recall: float = 0.0
    bonus_caught: int = 0
    decoys_accused: int = 0
    precision: float = 0.0


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _mentions(finding_entities: list[str], truth_entity: str) -> bool:
    """A ground-truth entity is mentioned when it appears inside a named entity."""
    needle = _normalize(truth_entity)
    return any(needle in _normalize(entity) for entity in finding_entities)


def load_ground_truth(path: Path = DEFAULT_GROUND_TRUTH) -> GroundTruth:
    return GroundTruth.model_validate(json.loads(path.read_text(encoding="utf-8")))


def score_report(report: FinalReport, truth: GroundTruth) -> Scorecard:
    """Score confirmed findings: recall on core expectations, decoy accusations, precision."""
    confirmed = [item.finding for item in report.confirmed]

    expected_results = []
    matched_finding_indexes: set[int] = set()
    for expected in truth.expected:
        result = ExpectedResult(id=expected.id, title=expected.title, core=expected.core)
        for index, finding in enumerate(confirmed):
            if finding.check not in expected.check_any:
                continue
            hits = [e for e in expected.must_mention_any if _mentions(finding.primary_entities, e)]
            if hits:
                result.caught = True
                result.matched_entities = sorted(set(result.matched_entities) | set(hits))
                matched_finding_indexes.add(index)
        expected_results.append(result)

    decoy_results = []
    for decoy in truth.decoys:
        decoy_result = DecoyResult(id=decoy.id)
        for finding in confirmed:
            hits = [e for e in decoy.entities if _mentions(finding.primary_entities, e)]
            if hits:
                decoy_result.accused = True
                decoy_result.matched_entities = sorted(
                    set(decoy_result.matched_entities) | set(hits)
                )
        decoy_results.append(decoy_result)

    core = [r for r in expected_results if r.core]
    return Scorecard(
        expected=expected_results,
        decoys=decoy_results,
        confirmed_findings=len(confirmed),
        core_recall=(sum(r.caught for r in core) / len(core)) if core else 0.0,
        bonus_caught=sum(r.caught for r in expected_results if not r.core),
        decoys_accused=sum(r.accused for r in decoy_results),
        precision=(len(matched_finding_indexes) / len(confirmed)) if confirmed else 0.0,
    )
