"""Deterministic date/number format detection for source columns.

Mixed standards are a real risk: native GDPdU files are German-style
(``DD.MM.YYYY``, decimal comma) while converted spreadsheets emit decimal
points and ISO timestamps, and a foreign dataset may use ``MM/DD/YYYY``.
The profiler classifies every column's values against a fixed candidate set
so the build agent receives each file's formats as facts, not guesses.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from jetai.agents.models import ColumnProfile

SAMPLE_CAP = 5000
# A format family is "genuinely present" above this share of matched values.
MIX_SHARE = 0.02
# A column is date/number typed when this share of non-null values matches.
KIND_SHARE = 0.8

# (family, strptime format, shape regex). Families group formats that share a
# visual shape: two *different* families in one column mean mixed standards,
# while d/m vs m/d inside the "slash" family is the ambiguous case.
_DATE_CANDIDATES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("dot", "%d.%m.%Y", re.compile(r"[0-3]?\d\.[01]?\d\.\d{4}$")),
    ("dot", "%d.%m.%Y %H:%M:%S", re.compile(r"[0-3]?\d\.[01]?\d\.\d{4} \d{1,2}:\d{2}:\d{2}$")),
    ("iso", "%Y-%m-%d", re.compile(r"\d{4}-[01]\d-[0-3]\d$")),
    ("iso", "%Y-%m-%d %H:%M:%S", re.compile(r"\d{4}-[01]\d-[0-3]\d \d{1,2}:\d{2}:\d{2}$")),
    ("iso", "%Y-%m-%dT%H:%M:%S", re.compile(r"\d{4}-[01]\d-[0-3]\dT\d{1,2}:\d{2}:\d{2}$")),
    ("slash", "%d/%m/%Y", re.compile(r"[0-3]?\d/[01]?\d/\d{4}$")),
    ("slash", "%m/%d/%Y", re.compile(r"[01]?\d/[0-3]?\d/\d{4}$")),
    ("time", "%H:%M:%S", re.compile(r"\d{1,2}:\d{2}:\d{2}$")),
)

# Grouped-only values ("1.234" / "1,234") fit both standards, so they are
# counted separately and resolved from surrounding evidence.
_AMBIGUOUS_DOT_GROUPED = re.compile(r"[+-]?\d{1,3}(?:\.\d{3})+$")
_AMBIGUOUS_COMMA_GROUPED = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+$")
_GERMAN_NUMBER = re.compile(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d+$")
_ENGLISH_NUMBER = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+$")
_INTEGER = re.compile(r"[+-]?\d+$")


def _date_matches(value: str) -> list[tuple[str, str]]:
    """Every (family, format) candidate that parses ``value``."""
    matches = []
    for family, fmt, shape in _DATE_CANDIDATES:
        if not shape.fullmatch(value):
            continue
        try:
            datetime.strptime(value, fmt)  # noqa: DTZ007 - format detection, not tz handling
        except ValueError:
            continue
        matches.append((family, fmt))
    return matches


def _number_label(value: str) -> str | None:
    if _AMBIGUOUS_DOT_GROUPED.fullmatch(value):
        return "ambiguous_dot"
    if _AMBIGUOUS_COMMA_GROUPED.fullmatch(value):
        return "ambiguous_comma"
    if _GERMAN_NUMBER.fullmatch(value):
        return "german"
    if _ENGLISH_NUMBER.fullmatch(value):
        return "english"
    if _INTEGER.fullmatch(value):
        return "integer"
    return None


def _classify_date_column(
    name: str,
    families: Counter[str],
    formats: Counter[str],
    slash_dmy_only: int,
    slash_mdy_only: int,
    matched: int,
) -> ColumnProfile:
    present = [f for f, count in families.items() if count / matched > MIX_SHARE]
    mixed = len(present) > 1
    dominant_family = families.most_common(1)[0][0]
    family_formats = {
        "dot": ["%d.%m.%Y", "%d.%m.%Y %H:%M:%S"],
        "iso": ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"],
        "slash": ["%d/%m/%Y", "%m/%d/%Y"],
        "time": ["%H:%M:%S"],
    }[dominant_family]
    date_format = max(family_formats, key=lambda f: formats.get(f, 0))
    ambiguous = False
    note = None

    if dominant_family == "slash":
        if slash_dmy_only and slash_mdy_only:
            mixed = True
            note = "slash dates disagree: some values only fit d/m, others only m/d"
        elif slash_dmy_only:
            date_format = "%d/%m/%Y"
        elif slash_mdy_only:
            date_format = "%m/%d/%Y"
        else:
            ambiguous = True
            date_format = "%d/%m/%Y"
            note = "all day parts <= 12; d/m vs m/d undecidable from this column"
    if mixed and note is None:
        note = f"multiple date standards present: {sorted(present)}"

    if "%H" in date_format and ("%d" in date_format or "%Y" in date_format):
        inferred = "datetime"
    elif date_format == "%H:%M:%S":
        inferred = "time"
    else:
        inferred = "date"
    return ColumnProfile(
        name=name,
        inferred_type=inferred,
        date_format=date_format,
        mixed=mixed,
        ambiguous=ambiguous,
        note=note,
    )


def _classify_number_column(name: str, labels: Counter[str], matched: int) -> ColumnProfile:
    german = labels.get("german", 0)
    english = labels.get("english", 0)
    grouped = labels.get("ambiguous_dot", 0) + labels.get("ambiguous_comma", 0)
    decimals = german + english
    mixed = bool(decimals and german / matched > MIX_SHARE and english / matched > MIX_SHARE)

    if mixed:
        style: str | None = "german" if german >= english else "english"
        note = "both decimal-comma and decimal-point values present"
        ambiguous = False
    elif german:
        style, note, ambiguous = "german", None, False
    elif english:
        style, note, ambiguous = "english", None, False
    elif grouped:
        # Only grouped values like "1.234" — thousands separator or decimal?
        style, ambiguous = None, True
        note = "only digit-grouped values; decimal style undecidable from this column"
    else:
        # Pure integers: castable under either style, nothing to resolve.
        return ColumnProfile(name=name, inferred_type="integer", note="integer-only")

    inferred = "number"
    return ColumnProfile(
        name=name,
        inferred_type=inferred,
        decimal_style=style,
        mixed=mixed,
        ambiguous=ambiguous,
        note=note,
    )


def detect_column_format(name: str, values: list[str]) -> ColumnProfile:
    """Classify one column's non-null values against the candidate formats."""
    sample = [v.strip() for v in values if v is not None and v.strip()][:SAMPLE_CAP]
    if not sample:
        return ColumnProfile(name=name, note="no non-null values")

    date_families: Counter[str] = Counter()
    date_formats: Counter[str] = Counter()
    number_labels: Counter[str] = Counter()
    slash_dmy_only = slash_mdy_only = 0
    date_values = number_values = 0

    for value in sample:
        matches = _date_matches(value)
        if matches:
            date_values += 1
            for family in {family for family, _ in matches}:
                date_families[family] += 1
            for _, fmt in matches:
                date_formats[fmt] += 1
            slash_formats = {fmt for family, fmt in matches if family == "slash"}
            if slash_formats == {"%d/%m/%Y"}:
                slash_dmy_only += 1
            elif slash_formats == {"%m/%d/%Y"}:
                slash_mdy_only += 1
            continue
        label = _number_label(value)
        if label:
            number_values += 1
            number_labels[label] += 1

    if date_values / len(sample) >= KIND_SHARE:
        return _classify_date_column(
            name, date_families, date_formats, slash_dmy_only, slash_mdy_only, date_values
        )
    if number_values / len(sample) >= KIND_SHARE:
        return _classify_number_column(name, number_labels, number_values)
    return ColumnProfile(name=name, inferred_type="text")


