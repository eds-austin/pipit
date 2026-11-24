"""Small value types with Scythebill's exact parsing and formatting rules.

- ``ApproximateNumber``: ``model/.../sighting/ApproximateNumber.kt``
- times: ``model/.../io/TimeIO.kt``
- float32 values and Java's ``Float.toString``: ``Area.kt`` and ``Distance.kt`` store
  32-bit floats rounded to three decimals and write them with ``Float.toString``
- coordinates: ``LatLongCoordinates.kt`` (seven decimals, its own number parser)
- links: ``Link.kt`` (URI validity, ``file://localhost`` normalization)
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from datetime import time
from fractions import Fraction

_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1
_KOTLIN_INT = re.compile(r"[+-]?\d+")  # Kotlin toIntOrNull: optional sign, Unicode digits


def kotlin_int_or_none(text: str) -> int | None:
    if not _KOTLIN_INT.fullmatch(text):
        return None
    value = int(text)
    return value if _INT_MIN <= value <= _INT_MAX else None


# ------------------------------------------------------------------ counts


@dataclass(frozen=True, slots=True)
class ApproximateNumber:
    """A positive count with an optional one-character prefix ("~20", ">100")."""

    number: int
    prefix: str = ""

    @property
    def is_exact(self) -> bool:
        return not self.prefix

    def __str__(self) -> str:
        return f"{self.prefix}{self.number}"

    @staticmethod
    def parse(text: str) -> ApproximateNumber | None:
        """``ApproximateNumber.tryParse``: None for anything that isn't a valid count."""
        trimmed = text.strip()
        if not trimmed:
            return None
        if "0" <= trimmed[0] <= "9":
            exact = kotlin_int_or_none(trimmed)
            return ApproximateNumber(exact) if exact is not None and exact > 0 else None
        number = kotlin_int_or_none(trimmed[1:])
        if number is None or number <= 0 or trimmed[0] == "-":
            return None
        return ApproximateNumber(number, trimmed[0])


# ------------------------------------------------------------------ times


def format_time(value: time) -> str:
    """``TimeIO.toString``: "HH:mm"."""
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_time(text: str) -> time | None:
    """``TimeIO.fromString``: "H:mm" or "HH:mm"; None if invalid."""
    normalized = text.replace("\u00a0", " ").replace("\u202f", " ")
    hour_part, colon, minute_part = normalized.partition(":")
    if not colon:
        return None
    if not hour_part or len(hour_part) > 2 or not hour_part.isdecimal():
        return None
    if len(minute_part) != 2 or not minute_part.isdecimal():
        return None
    hour = int(hour_part)
    minute = int(minute_part)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


# ------------------------------------------------------------------ float32


def float32(value: float) -> float:
    """Round a double to the nearest float32 (ties to even)."""
    if math.isnan(value) or math.isinf(value):
        return value
    try:
        rounded: float = struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)
    return rounded


def _float32_neighbors(value: float) -> tuple[float, float]:
    bits: int = struct.unpack("<I", struct.pack("<f", value))[0]
    if value == 0:
        tiny: float = struct.unpack("<f", struct.pack("<I", 1))[0]
        return -tiny, tiny
    below: float = struct.unpack("<f", struct.pack("<I", bits - 1))[0]
    above: float = struct.unpack("<f", struct.pack("<I", bits + 1))[0]
    return (below, above) if value > 0 else (above, below)


def _float32_of_fraction(exact: Fraction) -> float:
    """The float32 nearest to an exact rational (correct rounding, ties to even)."""
    candidate = float32(float(exact))
    if math.isinf(candidate):
        return candidate
    best = candidate
    for neighbor in _float32_neighbors(candidate):
        if math.isinf(neighbor):
            continue
        distance = abs(Fraction(neighbor) - exact)
        best_distance = abs(Fraction(best) - exact)
        if distance < best_distance or (
            distance == best_distance
            and struct.unpack("<I", struct.pack("<f", neighbor))[0] % 2 == 0
        ):
            best = neighbor
    return best


_JAVA_FLOAT = re.compile(
    r"[+-]?(NaN|Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)[fFdD]?"
)


def parse_float32(text: str) -> float | None:
    """Kotlin ``String.toFloatOrNull`` (decimal forms; correctly rounded to float32)."""
    if not _JAVA_FLOAT.fullmatch(text):
        return None
    body = text.rstrip("fFdD")
    if body.lstrip("+-") in ("NaN", "Infinity"):
        return float(body.replace("Infinity", "inf"))
    return _float32_of_fraction(Fraction(body))


def round_three_digits(value: float) -> float:
    """``Area/Distance.roundAtThreeDigits`` in float32 arithmetic."""
    scaled = float32(float32(value * 1000.0) + 0.5)
    return float32(float32(math.floor(scaled)) / 1000.0)


