"""Deterministic profiling: header detection and file survey (no LLM)."""

from __future__ import annotations

from pathlib import Path

from jetai.agents.profiling import build_deterministic_profile, detect_header_row


def test_header_on_first_row() -> None:
    rows = [["Konto", "Saldo"], ["100000", "1.234,56"]]
    assert detect_header_row(rows) == 0


def test_header_under_title_rows() -> None:
    rows = [
        ["Muster GmbH — Saldenliste per 31.12.2025", "", "", ""],
        ["", "", "", ""],
        ["Konto", "Bezeichnung", "Kontenart", "Saldo"],
        ["100000", "Kasse", "Bilanz", "1.234,56"],
    ]
    assert detect_header_row(rows) == 2


def test_header_under_two_title_rows() -> None:
    rows = [
        ["Muster Verpackungen GmbH, Musterhausen", "", "", "", "", ""],
        ["Summen- und Saldenliste per 31.12.2025", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["Konto", "Bezeichnung", "Kontenart", "EB", "Soll", "Haben"],
        ["100000", "Kasse", "Bilanz", "1", "2", "3"],
    ]
    assert detect_header_row(rows) == 3


def test_deterministic_profile_surveys_tables_and_documents(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    root.mkdir()
    (root / "vendors.csv").write_text(
        "vendor_id;name;amount;since\n"
        "V1;Alpha GmbH;1.234,56;01.02.2025\n"
        "V2;Beta KG;99,10;15.03.2025\n",
        encoding="utf-8",
    )
    (root / "paper.md").write_text("# Planung\nWesentlichkeit 400.000 EUR", encoding="utf-8")
    (root / "orphan.txt").write_bytes(b'"1";"x"\r\n"2";"y"\r\n')

    profile = build_deterministic_profile(root)
    by_path = {f.path: f for f in profile.files}

    vendors = by_path["vendors.csv"]
    assert vendors.rows == 2
    assert vendors.delimiter == ";"
    columns = {c.name: c for c in vendors.columns}
    assert columns["amount"].decimal_style == "german"
    assert columns["since"].date_format == "%d.%m.%Y"
    assert columns["name"].inferred_type == "text"

    assert by_path["paper.md"].kind == "document"
    orphan = by_path["orphan.txt"]
    assert any("descriptor" in note for note in orphan.quality_notes)
