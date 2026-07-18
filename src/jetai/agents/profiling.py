"""Profiling: deterministic file survey + one LLM annotation pass.

The deterministic pass walks the (preprocessed) dataset, sniffs encoding and
delimiter, finds the real header row (spreadsheet exports hide it under 1-2
title rows), extracts columns with detected date/number formats and sample
rows. The single LLM pass adds per-file descriptions, candidate join keys and
quality notes. The result (``profile.json``) is what makes every downstream
prompt schema-agnostic.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from jetai.agents.config import AgentSettings
from jetai.agents.formats import detect_table_formats
from jetai.agents.models import (
    DatasetAnnotations,
    DatasetProfile,
    FileProfile,
)
from jetai.agents.runner import run_structured_agent
from jetai.agents.tracing import JsonlTracer
from jetai.dataset import STALE_DIRNAME, build_inventory

MAX_ROWS_READ = 200_000
HEADER_SCAN_ROWS = 15
SAMPLE_ROWS = 3
_DELIMITERS = (";", ",", "\t", "|")
_MD_EXCERPT_LINES = 30


def _decode(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8?"


def _sniff_delimiter(text: str) -> str:
    first_lines = text.splitlines()[:5]
    sample = "\n".join(first_lines)
    return max(_DELIMITERS, key=lambda d: sample.count(d))


def _looks_numeric(cell: str) -> bool:
    cleaned = cell.strip().replace(".", "").replace(",", "").lstrip("+-")
    return bool(cleaned) and cleaned.isdigit()


def detect_header_row(rows: list[list[str]]) -> int:
    """First row that looks like a header: mostly non-empty, mostly non-numeric.

    Handles spreadsheet exports where 1-2 title rows precede the real header.
    """
    best_width = max((len(r) for r in rows[:HEADER_SCAN_ROWS]), default=0)
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not row or best_width == 0:
            continue
        filled = sum(1 for cell in row if cell.strip())
        numeric = sum(1 for cell in row if cell.strip() and _looks_numeric(cell))
        if filled / best_width >= 0.6 and (numeric / filled if filled else 1.0) <= 0.5:
            return index
    return 0


def _profile_table(path: Path, root: Path) -> FileProfile:
    text, encoding = _decode(path)
    delimiter = _sniff_delimiter(text)
    rows = list(csv.reader(text.splitlines()[:MAX_ROWS_READ], delimiter=delimiter))
    header_row = detect_header_row(rows)
    header = rows[header_row] if rows else []
    names = [cell.strip() or f"col_{i}" for i, cell in enumerate(header)]
    data = [row for row in rows[header_row + 1 :] if any(cell.strip() for cell in row)]

    column_values: list[tuple[str, list[str]]] = [
        (name, [row[i] for row in data if i < len(row)]) for i, name in enumerate(names)
    ]
    columns = detect_table_formats(column_values)

    quality_notes = []
    if path.suffix.lower() == ".txt":
        quality_notes.append(
            "raw .txt table without a GDPdU descriptor; header row is a heuristic guess"
        )
    ragged = sum(1 for row in data if len(row) != len(names))
    if ragged:
        quality_notes.append(f"{ragged} rows have a different field count than the header")

    return FileProfile(
        path=str(path.relative_to(root)),
        kind="table",
        rows=len(data),
        header_row=header_row,
        encoding=encoding,
        delimiter=delimiter,
        columns=columns,
        sample_rows=[row[:20] for row in data[:SAMPLE_ROWS]],
        quality_notes=quality_notes,
    )


def _profile_document(path: Path, root: Path) -> FileProfile:
    text, encoding = _decode(path)
    return FileProfile(
        path=str(path.relative_to(root)),
        kind="document",
        rows=0,
        encoding=encoding,
        sample_rows=[[line] for line in text.splitlines()[:_MD_EXCERPT_LINES] if line.strip()][
            : SAMPLE_ROWS * 2
        ],
    )


def build_deterministic_profile(root: Path) -> DatasetProfile:
    """The non-LLM pass: shape, formats and samples for every source file."""
    inventory = build_inventory(root)
    profile = DatasetProfile(root=str(root))
    for path in [*inventory.tables, *inventory.ledgers]:
        profile.files.append(_profile_table(path, root))
    markdown_files = sorted(
        p for p in root.rglob("*.md") if STALE_DIRNAME not in p.relative_to(root).parts[:-1]
    )
    for path in markdown_files:
        profile.files.append(_profile_document(path, root))
    profile.files.sort(key=lambda f: f.path)
    return profile


def _digest(profile: DatasetProfile) -> str:
    lines = []
    for file in profile.files:
        lines.append(f"## {file.path} [{file.kind}, {file.rows} rows]")
        if file.columns:
            rendered = []
            for column in file.columns:
                fmt = column.date_format or column.decimal_style or ""
                flags = "".join(
                    flag
                    for flag, on in (("!mixed", column.mixed), ("?ambiguous", column.ambiguous))
                    if on
                )
                rendered.append(
                    f"{column.name}({column.inferred_type}{' ' + fmt if fmt else ''}{flags})"
                )
            lines.append("columns: " + ", ".join(rendered))
        for sample in file.sample_rows:
            lines.append("  | " + " ; ".join(sample))
        if file.quality_notes:
            lines.append("notes: " + "; ".join(file.quality_notes))
    return "\n".join(lines)


_PROFILING_BRIEF = """You are profiling an accounting audit dataset. Below is a \
deterministic digest of every source file: detected columns, formats, sample rows.

For EVERY file, return an annotation with:
- description: one sentence saying what the file contains and its role in an audit;
- candidate_keys: column names that look like join keys to other files \
(account numbers, document/invoice numbers, user ids, entry numbers);
- quality_notes: anything a database builder must know (title rows, ragged rows, \
mixed or ambiguous formats, missing headers).

Use exactly the file paths given. Do not invent files or columns.

{digest}"""


def run_profiling_agent(settings: AgentSettings, root: Path, run_dir: Path) -> DatasetProfile:
    """Deterministic survey + one LLM annotation pass; writes ``profile.json``."""
    profile = build_deterministic_profile(root)
    tracer = JsonlTracer(run_dir / "traces.jsonl", agent="profile")
    annotations = run_structured_agent(
        settings=settings,
        name="profile",
        brief=_PROFILING_BRIEF.format(digest=_digest(profile)),
        tools=[],
        response_format=DatasetAnnotations,
        tracer=tracer,
    )
    by_path = {a.path: a for a in annotations.files}
    for file in profile.files:
        annotation = by_path.get(file.path)
        if annotation is None:
            file.quality_notes.append("profiling agent returned no annotation for this file")
            continue
        file.description = annotation.description
        file.candidate_keys = annotation.candidate_keys
        file.quality_notes.extend(annotation.quality_notes)
    write_profile(profile, run_dir)
    return profile


def write_profile(profile: DatasetProfile, run_dir: Path) -> None:
    (run_dir / "profile.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def load_profile(run_dir: Path) -> DatasetProfile:
    return DatasetProfile.model_validate(
        json.loads((run_dir / "profile.json").read_text(encoding="utf-8"))
    )
