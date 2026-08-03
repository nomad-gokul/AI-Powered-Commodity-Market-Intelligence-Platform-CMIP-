"""Base class for application service-layer objects.

Services own use-case orchestration: they call one or more repositories and
domain objects, and enforce transactional boundaries. They never talk to
SQLAlchemy directly and never import FastAPI types, so they stay testable
with plain mocked repositories and reusable outside the HTTP layer.
"""

from app.core.logging import get_logger


class BaseService:
    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__module__)