def java_float_to_string(value: float) -> str:
    """Java's ``Float.toString`` (JDK 19+): the shortest decimal that rounds back to the
    float32 (at least two digits when the shortest has one), closest to it."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    exact = Fraction(value)
    negative = exact < 0
    exact = abs(exact)
    digits, exponent = _shortest_digits(exact, value)
    text = _java_layout(digits, exponent)
    return ("-" if negative else "") + text


def _shortest_digits(exact: Fraction, value: float) -> tuple[str, int]:
    """(digits, exponent of the first digit) for the shortest round-tripping decimal."""
    magnitude = math.floor(math.log10(exact)) if exact > 0 else 0
    if Fraction(10) ** magnitude > exact:
        magnitude -= 1
    elif Fraction(10) ** (magnitude + 1) <= exact:
        magnitude += 1
    target = abs(value)
    for length in range(1, 10):
        found = _closest_with_length(exact, target, magnitude, length)
        if found is not None:
            if length == 1:
                longer = _closest_with_length(exact, target, magnitude, 2)
                if longer is not None:
                    return longer
            return found
    raise AssertionError(f"no decimal round-trips {value}")


def _closest_with_length(
    exact: Fraction, target: float, magnitude: int, length: int
) -> tuple[str, int] | None:
    scale = Fraction(10) ** (magnitude - length + 1)
    low = math.floor(exact / scale)
    best: tuple[Fraction, int] | None = None
    for integer in (low, low + 1):
        if integer <= 0:
            continue
        candidate = integer * scale
        if _float32_of_fraction(candidate) != target:
            continue
        distance = abs(candidate - exact)
        if best is None or distance < best[0] or (distance == best[0] and integer % 2 == 0):
            best = (distance, integer)
    if best is None:
        return None
    digits = str(best[1])
    exponent = magnitude
    if len(digits) > length:  # rounding up crossed a power of ten (99 -> 100)
        exponent += 1
    return digits.rstrip("0") or "0", exponent


def _java_layout(digits: str, exponent: int) -> str:
    """Java's layout: plain for 1e-3 <= x < 1e7, else "d.dddE±n"; always a fraction digit."""
    if -3 <= exponent < 7:
        if exponent >= 0:
            integer = digits[: exponent + 1].ljust(exponent + 1, "0")
            fraction = digits[exponent + 1 :] or "0"
        else:
            integer = "0"
            fraction = "0" * (-exponent - 1) + digits
        return f"{integer}.{fraction}"
    return f"{digits[0]}.{digits[1:] or '0'}E{exponent}"


# ------------------------------------------------------------------ coordinates

COORDINATE_DIGITS = 7


def _flexible_parse_double(text: str) -> float:
    """``LatLongCoordinates.flexibleParseDouble``, step by step (raises ValueError)."""
    if not text:
        raise ValueError("empty coordinate")
    negative = text[0] == "-"
    index = 1 if negative else 0
    accumulator = 0.0
    while index < len(text):
        character = text[index]
        if character in ",.":
            index += 1
            next_decimal = 0.1
            while index < len(text):
                character = text[index]
                if not "0" <= character <= "9":
                    if character == "E":
                        exponent = kotlin_int_or_none(text[index + 1 :])
                        if exponent is None:
                            raise ValueError(f"not a valid double: {text}")
                        accumulator *= 10.0**exponent
                        index = len(text)
                        break
                    raise ValueError(f"not a valid double: {text}")
                accumulator += next_decimal * (ord(character) - ord("0"))
                next_decimal /= 10.0
                index += 1
        elif not "0" <= character <= "9":
            raise ValueError(f"not a valid double: {text}")
        else:
            accumulator = accumulator * 10.0 + (ord(character) - ord("0"))
        index += 1
    return -accumulator if negative else accumulator


def _format_fixed(value: float, digits: int) -> str:
    negative = value < 0
    scale = 10.0**digits
    scaled = math.floor(abs(value) * scale + 0.5)
    scale_integer = int(scale)
    integer_part, fraction_part = divmod(scaled, scale_integer)
    return f"{'-' if negative else ''}{integer_part}.{str(fraction_part).rjust(digits, '0')}"


@dataclass(frozen=True, slots=True)
class LatLong:
    """Coordinates as Scythebill stores them: seven-decimal strings."""

    latitude: str
    longitude: str

    @staticmethod
    def parse(latitude: str, longitude: str) -> LatLong:
        """``LatLongCoordinates.withLatAndLong(String, String)``; raises ValueError."""
        return LatLong.of(_flexible_parse_double(latitude), _flexible_parse_double(longitude))

    @staticmethod
    def of(latitude: float, longitude: float) -> LatLong:
        if not -90 <= latitude <= 90:
            raise ValueError(f"latitude not in [-90, 90]: {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"longitude not in [-180, 180]: {longitude}")
        return LatLong(
            _format_fixed(latitude, COORDINATE_DIGITS), _format_fixed(longitude, COORDINATE_DIGITS)
        )


# ------------------------------------------------------------------ links

_SCHEME_CHARACTERS = re.compile(r"[\w+.-]+")


def uri_scheme(uri: str) -> str | None:
    """``Link.schemeOf``: letters/digits/+/-/., starting with a letter, before a colon."""
    colon = uri.find(":")
    if colon <= 0:
        return None
    candidate = uri[:colon]
    if not candidate[0].isalpha():
        return None
    if not all(c.isalnum() or c in "+-." for c in candidate):
        return None
    return candidate


def is_valid_uri(uri: str) -> bool:
    """``Link.isValidUriString``: has a scheme and no whitespace."""
    return uri_scheme(uri) is not None and not any(c.isspace() for c in uri)


def normalize_file_localhost(uri: str) -> str:
    """``file://localhost/x`` (from macOS drag and drop) becomes ``file:/x``."""
    prefix = "file://localhost"
    if not uri.startswith(prefix):
        return uri
    if len(uri) == len(prefix) or uri[len(prefix)] in "/?#":
        return "file:" + uri[len(prefix) :]
    return uri
