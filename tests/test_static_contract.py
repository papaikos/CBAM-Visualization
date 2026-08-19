from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def test_map_javascript_is_byte_for_byte_unchanged(self) -> None:
        expected = (ROOT / "tests/fixtures/app_js.sha256").read_text().strip()
        actual = hashlib.sha256((ROOT / "public/app.js").read_bytes()).hexdigest()
        self.assertEqual(actual, expected)

    def test_map_emissions_records_are_unchanged(self) -> None:
        connection = sqlite3.connect(ROOT / "data/cbam.sqlite3")
        rows = connection.execute(
            """
            SELECT cn_code, country, year, production_route, paid_emissions, duplicate_count
            FROM emissions
            ORDER BY cn_code, country, year, production_route
            """
        ).fetchall()
        connection.close()
        actual = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        expected = (ROOT / "tests/fixtures/emissions_table.sha256").read_text().strip()
        self.assertEqual(actual, expected)

    def test_map_page_has_non_invasive_top_level_navigation(self) -> None:
        html = (ROOT / "public/index.html").read_text()
        self.assertIn('href="/"', html)
        self.assertIn('href="/batch.html"', html)
        self.assertIn('aria-current="page">Map Explorer', html)
        self.assertIn('href="/tabs.css', html)
        self.assertIn('id="map"', html)

    def test_map_and_batch_pages_share_the_compact_site_brand(self) -> None:
        map_html = (ROOT / "public/index.html").read_text()
        batch_html = (ROOT / "public/batch.html").read_text()
        for html in (map_html, batch_html):
            self.assertRegex(html, r'class="[^"]*\bsite-brand\b[^"]*"')
            self.assertIn('class="brand-mark"', html)
            self.assertIn('class="brand-kicker">CBAM visualization', html)
            self.assertIn('class="brand-title">Global Trade Insights', html)
        self.assertNotIn("CBAM Visualization By Athanasios Papazikos", map_html)

    def test_shared_brand_uses_local_cbam_artwork_instead_of_initials(self) -> None:
        self.assertTrue((ROOT / "public/cbam-brand.png").is_file())
        for page in ("index.html", "batch.html"):
            html = (ROOT / "public" / page).read_text()
            self.assertIn('class="brand-image"', html)
            self.assertIn('src="/cbam-brand.png"', html)
            self.assertIn('alt="CBAM"', html)
            self.assertNotIn(">GT</a>", html)

    def test_shared_brand_artwork_is_precropped_for_the_square_header_slot(self) -> None:
        png_header = (ROOT / "public/cbam-brand.png").read_bytes()[:24]
        self.assertEqual(png_header[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png_header[16:24])
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 512)

    def test_desktop_headers_share_right_aligned_mode_toggle_geometry(self) -> None:
        map_css = (ROOT / "public/styles.css").read_text()
        batch_css = (ROOT / "public/batch-report.css").read_text()
        tabs_css = (ROOT / "public/tabs.css").read_text()
        self.assertIn("@media (min-width: 1200px)", map_css)
        self.assertIn(
            "grid-template-columns: minmax(13rem, 1fr) auto auto auto;",
            map_css,
        )
        for css in (map_css, batch_css):
            self.assertIn("min-height: 5.75rem;", css)
            self.assertIn("padding: 0.75rem clamp(1.5rem, 2vw, 2rem);", css)
        self.assertIn("grid-template-columns: 10rem 10.5rem 10rem;", map_css)
        self.assertIn("max-width: 10rem;", map_css)
        self.assertIn("width: 15.7rem;", tabs_css)
        self.assertIn("flex: 1 1 0;", tabs_css)
        self.assertIn("width: calc(100vw - 2rem);", tabs_css)

    def test_map_header_prerenders_stable_centered_control_defaults(self) -> None:
        html = (ROOT / "public/index.html").read_text()
        css = (ROOT / "public/styles.css").read_text()
        self.assertRegex(html, r'id="cn-code-input"\s+value="76011010"')
        self.assertIn('list="cn-code-options"', html)
        self.assertIn('id="cn-code-menu-toggle"', html)
        self.assertIn('id="cn-code-menu"', html)
        self.assertIn('src="/cn-code-picker.js', html)
        self.assertIn('class="year-button active" data-year="2026"', html)
        self.assertIn('class="year-button" data-year="2027"', html)
        self.assertRegex(
            css,
            r"(?s)\.topbar\s*\{[^}]*position: relative;[^}]*z-index: 2000;",
        )
        self.assertIn("grid-template-columns: 10rem 10.5rem 10rem;", css)
        self.assertIn("text-align: center;", css)

    def test_custom_cn_picker_suppresses_native_datalist_chrome(self) -> None:
        css = (ROOT / "public/styles.css").read_text()
        self.assertRegex(
            css,
            r"(?s)#cn-code-input\s*\{[^}]*appearance: none;[^}]*-webkit-appearance: none;",
        )
        self.assertRegex(
            css,
            r"(?s)#cn-code-input::-webkit-calendar-picker-indicator\s*\{[^}]*display: none !important;",
        )

    def test_co2_example_hides_only_while_the_empty_field_is_focused(self) -> None:
        css = (ROOT / "public/styles.css").read_text()
        self.assertRegex(
            css,
            r"(?s)#co2-price-input:focus::placeholder\s*\{[^}]*opacity: 0;",
        )

    def test_desktop_map_header_groups_center_in_the_white_header(self) -> None:
        html = (ROOT / "public/index.html").read_text()
        css = (ROOT / "public/styles.css").read_text()
        self.assertIn("CO₂ price (EUR/tCO₂)", html)
        self.assertNotIn("transform: translateY(0.65rem);", css)

    def test_desktop_map_labels_float_without_moving_the_control_row(self) -> None:
        html = (ROOT / "public/index.html").read_text()
        css = (ROOT / "public/styles.css").read_text()
        self.assertIn(
            '<span class="toolbar-field-label">CO₂ price (EUR/tCO₂)</span>',
            html,
        )
        self.assertIn('<span class="toolbar-field-label">Year</span>', html)
        self.assertIn('placeholder="e.g. 65 €"', html)
        self.assertRegex(
            css,
            r"(?s)@media \(min-width: 1200px\).*?\.toolbar\s*\{[^}]*align-items: center;",
        )
        self.assertRegex(
            css,
            r"(?s)@media \(min-width: 1200px\).*?\.toolbar-field-label\s*\{[^}]*position: absolute;[^}]*bottom: calc\(100% \+ 0\.42rem\);",
        )
        self.assertRegex(
            css,
            r"(?s)@media \(min-width: 1200px\).*?\.disclaimer-trigger\s*\{[^}]*min-height: 2\.85rem;",
        )

    def test_desktop_map_header_groups_share_the_same_small_downward_offset(self) -> None:
        css = (ROOT / "public/styles.css").read_text()
        self.assertRegex(
            css,
            r"(?s)@media \(min-width: 1200px\).*?\.title-copy,\s*\.disclaimer-trigger,\s*\.toolbar,\s*\.title-block \.primary-nav\s*\{[^}]*transform: translateY\(4px\);",
        )

    def test_desktop_country_detail_card_stays_compact_over_the_map(self) -> None:
        css = (ROOT / "public/styles.css").read_text()
        self.assertRegex(
            css,
            r"(?s)\.detail-card\s*\{[^}]*width: min\(clamp\(20rem, 30vw, 24rem\), calc\(100vw - 2rem\)\);[^}]*max-height: min\(62svh, 34rem\);",
        )
        self.assertRegex(
            css,
            r"(?s)\.detail-header h2\s*\{[^}]*font-size: clamp\(1\.3rem, 1\.8vw, 1\.55rem\);",
        )

    def test_map_country_search_is_compact_only_above_phone_width(self) -> None:
        css = (ROOT / "public/styles.css").read_text()
        self.assertIn("@media (min-width: 761px)", css)
        self.assertIn("clamp(16rem, 24vw, 19.5rem)", css)
        self.assertIn("padding: clamp(0.7rem, 0.85vw, 0.8rem);", css)
        self.assertIn("height: clamp(2.3rem, 2.5vw, 2.55rem);", css)

    def test_batch_hero_uses_compact_professional_dimensions(self) -> None:
        css = (ROOT / "public/batch-report.css").read_text()
        self.assertIn("padding: clamp(1.35rem, 2.5vw, 2.25rem);", css)
        self.assertIn("font-size: clamp(1.85rem, 3.2vw, 3rem);", css)
        self.assertIn("align-items: center;", css)
        self.assertIn("min-width: 15rem;", css)
        self.assertIn("padding: 0.95rem;", css)
        self.assertIn("min-height: 2.6rem;", css)

    def test_batch_page_exposes_accessible_controls_and_result_regions(self) -> None:
        html = (ROOT / "public/batch.html").read_text()
        for expected in (
            'href="/"',
            'aria-current="page">Batch Report',
            'id="batch-year-buttons"',
            'id="batch-input-card"',
            'id="batch-input-rows"',
            'id="batch-file-input"',
            'id="upload-workbook"',
            'id="batch-drop-hint"',
            'id="batch-status"',
            'id="batch-issues"',
            'id="duplicate-warning"',
            'id="batch-results"',
            'id="generate-report"',
            'id="export-report"',
        ):
            self.assertIn(expected, html)
        self.assertNotIn("countries.geojson", html)

    def test_batch_javascript_is_loaded_only_by_batch_page(self) -> None:
        map_html = (ROOT / "public/index.html").read_text()
        batch_html = (ROOT / "public/batch.html").read_text()
        self.assertNotIn("batch-report.js", map_html)
        self.assertIn('src="/batch-report.js', batch_html)

    def test_scrollable_input_table_labels_action_column_without_off_canvas_text(self) -> None:
        html = (ROOT / "public/batch.html").read_text()
        self.assertIn('<th scope="col" aria-label="Remove row"></th>', html)
        self.assertNotIn(
            '<th scope="col"><span class="visually-hidden">Remove row</span></th>',
            html,
        )

    def test_batch_table_centers_route_and_remove_actions(self) -> None:
        css = (ROOT / "public/batch-report.css").read_text()
        self.assertIn(
            ".results-table th:nth-child(4),\n"
            ".results-table td:nth-child(4) {\n"
            "  text-align: center;\n}",
            css,
        )
        self.assertIn(
            ".input-table td:last-child {\n  vertical-align: middle;\n}",
            css,
        )
        self.assertIn("margin: 0 auto;", css)


if __name__ == "__main__":
    unittest.main()
