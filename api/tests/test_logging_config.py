import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.logging_config import configure_logging


@contextmanager
def bare_root_logger() -> Iterator[logging.Logger]:
    """Root logger with no handlers. Used inside the test body: pytest's log capture adds its own
    root handlers after fixtures run, so a fixture could not clear them."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_adds_a_handler_when_none_exists() -> None:
    with bare_root_logger() as root:
        configure_logging()
        assert len(root.handlers) == 1
        assert root.level == logging.INFO


def test_leaves_existing_handlers_alone() -> None:
    with bare_root_logger() as root:
        existing = logging.NullHandler()
        root.addHandler(existing)
        configure_logging()
        assert root.handlers == [existing]
