# CBAM Visualization

CBAM Visualization is an interactive web application for exploring country-specific Carbon Border Adjustment Mechanism (CBAM) values by CN code and year. The project was developed as part of a thesis by Athanasios Papazikos and is intended as an academic, exploratory, and educational visualization tool.

The app combines a Leaflet-based world map, a local SQLite database, and a FastAPI backend. It is designed to make the underlying country and production-route data easier to inspect without relying on hard-coded frontend values.

## Architecture

```text
app/                    Python backend package
  main.py               FastAPI application factory and static file serving
  api.py                HTTP routes and the JSON error contract
  config.py             Paths, supported years, and domain constants
  db.py                 Read-only SQLite access helpers
  errors.py             Domain exceptions with stable API error codes
  services/
    emissions.py        Map explorer queries (meta, map data, country detail)
    batch.py            Batch report generation
    excel.py            Excel template, upload parsing, and report export
public/                 Static frontend (no build step)
  js/lib/               Shared fetch/download helpers
  js/map/               Map Explorer page modules
  js/batch/             Batch Report page modules
  countries.topojson    Country borders (+ .gz copy served pre-compressed)
  vendor/               topojson-client (ISC licence)
scripts/import_csv.py   Regenerates data/cbam.sqlite3 from the source CSV + electricity file
scripts/build_map_assets.py  Regenerates public/countries.topojson from the source GeoJSON
data/cbam.sqlite3       Bundled runtime database (read-only at runtime)
data/electricity_27160000.json  Electricity (CN 2716 00 00) default values
data/source/countries.geojson   Natural Earth 1:10m borders (source for the map geometry)
tests/                  Python unittest suite and Node test files
```

The backend is layered: routes in `app/api.py` validate the HTTP surface and translate domain exceptions into a consistent `{"error": code, "message": text}` contract, while the service modules contain all query and calculation logic and never touch HTTP. The frontend uses native ES modules, so the pure logic (payload building, country-name normalization, color scale) is importable and unit-tested with `node --test` without any bundler.

## Project Context

This application supports thesis work related to CBAM data visualization and comparative country-level analysis. It focuses on making the dataset easier to navigate by combining map-based exploration with searchable CN codes, yearly filters, country details, and production-route information.

It is not an official CBAM system, regulatory reporting platform, or compliance calculator.

## Features

- Interactive world map with country-level CBAM values
- CN code selector covering all available codes in the bundled database
- Electricity (CN `27160000`) with values in tCO2/MWh and costs in EUR/MWh
- Year selector for `2026` and `2027`
- Country search with instant value previews
- Country detail panel with displayed map value and available production routes
- Optional CO2 price input for quick EUR/ton estimates
- Separate Batch Report workspace for multi-line manual or Excel input
- Downloadable, validated Excel input template
- Professional three-sheet Excel report export
- SQLite-backed API instead of hard-coded country data
- Render-compatible deployment setup
- Bundled runtime database, so no CSV upload is required for deployment

## Data Handling

The app reads from:

```text
data/cbam.sqlite3
```

The original CSV source file is intentionally excluded from git:

```text
output_country_specific.csv
```

The SQLite database contains the runtime data needed by the application. If the source CSV changes locally, the database can be regenerated with:

```bash
python scripts/import_csv.py
```

or with explicit paths:

```bash
python scripts/import_csv.py --csv /path/to/output_country_specific.csv --db data/cbam.sqlite3
```

### Electricity (CN 2716 00 00)

Electricity is not part of the country-specific CSV. Its default emission factors (tCO2/MWh) live in `data/electricity_27160000.json` and are added by `scripts/import_csv.py` on every rebuild, so they survive a regeneration from the CSV. To refresh only the electricity records in the committed database (no CSV needed):

```bash
python scripts/import_csv.py --electricity-only
```

The file is expanded to one record per country already in the database, for both years:

- countries with a country-specific default use it (e.g. Bosnia and Herzegovina 1.148, Serbia 1.041, Kosovo 0.984, Albania 0.000);
- EU member states, Norway, Iceland, Liechtenstein, Switzerland, and the territories stored as zero for every other code are stored as zero;
- every other country uses the EU fallback factor of 0.612 tCO2/MWh.

