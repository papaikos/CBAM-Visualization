from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


SUPPORTED_YEARS = (2026, 2027)
AGGREGATED_DUPLICATE_WARNING = (
    "Potential duplicate source records found. The bundled SQLite database stores the "
    "averaged record and its duplicate count; individual original source values are not "
    "available. Verify the value against the applicable EU legislation before reporting "
    "or compliance use."
)


class UnsupportedYear(ValueError):
    pass


class SourceRowsUnavailable(RuntimeError):
    pass


def _connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if not path.exists():
        raise SourceRowsUnavailable("The bundled SQLite database is unavailable.")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_emissions_table(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emissions'"
    ).fetchone()
    if row is None:
        raise SourceRowsUnavailable("The bundled emissions records are unavailable.")


def get_batch_meta(db_path: Path) -> dict:
    with closing(_connect(db_path)) as connection:
        _ensure_emissions_table(connection)
        codes = [
            row["cn_code"]
            for row in connection.execute(
                "SELECT DISTINCT cn_code FROM emissions ORDER BY cn_code"
            )
        ]
        countries = [
            row["country"]
            for row in connection.execute(
                "SELECT DISTINCT country FROM emissions ORDER BY country"
            )
        ]
    return {
        "years": list(SUPPORTED_YEARS),
        "codes": codes,
        "countries": countries,
        "dataMode": "aggregated_sqlite",
    }


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_number(value: Any, *, default: float | None, error: str) -> float | None:
    if _is_blank(value):
        return default
    if isinstance(value, bool):
        raise ValueError(error)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not math.isfinite(number):
        raise ValueError(error)
    return number


def _issue(line: dict, input_line: int, error: str) -> dict:
    return {
        "inputLine": input_line,
        "cnCode": line.get("cnCode", ""),
        "country": line.get("country", ""),
        "weightTonnes": line.get("weightTonnes", ""),
        "co2Price": line.get("co2Price", ""),
        "error": error,
    }


