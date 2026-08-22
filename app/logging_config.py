"""Shared logging setup for both entrypoints (CLI and web server)."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    # basicConfig is a no-op if the root logger already has handlers, so it's safe to
    # call this from both app/main.py and app/server.py regardless of which runs first.
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