The same values are used for 2026 and 2027. Electricity values are per MWh, so the map, tooltip, detail card, and batch results show `tCO2/MWh` and `EUR/MWh` for this code; in the Batch Report the weight column holds MWh for electricity lines.

### Batch data mode

The Batch Report uses the committed `emissions` table directly and does not call the map display helpers, country mirrors, route averaging, or zero-emission display overrides. It returns one result for every matching record stored in SQLite, so different production routes remain separate.

The committed database contains one averaged value per `CN code + country + year + production route` and a `duplicate_count`; it does not contain the original individual source values. When `duplicate_count` is greater than one, the Batch Report shows a transparent warning. It does not fabricate or reconstruct unavailable source rows.

This limitation is also recorded in every exported workbook.

## Batch Report

Open `/batch.html` or choose **Batch Report** in the top navigation.

Select one global reporting year (`2026` or `2027`) and add any number of input lines. Each line contains:

- `CN Code` — required and preserved as text
- `Country` — required; suggestions come directly from SQLite
- `Weight (tonnes)` — optional and defaults to `1.00`
- `CO2 Price (EUR/tCO2)` — optional

Empty rows are ignored. A partially completed or invalid row is shown as an issue without preventing other valid rows from producing results.

### Calculations

For each matching stored database record:

```text
emissions per tonne = stored paid emissions
total emissions = emissions per tonne × weight tonnes
estimated cost per tonne = emissions per tonne × CO2 price
estimated total cost = emissions per tonne × weight tonnes × CO2 price
```

Total emissions appears only when weight differs from `1.0`. Cost fields appear only when a CO2 price is supplied, and total cost additionally requires weight to differ from `1.0`.

### Excel input and export

Download `CBAM_Batch_Input_Template.xlsx` from the Batch Report page. The `Input` worksheet name and these headers are matched case-insensitively after trimming:

```text
CN Code
Country
Weight (tonnes)
CO2 Price (EUR/tCO2)
```

Only standard `.xlsx` workbooks are accepted. The server enforces a 5 MiB upload limit and a 50 MiB maximum uncompressed workbook size. Legacy `.xls`, macro-enabled `.xlsm`, password-protected, malformed, and incorrectly structured files are rejected.

Numeric Excel cells stay numeric. Text values with one decimal comma (for example `1,5`) are accepted for weight and CO2 price. Formula cells are reported as input issues instead of being treated as blank defaults; paste their calculated values before uploading.

The exported `CBAM_Batch_Report_YYYY.xlsx` contains:

- `Report` — matching stored records and calculated values
- `Input Issues` — invalid or unmatched Excel and manual input lines, including rows skipped before calculation
- `Methodology & Disclaimer` — formulas, conditional-output rules, the aggregated-data limitation, timestamp, and disclaimer

Text that could be interpreted as an Excel formula is written as literal text. Numeric values remain numeric and intentionally unavailable conditional values remain blank.

## Display Logic

For each selected `CN code + year`, the map displays every country that has available data.

Country values are selected as follows:

- If a country has an unspecified production route, that value is used.
- If a country has one production route, that route value is used.
- If a country has multiple route values and no unspecified route, the map uses their average.
- The country detail panel still lists the available production routes.

Some map territories are handled with explicit display rules so the visualization remains consistent with the intended dataset interpretation. Kosovo normally mirrors Serbia, but keeps its own value for electricity, which has a Kosovo-specific default.

### Map geometry

The map draws `public/countries.topojson`, built from the Natural Earth 1:10m borders in `data/source/countries.geojson` by:

```bash
python scripts/build_map_assets.py   # needs Node.js; runs mapshaper via npx
```

Shared borders are stored once and a topology-preserving simplification removes vertices closer than 400 m to the line. At the map's maximum zoom (6) that is below one screen pixel, so the rendered map is visually the same as the full-resolution file (in side-by-side renders less than 0.2% of pixels differ, all on anti-aliased edges) while the download drops from 14.6 MB to 0.9 MB gzipped.

