"""Loads app/modules/extraction/trust/reference_data/*.json into cached
CanonicalRegistry instances, and bundles them into one CanonicalRegistries
object NormalizationAgent depends on. Loaded once per process via
lru_cache - both the API process and the worker process call
get_canonical_registries() independently, each populating its own copy.
"""

import json
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
)

_REFERENCE_DATA_DIR = Path(__file__).resolve().parent.parent / "reference_data"
_RESERVED_KEYS = frozenset({"canonical_id", "canonical_name", "aliases"})


def _load_entries(filename: str) -> list[CanonicalEntry]:
    path = _REFERENCE_DATA_DIR / filename
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [
        CanonicalEntry(
            canonical_id=item["canonical_id"],
            canonical_name=item["canonical_name"],
            aliases=tuple(item["aliases"]),
            extra={k: v for k, v in item.items() if k not in _RESERVED_KEYS},
        )
        for item in raw
    ]


@cache
def _load_registry(filename: str) -> CanonicalRegistry:
    return CanonicalRegistry(_load_entries(filename))


@dataclass(frozen=True, slots=True)
class CanonicalRegistries:
    countries: CanonicalRegistry
    currencies: CanonicalRegistry
    units: CanonicalRegistry
    incoterms: CanonicalRegistry
    hs_codes: CanonicalRegistry
    commodities: CanonicalRegistry
    ports: CanonicalRegistry


@lru_cache(maxsize=1)
def get_canonical_registries() -> CanonicalRegistries:
    return CanonicalRegistries(
        countries=_load_registry("countries.json"),
        currencies=_load_registry("currencies.json"),
        units=_load_registry("units.json"),
        incoterms=_load_registry("incoterms.json"),
        hs_codes=_load_registry("hs_code_prefixes.json"),
        commodities=_load_registry("commodities.json"),
        ports=_load_registry("ports.json"),
    )
