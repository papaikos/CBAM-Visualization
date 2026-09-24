"""Map-explorer queries: metadata, per-country map values, country detail.

Display-value rule (shared by the map and the detail card):

* a country with an *unspecified* production route uses that value;
* a country with a single route uses that route's value;
* a country with several specified routes uses their average.

Some territories are special-cased in :mod:`app.config`: micro-states are
shown as zero, and a few territories mirror the values of another country
(except where ``UNMIRRORED_COUNTRIES_BY_CODE`` keeps a territory's own records,
e.g. Kosovo for electricity).

Values are per tonne of goods, except for CN codes listed in
``QUANTITY_UNITS`` (electricity is per MWh); responses carry the ``unit``.
"""

from __future__ import annotations

import sqlite3

from app.config import (
    DEFAULT_CN_CODE,
    DEFAULT_QUANTITY_UNIT,
    MIRRORED_COUNTRIES,
    QUANTITY_UNITS,
    SILENT_MIRRORED_COUNTRIES,
    SUPPORTED_YEARS,
    UNMIRRORED_COUNTRIES_BY_CODE,
    ZERO_EMISSION_COUNTRIES,
)
from app.db import connection
from app.errors import BadRequest, NotFound

_COUNTRY_ROWS_SQL = """
    SELECT production_route, paid_emissions, duplicate_count
    FROM emissions
    WHERE cn_code = ? AND year = ? AND country = ?
    ORDER BY CASE WHEN production_route = '' THEN 0 ELSE 1 END, production_route
"""


def route_label(route: str) -> str:
    return route if route else "Unspecified"


def quantity_unit(cn_code: str) -> str:
    return QUANTITY_UNITS.get(cn_code, DEFAULT_QUANTITY_UNIT)


def _mirror_source(cn_code: str, country: str) -> str | None:
    if country in UNMIRRORED_COUNTRIES_BY_CODE.get(cn_code, ()):
        return None
    return MIRRORED_COUNTRIES.get(country)


def _require_supported_year(year: int) -> None:
    if year not in SUPPORTED_YEARS:
        raise BadRequest(f"Unsupported year: {year}")


def _choose_display_value(rows: list[sqlite3.Row]) -> dict:
    unspecified = [row for row in rows if row["production_route"] == ""]
    if unspecified:
        row = unspecified[0]
        return {
            "paidEmissions": row["paid_emissions"],
            "sourceType": "unspecified_route",
            "sourceLabel": "Unspecified route",
            "routeCount": len(rows),
            "displayRouteValue": row["production_route"],
        }

    if len(rows) == 1:
        row = rows[0]
        return {
            "paidEmissions": row["paid_emissions"],
            "sourceType": "single_route",
            "sourceLabel": route_label(row["production_route"]),
            "routeCount": 1,
            "displayRouteValue": row["production_route"],
        }

    average = sum(row["paid_emissions"] for row in rows) / len(rows)
    return {
        "paidEmissions": average,
        "sourceType": "average_routes",
        "sourceLabel": "Average of available routes",
        "routeCount": len(rows),
        "displayRouteValue": None,
    }


def _zero_emission_display() -> dict:
    return {
        "paidEmissions": 0.0,
        "sourceType": "zero_override",
        "sourceLabel": "Unspecified route",
        "routeCount": 1,
        "displayRouteValue": "",
    }


def _zero_emission_detail(cn_code: str, year: int, country: str) -> dict:
    display = _zero_emission_display()
    return {
        "cnCode": cn_code,
        "year": year,
        "unit": quantity_unit(cn_code),
        "country": country,
        "mirroredFrom": None,
        "displayValue": display["paidEmissions"],
        "displaySourceType": display["sourceType"],
        "displaySourceLabel": display["sourceLabel"],
        "routes": [
            {
                "value": "",
                "label": route_label(""),
                "paidEmissions": 0.0,
                "isDisplayedValue": True,
                "duplicateCount": 1,
            }
        ],
    }


def _map_entry(country: str, display: dict, **extra: object) -> dict:
    return {
        "country": country,
        "paidEmissions": display["paidEmissions"],
        "sourceType": display["sourceType"],
        "sourceLabel": display["sourceLabel"],
        "routeCount": display["routeCount"],
        **extra,
    }


