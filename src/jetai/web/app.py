"""The Gradio frontend: upload a dataset ZIP, watch the audit, read, then ask.

Three tabs — Upload & Run (live progress tailed from ``traces.jsonl``), Report
(rendered ``report.md`` plus findings with source-file links and an evidence
browser) and Ask the auditor (Q&A agent over the run's traces and artifacts).
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import gradio as gr
import pandas as pd
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import ValidationError

from jetai.agents.build import load_build_report
from jetai.agents.config import AgentSettings
from jetai.agents.models import FinalReport
from jetai.agents.verifier import load_report
from jetai.web import qa
from jetai.web.progress import (
    TRACES_FILENAME,
    render_log_md,
    render_stages_md,
    stage_status,
    tail_traces,
)
from jetai.web.report import evidence_rows, findings_table, render_findings_md
from jetai.web.runstate import UPLOADS_DIR, RunError, start_audit

RUNS_DIR = Path("runs")
ALLOWED_DIRS = (UPLOADS_DIR, RUNS_DIR)

_FINDINGS_HEADERS = ["Check", "Category", "Entities", "EUR", "Period", "Confidence"]
_POLL_SECONDS = 1.0

# The supervisor's opening brief names the dataset root; used to recover it
# when replaying an old run whose upload dir we no longer track.
_ROOT_RE = re.compile(r"dataset at (?P<root>.+?)\. The run directory is")


def _settings() -> AgentSettings:
    try:
        return AgentSettings()  # type: ignore[call-arg]  # loaded from env/.env
    except ValidationError as error:
        raise gr.Error(
            "Missing OpenAI configuration: set OPENAI_API_KEY in the environment "
            "or in .env, then restart."
        ) from error


def _list_runs() -> list[str]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted((str(d) for d in RUNS_DIR.iterdir() if d.is_dir()), reverse=True)


def _recover_root(run_dir: Path) -> str:
    events, _ = tail_traces(run_dir / TRACES_FILENAME, 0)
    for event in events:
        if event.get("agent") == "supervisor" and event.get("event") == "llm_start":
            match = _ROOT_RE.search(str(event.get("last_message", "")))
            if match:
                return match.group("root").strip("`'\" ")
    return ""


def _finding_choices(report: FinalReport) -> list[tuple[str, int]]:
    return [
        (f"{i + 1}. [{v.finding.check}] {v.finding.category}", i)
        for i, v in enumerate(report.confirmed)
    ]


def run_and_stream(zip_path: str | None) -> Iterator[tuple[str, str, str, str]]:
    """Kick off the audit and stream progress until the background thread ends."""
    if not zip_path:
        raise gr.Error("Upload a ZIP file first.")
    settings = _settings()
    try:
        audit = start_audit(settings, Path(zip_path))
    except RunError as error:
        raise gr.Error(str(error)) from error

    traces = audit.run_dir / TRACES_FILENAME
    offset = 0
    events: list[dict[str, Any]] = []
    while True:
        new_events, offset = tail_traces(traces, offset)
        events.extend(new_events)
        statuses, checks = stage_status(events)
        yield (
            render_stages_md(statuses, checks, audit.phase),
            render_log_md(events),
            str(audit.run_dir),
            str(audit.dataset_root),
        )
        if audit.finished:
            break
        time.sleep(_POLL_SECONDS)
    if audit.failed:
        raise gr.Error(f"Audit failed:\n{(audit.error or '')[-1500:]}")


def load_existing(run_dir_choice: str | None, root_fallback: str) -> tuple[str, str, str]:
    """Resolve run dir + dataset root for the replay path (no new agent run)."""
    if not run_dir_choice:
        raise gr.Error("Pick a run directory first.")
    run_dir = Path(run_dir_choice)
    if not (run_dir / "report.json").exists():
        raise gr.Error(f"{run_dir} has no report.json — it was not a completed run.")
    root = root_fallback.strip() or _recover_root(run_dir)
    if not root or not Path(root).is_dir():
        raise gr.Error(
            "Could not recover this run's dataset directory from its traces. "
            "Enter it manually in the 'Dataset root' box."
        )
    return (
        "**Loaded existing run.**",
        str(run_dir),
        root,
    )


def load_run_view(run_dir_str: str, root_str: str) -> tuple[Any, ...]:
    """Populate the Report tab (and enable chat) once a run is available."""
    run_dir, root = Path(run_dir_str), Path(root_str)
    report = load_report(run_dir)
    report_md = (run_dir / "report.md").read_text(encoding="utf-8")
    try:
        build_report = load_build_report(run_dir)
        findings_md = render_findings_md(report, build_report, root)
    except FileNotFoundError:
        findings_md = "No build report available — source files cannot be linked."
    rows = findings_table(report)
    choices = _finding_choices(report)
    return (
        f"## Summary\n\n{report.summary}",
        pd.DataFrame(rows, columns=_FINDINGS_HEADERS),
        findings_md,
        report_md,
        gr.Dropdown(choices=choices, value=choices[0][1] if choices else None),
        report,
        [],  # reset QA history for the new run
        [],  # reset chat display
        gr.Textbox(interactive=True, placeholder="Ask about the report or the agents…"),
        gr.Button(interactive=True),
        gr.Tabs(selected="report"),
    )


def pick_finding(index: int | None, report: FinalReport | None) -> gr.Dropdown:
    if report is None or index is None or index >= len(report.confirmed):
        return gr.Dropdown(choices=[], value=None)
    sqls = report.confirmed[index].finding.evidence_sql
    choices = [(f"{s[:100]}…" if len(s) > 100 else s, s) for s in sqls]
    return gr.Dropdown(choices=choices, value=choices[0][1] if choices else None)


def show_evidence(sql: str | None, run_dir_str: str) -> pd.DataFrame:
    if not sql:
        raise gr.Error("This finding has no evidence SQL.")
    try:
        columns, rows = evidence_rows(Path(run_dir_str), sql)
    except Exception as error:  # noqa: BLE001 - SQL replay is best-effort
        raise gr.Error(f"Could not replay evidence SQL: {error}") from error
    return pd.DataFrame(rows, columns=columns or None)


def ask(
    question: str,
    chat: list[dict[str, Any]],
    history: list[BaseMessage],
    run_dir_str: str,
) -> Iterator[tuple[str, list[dict[str, Any]], list[BaseMessage]]]:
    """One chat turn: stream the QA agent's tool usage, then its answer."""
    question = question.strip()
    if not question:
        raise gr.Error("Type a question first.")
    if not run_dir_str:
        raise gr.Error("Run or load an audit first.")
    settings = _settings()
    chat = [*chat, {"role": "user", "content": question}]
    yield "", chat, history
    final = ""
    for kind, payload in qa.answer(settings, Path(run_dir_str), history, question):
        if kind == "tool":
            name = payload.split(" ", 1)[0]
            chat = [
                *chat,
                {
                    "role": "assistant",
                    "content": f"`{payload}`",
                    "metadata": {"title": f"🔧 {name}"},
                },
            ]
        else:
            final = payload
            chat = [*chat, {"role": "assistant", "content": final}]
        yield "", chat, history
    history = [*history, HumanMessage(question), AIMessage(final)]
    yield "", chat, history


