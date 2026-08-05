"""Unit tests for CanonicalRegistry (alias resolution) and the real
reference-data files it loads."""

from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
    normalize_alias,
)
from app.modules.extraction.trust.normalization.loader import get_canonical_registries


class TestNormalizeAlias:
    def test_lowercases_and_collapses_whitespace(self) -> None:
        assert normalize_alias("  United   States  ") == "united states"


class TestCanonicalRegistry:
    def _registry(self) -> CanonicalRegistry:
        return CanonicalRegistry(
            [
                CanonicalEntry(
                    canonical_id="country:US",
                    canonical_name="United States",
                    aliases=("US", "USA", "United States"),
                ),
                CanonicalEntry(
                    canonical_id="country:IN", canonical_name="India", aliases=("IN", "India")
                ),
            ]
        )

    def test_resolve_exact_alias(self) -> None:
        match = self._registry().resolve("USA")
        assert match is not None
        assert match.canonical_id == "country:US"
        assert match.canonical_name == "United States"

    def test_resolve_is_case_and_whitespace_insensitive(self) -> None:
        match = self._registry().resolve("  usa  ")
        assert match is not None
        assert match.canonical_id == "country:US"

    def test_resolve_unknown_alias_returns_none(self) -> None:
        assert self._registry().resolve("Atlantis") is None

    def test_resolve_numeric_prefix_matches_chapter(self) -> None:
        registry = CanonicalRegistry(
            [CanonicalEntry(canonical_id="hs:27", canonical_name="Mineral fuels", aliases=("27",))]
        )
        match = registry.resolve_numeric_prefix("27101943", prefix_length=2)
        assert match is not None
        assert match.canonical_id == "hs:27"

    def test_resolve_numeric_prefix_too_short_returns_none(self) -> None:
        registry = CanonicalRegistry(
            [CanonicalEntry(canonical_id="hs:27", canonical_name="Mineral fuels", aliases=("27",))]
        )
        assert registry.resolve_numeric_prefix("2", prefix_length=2) is None

    def test_len_reflects_entry_count(self) -> None:
        assert len(self._registry()) == 2

    def test_iterates_over_every_entry(self) -> None:
        ids = {entry.canonical_id for entry in self._registry()}
        assert ids == {"country:US", "country:IN"}

    def test_resolve_by_id_returns_the_entry_for_a_known_canonical_id(self) -> None:
        match = self._registry().resolve_by_id("country:IN")
        assert match is not None
        assert match.canonical_name == "India"

    def test_resolve_by_id_unknown_id_returns_none(self) -> None:
        assert self._registry().resolve_by_id("country:atlantis") is None

    def test_extra_metadata_is_preserved_on_match(self) -> None:
        registry = CanonicalRegistry(
            [
                CanonicalEntry(
                    canonical_id="unit:metric_ton",
                    canonical_name="Metric Ton",
                    aliases=("MT",),
                    extra={"dimension": "mass"},
                )
            ]
        )
        match = registry.resolve("MT")
        assert match is not None
        assert match.extra == {"dimension": "mass"}


class TestRealReferenceData:
    """Smoke tests against the actual seeded JSON files, not synthetic
    entries - catches a malformed reference_data file or a broken loader
    path immediately, without needing to know every seeded alias."""

    def test_all_registries_load_and_are_non_empty(self) -> None:
        registries = get_canonical_registries()
        for registry in (
            registries.countries,
            registries.currencies,
            registries.units,
            registries.incoterms,
            registries.hs_codes,
            registries.commodities,
            registries.ports,
        ):
            assert len(registry) > 0

    def test_registries_are_cached_singletons(self) -> None:
        assert get_canonical_registries() is get_canonical_registries()

    def test_usd_resolves_to_currency_usd(self) -> None:
        match = get_canonical_registries().currencies.resolve("USD")
        assert match is not None
        assert match.canonical_id == "currency:USD"

    def test_known_incoterm_resolves(self) -> None:
        match = get_canonical_registries().incoterms.resolve("FOB")
        assert match is not None
        assert match.canonical_id == "incoterm:FOB"

    def test_metric_tons_alias_resolves_to_metric_ton_unit(self) -> None:
        match = get_canonical_registries().units.resolve("Metric Tons")
        assert match is not None
        assert match.canonical_id == "unit:metric_ton"

    def test_country_alias_variants_resolve_to_same_canonical_id(self) -> None:
        registry = get_canonical_registries().countries
        us_match = registry.resolve("US")
        usa_match = registry.resolve("USA")
        united_states_match = registry.resolve("United States")
        assert us_match is not None and usa_match is not None and united_states_match is not None
        assert us_match.canonical_id == usa_match.canonical_id == united_states_match.canonical_id