The borders are drawn once, as SVG paths in Web Mercator pixel space (`public/js/map/country-layer.js`), and zooming only resizes that SVG. Leaflet's own vector layers re-project and rebuild every path after each zoom step, which froze the page for a moment on every step (longest when zooming out); this way the browser just redraws the same shapes at the new size.

## Technology

- Frontend: HTML, CSS, JavaScript (native ES modules, no build step)
- Map: Leaflet
- Backend: FastAPI served by uvicorn
- Database: SQLite (opened read-only)
- Deployment: Render web service

Excel processing uses pinned `openpyxl` and `defusedxml` dependencies.

## Local Development

Start the local app:

```bash
python -m pip install -r requirements.txt
python -m app
```

Open:

```text
http://127.0.0.1:8000
```

The server reads `HOST` and `PORT` from environment variables. By default it binds to:

```text
0.0.0.0:8000
```

For browser testing on your own machine, use:

```text
http://127.0.0.1:8000
```

## API Endpoints

- `/api/health`
- `/api/meta`
- `/api/map-data?cn_code=76011000&year=2026`
- `/api/country?cn_code=76011000&year=2026&country=Greece`

Map responses include `unit` (`"ton"`, or `"MWh"` for electricity); `/api/meta` lists the non-tonne codes in `units`.
- `GET /api/batch-meta`
- `POST /api/batch-import`
- `POST /api/batch-report`
- `GET /api/batch-template`
- `POST /api/batch-export`

The health endpoint performs a real SQLite check, so deployment health checks fail if the database is missing or unreadable.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .
node --test tests/*.mjs
```

The Python suite covers the service layer, the HTTP contract (status codes, error codes, headers, downloads), and static page/CSS contracts, including a hash check that guards the bundled emissions data against accidental modification (the electricity records are checked against `data/electricity_27160000.json` instead). The Node suite unit-tests the frontend's pure logic modules.

## Deployment On Render

This repository includes:

- `render.yaml`
- `.python-version`
- `requirements.txt`
- `data/cbam.sqlite3`

Render can deploy the app directly from GitHub.

Recommended Render settings:

```text
Runtime: Python
Build command: pip install -r requirements.txt
Start command: python -m app
Health check path: /api/health
```

Because `data/cbam.sqlite3` is committed, Render does not need the original CSV file.

The server is tuned for the free tier's small CPU and bandwidth:

- read-only API results are cached in memory per database file, so repeated map, country, and batch-meta requests skip SQLite and JSON encoding;
- openpyxl (Excel) loads only when an Excel route is first used, which shortens cold starts;
- the country geometry is served from a pre-compressed `.gz` copy (no per-request compression work), and other text responses over 1 KiB are gzipped;
- static files are revalidated with ETags (`Cache-Control: no-cache`), so returning visitors get `304 Not Modified` instead of re-downloading; API responses stay `no-store`.

A free Render service still sleeps after about 15 minutes without traffic, and the first request after that waits for it to start.

## Repository Notes

Files intentionally included:

- `app/`
- `scripts/import_csv.py`
- `scripts/build_map_assets.py`
- `public/`
- `data/cbam.sqlite3`
- `data/electricity_27160000.json`
- `data/source/countries.geojson`
- `render.yaml`
- `requirements.txt`

Files intentionally excluded:

- `output_country_specific.csv`
- SQLite temporary sidecar files
- Python cache files
- local generated bundles such as `codebase`

## Disclaimer

This project is an informal academic visualization created for general informational and educational use as part of thesis work by Athanasios Papazikos. It is not legal, tax, accounting, financial, regulatory, CBAM compliance, or other professional advice.

The data, calculations, production-route handling, country handling, and displayed outputs may be incomplete, outdated, inaccurate, or unsuitable for a specific use case. Do not rely on this app for regulatory reporting, CBAM filings, legal compliance, commercial decisions, or any other decision where accuracy matters.

Users should independently verify all information and consult qualified professionals where appropriate. The creator, contributors, maintainers, and hosts provide this project as-is, without warranties of any kind, and disclaim liability for any loss, damage, claim, cost, or consequence arising from use of the project to the fullest extent permitted by law.
