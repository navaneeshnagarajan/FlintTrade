"""Shim for utils.logging — redirect OpenAlgo logging to Python stdlib."""
from __future__ import annotations

import logging


def setup_logger(name: str = "openalgo") -> logging.Logger:
    """Return a stdlib logger namespaced under flinttrade.gateway.

    Args:
        name: Logger sub-name appended to the ``flinttrade.gateway.`` prefix.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    return logging.getLogger(f"flinttrade.gateway.{name}")


# Alias that some broker modules use
get_logger = setup_logger
