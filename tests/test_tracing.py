"""JsonlTracer event writing and per-agent summaries."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from jetai.agents.tracing import (
    JsonlTracer,
    build_trace_tree,
    load_events,
    summarize_traces,
)


def _llm_result() -> LLMResult:
    message = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 100, "output_tokens": 7, "total_tokens": 107},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_tracer_appends_attributable_events(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    tracer = JsonlTracer(path, agent="build")

    tracer.on_chat_model_start({}, [[HumanMessage("brief")]], run_id=uuid4())
    tracer.on_llm_end(_llm_result(), run_id=uuid4())
    tracer.on_tool_start({"name": "execute_sql"}, "SELECT 1", run_id=uuid4())
    tracer.on_tool_end("1", run_id=uuid4())

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == [
        "llm_start",
        "llm_end",
        "tool_start",
        "tool_end",
    ]
    assert all(line["agent"] == "build" for line in lines)
    assert lines[1]["usage"] == {"input_tokens": 100, "output_tokens": 7}
    assert lines[2]["tool"] == "execute_sql"


def test_summarize_traces_rolls_up_per_agent(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    build = JsonlTracer(path, agent="build")
    check = JsonlTracer(path, agent="check:cutoff")

    build.on_llm_end(_llm_result(), run_id=uuid4())
    build.on_llm_end(_llm_result(), run_id=uuid4())
    build.on_tool_start({"name": "execute_sql"}, "SELECT 1", run_id=uuid4())
    check.on_tool_start({"name": "inspect_schema"}, "", run_id=uuid4())

    summary = {s["agent"]: s for s in summarize_traces(path)}
    assert summary["build"]["llm_calls"] == 2
    assert summary["build"]["input_tokens"] == 200
    assert summary["build"]["tools"] == ["execute_sql"]
    assert summary["check:cutoff"]["tool_calls"] == 1


def test_summarize_missing_file_is_empty(tmp_path: Path) -> None:
    assert summarize_traces(tmp_path / "nope.jsonl") == []


def test_tracer_records_run_ids(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    tracer = JsonlTracer(path, agent="build")
    run_id, parent = uuid4(), uuid4()

    tracer.on_tool_start({"name": "execute_sql"}, "SELECT 1", run_id=run_id, parent_run_id=parent)

    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["run_id"] == str(run_id)
    assert line["parent_run_id"] == str(parent)


def test_build_trace_tree_nests_by_parent(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    tracer = JsonlTracer(path, agent="build")
    chain, tool = uuid4(), uuid4()

    # An LLM call under the chain, then a tool call under the same chain.
    tracer.on_chat_model_start({}, [[HumanMessage("brief")]], run_id=uuid4(), parent_run_id=chain)
    tracer.on_tool_start({"name": "execute_sql"}, "SELECT 1", run_id=tool, parent_run_id=chain)
    tracer.on_tool_end("1", run_id=tool, parent_run_id=chain)

    roots = build_trace_tree(load_events(path))
    # The chain run itself was never traced, so its children surface as roots.
    assert len(roots) == 2
    tool_span = next(s for s in roots if s["kind"] == "tool")
    assert tool_span["label"] == "execute_sql"
    # tool_start + tool_end fold into one span.
    assert len(tool_span["events"]) == 2


def test_build_trace_tree_pairs_child_under_traced_parent() -> None:
    parent, child = "p", "c"
    events = [
        {
            "agent": "a",
            "event": "tool_start",
            "tool": "t",
            "run_id": parent,
            "parent_run_id": None,
            "ts": "2026-01-01T00:00:00.000+00:00",
        },
        {
            "agent": "a",
            "event": "llm_start",
            "run_id": child,
            "parent_run_id": parent,
            "ts": "2026-01-01T00:00:01.000+00:00",
        },
    ]
    roots = build_trace_tree(events)
    assert len(roots) == 1
    assert roots[0]["run_id"] == parent
    assert [c["run_id"] for c in roots[0]["children"]] == [child]
