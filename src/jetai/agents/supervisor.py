"""Supervisor agent: orchestrates the specialists as tools.

Every tool runs a full specialist and returns only a compact JSON summary —
the specialists' complete outputs live as artifacts in the run directory, and
the verifier reads the findings files directly. Evidence is never retyped by
the supervisor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from jetai.agents.audit_context import load_audit_context, run_audit_context_agent
from jetai.agents.build import load_build_report, run_build_agent
from jetai.agents.checks import CHECK_SPECS, run_check_agent
from jetai.agents.config import AgentSettings
from jetai.agents.profiling import load_profile, run_profiling_agent
from jetai.agents.runner import chat_model
from jetai.agents.tracing import JsonlTracer
from jetai.agents.verifier import run_verifier_agent

_SUPERVISOR_RECURSION_LIMIT = 50

_PROMPT = """You are the supervisor of a journal-entry-testing audit. You run \
specialist agents through your tools; each returns a compact summary and writes \
its full output to the run directory.

Standard audit program (adapt when results demand it):
1. profile_dataset — survey every source file.
2. extract_audit_context — thresholds and rules from the working papers.
3. build_database — canonical DuckDB views. If the build reports defects or \
missing views that the sources should support, re-run it ONCE with a refinement \
note describing what to fix.
4. run_check for each available check ({checks}). Skip a check whose required \
views are missing per the build summary. You may re-run a check once with a \
refinement note if its result looks broken (e.g. it found nothing because it \
queried a wrong column).
5. verify_findings — always finish with this; it produces the final report.

Do not re-interpret or retype findings yourself — the verifier reads them from \
disk. Finish with a 5-10 line summary of the run: what was profiled, built, \
checked, and the verifier's confirmed/rejected counts."""


def _summary(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def build_supervisor_tools(
    settings: AgentSettings, root: Path, run_dir: Path
) -> list[Any]:
    """The specialists, wrapped as supervisor tools over shared disk state."""

    @tool
    def profile_dataset() -> str:
        """Profile every source file in the dataset (writes profile.json)."""
        try:
            profile = run_profiling_agent(settings, root, run_dir)
        except Exception as error:  # noqa: BLE001 - summarized for the supervisor
            return _summary({"status": "error", "error": str(error)})
        flagged = [
            f"{f.path}:{c.name}"
            for f in profile.files
            for c in f.columns
            if c.mixed or c.ambiguous
        ]
        return _summary(
            {
                "status": "ok",
                "files": len(profile.files),
                "mixed_or_ambiguous_columns": flagged,
                "artifact": "profile.json",
            }
        )

    @tool
    def extract_audit_context() -> str:
        """Extract thresholds/materiality/special rules from the working papers."""
        try:
            profile = load_profile(run_dir)
            context = run_audit_context_agent(settings, root, profile, run_dir)
        except Exception as error:  # noqa: BLE001
            return _summary({"status": "error", "error": str(error)})
        return _summary({"status": "ok", "artifact": "audit_context.json", **context.model_dump()})

    @tool
    def build_database(refinement_note: str = "") -> str:
        """Build the canonical DuckDB views from the profiled sources.
        Pass a refinement_note only when re-running after reported defects."""
        try:
            profile = load_profile(run_dir)
            context = load_audit_context(run_dir)
            if refinement_note:
                profile.files[0].quality_notes.append(f"REFINEMENT NOTE: {refinement_note}")
            report = run_build_agent(settings, root, profile, context, run_dir)
        except Exception as error:  # noqa: BLE001
            return _summary({"status": "error", "error": str(error)})
        return _summary(
            {
                "status": "ok",
                "views_present": report.canonical_views_present,
                "views_missing": report.canonical_views_missing,
                "defects": report.defects,
                "unmapped": report.unmapped,
                "artifact": "build_report.json",
            }
        )

    @tool
    def run_check(check_name: str, refinement_note: str = "") -> str:
        """Run one check agent (three_way_match, cutoff, account_classification,
        split_payments, four_eyes). Writes findings/<check>.json."""
        spec = CHECK_SPECS.get(check_name)
        if spec is None:
            return _summary(
                {"status": "error", "error": f"unknown check; use one of {sorted(CHECK_SPECS)}"}
            )
        try:
            build_report = load_build_report(run_dir)
            missing = [v for v in spec.required_views if v in build_report.canonical_views_missing]
            if missing:
                return _summary(
                    {"status": "skipped", "reason": f"required views missing: {missing}"}
                )
            context = load_audit_context(run_dir)
            if refinement_note:
                context.special_rules.append(f"REFINEMENT NOTE: {refinement_note}")
            report = run_check_agent(settings, spec, context, run_dir)
        except Exception as error:  # noqa: BLE001
            return _summary({"status": "error", "error": str(error)})
        return _summary(
            {
                "status": "ok",
                "check": spec.name,
                "findings": len(report.findings),
                "categories": sorted({f.category for f in report.findings}),
                "limitations": report.limitations,
                "artifact": f"findings/{spec.name}.json",
            }
        )

    @tool
    def verify_findings() -> str:
        """Verify all findings and produce the final report (report.json/report.md)."""
        try:
            context = load_audit_context(run_dir)
            report = run_verifier_agent(settings, context, run_dir)
        except Exception as error:  # noqa: BLE001
            return _summary({"status": "error", "error": str(error)})
        return _summary(
            {
                "status": "ok",
                "confirmed": len(report.confirmed),
                "rejected": len(report.rejected),
                "summary": report.summary,
                "artifact": "report.json",
            }
        )

    @tool
    def list_run_artifacts() -> str:
        """List the artifacts currently present in the run directory."""
        artifacts = sorted(
            str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()
        )
        return _summary({"artifacts": artifacts})

    return [
        profile_dataset,
        extract_audit_context,
        build_database,
        run_check,
        verify_findings,
        list_run_artifacts,
    ]


def run_supervisor(settings: AgentSettings, root: Path, run_dir: Path) -> str:
    """Run the full audit program; returns the supervisor's final summary."""
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent="supervisor")
    agent = create_agent(
        chat_model(settings),
        tools=build_supervisor_tools(settings, root, run_dir),
        system_prompt=_PROMPT.format(checks=", ".join(sorted(CHECK_SPECS))),
        name="supervisor",
    )
    state = agent.invoke(
        {
            "messages": [
                HumanMessage(
                    f"Run the audit program on the dataset at {root}. "
                    f"The run directory is {run_dir}."
                )
            ]
        },
        config={
            "callbacks": [tracer],
            "run_name": "supervisor",
            "recursion_limit": max(_SUPERVISOR_RECURSION_LIMIT, settings.recursion_limit),
        },
    )
    final = state["messages"][-1]
    content = final.content
    return content if isinstance(content, str) else json.dumps(content)
