"""Value types: partial dates, counts, times, float32 values and coordinates, with
Scythebill's (and Java's) exact rules."""

from __future__ import annotations

import struct
from datetime import time
from pathlib import Path

import pytest

from pipit.domain.partial_date import (
    PartialDate,
    PartialField,
    format_partial_date,
    parse_partial_date,
    parse_with_century_fix,
)
from pipit.domain.values import (
    ApproximateNumber,
    LatLong,
    format_time,
    is_valid_uri,
    java_float_to_string,
    normalize_file_localhost,
    parse_float32,
    parse_time,
    round_three_digits,
)

JAVA_FLOATS = Path(__file__).parents[1] / "fixtures" / "java" / "floats.tsv"


@pytest.mark.parametrize(
    ("text", "fields"),
    [
        ("2025-05-01", ((PartialField.YEAR, 2025), (PartialField.MONTH, 5), (PartialField.DAY, 1))),
        ("2025", ((PartialField.YEAR, 2025),)),
        ("2025-06", ((PartialField.YEAR, 2025), (PartialField.MONTH, 6))),
        ("M05-12", ((PartialField.MONTH, 5), (PartialField.DAY, 12))),
        (
            "2025-02-30",
            ((PartialField.YEAR, 2025), (PartialField.MONTH, 2), (PartialField.DAY, 30)),
        ),
    ],
)
def test_partial_dates_round_trip(text: str, fields: tuple[tuple[PartialField, int], ...]) -> None:
    date = parse_partial_date(text)
    assert date.fields == fields
    assert format_partial_date(date) == text


def test_skipped_fields_get_a_letter() -> None:
    date = parse_partial_date("y2020-d05")
    assert date.fields == ((PartialField.YEAR, 2020), (PartialField.DAY, 5))
    assert format_partial_date(date) == "2020-d05"
    assert parse_partial_date("2025-") == PartialDate.of(2025)  # as Scythebill accepts it


@pytest.mark.parametrize("text", ["garbage", "y", "2025-05-01-12-30-15-9", "2025-x5", "-1"])
def test_invalid_partial_dates(text: str) -> None:
    with pytest.raises(ValueError):
        parse_partial_date(text)


def test_century_fix() -> None:
    assert parse_with_century_fix("25-05-02") == PartialDate.of(2025, 5, 2)
    assert parse_with_century_fix("99") == PartialDate.of(1999)
    assert parse_with_century_fix("M05") == PartialDate().with_field(PartialField.MONTH, 5)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("12", "12"), (" ~20 ", "~20"), (">100", ">100"), ("~+4", "~4"), ("+3", "+3"),
     ("0", None), ("-5", None), ("", None), ("x", None), ("2147483648", None), ("~0", None)],
)  # fmt: skip
def test_approximate_numbers(text: str, expected: str | None) -> None:
    parsed = ApproximateNumber.parse(text)
    assert (None if parsed is None else str(parsed)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("7:05", time(7, 5)), ("07:05", time(7, 5)), ("23:59", time(23, 59)), ("25:00", None),
     ("7:5", None), ("0705", None), ("", None), ("7 :05", None)],
)  # fmt: skip
def test_times(text: str, expected: time | None) -> None:
    assert parse_time(text) == expected
    if expected is not None:
        assert parse_time(format_time(expected)) == expected


def test_java_float_formatting_matches_java() -> None:
    """Ground truth recorded from Java's Float.toString and Float.parseFloat."""
    for line in JAVA_FLOATS.read_text().splitlines():
        parts = line.split("\t")
        if parts[0] == "parse":
            parsed = parse_float32(parts[1])
            assert parsed is not None
            assert f"{struct.unpack('<I', struct.pack('<f', parsed))[0]:x}" == parts[2], parts[1]
        else:
            value = struct.unpack("<f", struct.pack("<I", int(parts[0], 16)))[0]
            assert java_float_to_string(value) == parts[1], parts[0]


@pytest.mark.parametrize(
    ("raw", "written"),
    [("3.21456", "3.215"), ("0.0005", "0.001"), ("1e-4", "0.0"), ("12345678.9", "1.2345679E7"),
     ("0.40468564", "0.405"), ("5", "5.0")],
)  # fmt: skip
def test_three_digit_rounding(raw: str, written: str) -> None:
    value = parse_float32(raw)
    assert value is not None
    assert java_float_to_string(round_three_digits(value)) == written


def test_float_parsing_rejects_non_numbers() -> None:
    assert parse_float32("abc") is None
    assert parse_float32("1.5f") == 1.5
    assert parse_float32("") is None


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [("38.0682", "-122.8806", ("38.0682000", "-122.8806000")),
     ("38,1", "-122,9", ("38.1000000", "-122.9000000")),
     ("-0.00000001", "12.345678951", ("-0.0000000", "12.3456790")),
     ("0.5E1", "2.25E-1", ("5.0000000", "0.2250000"))],
)  # fmt: skip
def test_coordinates(latitude: str, longitude: str, expected: tuple[str, str]) -> None:
    parsed = LatLong.parse(latitude, longitude)
    assert (parsed.latitude, parsed.longitude) == expected


@pytest.mark.parametrize(("latitude", "longitude"), [("1.5E2", "0"), ("", "1"), ("1x", "2")])
def test_invalid_coordinates(latitude: str, longitude: str) -> None:
    with pytest.raises(ValueError):
        LatLong.parse(latitude, longitude)


def test_links() -> None:
    assert is_valid_uri("https://example.org/a.jpg")
    assert not is_valid_uri("not a uri")
    assert not is_valid_uri("1http://x")
    assert normalize_file_localhost("file://localhost/home/x.jpg") == "file:/home/x.jpg"
    assert normalize_file_localhost("file://localhostish/x") == "file://localhostish/x"
