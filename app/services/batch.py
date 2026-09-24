"""Batch report generation from user-supplied CN code / country lines."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from app.config import DEFAULT_QUANTITY_UNIT, QUANTITY_UNITS, SUPPORTED_YEARS
from app.db import connection, ensure_emissions_table
from app.errors import BadRequest, UnsupportedYear

AGGREGATED_DUPLICATE_WARNING = (
    "Potential duplicate source records found. The bundled SQLite database stores the "
    "averaged record and its duplicate count; individual original source values are not "
    "available. Verify the value against the applicable EU legislation before reporting "
    "or compliance use."
)

_WEIGHT_ERROR = "Weight must be a number greater than zero."
_PRICE_ERROR = "CO₂ price must be a number greater than or equal to zero."


def get_batch_meta(db_path: Path | str | None = None) -> dict:
    with connection(db_path) as conn:
        ensure_emissions_table(conn)
        codes = [
            row["cn_code"]
            for row in conn.execute("SELECT DISTINCT cn_code FROM emissions ORDER BY cn_code")
        ]
        countries = [
            row["country"]
            for row in conn.execute("SELECT DISTINCT country FROM emissions ORDER BY country")
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


def _normalize_input_line(raw: Any, fallback: int) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return raw
    return fallback


def _validated_input_issues(raw_issues: Any) -> list[dict]:
    if not isinstance(raw_issues, list):
        raise BadRequest("Input issues must be a JSON array.")
    issues: list[dict] = []
    for index, raw in enumerate(raw_issues, start=1):
        if not isinstance(raw, dict):
            raise BadRequest("Each input issue must be an object.")
        error = raw.get("error")
        if not isinstance(error, str) or not error.strip():
            raise BadRequest("Each input issue must include an error message.")
        issues.append(_issue(raw, _normalize_input_line(raw.get("inputLine"), index), error.strip()))
    return issues


class _LineError(Exception):
    """Validation failure for a single input line (collected, not raised to caller)."""


def _parse_line(raw_line: dict) -> tuple[str, str, float, float | None]:
    raw_code = raw_line.get("cnCode", "")
    raw_country = raw_line.get("country", "")

    if not isinstance(raw_code, str) or not raw_code.strip():
        raise _LineError("CN code is required.")
    if not isinstance(raw_country, str) or not raw_country.strip():
        raise _LineError("Country is required.")

    try:
        weight = _parse_number(raw_line.get("weightTonnes", ""), default=1.0, error=_WEIGHT_ERROR)
        if weight is None or weight <= 0:
            raise ValueError(_WEIGHT_ERROR)
        price = _parse_number(raw_line.get("co2Price", ""), default=None, error=_PRICE_ERROR)
        if price is not None and price < 0:
            raise ValueError(_PRICE_ERROR)
    except ValueError as exc:
        raise _LineError(str(exc)) from exc

    return raw_code.strip(), raw_country.strip(), weight, price


def _result_rows(
    stored_rows: list, input_line: int, weight: float, price: float | None
) -> tuple[list[dict], bool]:
    results: list[dict] = []
    has_duplicate = False
    for stored in stored_rows:
        emissions = float(stored["paid_emissions"])
        duplicate_count = int(stored["duplicate_count"])
        has_duplicate = has_duplicate or duplicate_count > 1
        source_row_id = int(stored["source_row_id"])
        route = stored["production_route"]
        results.append(
            {
                "inputLine": input_line,
                "sourceRowId": source_row_id,
                "sourceLine": source_row_id,
                "cnCode": stored["cn_code"],
                "country": stored["country"],
                "year": int(stored["year"]),
                "sourceProductionRoute": route,
                "productionRouteLabel": route if route else "Unspecified",
                "weightTonnes": weight,
                "quantityUnit": QUANTITY_UNITS.get(stored["cn_code"], DEFAULT_QUANTITY_UNIT),
                "emissionsPerTonne": emissions,
                "totalEmissions": emissions * weight if weight != 1.0 else None,
                "co2Price": price,
                "costPerTonne": emissions * price if price is not None else None,
                "totalCbamCost": (
                    emissions * weight * price if weight != 1.0 and price is not None else None
                ),
                "duplicateGroupSize": duplicate_count,
                "hasDuplicateSourceRows": duplicate_count > 1,
            }
        )
    return results, has_duplicate


def build_batch_report(payload: Any, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise BadRequest("The request body must be a JSON object.")
    year = payload.get("year")
    if year not in SUPPORTED_YEARS:
        raise UnsupportedYear(f"Unsupported year: {year}")
    lines = payload.get("lines", [])
    if not isinstance(lines, list):
        raise BadRequest("Lines must be a JSON array.")
    issues = _validated_input_issues(payload.get("inputIssues", []))

    results: list[dict] = []
    duplicate_warnings: list[dict] = []

    with connection(db_path) as conn:
        ensure_emissions_table(conn)
        valid_codes = {
            row["cn_code"] for row in conn.execute("SELECT DISTINCT cn_code FROM emissions")
        }
        country_by_key = {
            row["country"].casefold(): row["country"]
            for row in conn.execute("SELECT DISTINCT country FROM emissions")
        }

        for index, raw_line in enumerate(lines, start=1):
            if not isinstance(raw_line, dict):
                issues.append(_issue({}, index, "Each input line must be an object."))
                continue
            input_line = _normalize_input_line(raw_line.get("inputLine"), index)

            if all(
                _is_blank(raw_line.get(field, ""))
                for field in ("cnCode", "country", "weightTonnes", "co2Price")
            ):
                continue

            try:
                cn_code, country, weight, price = _parse_line(raw_line)
            except _LineError as exc:
                issues.append(_issue(raw_line, input_line, str(exc)))
                continue

            if cn_code not in valid_codes:
                issues.append(_issue(raw_line, input_line, "Unknown CN code."))
                continue
            canonical_country = country_by_key.get(country.casefold())
            if canonical_country is None:
                issues.append(_issue(raw_line, input_line, "Unknown country."))
                continue

            stored_rows = conn.execute(
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
                (cn_code, canonical_country, year),
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

            line_results, has_duplicate = _result_rows(stored_rows, input_line, weight, price)
            results.extend(line_results)
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
