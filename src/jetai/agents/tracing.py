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

    def _write(self, event: str, payload: dict[str, Any]) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "agent": self.agent,
            "event": event,
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
        **kwargs: Any,
    ) -> None:
        batch = messages[0] if messages else []
        self._write(
            "llm_start",
            {
                "messages": len(batch),
                "last_message": _excerpt(batch[-1].content) if batch else "",
            },
        )

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
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
        self._write("llm_end", {"completion": completion, "usage": usage})

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._write(
            "tool_start",
            {"tool": serialized.get("name", "?"), "input": _excerpt(input_str)},
        )

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._write("tool_end", {"output": _excerpt(getattr(output, "content", output))})

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._write("tool_error", {"error": _excerpt(error)})


def summarize_traces(path: Path) -> list[dict[str, Any]]:
    """Per-agent rollup of a ``traces.jsonl``: calls, tokens, tools used."""
    agents: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            line = json.loads(raw)
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
