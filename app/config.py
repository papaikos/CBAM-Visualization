"""Application-wide configuration and domain constants."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
DB_PATH = Path(os.environ.get("CBAM_DB_PATH", ROOT / "data" / "cbam.sqlite3"))

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

SUPPORTED_YEARS: tuple[int, ...] = (2026, 2027)
DEFAULT_CN_CODE = "76011010"

# Micro-states rendered as zero-emission on the map.
ZERO_EMISSION_COUNTRIES = frozenset({"Andorra", "San Marino", "Vatican"})

# Territories that display the values of another country.
MIRRORED_COUNTRIES: dict[str, str] = {
    "Kosovo": "Serbia",
    "Northern Cyprus": "Turkey",
    "Somaliland": "Somalia",
}

# Mirrored territories that must not disclose their source country.
SILENT_MIRRORED_COUNTRIES = frozenset({"Northern Cyprus"})

MAX_JSON_BYTES = 10 * 1024 * 1024
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
