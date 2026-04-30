# CBAM Visualization

CBAM Visualization is an interactive web application for exploring country-specific Carbon Border Adjustment Mechanism (CBAM) values by CN code and year. The project was developed as part of a thesis by Athanasios Papazikos and is intended as an academic, exploratory, and educational visualization tool.

The app combines a Leaflet-based world map, a local SQLite database, and a lightweight Python server. It is designed to make the underlying country and production-route data easier to inspect without relying on hard-coded frontend values.

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
python import_csv.py
```

or with explicit paths:

```bash
python import_csv.py --csv /path/to/output_country_specific.csv --db data/cbam.sqlite3
```

## Display Logic

For each selected `CN code + year`, the map displays every country that has available data.

Country values are selected as follows:

- If a country has an unspecified production route, that value is used.
- If a country has one production route, that route value is used.
- If a country has multiple route values and no unspecified route, the map uses their average.
- The country detail panel still lists the available production routes.

Some map territories are handled with explicit display rules so the visualization remains consistent with the intended dataset interpretation.

## Technology

- Frontend: HTML, CSS, JavaScript
- Map: Leaflet
- Backend: Python standard library HTTP server
- Database: SQLite
- Deployment: Render web service

No third-party Python packages are required.

## Local Development

Start the local app:

```bash
python server.py
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

The health endpoint performs a real SQLite check, so deployment health checks fail if the database is missing or unreadable.

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
Start command: python server.py
Health check path: /api/health
```

Because `data/cbam.sqlite3` is committed, Render does not need the original CSV file.

## Repository Notes

Files intentionally included:

- `server.py`
- `import_csv.py`
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
