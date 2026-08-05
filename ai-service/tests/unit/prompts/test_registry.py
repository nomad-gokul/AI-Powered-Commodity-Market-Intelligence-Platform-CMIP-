"""Unit tests for PromptRegistry: registration, immutability, version
resolution, search, and content hashing."""

import pytest
from shared.ai_exceptions import PromptAlreadyRegisteredError, PromptNotFoundError
from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from ai_service.prompts.registry import PromptRegistry


def _package(
    name: str = "test_prompt", major: int = 1, minor: int = 0, **metadata_kwargs: object
) -> PromptPackage:
    return PromptPackage(
        name=name,
        version=PromptVersion(major=major, minor=minor),
        system_prompt="system",
        user_prompt_template="template {x}",
        metadata=PromptMetadata(**metadata_kwargs),  # type: ignore[arg-type]
    )


class TestRegisterAndGet:
    def test_register_then_get_returns_the_same_package(self) -> None:
        registry = PromptRegistry()
        package = _package()
        registry.register(package)
        assert registry.get("test_prompt") is package

    def test_get_unknown_name_raises(self) -> None:
        registry = PromptRegistry()
        with pytest.raises(PromptNotFoundError):
            registry.get("does-not-exist")

    def test_get_specific_version(self) -> None:
        registry = PromptRegistry()
        v1 = _package(major=1)
        v2 = _package(major=2)
        registry.register(v1)
        registry.register(v2)
        assert registry.get("test_prompt", version="1.0") is v1
        assert registry.get("test_prompt", version="2.0") is v2

    def test_get_unknown_version_raises(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(major=1))
        with pytest.raises(PromptNotFoundError):
            registry.get("test_prompt", version="99.0")

    def test_get_without_version_returns_latest(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(major=1, minor=0))
        registry.register(_package(major=1, minor=5))
        registry.register(_package(major=1, minor=2))
        assert str(registry.get("test_prompt").version) == "1.5"

    def test_registering_the_same_version_twice_raises(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(major=1))
        with pytest.raises(PromptAlreadyRegisteredError):
            registry.register(_package(major=1))

    def test_major_version_takes_priority_over_minor(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(major=1, minor=9))
        registry.register(_package(major=2, minor=0))
        assert str(registry.get("test_prompt").version) == "2.0"


class TestListVersions:
    def test_lists_all_versions_sorted(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(major=2, minor=0))
        registry.register(_package(major=1, minor=0))
        registry.register(_package(major=1, minor=5))
        assert registry.list_versions("test_prompt") == ["1.0", "1.5", "2.0"]

    def test_unknown_name_returns_empty_list(self) -> None:
        assert PromptRegistry().list_versions("nope") == []


class TestSearch:
    def test_search_by_tag(self) -> None:
        registry = PromptRegistry()
        matching = _package(name="a", tags=["extraction"])
        other = _package(name="b", tags=["layout"])
        registry.register(matching)
        registry.register(other)
        assert registry.search(tag="extraction") == [matching]

    def test_search_by_author(self) -> None:
        registry = PromptRegistry()
        matching = _package(name="a", author="alice")
        other = _package(name="b", author="bob")
        registry.register(matching)
        registry.register(other)
        assert registry.search(author="alice") == [matching]

    def test_search_with_no_filters_returns_everything(self) -> None:
        registry = PromptRegistry()
        registry.register(_package(name="a"))
        registry.register(_package(name="b"))
        assert len(registry.search()) == 2


class TestComputeHash:
    def test_same_content_hashes_identically(self) -> None:
        a = _package(name="a")
        b = _package(name="b")  # different name, same system/user prompt content
        assert PromptRegistry.compute_hash(a) == PromptRegistry.compute_hash(b)

    def test_different_content_hashes_differently(self) -> None:
        a = _package(name="a")
        b = PromptPackage(
            name="a",
            version=PromptVersion(major=1),
            system_prompt="a completely different system prompt",
            user_prompt_template="template {x}",
        )
        assert PromptRegistry.compute_hash(a) != PromptRegistry.compute_hash(b)

    def test_hash_is_a_hex_sha256_digest(self) -> None:
        digest = PromptRegistry.compute_hash(_package())
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not valid hex
