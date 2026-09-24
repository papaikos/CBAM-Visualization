"""Read-only SQLite access helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config
from app.errors import DatabaseUnavailable


def _resolve(db_path: Path | str | None) -> Path:
    return Path(db_path) if db_path is not None else Path(config.DB_PATH)


def database_exists(db_path: Path | str | None = None) -> bool:
    return _resolve(db_path).exists()


def fingerprint(db_path: Path | str | None = None) -> tuple[str, int, int]:
    """Identify the database file's current contents for response caching.

    The bundled database is read-only at runtime, so cached query results stay
    valid until the file is replaced (which changes its mtime or size).
    """
    path = _resolve(db_path).resolve()
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def open_readonly(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the emissions database in read-only mode.

    Raises DatabaseUnavailable when the file is missing so callers can map it
    to a consistent 503 response.
    """
    path = _resolve(db_path).resolve()
    if not path.exists():
        raise DatabaseUnavailable("The bundled SQLite database is unavailable.")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = open_readonly(db_path)
    try:
        yield conn
    finally:
        conn.close()


def ensure_emissions_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'emissions'"
    ).fetchone()
    if row is None:
        raise DatabaseUnavailable("The bundled emissions records are unavailable.")
