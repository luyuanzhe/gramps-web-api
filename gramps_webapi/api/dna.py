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


def has_header(rows: list[str], delimiter: str) -> bool:
    """Determine if the table has a header."""
    if len(rows) < 2:
        return False
    header = rows[0]
    if len(header) < 4:
        return False
    header_columns = header.split(delimiter)
    if any(is_numeric(column.strip()) for column in header_columns):
        return False
    return True


def find_header_end(rows: list[str], delimiter: str) -> int:
    """Find the end of header rows (supports multi-line headers).
    
    Returns the index of the first data row (after all header rows).
    """
    for i, row in enumerate(rows):
        if not row.strip():
            continue
        columns = row.split(delimiter)
        if any(is_numeric(col.strip()) for col in columns):
            return i
    return 1


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
        if condition(column.lower().strip()):
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
    rows = raw_string.strip().split("\n")
    
    if len(rows) < 2:
        return []
    
    try:
        delimiter = get_delimiter(rows)
    except ValueError:
        return []
    
    header_rows = []
    header_end = find_header_end(rows, delimiter)
    
    if header_end > 0:
        header_rows = rows[:header_end]
    
    header: list[str] | None
    if header_rows:
        header = header_rows[-1].split(delimiter)
    else:
        header = None
    
    data_rows = rows[header_end:]
    
    data = [row.split(delimiter) for row in data_rows if row.strip()]
    if not data:
        return []
    
    data_columns = transpose_jagged_nested_list(data)
    try:
        order = get_order(header, data_columns=data_columns)
    except ValueError:
        return []
    
    segments = []
    for row in data_rows:
        if row.strip() == "":
            continue
        try:
            match_segment = process_row(fields=row.split(delimiter), order=order)
        except (ValueError, TypeError, IndexError):
            continue
        if match_segment:
            segments.append(match_segment)
    return segments


def get_field_value(fields: list[str], index: int | None) -> str:
    """Safely get field value from a list, returning empty string if index is out of bounds."""
    if index is None:
        return ""
    if index < len(fields):
        return fields[index].strip()
    return ""


def process_row(fields: list[str], order: SegmentColumnOrder) -> MatchSegment | None:
    """Process a row of a DNA match table."""
    if len(fields) < 4:
        return None
    
    chromo = get_field_value(fields, order.chromosome)
    if not chromo:
        return None
    
    start_str = get_field_value(fields, order.start_position)
    stop_str = get_field_value(fields, order.end_position)
    cms_str = get_field_value(fields, order.centimorgans)
    
    if not start_str or not stop_str or not cms_str:
        return None
    
    try:
        start = cast_int(start_str)
        stop = cast_int(stop_str)
        cms = cast_float(cms_str)
    except (ValueError, TypeError):
        return None
    
    snp_str = get_field_value(fields, order.num_snps)
    snp = cast_int(snp_str) if snp_str else 0
    
    side_str = get_field_value(fields, order.side)
    side = side_str.upper() if side_str else SIDE_UNKNOWN
    if side not in {SIDE_MATERNAL, SIDE_PATERNAL}:
        side = SIDE_UNKNOWN
    
    comment = get_field_value(fields, order.comment)
    
    return {
        "chromosome": chromo,
        "start": start,
        "stop": stop,
        "side": side,
        "cM": cms,
        "SNPs": snp,
        "comment": comment,
    }
