from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import batch, emissions

ROOT = Path(__file__).resolve().parents[1]
ELECTRICITY = json.loads((ROOT / "data/electricity_27160000.json").read_text(encoding="utf-8"))


def load_import_script():
    spec = importlib.util.spec_from_file_location("import_csv", ROOT / "scripts/import_csv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_database(path: Path, rows: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE emissions (
            cn_code TEXT NOT NULL,
            country TEXT NOT NULL,
            year INTEGER NOT NULL,
            production_route TEXT NOT NULL,
            paid_emissions REAL NOT NULL,
            duplicate_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (cn_code, country, year, production_route)
        )
        """
    )
    connection.executemany("INSERT INTO emissions VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def by_country(map_data: dict) -> dict[str, dict]:
    return {entry["country"]: entry for entry in map_data["mapValues"]}


class BundledElectricityTests(unittest.TestCase):
    """The committed database carries CN 27160000 exactly as the electricity source file says."""

    def test_electricity_records_match_the_source_file(self) -> None:
        connection = sqlite3.connect(ROOT / "data/cbam.sqlite3")
        stored = connection.execute(
            """
            SELECT country, year, production_route, paid_emissions, duplicate_count
            FROM emissions WHERE cn_code = '27160000'
            """
        ).fetchall()
        countries = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT country FROM emissions WHERE cn_code <> '27160000'"
            )
        ]
        connection.close()

        self.assertEqual(len(stored), len(countries) * len(ELECTRICITY["years"]))
        zero = set(ELECTRICITY["zeroCountries"])
        for country, year, route, value, duplicates in stored:
            if country in ELECTRICITY["specificValues"]:
                expected = ELECTRICITY["specificValues"][country]
            elif country in zero:
                expected = 0.0
            else:
                expected = ELECTRICITY["fallbackValue"]
            self.assertEqual(value, expected, (country, year))
            self.assertEqual((route, duplicates), ("", 1))
            self.assertIn(year, ELECTRICITY["years"])

    def test_bundled_database_opens_without_sidecar_journal(self) -> None:
        connection = sqlite3.connect(ROOT / "data/cbam.sqlite3")
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        connection.close()
        self.assertEqual(journal_mode, "delete")


class ElectricityMapTests(unittest.TestCase):
    def test_map_uses_mwh_units_and_country_specific_values(self) -> None:
        data = emissions.get_map_data("27160000", 2026)
        entries = by_country(data)

        self.assertEqual(data["unit"], "MWh")
        self.assertEqual(data["maxValue"], 1.148)
        self.assertEqual(entries["Bosnia and Herzegovina"]["paidEmissions"], 1.148)
        self.assertEqual(entries["Russia"]["paidEmissions"], 0.585)
        self.assertEqual(entries["Albania"]["paidEmissions"], 0.0)
        self.assertEqual(entries["Germany"]["paidEmissions"], 0.0)
        self.assertEqual(entries["Switzerland"]["paidEmissions"], 0.0)
        self.assertEqual(entries["China"]["paidEmissions"], 0.612)
        self.assertEqual(
            emissions.get_map_data("27160000", 2027)["mapValues"], data["mapValues"]
        )

    def test_kosovo_keeps_its_own_electricity_value(self) -> None:
        entries = by_country(emissions.get_map_data("27160000", 2026))
        self.assertEqual(entries["Kosovo"]["paidEmissions"], 0.984)
        self.assertNotIn("mirroredFrom", entries["Kosovo"])

        detail = emissions.get_country_detail("27160000", 2026, "Kosovo")
        self.assertIsNone(detail["mirroredFrom"])
        self.assertEqual(detail["displayValue"], 0.984)
        self.assertEqual(detail["unit"], "MWh")

    def test_other_codes_still_mirror_kosovo_from_serbia(self) -> None:
        entries = by_country(emissions.get_map_data("76011010", 2026))
        self.assertEqual(entries["Kosovo"]["mirroredFrom"], "Serbia")
        self.assertEqual(entries["Kosovo"]["paidEmissions"], entries["Serbia"]["paidEmissions"])

        detail = emissions.get_country_detail("76011010", 2026, "Kosovo")
        self.assertEqual(detail["mirroredFrom"], "Serbia")
        self.assertEqual(detail["unit"], "ton")

    def test_meta_lists_electricity_and_its_unit(self) -> None:
        meta = emissions.get_meta()
        self.assertIn("27160000", meta["codes"])
        self.assertEqual(meta["units"], {"27160000": "MWh"})
        self.assertEqual(meta["defaultUnit"], "ton")

    def test_batch_results_carry_the_quantity_unit(self) -> None:
        report = batch.build_batch_report(
            {
                "year": 2026,
                "lines": [
                    {"cnCode": "27160000", "country": "Serbia", "weightTonnes": 10, "co2Price": 75},
                    {"cnCode": "76011010", "country": "China"},
                ],
            }
        )
        electricity, aluminium = report["results"]
        self.assertEqual(electricity["quantityUnit"], "MWh")
        self.assertAlmostEqual(electricity["totalEmissions"], 10.41)
        self.assertAlmostEqual(electricity["totalCbamCost"], 780.75)
        self.assertEqual(aluminium["quantityUnit"], "ton")


class ElectricityImportTests(unittest.TestCase):
    def test_refresh_expands_electricity_to_every_known_country(self) -> None:
        module = load_import_script()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cbam.sqlite3"
            countries = sorted(
                set(ELECTRICITY["specificValues"]) | set(ELECTRICITY["zeroCountries"]) | {"China"}
            )
            create_database(db_path, [("76011010", c, 2026, "", 1.0, 1) for c in countries])

            module.refresh_electricity(db_path, ROOT / "data/electricity_27160000.json")
            module.refresh_electricity(db_path, ROOT / "data/electricity_27160000.json")

            connection = sqlite3.connect(db_path)
            values = dict(
                connection.execute(
                    "SELECT country, paid_emissions FROM emissions "
                    "WHERE cn_code = '27160000' AND year = 2027"
                ).fetchall()
            )
            count = connection.execute(
                "SELECT COUNT(*) FROM emissions WHERE cn_code = '27160000'"
            ).fetchone()[0]
            connection.close()

        self.assertEqual(count, len(countries) * 2)
        self.assertEqual(values["China"], 0.612)
        self.assertEqual(values["Serbia"], 1.041)
        self.assertEqual(values["France"], 0.0)

    def test_unknown_country_names_are_rejected(self) -> None:
        module = load_import_script()
        with self.assertRaisesRegex(ValueError, "missing from the database"):
            module.electricity_rows(["China"], ELECTRICITY)


class CachedMapApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "cbam.sqlite3"
        create_database(
            cls.db_path,
            [
                ("27160000", "Serbia", 2026, "", 1.041, 1),
                ("27160000", "Kosovo", 2026, "", 0.984, 1),
                ("76011010", "Serbia", 2026, "(L)", 0.5, 1),
            ],
        )
        cls.original_db_path = config.DB_PATH
        config.DB_PATH = cls.db_path
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        config.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def test_map_data_is_json_with_units(self) -> None:
        response = self.client.get("/api/map-data", params={"cn_code": "27160000", "year": 2026})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        payload = response.json()
        self.assertEqual(payload["unit"], "MWh")
        self.assertEqual(by_country(payload)["Kosovo"]["paidEmissions"], 0.984)

    def test_large_json_responses_are_gzipped(self) -> None:
        response = self.client.get("/api/batch-template", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", response.headers)  # xlsx is already compressed
        config.DB_PATH = self.original_db_path
        try:
            response = self.client.get(
                "/api/map-data",
                params={"cn_code": "27160000", "year": 2026},
                headers={"Accept-Encoding": "gzip"},
            )
        finally:
            config.DB_PATH = self.db_path
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        self.assertEqual(response.json()["unit"], "MWh")

    def test_cached_responses_follow_database_replacement(self) -> None:
        params = {"cn_code": "76011010", "year": 2026, "country": "Serbia"}
        first = self.client.get("/api/country", params=params)
        self.assertEqual(first.json()["displayValue"], 0.5)
        self.assertEqual(self.client.get("/api/country", params=params).content, first.content)

        connection = sqlite3.connect(self.db_path)
        connection.execute("UPDATE emissions SET paid_emissions = 0.75 WHERE cn_code = '76011010'")
        connection.commit()
        connection.close()
        stat = self.db_path.stat()
        os.utime(self.db_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        self.assertEqual(self.client.get("/api/country", params=params).json()["displayValue"], 0.75)

    def test_errors_are_not_cached(self) -> None:
        for _ in range(2):
            response = self.client.get("/api/map-data", params={"cn_code": "999", "year": 2026})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
