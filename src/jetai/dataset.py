"""Discovery and inventory of the source documents that make up an audit dataset.

A dataset is a directory tree of GDPdU exports (``.txt`` ledgers with their
``index.xml`` / ``.dtd`` descriptors) alongside supporting workbooks, working
papers and statements (``.csv`` / ``.xlsx`` / ``.xls`` / ``.docx`` / ``.pdf``). These
helpers locate that tree and group the files by kind so the rest of the agent
can plan which reader to apply to each document.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

# Extensions the agent knows how to ingest, grouped by the reader they need.
LEDGER_SUFFIXES = frozenset({".txt"})
TABLE_SUFFIXES = frozenset({".csv", ".xlsx", ".xls"})
DOCUMENT_SUFFIXES = frozenset({".docx", ".pdf"})

# Descriptor and OS artefacts that are not audit content.
IGNORED_SUFFIXES = frozenset({".dtd", ".xml"})
IGNORED_NAMES = frozenset({".DS_Store"})

# Archived originals live here once preprocessing has converted them; excluded
# from inventories so a second preprocessing run doesn't reprocess them.
STALE_DIRNAME = "stale"


@dataclass(frozen=True)
class SourceInventory:
    """Grouped view of the ingestible files found under a dataset root."""

    root: Path
    ledgers: list[Path] = field(default_factory=list)
    tables: list[Path] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)

    @property
    def all_files(self) -> list[Path]:
        """Every ingestible file, sorted by path."""
        return sorted([*self.ledgers, *self.tables, *self.documents])


def _is_ignored(path: Path) -> bool:
    """Whether a path is an OS artefact, GDPdU descriptor or editor lock file."""
    if path.name in IGNORED_NAMES or path.name.startswith("~$"):
        return True
    return path.suffix.lower() in IGNORED_SUFFIXES


def _has_ledger(root: Path) -> bool:
    """Whether any ledger-like export exists anywhere beneath ``root``.

    GDPdU exports ship ``.txt`` ledgers; other accounting software exports
    plain tables — either marks a dataset root.
    """
    ingestible = LEDGER_SUFFIXES | TABLE_SUFFIXES
    return any(
        child.is_file() and child.suffix.lower() in ingestible and not _is_ignored(child)
        for child in root.rglob("*")
    )


def find_dataset_root(start: Path) -> Path:
    """Return the dataset root at or beneath ``start``.

    ``start`` may be the dataset directory itself (a directory whose children are
    the category folders) or a wrapper that nests it — for example the
    repository's ``data/`` folder. Pass-through wrappers that hold nothing but a
    single subdirectory are descended into. Raises :class:`FileNotFoundError`
    when no ledger export can be located.
    """
    start = start.expanduser().resolve()
    if not start.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {start}")

    current = start
    while True:
        children = [c for c in current.iterdir() if not _is_ignored(c)]
        subdirs = [c for c in children if c.is_dir()]
        has_direct_files = any(c.is_file() for c in children)
        if not has_direct_files and len(subdirs) == 1:
            current = subdirs[0]
            continue
        break

    if not _has_ledger(current):
        raise FileNotFoundError(f"No ledger or table exports found under: {start}")
    return current


def _walk_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_ignored(path):
            continue
        if STALE_DIRNAME in path.relative_to(root).parts[:-1]:
            continue
        yield path


def build_inventory(root: Path) -> SourceInventory:
    """Group every ingestible file under ``root`` by the reader it requires."""
    inventory = SourceInventory(root=root.expanduser().resolve())
    for path in _walk_files(inventory.root):
        suffix = path.suffix.lower()
        if suffix in LEDGER_SUFFIXES:
            inventory.ledgers.append(path)
        elif suffix in TABLE_SUFFIXES:
            inventory.tables.append(path)
        elif suffix in DOCUMENT_SUFFIXES:
            inventory.documents.append(path)
    return inventory
