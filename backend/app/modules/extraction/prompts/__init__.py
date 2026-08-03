"""Registers this module's four PromptPackages into the shared
app.ai.prompts.PromptRegistry, exactly once per process.

get_prompt_registry() returns a process-wide singleton
(app.ai.prompts.registry._default_registry) and PromptRegistry.register()
raises on a duplicate (name, version) key - both the API process
(ExtractionService needs prompt_version/prompt_hash when creating an
extraction_run row) and the worker process (the pipeline needs the actual
PromptPackage content) call get_extraction_prompt_registry(), so
registration is wrapped in lru_cache to make it idempotent per process.
"""

from functools import lru_cache

from app.ai.prompts.registry import PromptRegistry, get_prompt_registry
from app.modules.extraction.prompts import (
    document_understanding,
    entity_extraction,
    layout_understanding,
    table_extraction,
)

_MODULES = (document_understanding, layout_understanding, entity_extraction, table_extraction)


@lru_cache
def get_extraction_prompt_registry() -> PromptRegistry:
    registry = get_prompt_registry()
    for module in _MODULES:
        registry.register(module.PACKAGE)
    return registry
