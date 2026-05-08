from __future__ import annotations

import json
import os
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DB_PATH = ROOT / "data" / "cbam.sqlite3"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
YEARS = [2026, 2027]
DEFAULT_CN_CODE = "76011010"
ZERO_EMISSION_COUNTRIES = {"Andorra", "San Marino", "Vatican"}
MIRRORED_COUNTRIES = {
    "Kosovo": "Serbia",
    "Northern Cyprus": "Turkey",
    "Somaliland": "Somalia",
}
SILENT_MIRRORED_COUNTRIES = {"Northern Cyprus"}


def route_label(route: str) -> str:
    return route if route else "Unspecified"


def zero_emission_display() -> dict:
    return {
        "paidEmissions": 0.0,
        "sourceType": "zero_override",
        "sourceLabel": "Unspecified route",
        "routeCount": 1,
        "displayRouteValue": "",
    }


def zero_emission_detail(cn_code: str, year: int, country: str) -> dict:
    display = zero_emission_display()
    return {
        "cnCode": cn_code,
        "year": year,
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


def choose_display_value(rows: list[sqlite3.Row]) -> dict:
    unspecified_rows = [row for row in rows if row["production_route"] == ""]
    if unspecified_rows:
        row = unspecified_rows[0]
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

    average_value = sum(row["paid_emissions"] for row in rows) / len(rows)
    return {
        "paidEmissions": average_value,
        "sourceType": "average_routes",
        "sourceLabel": "Average of available routes",
        "routeCount": len(rows),
        "displayRouteValue": None,
    }


def get_country_rows(
    connection: sqlite3.Connection, cn_code: str, year: int, country: str
) -> tuple[list[sqlite3.Row], str | None]:
    mirrored_from = MIRRORED_COUNTRIES.get(country)
    if mirrored_from:
        rows = connection.execute(
            """
            SELECT production_route, paid_emissions, duplicate_count
            FROM emissions
            WHERE cn_code = ? AND year = ? AND country = ?
            ORDER BY CASE WHEN production_route = '' THEN 0 ELSE 1 END, production_route
            """,
            (cn_code, year, mirrored_from),
        ).fetchall()
        if not rows:
            return [], None
        if country in SILENT_MIRRORED_COUNTRIES:
            return rows, None
        return rows, mirrored_from

    rows = connection.execute(
        """
        SELECT production_route, paid_emissions, duplicate_count
        FROM emissions
        WHERE cn_code = ? AND year = ? AND country = ?
        ORDER BY CASE WHEN production_route = '' THEN 0 ELSE 1 END, production_route
        """,
        (cn_code, year, country),
    ).fetchall()
    if rows:
        return rows, None

    return [], None


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api(parsed)
            return

        if parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"
        super().do_GET()

    def handle_api(self, parsed) -> None:
        if parsed.path == "/api/health":
            status, payload = get_health()
            self.write_json(status, payload)
            return

        if not DB_PATH.exists():
            self.write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "error": "database_not_ready",
                    "message": (
                        "The SQLite database is missing. Run `python import_csv.py` first."
                    ),
                },
            )
            return

        try:
            if parsed.path == "/api/meta":
                self.write_json(HTTPStatus.OK, get_meta())
                return
            if parsed.path == "/api/map-data":
                params = parse_qs(parsed.query)
                cn_code = require_query_value(params, "cn_code")
                year = int(require_query_value(params, "year"))
                self.write_json(HTTPStatus.OK, get_map_data(cn_code, year))
                return
            if parsed.path == "/api/country":
                params = parse_qs(parsed.query)
                cn_code = require_query_value(params, "cn_code")
                year = int(require_query_value(params, "year"))
                country = unquote(require_query_value(params, "country"))
                self.write_json(HTTPStatus.OK, get_country_detail(cn_code, year, country))
                return
        except ValueError as exc:
            self.write_json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "message": str(exc)})
            return
        except LookupError as exc:
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": str(exc)})
            return
        except Exception as exc:  # pragma: no cover - defensive API wrapper
            self.write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "message": str(exc)},
            )
            return

        self.write_json(
            HTTPStatus.NOT_FOUND,
            {"error": "not_found", "message": f"Unknown API path: {parsed.path}"},
        )

    def write_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def require_query_value(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key, [])
    if not values or not values[0].strip():
        raise ValueError(f"Missing required query parameter: {key}")
    return values[0].strip()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def get_health() -> tuple[HTTPStatus, dict]:
    if not DB_PATH.exists():
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "ok": False,
                "error": "database_not_ready",
                "message": f"Database file not found at {DB_PATH}",
            },
        )

    try:
        with connect() as connection:
            has_rows = connection.execute("SELECT 1 FROM emissions LIMIT 1").fetchone() is not None
    except sqlite3.Error as exc:
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "ok": False,
                "error": "database_unavailable",
                "message": str(exc),
            },
        )

    return HTTPStatus.OK, {"ok": True, "hasData": has_rows}


