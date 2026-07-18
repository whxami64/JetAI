"""Trace tailing and stage derivation for the web UI."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from jetai.web.progress import render_log_md, render_stages_md, stage_status, tail_traces
from jetai.web.runstate import RunError, extract_zip


def _event(agent: str, event: str, **payload: object) -> dict[str, object]:
    return {"ts": "2026-07-18T12:00:00.000+00:00", "agent": agent, "event": event, **payload}


def _write(path: Path, events: list[dict[str, object]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def test_tail_traces_tracks_offset_and_partial_lines(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    _write(path, [_event("supervisor", "llm_start", messages=1)])

    events, offset = tail_traces(path, 0)
    assert len(events) == 1

    # A partial trailing line is left for the next poll.
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"agent": "supervi')
    events, offset2 = tail_traces(path, offset)
    assert events == []
    assert offset2 == offset

    with path.open("a", encoding="utf-8") as handle:
        handle.write('sor", "event": "llm_end"}\n')
    events, offset3 = tail_traces(path, offset2)
    assert [e["event"] for e in events] == ["llm_end"]
    assert offset3 > offset2


def test_tail_traces_missing_file(tmp_path: Path) -> None:
    assert tail_traces(tmp_path / "nope.jsonl", 0) == ([], 0)


def test_stage_status_pairs_serial_supervisor_tools(tmp_path: Path) -> None:
    events = [
        _event("supervisor", "tool_start", tool="profile_dataset", input=""),
        _event("profile", "llm_start", messages=1),
        _event("supervisor", "tool_end", output="{}"),
        _event("supervisor", "tool_start", tool="run_check", input="{'check_name': 'cutoff'}"),
        _event("check:cutoff", "tool_start", tool="execute_sql", input="SELECT 1"),
        _event("check:cutoff", "tool_end", output="1"),
    ]
    statuses, checks = stage_status(events)
    assert statuses[0] == "done"  # profile
    assert statuses[3] == "running"  # checks stage still open
    assert checks == {"cutoff": "running"}

    events.append(_event("supervisor", "tool_end", output="{}"))
    statuses, checks = stage_status(events)
    assert statuses[3] == "done"
    assert checks == {"cutoff": "done"}


def test_stage_status_ignores_unmapped_tools() -> None:
    events = [
        _event("supervisor", "tool_start", tool="list_run_artifacts", input=""),
        _event("supervisor", "tool_end", output="{}"),
        _event("supervisor", "tool_start", tool="verify_findings", input=""),
    ]
    statuses, checks = stage_status(events)
    assert statuses == ["pending", "pending", "pending", "pending", "running"]
    assert checks == {}


def test_render_helpers_produce_markdown() -> None:
    statuses, checks = ["done", "running", "pending", "pending", "pending"], {}
    md = render_stages_md(statuses, checks, phase="running")
    assert "Profile dataset" in md and "⏳" in md
    log = render_log_md([_event("build", "tool_start", tool="execute_sql", input="SELECT 1")])
    assert "execute_sql" in log and log.startswith("```text")


def test_extract_zip_rejects_traversal_and_bad_zip(tmp_path: Path) -> None:
    bad = tmp_path / "evil.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escape.txt", "boom")
    with pytest.raises(RunError, match="unsafe path"):
        extract_zip(bad, uploads_dir=tmp_path / "uploads")

    not_zip = tmp_path / "not.zip"
    not_zip.write_text("hello")
    with pytest.raises(RunError, match="not a valid ZIP"):
        extract_zip(not_zip, uploads_dir=tmp_path / "uploads")


def test_extract_zip_extracts_to_fresh_dir(tmp_path: Path) -> None:
    source = tmp_path / "data.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("dataset/postings.csv", "a;b\n1;2\n")
    extracted = extract_zip(source, uploads_dir=tmp_path / "uploads")
    assert (extracted / "dataset" / "postings.csv").read_text() == "a;b\n1;2\n"
