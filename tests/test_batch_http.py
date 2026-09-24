from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app import db as app_db
from app.main import app

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ElementTextParser(HTMLParser):
    def __init__(self, element_id: str) -> None:
        super().__init__()
        self.element_id = element_id
        self.inside_target = False
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if dict(attrs).get("id") == self.element_id:
            self.inside_target = True

    def handle_endtag(self, tag: str) -> None:
        if self.inside_target:
            self.inside_target = False

    def handle_data(self, data: str) -> None:
        if self.inside_target:
            self.text.append(data)


class BatchHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "cbam.sqlite3"
        connection = sqlite3.connect(cls.db_path)
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
            INSERT INTO emissions VALUES ('76011010', 'Türkiye', 2026, 'K', 14.32, 1);
            """
        )
        connection.commit()
        connection.close()
        cls.original_db_path = config.DB_PATH
        config.DB_PATH = cls.db_path
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        config.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def test_batch_page_first_response_includes_the_ready_status(self) -> None:
        response = self.client.get("/batch.html")
        parser = ElementTextParser("batch-status")
        parser.feed(response.text)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            "".join(parser.text).strip(),
            "Ready for manual entry or an Excel upload.",
        )

    def test_health_check_closes_its_database_connection(self) -> None:
        connections: list[sqlite3.Connection] = []
        original_connect = app_db.open_readonly

        def tracked_connect(db_path: Path | None = None) -> sqlite3.Connection:
            connection = original_connect(db_path)
            connections.append(connection)
            return connection

        from app.api import health

        with patch.object(app_db, "open_readonly", side_effect=tracked_connect):
            response = health()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
            connections[0].execute("SELECT 1")

    def test_batch_meta_and_report_contracts(self) -> None:
        response = self.client.get("/api/batch-meta")
        self.assertEqual(response.status_code, 200)
        meta = response.json()
        self.assertEqual(meta["codes"], ["76011010"])
        self.assertEqual(meta["countries"], ["Türkiye"])

        response = self.client.post(
            "/api/batch-report",
            json={
                "year": 2026,
                "lines": [
                    {
                        "inputLine": 1,
                        "cnCode": "76011010",
                        "country": "Türkiye",
                        "weightTonnes": 2,
                        "co2Price": 65,
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["totalEmissions"], 28.64)

    def test_template_and_export_are_downloadable_xlsx_files(self) -> None:
        response = self.client.get("/api/batch-template")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], XLSX_MIME)
        self.assertIn("CBAM_Batch_Input_Template.xlsx", response.headers["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"PK"))

        response = self.client.post(
            "/api/batch-export",
            json={
                "year": 2026,
                "lines": [{"inputLine": 1, "cnCode": "76011010", "country": "Türkiye"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], XLSX_MIME)
        self.assertIn("CBAM_Batch_Report_2026.xlsx", response.headers["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"PK"))

    def test_import_requires_xlsx_content_type_and_valid_workbook(self) -> None:
        response = self.client.post(
            "/api/batch-import",
            content=b"not-xlsx",
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_workbook_type")

        response = self.client.post(
            "/api/batch-import",
            content=b"not-xlsx",
            headers={"Content-Type": XLSX_MIME},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_workbook")

    def test_invalid_json_and_unsupported_year_have_precise_errors(self) -> None:
        response = self.client.post(
            "/api/batch-report",
            content=b"{",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_json")

        response = self.client.post("/api/batch-report", json={"year": 2025, "lines": []})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_year")

    def test_json_payload_limit_is_checked_before_body_read(self) -> None:
        response = self.client.post(
            "/api/batch-report",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(10 * 1024 * 1024 + 1),
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "payload_too_large")

    def test_unknown_api_path_returns_the_json_error_contract(self) -> None:
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"], "not_found")
        self.assertIn("/api/does-not-exist", payload["message"])

    def test_api_responses_are_never_cached(self) -> None:
        for path in ("/api/health", "/api/batch-meta", "/api/does-not-exist"):
            response = self.client.get(path)
            self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0", path)

    def test_static_files_are_always_revalidated(self) -> None:
        for path in ("/", "/batch.html", "/js/map/main.js", "/cbam-brand.png"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.headers["Cache-Control"], "no-cache", path)
            revalidated = self.client.get(path, headers={"If-None-Match": response.headers["ETag"]})
            self.assertEqual(revalidated.status_code, 304, path)
            self.assertEqual(revalidated.content, b"", path)

    def test_map_geometry_is_served_precompressed(self) -> None:
        raw = (config.PUBLIC_DIR / "countries.topojson").read_bytes()
        compressed = (config.PUBLIC_DIR / "countries.topojson.gz").read_bytes()

        response = self.client.get("/countries.topojson", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        self.assertEqual(response.headers["Content-Length"], str(len(compressed)))
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(response.headers["Vary"], "Accept-Encoding")
        self.assertEqual(response.content, raw)

        revalidated = self.client.get(
            "/countries.topojson",
            headers={"Accept-Encoding": "gzip", "If-None-Match": response.headers["ETag"]},
        )
        self.assertEqual(revalidated.status_code, 304)

        plain = self.client.get("/countries.topojson", headers={"Accept-Encoding": "identity"})
        self.assertNotIn("Content-Encoding", plain.headers)
        self.assertEqual(plain.content, raw)

    def test_images_are_not_gzipped_again(self) -> None:
        response = self.client.get("/cbam-brand.png", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", response.headers)

    def test_missing_emissions_table_returns_service_unavailable(self) -> None:
        empty_db = Path(self.temp_dir.name) / "empty.sqlite3"
        sqlite3.connect(empty_db).close()
        original = config.DB_PATH
        config.DB_PATH = empty_db
        try:
            response = self.client.get("/api/batch-meta")
        finally:
            config.DB_PATH = original
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "source_rows_unavailable")


if __name__ == "__main__":
    unittest.main()
