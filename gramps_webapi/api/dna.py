"""Parser for raw DNA match data."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Sequence, overload

from gramps_webapi.types import MatchSegment

SIDE_UNKNOWN = "U"
SIDE_MATERNAL = "M"
SIDE_PATERNAL = "P"


@dataclass
class SegmentColumnMap:
    """Column mapping for a DNA match table."""

    chromosome: str
    start_position: str
    end_position: str
    centimorgans: str
    num_snps: str | None = None
    side: str | None = None
    comment: str | None = None


def get_delimiter(rows: list[str]) -> str:
    """Guess the delimiter of a string containing a CSV-like table."""
    for delimiter in ("\t", ",", ";"):
        if any(row.count(delimiter) >= 3 for row in rows if row.strip()):
            return delimiter
    raise ValueError("Could not determine delimiter.")


def normalize_column_name(value: str) -> str:
    """Normalize a column name for resilient matching."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def is_placeholder_column_name(value: str) -> bool:
    """Determine whether a column name is a synthetic placeholder."""
    return value.startswith("__column_")


def make_header_keys(column_names: Sequence[str]) -> list[str]:
    """Create normalized, unique keys for a header row."""
    keys: list[str] = []
    for i, column_name in enumerate(column_names):
        normalized = normalize_column_name(column_name)
        if normalized == "":
            normalized = f"__column_{i}"
        elif normalized in keys:
            normalized = f"{normalized}_{i}"
        keys.append(normalized)
    return keys


def is_numeric(value: str) -> bool:
    """Determine if a string is number-like."""
    if value == "":
        return False
    try:
        float(value)
        return True
    except ValueError:
        pass
    if re.match(r"^\d[\d\.,]*$", value):
        return True
    return False


def is_probable_data_row(fields: Sequence[str]) -> bool:
    """Determine whether a parsed row looks like DNA segment data."""
    stripped_fields = [field.strip() for field in fields]
    if len([field for field in stripped_fields if field]) < 4:
        return False
    return sum(is_numeric(field) for field in stripped_fields) >= 3


def cast_int(value: str) -> int:
    """Cast a string to an integer."""
    try:
        return int(value.replace(",", "").replace(".", ""))
    except (ValueError, TypeError):
        return 0


def cast_float(value: str) -> float:
    """Cast a string to a float."""
    value = value.replace(" ", "")
    if value.count(".") > 1:
        value = value.replace(".", "")
    if value.count(",") > 1:
        value = value.replace(",", "")
    if value.count(",") == 1 and value.count(".") == 0:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return 0.0


@overload
def find_column_name(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_columns: Sequence[str],
    allow_missing: Literal[False],
) -> str: ...


@overload
def find_column_name(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_columns: Sequence[str],
    allow_missing: Literal[True],
) -> str | None: ...


def find_column_name(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_columns: Sequence[str],
    allow_missing: bool = False,
) -> str | None:
    """Find a column name in a list of normalized columns."""
    for column in column_names:
        if column in exclude_columns or is_placeholder_column_name(column):
            continue
        if condition(column):
            return column
    if allow_missing:
        return None
    raise ValueError("Column not found.")


def get_header_column_map(header: list[str]) -> SegmentColumnMap:
    """Get the column mapping for a header row."""
    exclude_columns: list[str] = []
    chromosome = find_column_name(
        header,
        lambda col: col.startswith("chr") or "chromosome" in col,
        exclude_columns=exclude_columns,
        allow_missing=False,
    )
    exclude_columns.append(chromosome)
    start_position = find_column_name(
        header,
        lambda col: "start" in col,
        exclude_columns=exclude_columns,
        allow_missing=False,
    )
    exclude_columns.append(start_position)
    end_position = find_column_name(
        header,
        lambda col: "end" in col
        or "stop" in col
        or ("length" in col and "morgan" not in col),
        exclude_columns=exclude_columns,
        allow_missing=False,
    )
    exclude_columns.append(end_position)
    centimorgans = find_column_name(
        header,
        lambda col: col.startswith("cm") or "centimorgan" in col or "length" in col,
        exclude_columns=exclude_columns,
        allow_missing=False,
    )
    exclude_columns.append(centimorgans)
    num_snps = find_column_name(
        header,
        lambda col: "snp" in col,
        exclude_columns=exclude_columns,
        allow_missing=True,
    )
    if num_snps is not None:
        exclude_columns.append(num_snps)
    side = find_column_name(
        header,
        lambda col: col.startswith("side"),
        exclude_columns=exclude_columns,
        allow_missing=True,
    )
    if side is not None:
        exclude_columns.append(side)
    comment = find_column_name(
        header,
        lambda col: col == "name"
        or col.endswith("name")
        or col.startswith("type")
        or "comment" in col
        or "note" in col,
        exclude_columns=exclude_columns,
        allow_missing=True,
    )
    if comment is None:
        comment = find_column_name(
            header,
            lambda _: True,
            exclude_columns=exclude_columns,
            allow_missing=True,
        )
    return SegmentColumnMap(
        chromosome=chromosome,
        start_position=start_position,
        end_position=end_position,
        centimorgans=centimorgans,
        num_snps=num_snps,
        side=side,
        comment=comment,
    )


