"""GDPdU descriptor parsing and ledger conversion round-trip."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from jetai.preprocess import _parse_gdpdu_tables, preprocess_dataset

_INDEX_XML = """<?xml version="1.0" encoding="utf-8"?>
<DataSet>
  <Version>1</Version>
  <Media>
    <Name>1</Name>
    <Table>
      <URL>Lieferanten.txt</URL>
      <Name>Lieferanten</Name>
      <VariableLength>
        <TextEncapsulator>"</TextEncapsulator>
        <VariableColumn><Name>KONTO</Name><AlphaNumeric /></VariableColumn>
        <VariableColumn><Name>NAME</Name><AlphaNumeric /></VariableColumn>
        <VariableColumn><Name>WÄHRUNG</Name><AlphaNumeric /></VariableColumn>
      </VariableLength>
    </Table>
  </Media>
</DataSet>
"""


@pytest.fixture
def gdpdu_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    ledger_dir = root / "Kreditoren"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "index.xml").write_text(_INDEX_XML, encoding="utf-8")
    rows = [
        '"200001";"Müller GmbH";"EUR"',
        '"200002";"Schröder & Söhne";"EUR"',
        '"200003";"Kurz KG"',  # field count mismatch: kept, counted
    ]
    (ledger_dir / "Lieferanten.txt").write_bytes("\r\n".join(rows).encode("cp1252"))
    (ledger_dir / "Orphan.txt").write_bytes(b'"1";"x"\r\n')  # no descriptor entry
    return root


def test_parse_gdpdu_tables_reads_every_table(gdpdu_dataset: Path) -> None:
    tables = _parse_gdpdu_tables(gdpdu_dataset / "Kreditoren" / "index.xml")
    assert tables == {"Lieferanten.txt": ["KONTO", "NAME", "WÄHRUNG"]}


def test_convert_ledger_round_trip(gdpdu_dataset: Path) -> None:
    result = preprocess_dataset(gdpdu_dataset)

    out = gdpdu_dataset / "Kreditoren" / "Lieferanten.csv"
    assert out in result.converted
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[0] == ["KONTO", "NAME", "WÄHRUNG"]
    assert rows[1] == ["200001", "Müller GmbH", "EUR"]  # cp1252 umlauts survive
    assert rows[3] == ["200003", "Kurz KG"]  # mismatched row kept
    assert result.mismatched_rows[out] == 1


def test_original_archived_and_orphan_left_in_place(gdpdu_dataset: Path) -> None:
    preprocess_dataset(gdpdu_dataset)

    assert not (gdpdu_dataset / "Kreditoren" / "Lieferanten.txt").exists()
    assert (gdpdu_dataset / "stale" / "Kreditoren" / "Lieferanten.txt").exists()
    # A ledger without a descriptor stays for the profiler to flag.
    assert (gdpdu_dataset / "Kreditoren" / "Orphan.txt").exists()


def test_gdpdu_conversion_is_idempotent(gdpdu_dataset: Path) -> None:
    preprocess_dataset(gdpdu_dataset)
    second = preprocess_dataset(gdpdu_dataset)
    assert not second.converted