def get_meta() -> dict:
    with connection() as conn:
        codes = [
            row["cn_code"]
            for row in conn.execute("SELECT DISTINCT cn_code FROM emissions ORDER BY cn_code")
        ]
        route_catalog = [
            {"value": row["production_route"], "label": route_label(row["production_route"])}
            for row in conn.execute(
                """
                SELECT DISTINCT production_route
                FROM emissions
                ORDER BY CASE WHEN production_route = '' THEN 1 ELSE 0 END, production_route
                """
            )
        ]

    return {
        "codes": codes,
        "years": list(SUPPORTED_YEARS),
        "routeCatalog": route_catalog,
        "defaultCode": DEFAULT_CN_CODE if DEFAULT_CN_CODE in codes else (codes[0] if codes else None),
        "defaultYear": SUPPORTED_YEARS[0],
        "defaultUnit": DEFAULT_QUANTITY_UNIT,
        "units": {code: unit for code, unit in QUANTITY_UNITS.items() if code in codes},
    }


def get_map_data(cn_code: str, year: int) -> dict:
    _require_supported_year(year)

    with connection() as conn:
        rows = conn.execute(
            """
            SELECT country, production_route, paid_emissions, duplicate_count
            FROM emissions
            WHERE cn_code = ? AND year = ?
            ORDER BY country, CASE WHEN production_route = '' THEN 0 ELSE 1 END, production_route
            """,
            (cn_code, year),
        ).fetchall()
    if not rows:
        raise NotFound(f"No data found for CN code {cn_code} in {year}")

    rows_by_country: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        rows_by_country.setdefault(row["country"], []).append(row)

    entries: dict[str, dict] = {
        country: _map_entry(country, _choose_display_value(country_rows))
        for country, country_rows in rows_by_country.items()
    }

    for zero_country in ZERO_EMISSION_COUNTRIES:
        rows_by_country[zero_country] = []
        entries[zero_country] = _map_entry(zero_country, _zero_emission_display())

    for mirrored_country in MIRRORED_COUNTRIES:
        source_country = _mirror_source(cn_code, mirrored_country)
        source_rows = rows_by_country.get(source_country) if source_country else None
        if not source_rows:
            continue
        rows_by_country[mirrored_country] = source_rows
        display = _choose_display_value(source_rows)
        if mirrored_country in SILENT_MIRRORED_COUNTRIES:
            entries[mirrored_country] = _map_entry(mirrored_country, display)
        else:
            entries[mirrored_country] = _map_entry(
                mirrored_country,
                {
                    **display,
                    "sourceType": "mirrored_country",
                    "sourceLabel": f"Mirrored from {source_country}",
                },
                mirroredFrom=source_country,
            )

    map_values = sorted(entries.values(), key=lambda item: item["country"])
    displayed = [float(item["paidEmissions"]) for item in map_values]

    return {
        "cnCode": cn_code,
        "year": year,
        "unit": quantity_unit(cn_code),
        "displayRuleSummary": "Each country uses its own value",
        "displayRuleDescription": (
            "If a country has an unspecified production route, that value is used. "
            "If it has a single route, that route value is used. "
            "If it has multiple route values and no unspecified route, the map uses their average."
        ),
        "coverage": {
            "totalCountries": len(rows_by_country),
            "mapCountries": len(rows_by_country),
        },
        "minValue": min(displayed) if displayed else 0.0,
        "maxValue": max(displayed) if displayed else 0.0,
        "mapValues": map_values,
        "countries": sorted(rows_by_country.keys()),
    }


def get_country_detail(cn_code: str, year: int, country: str) -> dict:
    _require_supported_year(year)

    if country in ZERO_EMISSION_COUNTRIES:
        return _zero_emission_detail(cn_code, year, country)

    with connection() as conn:
        rows, mirrored_from = _country_rows(conn, cn_code, year, country)
    if not rows:
        raise NotFound(f"No country data found for {country} for CN code {cn_code} in {year}")

    display = _choose_display_value(rows)
    return {
        "cnCode": cn_code,
        "year": year,
        "unit": quantity_unit(cn_code),
        "country": country,
        "mirroredFrom": mirrored_from,
        "displayValue": display["paidEmissions"],
        "displaySourceType": display["sourceType"],
        "displaySourceLabel": display["sourceLabel"],
        "routes": [
            {
                "value": row["production_route"],
                "label": route_label(row["production_route"]),
                "paidEmissions": row["paid_emissions"],
                "isDisplayedValue": (
                    display["displayRouteValue"] is not None
                    and row["production_route"] == display["displayRouteValue"]
                ),
                "duplicateCount": row["duplicate_count"],
            }
            for row in rows
        ],
    }


def _country_rows(
    conn: sqlite3.Connection, cn_code: str, year: int, country: str
) -> tuple[list[sqlite3.Row], str | None]:
    """Return the stored rows for a country plus its disclosed mirror source."""
    source_country = _mirror_source(cn_code, country) or country
    rows = conn.execute(_COUNTRY_ROWS_SQL, (cn_code, year, source_country)).fetchall()
    if not rows:
        return [], None
    if source_country == country or country in SILENT_MIRRORED_COUNTRIES:
        return rows, None
    return rows, source_country