def get_meta() -> dict:
    with connect() as connection:
        codes = [
            row["cn_code"]
            for row in connection.execute(
                "SELECT DISTINCT cn_code FROM emissions ORDER BY cn_code"
            )
        ]
        route_catalog = [
            {"value": row["production_route"], "label": route_label(row["production_route"])}
            for row in connection.execute(
                """
                SELECT DISTINCT production_route
                FROM emissions
                ORDER BY CASE WHEN production_route = '' THEN 1 ELSE 0 END, production_route
                """
            )
        ]

    return {
        "codes": codes,
        "years": YEARS,
        "routeCatalog": route_catalog,
        "defaultCode": DEFAULT_CN_CODE if DEFAULT_CN_CODE in codes else (codes[0] if codes else None),
        "defaultYear": YEARS[0],
    }


def get_map_data(cn_code: str, year: int) -> dict:
    if year not in YEARS:
        raise ValueError(f"Unsupported year: {year}")

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT country, production_route, paid_emissions, duplicate_count
            FROM emissions
            WHERE cn_code = ? AND year = ?
            ORDER BY country, CASE WHEN production_route = '' THEN 0 ELSE 1 END, production_route
            """,
            (cn_code, year),
        ).fetchall()
        if not rows:
            raise LookupError(f"No data found for CN code {cn_code} in {year}")
    rows_by_country: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        rows_by_country.setdefault(row["country"], []).append(row)

    map_values = []
    max_value = 0.0
    min_value = None
    for country, country_rows in rows_by_country.items():
        display = choose_display_value(country_rows)
        max_value = max(max_value, float(display["paidEmissions"]))
        min_value = (
            float(display["paidEmissions"])
            if min_value is None
            else min(min_value, float(display["paidEmissions"]))
        )
        map_values.append(
            {
                "country": country,
                "paidEmissions": display["paidEmissions"],
                "sourceType": display["sourceType"],
                "sourceLabel": display["sourceLabel"],
                "routeCount": display["routeCount"],
            }
        )

    for zero_country in ZERO_EMISSION_COUNTRIES:
        display = zero_emission_display()
        rows_by_country[zero_country] = []
        map_values = [item for item in map_values if item["country"] != zero_country]
        map_values.append(
            {
                "country": zero_country,
                "paidEmissions": display["paidEmissions"],
                "sourceType": display["sourceType"],
                "sourceLabel": display["sourceLabel"],
                "routeCount": display["routeCount"],
            }
        )

    for mirrored_country, source_country in MIRRORED_COUNTRIES.items():
        source_rows = rows_by_country.get(source_country)
        if not source_rows:
            continue
        rows_by_country[mirrored_country] = source_rows
        display = choose_display_value(source_rows)
        is_silent_mirror = mirrored_country in SILENT_MIRRORED_COUNTRIES
        max_value = max(max_value, float(display["paidEmissions"]))
        min_value = (
            float(display["paidEmissions"])
            if min_value is None
            else min(min_value, float(display["paidEmissions"]))
        )
        map_values = [item for item in map_values if item["country"] != mirrored_country]
        map_values.append(
            {
                "country": mirrored_country,
                "paidEmissions": display["paidEmissions"],
                "sourceType": display["sourceType"] if is_silent_mirror else "mirrored_country",
                "sourceLabel": (
                    display["sourceLabel"] if is_silent_mirror else f"Mirrored from {source_country}"
                ),
                "routeCount": display["routeCount"],
                **({} if is_silent_mirror else {"mirroredFrom": source_country}),
            }
        )

    if map_values:
        displayed_values = [float(item["paidEmissions"]) for item in map_values]
        min_value = min(displayed_values)
        max_value = max(displayed_values)

    map_values.sort(key=lambda item: item["country"])
    return {
        "cnCode": cn_code,
        "year": year,
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
        "minValue": 0.0 if min_value is None else min_value,
        "maxValue": max_value,
        "mapValues": map_values,
        "countries": sorted(rows_by_country.keys()),
    }


def get_country_detail(cn_code: str, year: int, country: str) -> dict:
    if year not in YEARS:
        raise ValueError(f"Unsupported year: {year}")

    if country in ZERO_EMISSION_COUNTRIES:
        return zero_emission_detail(cn_code, year, country)

    with connect() as connection:
        rows, mirrored_from = get_country_rows(connection, cn_code, year, country)
        if not rows:
            raise LookupError(f"No country data found for {country} for CN code {cn_code} in {year}")

    display = choose_display_value(rows)
    return {
        "cnCode": cn_code,
        "year": year,
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


def main() -> None:
    if not PUBLIC_DIR.exists():
        raise FileNotFoundError(f"Public directory not found: {PUBLIC_DIR}")

    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Serving CBAM app on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
