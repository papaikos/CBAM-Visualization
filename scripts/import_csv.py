"""Build data/cbam.sqlite3 from the source CSV plus the bundled electricity values.

Usage:

    python scripts/import_csv.py                    # full rebuild from the CSV
    python scripts/import_csv.py --electricity-only # refresh CN 27160000 in the existing DB
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "output_country_specific.csv"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "cbam.sqlite3"
ELECTRICITY_PATH = DATA_DIR / "electricity_27160000.json"
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

CREATE INDEX idx_emissions_country ON emissions (country);
CREATE INDEX idx_emissions_code_year_country ON emissions (cn_code, year, country);
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
    parser.add_argument(
        "--electricity",
        default=str(ELECTRICITY_PATH),
        help="Path to the electricity (CN 27160000) default-value file.",
    )
    parser.add_argument(
        "--electricity-only",
        action="store_true",
        help="Only refresh the electricity records in an existing database (no CSV needed).",
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


def electricity_rows(countries: list[str], spec: dict) -> list[tuple[str, str, int, str, float, int]]:
    """Expand the electricity defaults to one record per country and year.

    Countries with a specific default use it, zero countries (EU/EEA/Swiss ETS
    and territories that are zero for every other code) are stored as zero, and
    every other country uses the EU fallback emission factor.
    """
    specific = spec["specificValues"]
    zero = set(spec["zeroCountries"])
    unknown = sorted((set(specific) | zero).difference(countries))
    if unknown:
        raise ValueError(f"Electricity countries missing from the database: {', '.join(unknown)}")

    rows = []
    for country in countries:
        if country in specific:
            value = float(specific[country])
        elif country in zero:
            value = 0.0
        else:
            value = float(spec["fallbackValue"])
        for year in spec["years"]:
            rows.append((spec["cnCode"], country, int(year), "", value, 1))
    return rows


def import_electricity(connection: sqlite3.Connection, spec_path: Path) -> int:
    """Replace the electricity records using the countries already in the database."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cn_code = spec["cnCode"]
    countries = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT country FROM emissions WHERE cn_code <> ? ORDER BY country",
            (cn_code,),
        )
    ]
    rows = electricity_rows(countries, spec)
    connection.execute("DELETE FROM emissions WHERE cn_code = ?", (cn_code,))
    connection.executemany(
        """
        INSERT INTO emissions (
            cn_code, country, year, production_route, paid_emissions, duplicate_count
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def finalize(connection: sqlite3.Connection) -> None:
    """Leave a single self-contained file that opens read-only without sidecars."""
    connection.commit()
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("VACUUM")


def import_to_sqlite(csv_path: Path, db_path: Path, electricity_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    grouped_rows = load_grouped_rows(csv_path)

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
        electricity_count = import_electricity(connection, electricity_path)
        finalize(connection)
    finally:
        connection.close()

    print(
        f"Imported {len(grouped_rows):,} unique code/country/year/route rows "
        f"and {electricity_count:,} electricity rows into {db_path} from {csv_path}."
    )


def refresh_electricity(db_path: Path, electricity_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    connection = sqlite3.connect(db_path)
    try:
        # Legacy summary tables and the (cn_code, year) index are unused by the app.
        connection.executescript(
            """
            DROP TABLE IF EXISTS code_year_route_counts;
            DROP TABLE IF EXISTS code_year_summary;
            DROP INDEX IF EXISTS idx_emissions_code_year;
            """
        )
        electricity_count = import_electricity(connection, electricity_path)
        finalize(connection)
    finally:
        connection.close()
    print(f"Refreshed {electricity_count:,} electricity rows in {db_path}.")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).resolve()
    electricity_path = Path(args.electricity).resolve()

    if args.electricity_only:
        refresh_electricity(db_path, electricity_path)
        return

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    import_to_sqlite(csv_path, db_path, electricity_path)


if __name__ == "__main__":
    main()