def build_app() -> gr.Blocks:
    with gr.Blocks(title="JetAI Audit") as demo:
        gr.Markdown(
            "# JetAI — Journal Entry Testing\n"
            "Upload an audit dataset as a ZIP; a supervisor agent profiles it, "
            "builds a database, runs the checks and verifies the findings. "
            "Afterwards, ask the auditor anything about the run."
        )
        run_dir_state = gr.State("")
        root_state = gr.State("")
        report_state = gr.State(None)
        qa_history_state = gr.State([])

        with gr.Tabs() as tabs:
            with gr.Tab("Upload & Run", id="run"), gr.Row():
                with gr.Column(scale=1):
                    zip_file = gr.File(label="Audit dataset (ZIP)", file_types=[".zip"])
                    run_btn = gr.Button("Run audit", variant="primary")
                    gr.Markdown("---")
                    existing_dd = gr.Dropdown(
                        label="…or load an existing run (no API cost)",
                        choices=_list_runs(),
                    )
                    with gr.Row():
                        refresh_btn = gr.Button("Refresh", size="sm")
                        load_btn = gr.Button("Load run", size="sm")
                    root_fallback = gr.Textbox(
                        label="Dataset root (only needed if it cannot be "
                        "recovered from the run's traces)",
                        placeholder="uploads/20260718T.../dataset",
                    )
                with gr.Column(scale=2):
                    stages_md = gr.Markdown("*No run yet.*")
                    with gr.Accordion("Agent activity", open=True):
                        log_md = gr.Markdown("*Waiting for agent activity…*")

            with gr.Tab("Report", id="report"):
                summary_md = gr.Markdown("*Run an audit to see the report.*")
                findings_df = gr.Dataframe(
                    headers=_FINDINGS_HEADERS, interactive=False, label="Confirmed findings"
                )
                findings_md = gr.Markdown()
                with gr.Accordion("Full report (report.md)", open=False):
                    report_md = gr.Markdown()
                gr.Markdown("### Evidence browser")
                with gr.Row():
                    finding_dd = gr.Dropdown(label="Finding", choices=[])
                    sql_dd = gr.Dropdown(label="Evidence SQL", choices=[])
                evidence_btn = gr.Button("Show offending rows")
                evidence_df = gr.Dataframe(interactive=False, label="Evidence rows")

            with gr.Tab("Ask the auditor", id="chat"):
                chatbot = gr.Chatbot(type="messages", height=480, label="Auditor Q&A")
                with gr.Row():
                    question_tb = gr.Textbox(
                        label="Question",
                        scale=4,
                        interactive=False,
                        placeholder="Run or load an audit first…",
                    )
                    send_btn = gr.Button("Ask", variant="primary", interactive=False)

        view_outputs = [
            summary_md,
            findings_df,
            findings_md,
            report_md,
            finding_dd,
            report_state,
            qa_history_state,
            chatbot,
            question_tb,
            send_btn,
            tabs,
        ]
        run_btn.click(
            run_and_stream,
            inputs=[zip_file],
            outputs=[stages_md, log_md, run_dir_state, root_state],
        ).success(load_run_view, inputs=[run_dir_state, root_state], outputs=view_outputs)

        refresh_btn.click(lambda: gr.Dropdown(choices=_list_runs()), outputs=[existing_dd])
        load_btn.click(
            load_existing,
            inputs=[existing_dd, root_fallback],
            outputs=[stages_md, run_dir_state, root_state],
        ).success(load_run_view, inputs=[run_dir_state, root_state], outputs=view_outputs)

        finding_dd.change(pick_finding, inputs=[finding_dd, report_state], outputs=[sql_dd])
        evidence_btn.click(show_evidence, inputs=[sql_dd, run_dir_state], outputs=[evidence_df])

        ask_inputs = [question_tb, chatbot, qa_history_state, run_dir_state]
        ask_outputs = [question_tb, chatbot, qa_history_state]
        send_btn.click(ask, inputs=ask_inputs, outputs=ask_outputs)
        question_tb.submit(ask, inputs=ask_inputs, outputs=ask_outputs)
    return cast(gr.Blocks, demo)