def get_default_column_map(
    data_columns: Sequence[Sequence[str | None]],
) -> SegmentColumnMap:
    """Get the fallback column mapping for headerless DNA match tables."""
    if len(data_columns) < 4:
        raise ValueError("Column not found.")

    def column_name(index: int) -> str:
        return f"__column_{index}"

    if len(data_columns) >= 6:
        side_values = [
            value.strip().upper() if isinstance(value, str) else ""
            for value in data_columns[5]
        ]
        if all(
            (not value) or (value in {SIDE_MATERNAL, SIDE_PATERNAL, SIDE_UNKNOWN})
            for value in side_values
        ):
            return SegmentColumnMap(
                chromosome=column_name(0),
                start_position=column_name(1),
                end_position=column_name(2),
                centimorgans=column_name(3),
                num_snps=column_name(4),
                side=column_name(5),
                comment=column_name(6) if len(data_columns) >= 7 else None,
            )

    return SegmentColumnMap(
        chromosome=column_name(0),
        start_position=column_name(1),
        end_position=column_name(2),
        centimorgans=column_name(3),
        num_snps=column_name(4) if len(data_columns) >= 5 else None,
        comment=column_name(5) if len(data_columns) >= 6 else None,
    )


def transpose_jagged_nested_list(
    data: Sequence[Sequence[str | None]],
) -> list[list[str | None]]:
    """Transpose a jagged nested list, replacing missing values with None."""
    return list(map(list, itertools.zip_longest(*data, fillvalue=None)))


def build_row_lookup(
    fields: Sequence[str], header_keys: Sequence[str] | None = None
) -> dict[str, str]:
    """Build a lookup of normalized column keys to row values."""
    if header_keys is None:
        header_keys = make_header_keys([f"__column_{i}" for i in range(len(fields))])
    return {
        key: fields[i].strip() if i < len(fields) else ""
        for i, key in enumerate(header_keys)
    }


def get_header_column_map_or_none(fields: Sequence[str]) -> SegmentColumnMap | None:
    """Return a header column mapping if a row looks like a header."""
    if is_probable_data_row(fields):
        return None
    header_keys = make_header_keys(fields)
    try:
        return get_header_column_map(header_keys)
    except ValueError:
        return None


def parse_raw_dna_match_string(raw_string: str) -> list[MatchSegment]:
    """Parse a raw DNA match string."""
    rows = [row for row in raw_string.splitlines() if row.strip()]
    if not rows:
        return []
    try:
        delimiter = get_delimiter(rows)
    except ValueError:
        return []

    parsed_rows = [row.split(delimiter) for row in rows]
    header_keys: list[str] | None = None
    column_map: SegmentColumnMap | None = None
    data_rows: list[list[str]] = []

    for fields in parsed_rows:
        header_map = get_header_column_map_or_none(fields)
        if header_map is not None:
            header_keys = make_header_keys(fields)
            column_map = header_map
            continue
        if is_probable_data_row(fields):
            data_rows.append(fields)

    if not data_rows:
        return []

    if column_map is None:
        data_columns = transpose_jagged_nested_list(data_rows)
        try:
            column_map = get_default_column_map(data_columns)
        except ValueError:
            return []

    segments = []
    for fields in data_rows:
        try:
            row_lookup = build_row_lookup(fields, header_keys=header_keys)
            match_segment = process_row(row_lookup=row_lookup, column_map=column_map)
        except (ValueError, TypeError):
            continue
        if match_segment:
            segments.append(match_segment)
    return segments


def process_row(
    row_lookup: dict[str, str], column_map: SegmentColumnMap
) -> MatchSegment | None:
    """Process a row of a DNA match table."""
    try:
        chromo = row_lookup.get(column_map.chromosome, "").strip()
        start = cast_int(row_lookup.get(column_map.start_position, "").strip())
        stop = cast_int(row_lookup.get(column_map.end_position, "").strip())
        cms = cast_float(row_lookup.get(column_map.centimorgans, "").strip())
        if column_map.num_snps is not None:
            snp = cast_int(row_lookup.get(column_map.num_snps, "").strip())
        else:
            snp = 0
        if column_map.side is not None:
            side = row_lookup.get(column_map.side, "").strip().upper()
            if side not in {SIDE_MATERNAL, SIDE_PATERNAL}:
                side = SIDE_UNKNOWN
        else:
            side = SIDE_UNKNOWN
        if column_map.comment is not None:
            comment = row_lookup.get(column_map.comment, "").strip()
        else:
            comment = ""
    except (ValueError, TypeError):
        return None
    return {
        "chromosome": chromo,
        "start": start,
        "stop": stop,
        "side": side,
        "cM": cms,
        "SNPs": snp,
        "comment": comment,
    }
