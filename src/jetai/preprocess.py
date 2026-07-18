"""Convert audit source documents into greppable text.

Every ``.xlsx``/``.xls`` workbook becomes one or more ``;``-separated ``.csv``
files (one per sheet) and every ``.docx``/``.pdf`` becomes a single ``.md`` file.
Converted originals are relocated to ``<dataset root>/stale/<relative path>``
so the dataset only holds greppable text once preprocessing has run.

PDF conversion uses ``pdfplumber`` rather than ``markitdown``'s default pdf
backend: for label/value layouts common in financial statement extracts,
markitdown's pdfminer-based backend emits every label followed by every
value, which severs the line-level association a reader (or a grep) relies
on. ``pdfplumber.extract_text`` reconstructs rows from glyph positions and
keeps a label and its value on the same line. ``pdfplumber`` ships as part of
the ``markitdown[pdf]`` extra, so this costs no extra dependency.
"""

from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pdfplumber
from markitdown import MarkItDown

from jetai.dataset import STALE_DIRNAME, build_inventory

_SHEET_NAME_RE = re.compile(r"[^\w\-]+")
_SPREADSHEET_SUFFIXES = frozenset({".xlsx", ".xls"})
_GDPDU_INDEX_NAME = "index.xml"

_markitdown = MarkItDown()


@dataclass
class PreprocessResult:
    """Paths written and archived by a :func:`preprocess_dataset` run."""

    converted: list[Path] = field(default_factory=list)
    archived: list[Path] = field(default_factory=list)
    # csv output -> number of rows whose field count mismatched the descriptor
    # (rows are kept; a nonzero count flags the file for the profiler).
    mismatched_rows: dict[Path, int] = field(default_factory=dict)


def _parse_gdpdu_tables(index_xml: Path) -> dict[str, list[str]]:
    """Map each ``<Table>`` URL in a GDPdU ``index.xml`` to its ordered column names.

    Follows the published GDPdU descriptor standard: nothing about specific
    table names, column names or counts is assumed.
    """
    root = ET.parse(index_xml).getroot()
    tables: dict[str, list[str]] = {}
    for table in root.iter("Table"):
        url = table.findtext("URL")
        if not url:
            continue
        columns = [
            name.text.strip()
            for name in table.findall(".//VariableColumn/Name")
            if name.text and name.text.strip()
        ]
        if columns:
            tables[url] = columns
    return tables


def _decode_ledger(path: Path) -> str:
    """Decode a GDPdU ledger; both encodings occur within a single export."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _convert_ledger(txt: Path, columns: list[str]) -> tuple[Path, int]:
    """Write ``txt`` as a ``;``-separated UTF-8 csv with the descriptor's header row.

    Values stay raw (decimal commas, ``DD.MM.YYYY`` dates untouched) — typing
    happens in SQL at build time. Rows whose field count mismatches the
    descriptor are kept and counted, not dropped.
    """
    rows = list(csv.reader(_decode_ledger(txt).splitlines(), delimiter=";", quotechar='"'))
    mismatched = sum(1 for row in rows if len(row) != len(columns))

    out = txt.with_suffix(".csv")
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", quotechar='"')
        writer.writerow(columns)
        writer.writerows(rows)
    return out, mismatched


def _convert_spreadsheet(path: Path) -> list[Path]:
    """Write each sheet of ``path`` (``.xlsx`` or ``.xls``) to its own ``;``-separated csv.

    Sheets are written row-for-row (``header=None``): letting pandas treat the
    first row as a header would turn title rows into ``Unnamed: N`` column
    names and hide the real header from the profiler's detection.
    """
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    if len(sheets) == 1:
        (frame,) = sheets.values()
        out = path.with_suffix(".csv")
        frame.to_csv(out, sep=";", index=False, header=False)
        return [out]

    outputs = []
    for name, frame in sheets.items():
        safe_name = _SHEET_NAME_RE.sub("_", name).strip("_")
        out = path.with_name(f"{path.stem}__{safe_name}.csv")
        frame.to_csv(out, sep=";", index=False, header=False)
        outputs.append(out)
    return outputs


def _convert_pdf(path: Path) -> Path:
    lines = [f"# {path.stem}", ""]
    with pdfplumber.open(path) as pdf:
        multi_page = len(pdf.pages) > 1
        for number, page in enumerate(pdf.pages, start=1):
            if multi_page:
                lines.append(f"## Page {number}")
            lines.append(page.extract_text() or "")
            lines.append("")
    out = path.with_suffix(".md")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _convert_docx(path: Path) -> Path:
    out = path.with_suffix(".md")
    out.write_text(_markitdown.convert(str(path)).text_content, encoding="utf-8")
    return out


def _archive(path: Path, root: Path) -> Path:
    """Move ``path`` into ``root/stale/<relative path>``."""
    destination = root / STALE_DIRNAME / path.relative_to(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return path.rename(destination)


def _reencode_csvs(root: Path, result: PreprocessResult) -> None:
    """Re-encode every non-UTF-8 source csv to UTF-8, archiving the original.

    DuckDB's ``read_csv`` cannot read cp1252, so a single legacy-encoded
    supporting file otherwise sends the build agent into encoding
    trial-and-error. Content is transcoded byte-for-byte (no reparsing), so
    structure and quoting stay exactly as exported.
    """
    for path in build_inventory(root).tables:
        if path.suffix.lower() != ".csv":
            continue
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
            continue  # already fine, leave untouched
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        archived = _archive(path, root)
        path.write_text(text, encoding="utf-8")
        result.converted.append(path)
        result.archived.append(archived)


def _convert_gdpdu_exports(root: Path, result: PreprocessResult) -> None:
    """Convert every ``.txt`` ledger described by an ``index.xml`` beneath ``root``.

    A ``.txt`` ledger *without* a descriptor is left in place — the profiling
    agent will flag it (that is the generalization path for non-GDPdU software,
    whose CSVs usually ship their own headers).
    """
    for index_xml in sorted(root.rglob(_GDPDU_INDEX_NAME)):
        if STALE_DIRNAME in index_xml.relative_to(root).parts[:-1]:
            continue
        for url, columns in _parse_gdpdu_tables(index_xml).items():
            source = index_xml.parent / url
            if not source.is_file() or source.suffix.lower() != ".txt":
                continue
            out, mismatched = _convert_ledger(source, columns)
            result.converted.append(out)
            if mismatched:
                result.mismatched_rows[out] = mismatched
            result.archived.append(_archive(source, root))


def preprocess_dataset(root: Path) -> PreprocessResult:
    """Convert every GDPdU txt/xlsx/xls/docx/pdf under ``root`` and archive the originals."""
    root = root.expanduser().resolve()
    inventory = build_inventory(root)
    result = PreprocessResult()

    _convert_gdpdu_exports(root, result)

    for path in inventory.tables:
        if path.suffix.lower() not in _SPREADSHEET_SUFFIXES:
            continue
        result.converted.extend(_convert_spreadsheet(path))
        result.archived.append(_archive(path, root))

    for path in inventory.documents:
        convert = _convert_pdf if path.suffix.lower() == ".pdf" else _convert_docx
        result.converted.append(convert(path))
        result.archived.append(_archive(path, root))

    _reencode_csvs(root, result)
    return result
