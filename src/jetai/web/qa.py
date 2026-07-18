"""Q&A agent for a finished audit run: answers questions from traces + artifacts.

A fresh ``create_agent`` per question batch, armed with read-only tools over the
run directory: the trace log (who did what, which SQL ran, token spend), the
structured artifacts, and the audit DuckDB itself. Deliberately *not* traced
with :class:`JsonlTracer` — it would pollute the very file it inspects.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from jetai.agents.build import DB_FILENAME
from jetai.agents.checks import CHECK_SPECS
from jetai.agents.config import AgentSettings
from jetai.agents.runner import DEFAULT_RECURSION_LIMIT, chat_model
from jetai.agents.tools import make_execute_sql_tool, make_schema_tool
from jetai.agents.tracing import summarize_traces
from jetai.web.progress import TRACES_FILENAME

_MAX_TOOL_OUTPUT = 6000

QA_SYSTEM_PROMPT = """You are the Q&A assistant for a completed journal-entry-testing \
audit. A supervisor agent orchestrated specialist subagents (profile, audit_context, \
build, check:<name>, verifier); everything they did is recorded in a trace log and in \
run artifacts, and the audit database is still queryable.

Answer the user's questions about the audit report and about HOW the agents reached \
their conclusions. Ground every answer in evidence: cite the agent, artifact, trace \
event or SQL you used. Start with summarize_run or list_findings to orient yourself; \
use read_trace_events to dig into a specific agent's actions; re-run SQL only when \
the user asks about concrete records. If the traces genuinely do not contain the \
answer, say so instead of guessing. Keep answers concise and audit-grade precise."""

_ARTIFACTS = (
    "report.json",
    "report.md",
    "profile.json",
    "audit_context.json",
    "build_report.json",
    *(f"findings/{name}.json" for name in sorted(CHECK_SPECS)),
)


def _cap(text: str, limit: int = _MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} chars total]"


def build_qa_tools(run_dir: Path, conn: duckdb.DuckDBPyConnection) -> list[BaseTool]:
    """Read-only tools over one run directory and its (read-only) DuckDB."""
    traces_path = run_dir / TRACES_FILENAME

    @tool
    def summarize_run() -> str:
        """Per-agent rollup of the whole run: LLM calls, tool calls, tokens and
        which tools each agent used. Start here to see who did what."""
        lines = [
            f"{s['agent']}: {s['llm_calls']} LLM calls, {s['tool_calls']} tool calls, "
            f"{s['input_tokens']}→{s['output_tokens']} tokens, tools: "
            f"{', '.join(s['tools']) or '—'}"
            for s in summarize_traces(traces_path)
        ]
        return _cap("\n".join(lines) or "(no trace events)")

    @tool
    def read_trace_events(
        agent: str = "", event: str = "", tool_name: str = "", offset: int = 0, limit: int = 20
    ) -> str:
        """Read raw trace events, newest last. Filters are substring matches:
        agent (e.g. 'check:cutoff', 'verifier'), event ('llm_start', 'llm_end',
        'tool_start', 'tool_end', 'tool_error'), tool_name (e.g. 'execute_sql').
        Paginate with offset/limit; the total match count is reported."""
        if not traces_path.exists():
            return "(no trace file)"
        matches: list[str] = []
        with traces_path.open(encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if agent and agent not in str(line.get("agent", "")):
                    continue
                if event and event != line.get("event"):
                    continue
                if tool_name and tool_name not in str(line.get("tool", "")):
                    continue
                matches.append(raw)
        window = matches[offset : offset + max(1, limit)]
        header = f"{len(matches)} matching events; showing {offset}..{offset + len(window)}"
        return _cap("\n".join([header, *window]))

    @tool
    def read_artifact(name: str) -> str:
        """Read one run artifact verbatim. Available: report.json, report.md,
        profile.json, audit_context.json, build_report.json,
        findings/<check>.json."""
        if name not in _ARTIFACTS:
            return f"error: unknown artifact; choose one of {', '.join(_ARTIFACTS)}"
        path = run_dir / name
        if not path.exists():
            return f"error: {name} was not produced by this run"
        return _cap(path.read_text(encoding="utf-8"))

    @tool
    def list_findings() -> str:
        """Compact list of the report's confirmed and rejected findings."""
        from jetai.agents.verifier import load_report

        try:
            report = load_report(run_dir)
        except FileNotFoundError:
            return "error: this run has no report.json yet"
        lines = []
        for index, verified in enumerate(report.confirmed, start=1):
            f = verified.finding
            lines.append(
                f"confirmed #{index}: [{f.check}] {f.category} — "
                f"{', '.join(f.primary_entities) or 'no entities'}, "
                f"EUR {f.amount_eur or 0:,.2f}, confidence {f.confidence}. "
                f"{verified.verifier_notes}"
            )
        for index, rejected in enumerate(report.rejected, start=1):
            f = rejected.finding
            lines.append(f"rejected #{index}: [{f.check}] {f.category} — reason: {rejected.reason}")
        return _cap("\n".join(lines) or "(empty report)")

    return [
        summarize_run,
        read_trace_events,
        read_artifact,
        list_findings,
        make_execute_sql_tool(conn),
        make_schema_tool(conn),
    ]


def _text(content: object) -> str:
    """Flatten Responses-API content blocks into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return str(content)


def answer(
    settings: AgentSettings,
    run_dir: Path,
    history: list[BaseMessage],
    question: str,
) -> Iterator[tuple[str, str]]:
    """Stream one Q&A turn: yields ("tool", label) steps then ("answer", text).

    ``history`` is the prior LangChain message list; the caller appends the
    HumanMessage/AIMessage pair itself after the generator finishes.
    """
    # Typed as Any: langgraph's input state is a TypedDict mypy cannot infer here.
    state: Any = {"messages": [*history, HumanMessage(question)]}
    config: RunnableConfig = {"recursion_limit": DEFAULT_RECURSION_LIMIT, "run_name": "qa"}
    final = ""
    with duckdb.connect(str(run_dir / DB_FILENAME), read_only=True) as conn:
        agent = create_agent(
            chat_model(settings),
            tools=build_qa_tools(run_dir, conn),
            system_prompt=QA_SYSTEM_PROMPT,
            name="qa",
        )
        for update in agent.stream(
            state,
            config=config,
            stream_mode="updates",
        ):
            for node_state in update.values():
                for message in (node_state or {}).get("messages", []):
                    if isinstance(message, AIMessage):
                        if message.tool_calls:
                            for call in message.tool_calls:
                                args = json.dumps(call.get("args", {}), ensure_ascii=False)
                                yield "tool", f"{call['name']} {args[:200]}"
                        elif _text(message.content).strip():
                            final = _text(message.content)
    yield "answer", final or "(the agent produced no answer)"
