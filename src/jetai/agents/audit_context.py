"""Audit-context agent: extract thresholds and rules from the working papers.

Nothing is hardcoded — on another dataset it reads whatever the working paper
there says (approval threshold, materiality, special selection criteria).
"""

from __future__ import annotations

import json
from pathlib import Path

from jetai.agents.config import AgentSettings
from jetai.agents.models import AuditContext, DatasetProfile
from jetai.agents.runner import run_structured_agent
from jetai.agents.tools import make_list_sources_tool, make_read_markdown_tool
from jetai.agents.tracing import JsonlTracer

_BRIEF = """You are preparing a journal-entry-testing audit. The dataset contains \
converted working papers and statements as markdown documents.

1. Use list_sources to see every file, then read the documents that look like \
audit planning / working papers, export protocols, IT confirmations or \
rights/permissions evaluations with read_markdown.
2. Extract into the structured answer:
- client name and fiscal year end;
- the payment approval threshold (amounts above it need a second approval), \
overall materiality, and the trivial/clearly-inconsequential threshold, in EUR;
- special_rules: every risk-based selection criterion or control rule the papers \
state (four-eyes requirements, segregation-of-duties expectations, cut-off rules, \
round-amount criteria, ...), one rule per list entry, in your own short words;
- source_documents: the paths of the documents you actually used.

If a value is genuinely absent from the papers, leave it null rather than guessing."""


def run_audit_context_agent(
    settings: AgentSettings, root: Path, profile: DatasetProfile, run_dir: Path
) -> AuditContext:
    """Extract the audit context and write ``audit_context.json``."""
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent="audit_context")
    context = run_structured_agent(
        settings=settings,
        name="audit_context",
        brief=_BRIEF,
        tools=[make_list_sources_tool(profile), make_read_markdown_tool(root)],
        response_format=AuditContext,
        tracer=tracer,
    )
    (run_dir / "audit_context.json").write_text(
        context.model_dump_json(indent=2), encoding="utf-8"
    )
    return context


def load_audit_context(run_dir: Path) -> AuditContext:
    return AuditContext.model_validate(
        json.loads((run_dir / "audit_context.json").read_text(encoding="utf-8"))
    )
