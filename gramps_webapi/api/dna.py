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
class SegmentColumnOrder:
    """Order of the columns of a DNA match table."""

    chromosome: int
    start_position: int
    end_position: int
    centimorgans: int
    num_snps: int | None = None
    side: int | None = None
    comment: int | None = None


def get_delimiter(rows: list[str]) -> str:
    """Guess the delimiter of a string containing a CSV-like table.

    It is assumed that the table has at least 4 columns and at least one
    row.
    """
    if rows[0].count("\t") >= 3:
        return "\t"
    if rows[0].count(",") >= 3:
        return ","
    if rows[0].count(";") >= 3:
        return ";"
    raise ValueError("Could not determine delimiter.")


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


def _is_header_row(row: str, delimiter: str) -> bool:
    """Determine if a single row looks like a header row."""
    if not row.strip():
        return False
    columns = row.split(delimiter)
    if len(columns) < 4:
        return False
    return not any(is_numeric(col) for col in columns)


def _get_header_rows(rows: list[str], delimiter: str) -> list[int]:
    """Find the indices of all consecutive header rows at the start."""
    header_indices: list[int] = []
    for i, row in enumerate(rows):
        if not row.strip():
            header_indices.append(i)
            continue
        if _is_header_row(row, delimiter):
            header_indices.append(i)
        else:
            break
    return header_indices


def has_header(rows: list[str], delimiter: str) -> bool:
    """Determine if the table has a header."""
    if len(rows) < 2:
        return False
    header_indices = _get_header_rows(rows, delimiter)
    return len(header_indices) > 0 and len(header_indices) < len(rows)


def _normalize_column_name(name: str) -> str:
    """Normalize a column name for comparison: lowercase, strip whitespace, collapse spaces."""
    return re.sub(r"\s+", " ", name.lower().strip())


@overload
def find_column_position(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_indices: Sequence[int],
    allow_missing: Literal[False],
) -> int: ...


@overload
def find_column_position(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_indices: Sequence[int],
    allow_missing: Literal[True],
) -> int | None: ...


def find_column_position(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_indices: Sequence[int],
    allow_missing: bool = False,
) -> int | None:
    """Find the position of a column in a list of column names or raise a ValueError."""
    for i, column in enumerate(column_names):
        if i in exclude_indices:
            continue
        if condition(_normalize_column_name(column)):
            return i
    if allow_missing:
        return None
    raise ValueError("Column not found.")


def get_order(
    header: list[str] | None, data_columns: Sequence[Sequence[str | None]]
) -> SegmentColumnOrder:
    """Get the order of the columns."""
    if header is None:
        # use the default ordering of the DNASegmentMap Gramplet
        # https://gramps-project.org/wiki/index.php/Addon:DNASegmentMapGramplet
        if len(data_columns) >= 6:
            # check whether the 6th column contains side information
            if all(
                (not value) or (value in {SIDE_MATERNAL, SIDE_PATERNAL, SIDE_UNKNOWN})
                for value in data_columns[5]
            ):
                return SegmentColumnOrder(
                    chromosome=0,
                    start_position=1,
                    end_position=2,
                    centimorgans=3,
                    num_snps=4,
                    side=5,
                    comment=6,
                )
        return SegmentColumnOrder(
            chromosome=0,
            start_position=1,
            end_position=2,
            centimorgans=3,
            num_snps=4,
            comment=5,
        )
    exclude_indices: list[int] = []
    chromosome = find_column_position(
        header,
        lambda col: col.startswith("chr"),
        exclude_indices=exclude_indices,
        allow_missing=False,
    )
    exclude_indices.append(chromosome)
    start_position = find_column_position(
        header,
        lambda col: "start" in col,
        exclude_indices=exclude_indices,
        allow_missing=False,
    )
    exclude_indices.append(start_position)
    end_position = find_column_position(
        header,
        lambda col: "end" in col
        or "stop" in col
        or ("length" in col and "morgan" not in col),
        exclude_indices=exclude_indices,
        allow_missing=False,
    )
    exclude_indices.append(end_position)
    centimorgans = find_column_position(
        header,
        lambda col: col.startswith("cm") or "centimorgan" in col or "length" in col,
        exclude_indices=exclude_indices,
        allow_missing=False,
    )
    exclude_indices.append(centimorgans)
    num_snps = find_column_position(
        header,
        lambda col: "snp" in col,
        exclude_indices=exclude_indices,
        allow_missing=True,
    )
    if num_snps is not None:
        exclude_indices.append(num_snps)
    side = find_column_position(
        header,
        lambda col: col.startswith("side"),
        exclude_indices=exclude_indices,
        allow_missing=True,
    )
    if side is not None:
        exclude_indices.append(side)
    comment = find_column_position(
        header,
        lambda _: True,  # take the first column that has not been matched yet
        exclude_indices=exclude_indices,
        allow_missing=True,
    )
    return SegmentColumnOrder(
        chromosome=chromosome,
        start_position=start_position,
        end_position=end_position,
        centimorgans=centimorgans,
        num_snps=num_snps,
        side=side,
        comment=comment,
    )


