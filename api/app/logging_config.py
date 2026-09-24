"""Minimal logging setup so ``app.*`` INFO lines (purge counts, deploy checks) reach Railway."""

import logging


def configure_logging() -> None:
    """Add a stderr handler at INFO if the root logger has none (idempotent)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
