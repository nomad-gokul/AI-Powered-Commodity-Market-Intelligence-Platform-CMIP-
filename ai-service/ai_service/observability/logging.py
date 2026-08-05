"""A thin structlog accessor with zero dependency on app.core.

structlog.configure(...) is process-global state, set up once at process
startup by backend's app.core.logging.configure_logging() (called from
app.main / app.worker before any ai-service code runs, since this package
always runs in-process alongside backend - see docs/ARCHITECTURE.md's
Pre-Phase 5 section). get_logger() itself never reads Settings, so this
wrapper needs nothing from backend to pick up whatever configuration is
already active.
"""

from typing import cast

import structlog


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