def transpose_jagged_nested_list(
    data: Sequence[Sequence[str | None]],
) -> list[list[str | None]]:
    """Transpose a jagged nested list, replacing missing values with None."""
    return list(map(list, itertools.zip_longest(*data, fillvalue=None)))


def parse_raw_dna_match_string(raw_string: str) -> list[MatchSegment]:
    """Parse a raw DNA match string."""
    all_lines = raw_string.strip().split("\n")
    if not all_lines:
        return []
    try:
        delimiter = get_delimiter(all_lines)
    except ValueError:
        return []
    header: list[str] | None
    if has_header(all_lines, delimiter):
        header_indices = _get_header_rows(all_lines, delimiter)
        header_line = all_lines[header_indices[-1]]
        header = [col.strip().lower() for col in header_line.split(delimiter)]
        data_rows = all_lines[header_indices[-1] + 1:]
    else:
        header = None
        data_rows = all_lines
    data_rows = [row for row in data_rows if row.strip() != ""]
    if not data_rows:
        return []
    data = [row.split(delimiter) for row in data_rows]
    data_columns = transpose_jagged_nested_list(data)
    try:
        order = get_order(header, data_columns=data_columns)
    except ValueError:
        return []
    segments = []
    for row in data_rows:
        try:
            match_segment = process_row(fields=row.split(delimiter), order=order)
        except (ValueError, TypeError, IndexError):
            continue
        if match_segment:
            segments.append(match_segment)
    return segments


def _safe_get_field(fields: list[str], index: int) -> str:
    """Safely get a field from a list by index, returning empty string if out of bounds."""
    if index < len(fields):
        return fields[index].strip()
    return ""


def process_row(fields: list[str], order: SegmentColumnOrder) -> MatchSegment | None:
    """Process a row of a DNA match table."""
    try:
        chromo = _safe_get_field(fields, order.chromosome)
        if not chromo:
            return None
        start_raw = _safe_get_field(fields, order.start_position)
        if not start_raw:
            return None
        start = cast_int(start_raw)
        stop_raw = _safe_get_field(fields, order.end_position)
        if not stop_raw:
            return None
        stop = cast_int(stop_raw)
        cms_raw = _safe_get_field(fields, order.centimorgans)
        if not cms_raw:
            return None
        cms = cast_float(cms_raw)
        if order.num_snps is not None:
            snp = cast_int(_safe_get_field(fields, order.num_snps))
        else:
            snp = 0
        if order.side is not None:
            side = _safe_get_field(fields, order.side).upper()
            if side not in {SIDE_MATERNAL, SIDE_PATERNAL}:
                side = SIDE_UNKNOWN
        else:
            side = SIDE_UNKNOWN
        if order.comment is not None:
            comment = _safe_get_field(fields, order.comment)
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
