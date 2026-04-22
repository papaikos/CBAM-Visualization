# CBAM Visualization

This repository packages a local CBAM map app backed by SQLite instead of hard-coded country data. The repo already includes `data/cbam.sqlite3`, so the app runs immediately after cloning. The source CSV file `output_country_specific.csv` is intentionally excluded from git.

## What It Does

- Serves CBAM country data from `data/cbam.sqlite3`
- Keeps only `2026` and `2027`
- Exposes all available CN codes
- Colors the map for every country that has data for the selected `CN code + year`
- Uses each country's own displayed value instead of filtering the map by a majority production route
- Shows all available production routes in the country detail panel
- Uses the unspecified route when present; otherwise averages the available route values for the country

## Run It

1. Start the local app:

```bash
python server.py
```

2. Open:

```text
http://127.0.0.1:8000
```

## Deployment Notes

- `requirements.txt` is intentionally minimal because the app uses only the Python standard library.
- The server reads `HOST` and `PORT` from environment variables.
- By default it binds to `0.0.0.0:8000`, which is suitable for most hosting platforms.

Example:

```bash
HOST=0.0.0.0 PORT=8000 python server.py
```

## Rebuild The Database From A Local CSV

If you have your own local copy of `output_country_specific.csv`, you can regenerate the SQLite database:

```bash
python import_csv.py
```

Or point the importer at a different CSV path:

```bash
python import_csv.py --csv /path/to/output_country_specific.csv --db data/cbam.sqlite3
```

## API Endpoints

- `/api/meta`
- `/api/map-data?cn_code=76011000&year=2026`
- `/api/country?cn_code=76011000&year=2026&country=Greece`
- `/api/health`
