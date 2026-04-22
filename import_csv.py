from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "output_country_specific.csv"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "cbam.sqlite3"
VALID_YEARS = {2026, 2027}


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

DROP TABLE IF EXISTS emissions;
DROP TABLE IF EXISTS code_year_route_counts;
DROP TABLE IF EXISTS code_year_summary;

CREATE TABLE emissions (
    cn_code TEXT NOT NULL,
    country TEXT NOT NULL,
    year INTEGER NOT NULL,
    production_route TEXT NOT NULL,
    paid_emissions REAL NOT NULL,
    duplicate_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (cn_code, country, year, production_route)
);

CREATE TABLE code_year_route_counts (
    cn_code TEXT NOT NULL,
    year INTEGER NOT NULL,
    production_route TEXT NOT NULL,
    country_count INTEGER NOT NULL,
    PRIMARY KEY (cn_code, year, production_route)
);

CREATE TABLE code_year_summary (
    cn_code TEXT NOT NULL,
    year INTEGER NOT NULL,
    majority_route TEXT NOT NULL,
    majority_country_count INTEGER NOT NULL,
    total_country_count INTEGER NOT NULL,
    map_country_count INTEGER NOT NULL,
    max_map_value REAL NOT NULL,
    PRIMARY KEY (cn_code, year)
);

CREATE INDEX idx_emissions_code_year ON emissions (cn_code, year);
CREATE INDEX idx_emissions_country ON emissions (country);
CREATE INDEX idx_emissions_code_year_country ON emissions (cn_code, year, country);
CREATE INDEX idx_route_counts_code_year ON code_year_route_counts (cn_code, year, country_count DESC);
"""


def normalize_route(value: str | None) -> str:
    return (value or "").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import output_country_specific.csv into a local SQLite database."
    )
    parser.add_argument(
        "--csv",
        default=str(CSV_PATH),
        help="Path to the source CSV file.",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="Path to the SQLite database file to create.",
    )
    return parser.parse_args()


def load_grouped_rows(csv_path: Path) -> dict[tuple[str, str, int, str], tuple[float, int]]:
    grouped_values: dict[tuple[str, str, int, str], list[float]] = defaultdict(list)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"cn code", "country", "paid emissions", "production route", "year"}
        missing = required_columns.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            year = int(row["year"])
            if year not in VALID_YEARS:
                continue

            key = (
                row["cn code"].strip(),
                row["country"].strip(),
                year,
                normalize_route(row["production route"]),
            )
            grouped_values[key].append(float(row["paid emissions"] or 0.0))

    grouped_rows: dict[tuple[str, str, int, str], tuple[float, int]] = {}
    for key, values in grouped_values.items():
        grouped_rows[key] = (sum(values) / len(values), len(values))
    return grouped_rows


def compute_route_counts(
    grouped_rows: dict[tuple[str, str, int, str], tuple[float, int]]
) -> list[tuple[str, int, str, int]]:
    route_counts: dict[tuple[str, int, str], int] = defaultdict(int)
    for cn_code, _country, year, route in grouped_rows:
        route_counts[(cn_code, year, route)] += 1

    return [
        (cn_code, year, route, country_count)
        for (cn_code, year, route), country_count in route_counts.items()
    ]


def compute_summaries(
    grouped_rows: dict[tuple[str, str, int, str], tuple[float, int]],
    route_counts: list[tuple[str, int, str, int]],
) -> list[tuple[str, int, str, int, int, int, float]]:
    route_counts_by_code_year: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    all_countries_by_code_year: dict[tuple[str, int], set[str]] = defaultdict(set)
    map_rows_by_code_year_route: dict[tuple[str, int, str], list[float]] = defaultdict(list)

    for cn_code, year, route, country_count in route_counts:
        route_counts_by_code_year[(cn_code, year)].append((route, country_count))

    for (cn_code, country, year, route), (paid_emissions, _duplicate_count) in grouped_rows.items():
        all_countries_by_code_year[(cn_code, year)].add(country)
        map_rows_by_code_year_route[(cn_code, year, route)].append(paid_emissions)

    summaries: list[tuple[str, int, str, int, int, int, float]] = []
    for code_year, routes in route_counts_by_code_year.items():
        cn_code, year = code_year
        majority_route, majority_country_count = sorted(
            routes, key=lambda item: (-item[1], item[0])
        )[0]
        map_values = map_rows_by_code_year_route[(cn_code, year, majority_route)]
        summaries.append(
            (
                cn_code,
                year,
                majority_route,
                majority_country_count,
                len(all_countries_by_code_year[(cn_code, year)]),
                len(map_values),
                max(map_values) if map_values else 0.0,
            )
        )

    return summaries


def import_to_sqlite(csv_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    grouped_rows = load_grouped_rows(csv_path)
    route_counts = compute_route_counts(grouped_rows)
    summaries = compute_summaries(grouped_rows, route_counts)

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(SCHEMA_SQL)
        connection.executemany(
            """
            INSERT INTO emissions (
                cn_code, country, year, production_route, paid_emissions, duplicate_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    cn_code,
                    country,
                    year,
                    route,
                    paid_emissions,
                    duplicate_count,
                )
                for (cn_code, country, year, route), (paid_emissions, duplicate_count) in grouped_rows.items()
            ],
        )
        connection.executemany(
            """
            INSERT INTO code_year_route_counts (
                cn_code, year, production_route, country_count
            )
            VALUES (?, ?, ?, ?)
            """,
            route_counts,
        )
        connection.executemany(
            """
            INSERT INTO code_year_summary (
                cn_code,
                year,
                majority_route,
                majority_country_count,
                total_country_count,
                map_country_count,
                max_map_value
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            summaries,
        )
        connection.commit()
    finally:
        connection.close()

    print(
        f"Imported {len(grouped_rows):,} unique code/country/year/route rows "
        f"into {db_path} from {csv_path}."
    )


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv).resolve()
    db_path = Path(args.db).resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    import_to_sqlite(csv_path, db_path)


if __name__ == "__main__":
    main()
