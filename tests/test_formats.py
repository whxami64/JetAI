"""Deterministic date/number format detection."""

from __future__ import annotations

from jetai.agents.formats import detect_column_format, detect_table_formats


def test_german_decimal_column() -> None:
    profile = detect_column_format("BETRAG", ["1.234,56", "12,00", "-987,10"])
    assert profile.inferred_type == "number"
    assert profile.decimal_style == "german"
    assert not profile.mixed and not profile.ambiguous


def test_english_decimal_column() -> None:
    profile = detect_column_format("amount", ["1,234.56", "12.00", "-0.5"])
    assert profile.decimal_style == "english"
    assert not profile.mixed


def test_genuinely_mixed_decimal_styles() -> None:
    values = ["12,5"] * 10 + ["12.5"] * 10
    profile = detect_column_format("betrag", values)
    assert profile.mixed


def test_integer_only_column_is_not_flagged() -> None:
    profile = detect_column_format("KONTO", ["100000", "200000", "300000"])
    assert profile.inferred_type == "integer"
    assert not profile.ambiguous


def test_grouped_only_values_are_ambiguous() -> None:
    profile = detect_column_format("betrag", ["1.234", "2.345", "10.000"])
    assert profile.inferred_type == "number"
    assert profile.ambiguous
    assert profile.decimal_style is None


def test_german_date_column() -> None:
    profile = detect_column_format("DATUM", ["31.12.2025", "01.01.2025"])
    assert profile.inferred_type == "date"
    assert profile.date_format == "%d.%m.%Y"


def test_iso_date_column() -> None:
    profile = detect_column_format("date", ["2025-12-31", "2025-01-01"])
    assert profile.date_format == "%Y-%m-%d"


def test_iso_datetime_column() -> None:
    profile = detect_column_format("ts", ["2025-12-31 23:59:59", "2025-01-01 00:00:00"])
    assert profile.inferred_type == "datetime"
    assert profile.date_format == "%Y-%m-%d %H:%M:%S"


def test_time_only_column() -> None:
    profile = detect_column_format("ERFASSUNGSZEIT", ["21:03:11", "09:15:43"])
    assert profile.inferred_type == "time"
    assert profile.date_format == "%H:%M:%S"


def test_slash_dates_disambiguated_by_high_day() -> None:
    profile = detect_column_format("date", ["13/02/2025", "01/02/2025"])
    assert profile.date_format == "%d/%m/%Y"
    assert not profile.ambiguous


def test_slash_dates_all_days_below_13_are_ambiguous() -> None:
    profile = detect_column_format("date", ["01/02/2025", "03/04/2025"])
    assert profile.ambiguous
    assert profile.date_format == "%d/%m/%Y"  # documented default


def test_mixed_date_standards_flagged() -> None:
    values = ["31.12.2025"] * 10 + ["2025-12-31"] * 10
    profile = detect_column_format("datum", values)
    assert profile.mixed


def test_file_level_decimal_resolution() -> None:
    profiles = detect_table_formats(
        [
            ("betrag", ["1.234,56", "12,00"]),  # unambiguously german
            ("netto", ["1.234", "2.345", "10.000"]),  # grouped-only: undecidable alone
        ]
    )
    by_name = {p.name: p for p in profiles}
    assert by_name["netto"].decimal_style == "german"
    assert by_name["netto"].ambiguous  # stays flagged: style was adopted, not observed


def test_file_level_slash_resolution() -> None:
    profiles = detect_table_formats(
        [
            ("shipped", ["13/02/2025", "14/02/2025"]),
            ("ordered", ["01/02/2025", "03/04/2025"]),
        ]
    )
    by_name = {p.name: p for p in profiles}
    assert by_name["ordered"].date_format == "%d/%m/%Y"


def test_empty_and_text_columns() -> None:
    assert detect_column_format("x", []).inferred_type == "text"
    assert detect_column_format("name", ["Alpha GmbH", "Beta KG"]).inferred_type == "text"
