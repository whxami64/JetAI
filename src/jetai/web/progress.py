"""Live progress for a running audit, derived by tailing ``traces.jsonl``.

Every agent appends to the shared trace file while the supervisor runs, so the
UI can poll it with a byte offset and derive both a stage checklist (from the
supervisor's tool calls) and a scrolling activity log — without duplicating any
orchestration logic.
"""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

from jetai.agents.checks import CHECK_SPECS

TRACES_FILENAME = "traces.jsonl"

STAGES = (
    "Profile dataset",
    "Extract audit context",
    "Build database",
    "Run checks",
    "Verify findings",
)

_STAGE_BY_TOOL = {
    "profile_dataset": 0,
    "extract_audit_context": 1,
    "build_database": 2,
    "run_check": 3,
    "verify_findings": 4,
}

_CHECK_NAME_RE = re.compile("|".join(re.escape(name) for name in sorted(CHECK_SPECS)))

_GLYPHS = {"pending": "▫️", "running": "⏳", "done": "✅", "error": "⚠️"}


def tail_traces(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Return the complete JSONL events appended since ``offset`` (in bytes)."""
    if not path.exists():
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
    # Only consume up to the last full line; a partial tail is re-read next poll.
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return [], offset
    events = []
    for raw in chunk[: cut + 1].splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events, offset + cut + 1


def stage_status(events: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    """Derive per-stage and per-check statuses from supervisor tool events.

    The supervisor calls its tools serially, so starts and ends pair FIFO even
    though ``tool_end`` events carry no tool name.
    """
    statuses = ["pending"] * len(STAGES)
    checks: dict[str, str] = {}
    pending: deque[tuple[int | None, str | None]] = deque()
    for event in events:
        if event.get("agent") != "supervisor":
            continue
        kind = event.get("event")
        if kind == "tool_start":
            index = _STAGE_BY_TOOL.get(event.get("tool", ""))
            check = None
            if event.get("tool") == "run_check":
                match = _CHECK_NAME_RE.search(event.get("input", ""))
                check = match.group(0) if match else None
                if check:
                    checks[check] = "running"
            pending.append((index, check))
            if index is not None:
                statuses[index] = "running"
        elif kind in ("tool_end", "tool_error") and pending:
            index, check = pending.popleft()
            outcome = "done" if kind == "tool_end" else "error"
            if index is not None:
                statuses[index] = outcome
            if check:
                checks[check] = outcome
    return statuses, checks


def render_stages_md(statuses: list[str], checks: dict[str, str], phase: str) -> str:
    """The stage checklist shown while (and after) the audit runs."""
    if phase == "preprocessing":
        header = "**Preprocessing dataset** (converting workbooks and ledgers)…"
    elif phase == "running":
        header = "**Audit in progress** — the supervisor is orchestrating specialists."
    elif phase == "done":
        header = "**Audit complete.**"
    elif phase == "failed":
        header = "**Audit failed.** See the error below."
    else:
        header = "**Starting…**"
    lines = [header, ""]
    for label, status in zip(STAGES, statuses, strict=True):
        lines.append(f"{_GLYPHS[status]} {label}")
        if label == "Run checks" and checks:
            for name, check_status in checks.items():
                lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;{_GLYPHS[check_status]} `{name}`")
    return "\n\n".join(lines)


def _format_event(event: dict[str, Any]) -> str:
    ts = event.get("ts", "")[11:19]
    agent = event.get("agent", "?")
    kind = event.get("event")
    if kind == "llm_start":
        body = f"thinking ({event.get('messages', '?')} messages in context)"
    elif kind == "llm_end":
        usage = event.get("usage") or {}
        tokens = f"{usage.get('input_tokens', 0)}→{usage.get('output_tokens', 0)} tok"
        body = f"responded ({tokens})"
    elif kind == "tool_start":
        body = f"tool {event.get('tool', '?')}: {_clip(event.get('input', ''))}"
    elif kind == "tool_end":
        body = f"tool result: {_clip(event.get('output', ''))}"
    elif kind == "tool_error":
        body = f"TOOL ERROR: {_clip(event.get('error', ''))}"
    else:
        body = str(kind)
    return f"{ts}  [{agent}]  {body}"


def _clip(text: str, limit: int = 110) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_log_md(events: list[dict[str, Any]], max_lines: int = 40) -> str:
    """The scrolling activity log: last ``max_lines`` events as a code block."""
    if not events:
        return "*Waiting for agent activity…*"
    lines = [_format_event(event) for event in events[-max_lines:]]
    return "```text\n" + "\n".join(lines) + "\n```"
