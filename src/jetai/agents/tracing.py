"""Local JSONL tracing for every LLM and tool call of every agent.

No external service: one :class:`JsonlTracer` per agent invocation appends
attributable events to ``<run>/traces.jsonl``. ``jetai trace`` summarizes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

_EXCERPT = 400


def _excerpt(value: object, limit: int = _EXCERPT) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


class JsonlTracer(BaseCallbackHandler):
    """Appends one JSON line per LLM/tool event, tagged with the agent's name."""

    def __init__(self, path: Path, agent: str) -> None:
        self.path = path
        self.agent = agent

    def _write(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
    ) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "agent": self.agent,
            "event": event,
            # run_id/parent_run_id let a viewer pair start/end events and
            # reconstruct the call tree (which LLM/tool sits under which parent).
            "run_id": str(run_id) if run_id else None,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        batch = messages[0] if messages else []
        self._write(
            "llm_start",
            {
                "messages": len(batch),
                "last_message": _excerpt(batch[-1].content) if batch else "",
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        usage: dict[str, Any] = {}
        completion = ""
        generations = response.generations[0] if response.generations else []
        if generations:
            generation = generations[0]
            completion = _excerpt(generation.text)
            message = getattr(generation, "message", None)
            usage_metadata = getattr(message, "usage_metadata", None)
            if usage_metadata:
                usage = {
                    "input_tokens": usage_metadata.get("input_tokens", 0),
                    "output_tokens": usage_metadata.get("output_tokens", 0),
                }
        self._write(
            "llm_end",
            {"completion": completion, "usage": usage},
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._write(
            "tool_start",
            {"tool": serialized.get("name", "?"), "input": _excerpt(input_str)},
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._write(
            "tool_end",
            {"output": _excerpt(getattr(output, "content", output))},
            run_id=run_id,
            parent_run_id=parent_run_id,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._write(
            "tool_error",
            {"error": _excerpt(error)},
            run_id=run_id,
            parent_run_id=parent_run_id,
        )


def load_events(path: Path) -> list[dict[str, Any]]:
    """Read a ``traces.jsonl`` into a chronological list of event dicts."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if raw:
                events.append(json.loads(raw))
    return events


def build_trace_tree(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold start/end events into spans and nest them via ``parent_run_id``.

    Each span pairs the ``*_start``/``*_end`` events sharing a ``run_id`` into a
    single node with ``children``. Spans whose parent was never traced (e.g. the
    LangGraph chain run) surface as roots, preserving first-seen order. Events
    from older traces without a ``run_id`` each become their own standalone span.
    """
    spans: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, event in enumerate(events):
        run_id = event.get("run_id") or f"_anon{index}"
        name = event.get("event", "")
        kind = "tool" if name.startswith("tool") else "llm"
        span = spans.get(run_id)
        if span is None:
            span = {
                "run_id": run_id,
                "parent_run_id": event.get("parent_run_id"),
                "agent": event.get("agent", "?"),
                "kind": kind,
                "label": event.get("tool", kind),
                "start_ts": event.get("ts"),
                "end_ts": event.get("ts"),
                "events": [],
                "children": [],
            }
            spans[run_id] = span
            order.append(run_id)
        span["events"].append(event)
        span["end_ts"] = event.get("ts")
        if event.get("tool"):
            span["label"] = event["tool"]

    roots: list[dict[str, Any]] = []
    for run_id in order:
        span = spans[run_id]
        parent = spans.get(span["parent_run_id"] or "")
        if parent is not None and parent is not span:
            parent["children"].append(span)
        else:
            roots.append(span)
    return roots


def summarize_traces(path: Path) -> list[dict[str, Any]]:
    """Per-agent rollup of a ``traces.jsonl``: calls, tokens, tools used."""
    agents: dict[str, dict[str, Any]] = {}
    for line in load_events(path):
        stats = agents.setdefault(
            line.get("agent", "?"),
            {
                "agent": line.get("agent", "?"),
                "llm_calls": 0,
                "tool_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "tools": set(),
            },
        )
        event = line.get("event")
        if event == "llm_end":
            stats["llm_calls"] += 1
            usage = line.get("usage") or {}
            stats["input_tokens"] += usage.get("input_tokens", 0)
            stats["output_tokens"] += usage.get("output_tokens", 0)
        elif event == "tool_start":
            stats["tool_calls"] += 1
            stats["tools"].add(line.get("tool", "?"))
    summary = []
    for stats in agents.values():
        stats["tools"] = sorted(stats["tools"])
        summary.append(stats)
    return summary
