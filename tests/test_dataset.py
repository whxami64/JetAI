"""Tests for dataset discovery and inventory."""

from __future__ import annotations

from pathlib import Path

import pytest

from jetai.dataset import build_inventory, find_dataset_root


@pytest.fixture
def sample_dataset(tmp_path: Path) -> Path:
    """A miniature dataset mirroring the real GDPdU layout under a ``data`` parent."""
    root = tmp_path / "data" / "Uebungsdaten Muster"
    (root / "Sachkonten").mkdir(parents=True)
    (root / "Begleitdokumente").mkdir()

    (root / "Sachkonten" / "Sachkontobuchungen.txt").write_text("x", encoding="cp1252")
    (root / "Sachkonten" / "index.xml").write_text("<x/>", encoding="utf-8")
    (root / "Sachkonten" / "gdpdu-01-08-2002.dtd").write_text("", encoding="utf-8")
    csv = root / "Begleitdokumente" / "Stammdatenaenderungen_2025.csv"
    csv.write_text("a;b", encoding="utf-8")
    (root / "Begleitdokumente" / "Saldenliste_2025.xlsx").write_bytes(b"PK")
    (root / "Begleitdokumente" / "Saldenliste_2024.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    (root / "Begleitdokumente" / "Pruefungsplanung_JET_2025.docx").write_bytes(b"PK")
    (root / "Begleitdokumente" / "JA-Entwurf_2025.pdf").write_bytes(b"%PDF")
    # Noise that must be ignored.
    (root / ".DS_Store").write_bytes(b"\x00")
    (root / "Begleitdokumente" / "~$uefungsplanung_JET_2025.docx").write_bytes(b"PK")
    return tmp_path / "data"


def test_find_dataset_root_descends_into_dataset(sample_dataset: Path) -> None:
    root = find_dataset_root(sample_dataset)
    assert root.name == "Uebungsdaten Muster"


def test_find_dataset_root_accepts_dataset_itself(sample_dataset: Path) -> None:
    dataset = sample_dataset / "Uebungsdaten Muster"
    assert find_dataset_root(dataset) == dataset.resolve()


def test_find_dataset_root_missing_path() -> None:
    with pytest.raises(FileNotFoundError):
        find_dataset_root(Path("/no/such/dataset"))


def test_build_inventory_groups_by_kind(sample_dataset: Path) -> None:
    inventory = build_inventory(find_dataset_root(sample_dataset))
    assert [p.name for p in inventory.ledgers] == ["Sachkontobuchungen.txt"]
    assert sorted(p.name for p in inventory.tables) == [
        "Saldenliste_2024.xls",
        "Saldenliste_2025.xlsx",
        "Stammdatenaenderungen_2025.csv",
    ]
    assert sorted(p.name for p in inventory.documents) == [
        "JA-Entwurf_2025.pdf",
        "Pruefungsplanung_JET_2025.docx",
    ]


def test_build_inventory_ignores_descriptors_and_artefacts(sample_dataset: Path) -> None:
    inventory = build_inventory(find_dataset_root(sample_dataset))
    names = {p.name for p in inventory.all_files}
    assert ".DS_Store" not in names
    assert "index.xml" not in names
    assert "gdpdu-01-08-2002.dtd" not in names
    assert not any(n.startswith("~$") for n in names)
