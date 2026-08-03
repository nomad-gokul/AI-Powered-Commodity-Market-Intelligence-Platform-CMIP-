"""Shared response envelopes used by every API endpoint.

Every route returns ApiResponse[T] (single resource/action) or
PaginatedResponse[T] (list endpoints) so frontend clients rely on one
consistent shape instead of per-endpoint ad hoc responses.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiResponse[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool = True
    data: T | None = None
    message: str | None = None


class ApiErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str
    details: dict[str, Any] = {}


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class PaginatedResponse[T](BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool = True
    data: list[T]
    meta: PageMeta


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
