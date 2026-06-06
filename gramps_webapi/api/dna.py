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

    chromosome: int | str
    start_position: int | str
    end_position: int | str
    centimorgans: int | str
    num_snps: int | str | None = None
    side: int | str | None = None
    comment: int | str | None = None


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
    if any(is_numeric(column) for column in header_columns):
        return False
    return True


def normalize_column_name(name: str) -> str:
    """Normalize a column name by lowercasing and removing spaces and underscores."""
    return name.lower().replace(" ", "").replace("_", "")


@overload
def find_column_key(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_keys: set[str],
    allow_missing: Literal[False],
) -> str: ...


@overload
def find_column_key(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_keys: set[str],
    allow_missing: Literal[True],
) -> str | None: ...


def find_column_key(
    column_names: list[str],
    condition: Callable[[str], bool],
    exclude_keys: set[str],
    allow_missing: bool = False,
) -> str | None:
    """Find the key of a column in a list of column names or raise a ValueError."""
    for column in column_names:
        if column in exclude_keys:
            continue
        if condition(column):
            return column
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
    exclude_keys: set[str] = set()
    chromosome = find_column_key(
        header,
        lambda col: col.startswith("chr"),
        exclude_keys=exclude_keys,
        allow_missing=False,
    )
    exclude_keys.add(chromosome)
    start_position = find_column_key(
        header,
        lambda col: "start" in col,
        exclude_keys=exclude_keys,
        allow_missing=False,
    )
    exclude_keys.add(start_position)
    end_position = find_column_key(
        header,
        lambda col: "end" in col
        or "stop" in col
        or ("length" in col and "morgan" not in col),
        exclude_keys=exclude_keys,
        allow_missing=False,
    )
    exclude_keys.add(end_position)
    centimorgans = find_column_key(
        header,
        lambda col: col.startswith("cm") or "centimorgan" in col or "length" in col,
        exclude_keys=exclude_keys,
        allow_missing=False,
    )
    exclude_keys.add(centimorgans)
    num_snps = find_column_key(
        header,
        lambda col: "snp" in col,
        exclude_keys=exclude_keys,
        allow_missing=True,
    )
    if num_snps is not None:
        exclude_keys.add(num_snps)
    side = find_column_key(
        header,
        lambda col: col.startswith("side"),
        exclude_keys=exclude_keys,
        allow_missing=True,
    )
    if side is not None:
        exclude_keys.add(side)
    comment = find_column_key(
        header,
        lambda _: True,  # take the first column that has not been matched yet
        exclude_keys=exclude_keys,
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
    rows = [r for r in rows if r.strip() != ""]
    if not rows:
        return []

    delimiter = None
    header = None
    order = None
    start_idx = 0

    for i in range(len(rows)):
        candidate_rows = rows[i:]
        for delim in ["\t", ",", ";"]:
            if candidate_rows[0].count(delim) < 3:
                continue

            if has_header(candidate_rows, delim):
                cand_header = [normalize_column_name(col) for col in candidate_rows[0].split(delim)]
                try:
                    data = [r.split(delim) for r in candidate_rows[1:]]
                    data_columns = transpose_jagged_nested_list(data)
                    order = get_order(cand_header, data_columns=data_columns)
                    delimiter = delim
                    header = cand_header
                    start_idx = i + 1
                    break
                except ValueError:
                    pass
            else:
                try:
                    data = [r.split(delim) for r in candidate_rows]
                    data_columns = transpose_jagged_nested_list(data)
                    order = get_order(None, data_columns=data_columns)
                    delimiter = delim
                    header = None
                    start_idx = i
                    break
                except ValueError:
                    pass
        if delimiter is not None:
            break

    if delimiter is None or order is None:
        return []

    data = [row.split(delimiter) for row in rows[start_idx:]]

    segments = []
    for row_fields in data:
        if header is not None:
            row_data: dict[int | str, str] = {
                header[i]: value
                for i, value in enumerate(row_fields)
                if i < len(header)
            }
        else:
            row_data = {
                i: value
                for i, value in enumerate(row_fields)
            }
        try:
            match_segment = process_row(row_data, order)
        except (ValueError, TypeError):
            continue
        if match_segment:
            segments.append(match_segment)
    return segments


def process_row(fields: dict[int | str, str], order: SegmentColumnOrder) -> MatchSegment | None:
    """Process a row of a DNA match table."""
    try:
        chromo_val = fields.get(order.chromosome)
        if chromo_val is None:
            return None
        chromo = chromo_val.strip()

        start_val = fields.get(order.start_position)
        if start_val is None:
            return None
        start = cast_int(start_val.strip())

        stop_val = fields.get(order.end_position)
        if stop_val is None:
            return None
        stop = cast_int(stop_val.strip())

        cms_val = fields.get(order.centimorgans)
        if cms_val is None:
            return None
        cms = cast_float(cms_val.strip())

        if order.num_snps is not None:
            snp_val = fields.get(order.num_snps)
            snp = cast_int(snp_val.strip()) if snp_val else 0
        else:
            snp = 0

        if order.side is not None:
            side_val = fields.get(order.side)
            if side_val:
                side = side_val.strip().upper()
                if side not in {SIDE_MATERNAL, SIDE_PATERNAL}:
                    side = SIDE_UNKNOWN
            else:
                side = SIDE_UNKNOWN
        else:
            side = SIDE_UNKNOWN

        if order.comment is not None:
            comment_val = fields.get(order.comment)
            comment = comment_val.strip() if comment_val else ""
        else:
            comment = ""

    except (ValueError, TypeError, KeyError):
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
