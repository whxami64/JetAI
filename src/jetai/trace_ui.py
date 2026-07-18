"""Local Gradio viewer for a run's ``traces.jsonl``.

No external service: the app reads the on-disk trace files under ``runs/`` and
renders a per-agent rollup plus a nested call tree (LLM/tool spans paired by
``run_id`` and nested by ``parent_run_id``). Launched via ``jetai trace-ui``.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from jetai.agents.tracing import build_trace_tree, load_events, summarize_traces

_TRACES = "traces.jsonl"

_AGENT_COLORS = [
    "#2563eb",
    "#059669",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#be185d",
]


def list_runs(runs_dir: Path) -> list[str]:
    """Run directory names that contain a ``traces.jsonl``, newest first."""
    if not runs_dir.is_dir():
        return []
    runs = [d.name for d in runs_dir.iterdir() if d.is_dir() and (d / _TRACES).exists()]
    return sorted(runs, reverse=True)


def _agent_color(agent: str) -> str:
    return _AGENT_COLORS[hash(agent) % len(_AGENT_COLORS)]


def _duration_ms(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except ValueError:
        return ""
    return f"{delta.total_seconds() * 1000:.0f} ms"


def _field(events: list[dict[str, Any]], key: str) -> str:
    for event in events:
        if event.get(key):
            return str(event[key])
    return ""


def _span_detail(span: dict[str, Any]) -> str:
    events = span["events"]
    rows: list[tuple[str, str]] = []
    if span["kind"] == "llm":
        rows.append(("prompt", _field(events, "last_message")))
        rows.append(("completion", _field(events, "completion")))
        usage = next((e.get("usage") for e in events if e.get("usage")), None)
        if usage:
            rows.append(
                (
                    "tokens",
                    f"in {usage.get('input_tokens', 0)} / out {usage.get('output_tokens', 0)}",
                )
            )
    else:
        rows.append(("input", _field(events, "input")))
        rows.append(("output", _field(events, "output")))
        error = _field(events, "error")
        if error:
            rows.append(("error", error))
    body = "".join(
        f"<div style='margin:2px 0'><b>{label}:</b> "
        f"<code style='white-space:pre-wrap'>{html.escape(value)}</code></div>"
        for label, value in rows
        if value
    )
    return body or "<div style='color:#888'>no detail</div>"


def _render_span(span: dict[str, Any], depth: int) -> str:
    color = _agent_color(span["agent"])
    icon = "🔧" if span["kind"] == "tool" else "🧠"
    duration = _duration_ms(span["start_ts"], span["end_ts"])
    errored = any(e.get("event") == "tool_error" for e in span["events"])
    label = html.escape(str(span["label"]))
    summary = (
        f"<span style='color:{color};font-weight:600'>{html.escape(span['agent'])}</span> "
        f"{icon} {label}"
        f"{'  ⚠️' if errored else ''}"
        f"<span style='color:#888;float:right'>{duration}</span>"
    )
    detail = _span_detail(span)
    children = "".join(_render_span(child, depth + 1) for child in span["children"])
    return (
        f"<div style='margin-left:{depth * 18}px;border-left:3px solid {color};"
        f"padding:4px 8px;margin-top:4px'>"
        f"<details><summary style='cursor:pointer'>{summary}</summary>"
        f"<div style='margin-top:4px'>{detail}</div></details>"
        f"{children}</div>"
    )


def render_tree_html(events: list[dict[str, Any]]) -> str:
    """Nested call tree of a run's events as a self-contained HTML fragment."""
    roots = build_trace_tree(events)
    if not roots:
        return "<p style='color:#888'>No trace events for this run.</p>"
    return "".join(_render_span(root, 0) for root in roots)


def _summary_rows(path: Path) -> list[list[Any]]:
    return [
        [
            s["agent"],
            s["llm_calls"],
            s["tool_calls"],
            s["input_tokens"],
            s["output_tokens"],
            ", ".join(s["tools"]),
        ]
        for s in summarize_traces(path)
    ]


def build_app(runs_dir: Path) -> Any:
    """Build (but do not launch) the Gradio Blocks app for ``runs_dir``."""
    import gradio as gr

    def load(run: str | None) -> tuple[list[list[Any]], str]:
        if not run:
            return [], "<p style='color:#888'>Select a run.</p>"
        path = runs_dir / run / _TRACES
        return _summary_rows(path), render_tree_html(load_events(path))

    runs = list_runs(runs_dir)
    with gr.Blocks(title="JetAI agent traces") as app:
        gr.Markdown(f"# JetAI agent traces\nReading `{runs_dir}/`")
        with gr.Row():
            run_dd = gr.Dropdown(
                choices=runs, value=runs[0] if runs else None, label="Run", scale=4
            )
            refresh = gr.Button("↻ Refresh runs", scale=1)
        summary = gr.Dataframe(
            headers=["Agent", "LLM calls", "Tool calls", "Tokens in", "Tokens out", "Tools"],
            label="Per-agent summary",
            wrap=True,
        )
        tree = gr.HTML(label="Call tree")

        run_dd.change(load, inputs=run_dd, outputs=[summary, tree])
        refresh.click(lambda: gr.update(choices=list_runs(runs_dir)), outputs=run_dd)
        if runs:
            app.load(load, inputs=run_dd, outputs=[summary, tree])
    return app


def launch(runs_dir: Path, **kwargs: Any) -> None:
    """Launch the trace viewer (blocking)."""
    build_app(runs_dir).launch(**kwargs)
