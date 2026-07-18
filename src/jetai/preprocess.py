"""Convert audit source documents into greppable text.

Every ``.xlsx`` workbook becomes one or more ``;``-separated ``.csv`` files
(one per sheet) and every ``.docx``/``.pdf`` becomes a single ``.md`` file.
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

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pdfplumber
from markitdown import MarkItDown

from jetai.dataset import STALE_DIRNAME, build_inventory

_SHEET_NAME_RE = re.compile(r"[^\w\-]+")

_markitdown = MarkItDown()


@dataclass
class PreprocessResult:
    """Paths written and archived by a :func:`preprocess_dataset` run."""

    converted: list[Path] = field(default_factory=list)
    archived: list[Path] = field(default_factory=list)


def _convert_xlsx(path: Path) -> list[Path]:
    """Write each sheet of ``path`` to its own ``;``-separated csv."""
    sheets = pd.read_excel(path, sheet_name=None)
    if len(sheets) == 1:
        (frame,) = sheets.values()
        out = path.with_suffix(".csv")
        frame.to_csv(out, sep=";", index=False)
        return [out]

    outputs = []
    for name, frame in sheets.items():
        safe_name = _SHEET_NAME_RE.sub("_", name).strip("_")
        out = path.with_name(f"{path.stem}__{safe_name}.csv")
        frame.to_csv(out, sep=";", index=False)
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


def preprocess_dataset(root: Path) -> PreprocessResult:
    """Convert every xlsx/docx/pdf under ``root`` and archive the originals."""
    root = root.expanduser().resolve()
    inventory = build_inventory(root)
    result = PreprocessResult()

    for path in inventory.tables:
        if path.suffix.lower() != ".xlsx":
            continue
        result.converted.extend(_convert_xlsx(path))
        result.archived.append(_archive(path, root))

    for path in inventory.documents:
        convert = _convert_pdf if path.suffix.lower() == ".pdf" else _convert_docx
        result.converted.append(convert(path))
        result.archived.append(_archive(path, root))

    return result
