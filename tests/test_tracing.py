"""JsonlTracer event writing and per-agent summaries."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from jetai.agents.tracing import JsonlTracer, summarize_traces


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
