"""Run the development/production server: ``python -m app``."""

from __future__ import annotations

import uvicorn

from app import config


def main() -> None:
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
