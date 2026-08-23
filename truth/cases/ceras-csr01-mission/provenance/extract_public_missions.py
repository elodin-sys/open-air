"""Extract CSR-01 mission summary tables from saved CeRAS HTML pages."""

from __future__ import annotations

import argparse
import csv
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            text = " ".join("".join(self.cell_parts).split())
            self.row.append(unescape(text))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)


FIELDS = {
    "Range": "range_nm",
    "Payload (PL)": "payload_kg",
    "Take-off weight": "takeoff_mass_kg",
    "Mission (loaded) fuel": "mission_fuel_kg",
    "Block fuel": "block_fuel_kg",
    "Trip fuel": "trip_fuel_kg",
    "Reserve fuel": "reserve_fuel_kg",
    "Taxi-out fuel": "taxi_out_fuel_kg",
    "Taxi-in fuel": "taxi_in_fuel_kg",
    "Landing weight": "landing_mass_kg",
    "Block time": "block_time_h",
    "Flight time": "flight_time_h",
}


def extract(path: Path) -> dict[str, str]:
    parser = TableParser()
    parser.feed(path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for row in parser.rows:
        if row and row[0] in FIELDS:
            match = re.search(r"-?\d+(?:\.\d+)?", row[-1])
            if match:
                values[FIELDS[row[0]]] = match.group(0)
    missing = set(FIELDS.values()) - values.keys()
    if missing:
        raise ValueError(f"{path}: missing mission fields {sorted(missing)}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mission", nargs=3, type=Path)
    parser.add_argument(
        "--ids",
        nargs=3,
        default=["study_500", "design_2750", "mtow_2500"],
    )
    args = parser.parse_args()
    rows = [
        {"mission_id": mission_id, **extract(path)}
        for mission_id, path in zip(args.ids, args.mission, strict=True)
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=["mission_id", *FIELDS.values()])
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