def build_batch_report(db_path: Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("The request body must be a JSON object.")
    year = payload.get("year")
    if year not in SUPPORTED_YEARS:
        raise UnsupportedYear(f"Unsupported year: {year}")
    lines = payload.get("lines", [])
    if not isinstance(lines, list):
        raise ValueError("Lines must be a JSON array.")
    raw_input_issues = payload.get("inputIssues", [])
    if not isinstance(raw_input_issues, list):
        raise ValueError("Input issues must be a JSON array.")

    input_issues: list[dict] = []
    for index, raw_issue in enumerate(raw_input_issues, start=1):
        if not isinstance(raw_issue, dict):
            raise ValueError("Each input issue must be an object.")
        error = raw_issue.get("error")
        if not isinstance(error, str) or not error.strip():
            raise ValueError("Each input issue must include an error message.")
        input_line = raw_issue.get("inputLine", index)
        if not isinstance(input_line, int) or isinstance(input_line, bool) or input_line < 1:
            input_line = index
        input_issues.append(_issue(raw_issue, input_line, error.strip()))

    with closing(_connect(db_path)) as connection:
        _ensure_emissions_table(connection)
        valid_codes = {
            row["cn_code"] for row in connection.execute("SELECT DISTINCT cn_code FROM emissions")
        }
        country_by_key = {
            row["country"].casefold(): row["country"]
            for row in connection.execute("SELECT DISTINCT country FROM emissions")
        }

        results: list[dict] = []
        issues: list[dict] = list(input_issues)
        duplicate_warnings: list[dict] = []

        for index, raw_line in enumerate(lines, start=1):
            if not isinstance(raw_line, dict):
                issues.append(_issue({}, index, "Each input line must be an object."))
                continue
            input_line = raw_line.get("inputLine", index)
            if not isinstance(input_line, int) or isinstance(input_line, bool) or input_line < 1:
                input_line = index

            raw_code = raw_line.get("cnCode", "")
            raw_country = raw_line.get("country", "")
            raw_weight = raw_line.get("weightTonnes", "")
            raw_price = raw_line.get("co2Price", "")
            if all(_is_blank(value) for value in (raw_code, raw_country, raw_weight, raw_price)):
                continue

            if not isinstance(raw_code, str) or not raw_code.strip():
                issues.append(_issue(raw_line, input_line, "CN code is required."))
                continue
            cn_code = raw_code.strip()
            if not isinstance(raw_country, str) or not raw_country.strip():
                issues.append(_issue(raw_line, input_line, "Country is required."))
                continue
            country = raw_country.strip()

            try:
                weight = _parse_number(
                    raw_weight,
                    default=1.0,
                    error="Weight must be a number greater than zero.",
                )
                if weight is None or weight <= 0:
                    raise ValueError("Weight must be a number greater than zero.")
            except ValueError as exc:
                issues.append(_issue(raw_line, input_line, str(exc)))
                continue

            try:
                price = _parse_number(
                    raw_price,
                    default=None,
                    error="CO₂ price must be a number greater than or equal to zero.",
                )
                if price is not None and price < 0:
                    raise ValueError("CO₂ price must be a number greater than or equal to zero.")
            except ValueError as exc:
                issues.append(_issue(raw_line, input_line, str(exc)))
                continue

            if cn_code not in valid_codes:
                issues.append(_issue(raw_line, input_line, "Unknown CN code."))
                continue
            canonical_country = country_by_key.get(country.casefold())
            if canonical_country is None:
                issues.append(_issue(raw_line, input_line, "Unknown country."))
                continue
            country = canonical_country

            stored_rows = connection.execute(
                """
                SELECT
                    rowid AS source_row_id,
                    cn_code,
                    country,
                    year,
                    production_route,
                    paid_emissions,
                    duplicate_count
                FROM emissions
                WHERE cn_code = ? AND country = ? AND year = ?
                ORDER BY production_route, rowid
                """,
                (cn_code, country, year),
            ).fetchall()
            if not stored_rows:
                issues.append(
                    _issue(
                        raw_line,
                        input_line,
                        "No source rows found for this CN code, country, and year.",
                    )
                )
                continue

            has_duplicate = False
            for stored_row in stored_rows:
                emissions = float(stored_row["paid_emissions"])
                duplicate_count = int(stored_row["duplicate_count"])
                row_has_duplicate = duplicate_count > 1
                has_duplicate = has_duplicate or row_has_duplicate
                total_emissions = emissions * weight if weight != 1.0 else None
                cost_per_tonne = emissions * price if price is not None else None
                total_cost = (
                    emissions * weight * price
                    if weight != 1.0 and price is not None
                    else None
                )
                source_row_id = int(stored_row["source_row_id"])
                route = stored_row["production_route"]
                results.append(
                    {
                        "inputLine": input_line,
                        "sourceRowId": source_row_id,
                        "sourceLine": source_row_id,
                        "cnCode": stored_row["cn_code"],
                        "country": stored_row["country"],
                        "year": int(stored_row["year"]),
                        "sourceProductionRoute": route,
                        "productionRouteLabel": route if route else "Unspecified",
                        "weightTonnes": weight,
                        "emissionsPerTonne": emissions,
                        "totalEmissions": total_emissions,
                        "co2Price": price,
                        "costPerTonne": cost_per_tonne,
                        "totalCbamCost": total_cost,
                        "duplicateGroupSize": duplicate_count,
                        "hasDuplicateSourceRows": row_has_duplicate,
                    }
                )
            if has_duplicate:
                duplicate_warnings.append(
                    {"inputLine": input_line, "message": AGGREGATED_DUPLICATE_WARNING}
                )

    return {
        "year": year,
        "dataMode": "aggregated_sqlite",
        "results": results,
        "issues": issues,
        "duplicateWarnings": duplicate_warnings,
    }
