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
scripts/import_csv.py   Regenerates data/cbam.sqlite3 from the source CSV
data/cbam.sqlite3       Bundled runtime database (read-only at runtime)
tests/                  Python unittest suite and Node test files
```

The backend is layered: routes in `app/api.py` validate the HTTP surface and translate domain exceptions into a consistent `{"error": code, "message": text}` contract, while the service modules contain all query and calculation logic and never touch HTTP. The frontend uses native ES modules, so the pure logic (payload building, country-name normalization, color scale) is importable and unit-tested with `node --test` without any bundler.

## Project Context

This application supports thesis work related to CBAM data visualization and comparative country-level analysis. It focuses on making the dataset easier to navigate by combining map-based exploration with searchable CN codes, yearly filters, country details, and production-route information.

It is not an official CBAM system, regulatory reporting platform, or compliance calculator.

## Features

- Interactive world map with country-level CBAM values
- CN code selector covering all available codes in the bundled database
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

Some map territories are handled with explicit display rules so the visualization remains consistent with the intended dataset interpretation.

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

The Python suite covers the service layer, the HTTP contract (status codes, error codes, headers, downloads), and static page/CSS contracts, including a hash check that guards the bundled emissions data against accidental modification. The Node suite unit-tests the frontend's pure logic modules.

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

## Repository Notes

Files intentionally included:

- `app/`
- `scripts/import_csv.py`
- `public/`
- `data/cbam.sqlite3`
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
