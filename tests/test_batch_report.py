from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import batch_report

from batch_report import (
    AGGREGATED_DUPLICATE_WARNING,
    SourceRowsUnavailable,
    UnsupportedYear,
    build_batch_report,
    get_batch_meta,
)


class BatchReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cbam.sqlite3"
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            """
            CREATE TABLE emissions (
                cn_code TEXT NOT NULL,
                country TEXT NOT NULL,
                year INTEGER NOT NULL,
                production_route TEXT NOT NULL,
                paid_emissions REAL NOT NULL,
                duplicate_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (cn_code, country, year, production_route)
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO emissions (
                cn_code, country, year, production_route, paid_emissions, duplicate_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("76011010", "Türkiye", 2026, "K", 14.32, 3),
                ("76011010", "Türkiye", 2026, "L", 10.0, 1),
                ("76011010", "Egypt", 2026, "", 8.5, 1),
                ("76011010", "Türkiye", 2027, "K", 12.0, 1),
                ("25231000", "Egypt", 2026, "Dry", 0.7, 1),
            ],
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_meta_comes_only_from_stored_emissions_records(self) -> None:
        self.assertEqual(
            get_batch_meta(self.db_path),
            {
                "years": [2026, 2027],
                "codes": ["25231000", "76011010"],
                "countries": ["Egypt", "Türkiye"],
                "dataMode": "aggregated_sqlite",
            },
        )

    def test_database_connection_is_closed_after_meta_is_loaded(self) -> None:
        connections: list[sqlite3.Connection] = []
        original_connect = batch_report._connect

        def tracked_connect(db_path: Path) -> sqlite3.Connection:
            connection = original_connect(db_path)
            connections.append(connection)
            return connection

        with patch.object(batch_report, "_connect", side_effect=tracked_connect):
            get_batch_meta(self.db_path)

        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
            connections[0].execute("SELECT 1")

    def test_weight_defaults_to_one_and_conditional_values_stay_blank(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {
                        "inputLine": 1,
                        "cnCode": "76011010",
                        "country": "Egypt",
                        "weightTonnes": "",
                        "co2Price": "",
                    }
                ],
            },
        )
        row = report["results"][0]
        self.assertEqual(row["productionRouteLabel"], "Unspecified")
        self.assertEqual(row["weightTonnes"], 1.0)
        self.assertIsNone(row["totalEmissions"])
        self.assertIsNone(row["costPerTonne"])
        self.assertIsNone(row["totalCbamCost"])

    def test_custom_weight_and_price_calculations_are_numeric(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {
                        "inputLine": 7,
                        "cnCode": "76011010",
                        "country": "Egypt",
                        "weightTonnes": 100,
                        "co2Price": 65,
                    }
                ],
            },
        )
        row = report["results"][0]
        self.assertEqual(row["totalEmissions"], 850.0)
        self.assertEqual(row["costPerTonne"], 552.5)
        self.assertEqual(row["totalCbamCost"], 55250.0)

    def test_country_matching_is_case_insensitive_and_returns_canonical_name(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {
                        "inputLine": 9,
                        "cnCode": "76011010",
                        "country": "  türkiYE  ",
                    }
                ],
            },
        )
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["results"][0]["country"], "Türkiye")

    def test_each_stored_route_is_returned_without_map_route_selection(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {"inputLine": 1, "cnCode": "76011010", "country": "Türkiye"}
                ],
            },
        )
        self.assertEqual(
            [(row["sourceProductionRoute"], row["emissionsPerTonne"]) for row in report["results"]],
            [("K", 14.32), ("L", 10.0)],
        )

    def test_duplicate_count_flags_one_warning_without_fabricating_rows(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {"inputLine": 1, "cnCode": "76011010", "country": "Türkiye"}
                ],
            },
        )
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual(report["results"][0]["duplicateGroupSize"], 3)
        self.assertTrue(report["results"][0]["hasDuplicateSourceRows"])
        self.assertFalse(report["results"][1]["hasDuplicateSourceRows"])
        self.assertEqual(
            report["duplicateWarnings"],
            [{"inputLine": 1, "message": AGGREGATED_DUPLICATE_WARNING}],
        )

    def test_invalid_and_unmatched_lines_become_issues_without_blocking_valid_lines(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "lines": [
                    {"inputLine": 1, "cnCode": "", "country": "Egypt"},
                    {"inputLine": 2, "cnCode": "76011010", "country": ""},
                    {
                        "inputLine": 3,
                        "cnCode": "76011010",
                        "country": "Egypt",
                        "weightTonnes": 0,
                    },
                    {
                        "inputLine": 4,
                        "cnCode": "76011010",
                        "country": "Egypt",
                        "co2Price": -1,
                    },
                    {"inputLine": 5, "cnCode": "99999999", "country": "Egypt"},
                    {"inputLine": 6, "cnCode": "76011010", "country": "Atlantis"},
                    {"inputLine": 7, "cnCode": "25231000", "country": "Türkiye"},
                    {"inputLine": 8, "cnCode": "76011010", "country": "Egypt"},
                ],
            },
        )
        self.assertEqual([row["inputLine"] for row in report["results"]], [8])
        self.assertEqual(
            [issue["error"] for issue in report["issues"]],
            [
                "CN code is required.",
                "Country is required.",
                "Weight must be a number greater than zero.",
                "CO₂ price must be a number greater than or equal to zero.",
                "Unknown CN code.",
                "Unknown country.",
                "No source rows found for this CN code, country, and year.",
            ],
        )

    def test_excel_import_issues_are_preserved_with_valid_report_rows(self) -> None:
        report = build_batch_report(
            self.db_path,
            {
                "year": 2026,
                "inputIssues": [
                    {
                        "inputLine": 4,
                        "cnCode": "76011010",
                        "country": "Egypt",
                        "weightTonnes": "=1+1",
                        "co2Price": 65,
                        "error": (
                            "Excel formulas are not supported. "
                            "Paste calculated values instead."
                        ),
                    }
                ],
                "lines": [
                    {"inputLine": 2, "cnCode": "76011010", "country": "Egypt"}
                ],
            },
        )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(len(report["issues"]), 1)
        self.assertEqual(report["issues"][0]["inputLine"], 4)
        self.assertIn("Excel formulas", report["issues"][0]["error"])

    def test_fully_empty_rows_are_ignored(self) -> None:
        report = build_batch_report(
            self.db_path,
            {"year": 2026, "lines": [{"inputLine": 1, "cnCode": "", "country": ""}]},
        )
        self.assertEqual(report["results"], [])
        self.assertEqual(report["issues"], [])

    def test_unsupported_year_is_rejected(self) -> None:
        with self.assertRaisesRegex(UnsupportedYear, "Unsupported year: 2025"):
            build_batch_report(self.db_path, {"year": 2025, "lines": []})

    def test_missing_emissions_table_is_reported(self) -> None:
        missing_db = Path(self.temp_dir.name) / "missing.sqlite3"
        sqlite3.connect(missing_db).close()
        with self.assertRaises(SourceRowsUnavailable):
            get_batch_meta(missing_db)


if __name__ == "__main__":
    unittest.main()