def detect_table_formats(columns: list[tuple[str, list[str]]]) -> list[ColumnProfile]:
    """Classify every column, then resolve per-column ambiguity from file-level style.

    A column whose data cannot discriminate (grouped-only numbers, slash dates
    with all day parts <= 12) adopts the unanimous style of the file's
    unambiguous columns; failing that it keeps a documented default and stays
    flagged for the build agent.
    """
    profiles = [detect_column_format(name, values) for name, values in columns]

    decimal_styles = {p.decimal_style for p in profiles if p.decimal_style and not p.ambiguous}
    if len(decimal_styles) == 1:
        (file_style,) = decimal_styles
        for profile in profiles:
            if profile.ambiguous and profile.inferred_type == "number":
                profile.decimal_style = file_style
                profile.note = f"adopted the file's unambiguous {file_style} decimal style"

    slash_formats = {
        p.date_format
        for p in profiles
        if p.date_format in ("%d/%m/%Y", "%m/%d/%Y") and not p.ambiguous and not p.mixed
    }
    if len(slash_formats) == 1:
        (file_slash,) = slash_formats
        for profile in profiles:
            if profile.ambiguous and profile.date_format in ("%d/%m/%Y", "%m/%d/%Y"):
                profile.date_format = file_slash
                profile.note = f"adopted the file's unambiguous slash date order {file_slash}"

    return profiles
