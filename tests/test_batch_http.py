from __future__ import annotations

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import server


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
        cls.original_db_path = server.DB_PATH
        server.DB_PATH = cls.db_path
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        server.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        response_headers = {key: value for key, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, response_body

    def post_json(self, path: str, payload: dict) -> tuple[int, dict[str, str], bytes]:
        return self.request(
            "POST",
            path,
            json.dumps(payload).encode("utf-8"),
            "application/json",
        )

    def test_batch_page_first_response_includes_the_ready_status(self) -> None:
        status, _headers, body = self.request("GET", "/batch.html")
        parser = ElementTextParser("batch-status")
        parser.feed(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(
            "".join(parser.text).strip(),
            "Ready for manual entry or an Excel upload.",
        )

    def test_health_check_closes_its_database_connection(self) -> None:
        connections: list[sqlite3.Connection] = []
        original_connect = server.connect

        def tracked_connect() -> sqlite3.Connection:
            connection = original_connect()
            connections.append(connection)
            return connection

        with patch.object(server, "connect", side_effect=tracked_connect):
            status, _body = server.get_health()

        self.assertEqual(status, 200)
        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
            connections[0].execute("SELECT 1")

    def test_batch_meta_and_report_contracts(self) -> None:
        status, _headers, body = self.request("GET", "/api/batch-meta")
        self.assertEqual(status, 200)
        meta = json.loads(body)
        self.assertEqual(meta["codes"], ["76011010"])
        self.assertEqual(meta["countries"], ["Türkiye"])

        status, _headers, body = self.post_json(
            "/api/batch-report",
            {
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
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["results"][0]["totalEmissions"], 28.64)

    def test_template_and_export_are_downloadable_xlsx_files(self) -> None:
        status, headers, body = self.request("GET", "/api/batch-template")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], XLSX_MIME)
        self.assertIn("CBAM_Batch_Input_Template.xlsx", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"PK"))

        status, headers, body = self.post_json(
            "/api/batch-export",
            {
                "year": 2026,
                "lines": [
                    {"inputLine": 1, "cnCode": "76011010", "country": "Türkiye"}
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], XLSX_MIME)
        self.assertIn("CBAM_Batch_Report_2026.xlsx", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"PK"))

    def test_import_requires_xlsx_content_type_and_valid_workbook(self) -> None:
        status, _headers, body = self.request(
            "POST", "/api/batch-import", b"not-xlsx", "application/octet-stream"
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "unsupported_workbook_type")

        status, _headers, body = self.request(
            "POST", "/api/batch-import", b"not-xlsx", XLSX_MIME
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_workbook")

    def test_invalid_json_and_unsupported_year_have_precise_errors(self) -> None:
        status, _headers, body = self.request(
            "POST", "/api/batch-report", b"{", "application/json"
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_json")

        status, _headers, body = self.post_json(
            "/api/batch-report", {"year": 2025, "lines": []}
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "unsupported_year")

    def test_json_payload_limit_is_checked_before_body_read(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("POST", "/api/batch-report")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(10 * 1024 * 1024 + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        connection.close()
        self.assertEqual(response.status, 413)
        self.assertEqual(json.loads(body)["error"], "payload_too_large")

    def test_missing_emissions_table_returns_service_unavailable(self) -> None:
        empty_db = Path(self.temp_dir.name) / "empty.sqlite3"
        sqlite3.connect(empty_db).close()
        server.DB_PATH = empty_db
        try:
            status, _headers, body = self.request("GET", "/api/batch-meta")
        finally:
            server.DB_PATH = self.db_path
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "source_rows_unavailable")


if __name__ == "__main__":
    unittest.main()
