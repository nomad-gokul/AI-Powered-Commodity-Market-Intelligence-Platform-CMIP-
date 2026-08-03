"""Unit tests for the extraction module's prompt registration wiring."""

from app.modules.extraction.prompts import get_extraction_prompt_registry


class TestGetExtractionPromptRegistry:
    def test_returns_the_same_cached_registry_on_repeated_calls(self) -> None:
        first = get_extraction_prompt_registry()
        second = get_extraction_prompt_registry()
        assert first is second

    def test_registers_all_four_prompts(self) -> None:
        registry = get_extraction_prompt_registry()
        for name in (
            "document_understanding",
            "layout_understanding",
            "entity_extraction",
            "table_extraction",
        ):
            package = registry.get(name)
            assert package.name == name
            assert package.system_prompt
            assert package.user_prompt_template
            assert package.expected_schema is not None
