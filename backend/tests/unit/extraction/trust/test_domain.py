"""Unit tests for trust/domain.py's pure logic: date/numeric parsing,
slug/canonical-id derivation, tolerance comparison, and score math."""

from datetime import date

from app.modules.extraction.domain import compute_extraction_fingerprint
from app.modules.extraction.trust.domain import (
    SEVERITY_WEIGHTS,
    clamp,
    derive_canonical_id,
    parse_flexible_date,
    parse_numeric,
    slugify,
    values_equal_within_tolerance,
    weighted_average,
)


class TestParseFlexibleDate:
    def test_iso_format(self) -> None:
        assert parse_flexible_date("2026-01-12") == date(2026, 1, 12)

    def test_slash_format_is_day_month_year(self) -> None:
        assert parse_flexible_date("12/01/2026") == date(2026, 1, 12)

    def test_day_month_name_year(self) -> None:
        assert parse_flexible_date("12 January 2026") == date(2026, 1, 12)

    def test_month_name_day_year(self) -> None:
        assert parse_flexible_date("January 12, 2026") == date(2026, 1, 12)

    def test_abbreviated_month_name(self) -> None:
        assert parse_flexible_date("12 Jan 2026") == date(2026, 1, 12)

    def test_unparseable_text_returns_none(self) -> None:
        assert parse_flexible_date("not a date") is None

    def test_impossible_calendar_date_returns_none(self) -> None:
        assert parse_flexible_date("2026-02-30") is None

    def test_unknown_month_name_returns_none(self) -> None:
        assert parse_flexible_date("12 Blorpuary 2026") is None

    def test_whitespace_is_stripped(self) -> None:
        assert parse_flexible_date("  2026-01-12  ") == date(2026, 1, 12)


class TestParseNumeric:
    def test_plain_integer(self) -> None:
        assert parse_numeric("500") == 500.0

    def test_decimal_with_currency_symbol(self) -> None:
        assert parse_numeric("$82.14 per barrel") == 82.14

    def test_thousands_separator_is_stripped(self) -> None:
        assert parse_numeric("1,250 MT") == 1250.0

    def test_negative_number(self) -> None:
        assert parse_numeric("-5.5") == -5.5

    def test_no_numeric_token_returns_none(self) -> None:
        assert parse_numeric("no numbers here") is None


class TestSlugifyAndCanonicalId:
    def test_lowercases_and_joins_with_underscore(self) -> None:
        assert slugify("Adani Ports") == "adani_ports"

    def test_strips_trailing_legal_suffix(self) -> None:
        assert slugify("Adani Ports & SEZ Ltd") == "adani_ports_sez"

    def test_strips_pvt_ltd(self) -> None:
        assert slugify("Reliance Industries Pvt Ltd") == "reliance_industries"

    def test_empty_input_falls_back_to_unknown(self) -> None:
        assert slugify("&&&") == "unknown"

    def test_derive_canonical_id_prefixes_the_slug(self) -> None:
        assert derive_canonical_id("company", "Adani Ports Ltd") == "company:adani_ports"


class TestValuesEqualWithinTolerance:
    def test_identical_values(self) -> None:
        assert values_equal_within_tolerance(100.0, 100.0)

    def test_within_default_tolerance(self) -> None:
        assert values_equal_within_tolerance(100.0, 104.0)

    def test_outside_default_tolerance(self) -> None:
        assert not values_equal_within_tolerance(100.0, 120.0)

    def test_both_zero_is_equal(self) -> None:
        assert values_equal_within_tolerance(0.0, 0.0)

    def test_custom_tolerance(self) -> None:
        assert values_equal_within_tolerance(100.0, 101.0, relative_tolerance=0.02)
        assert not values_equal_within_tolerance(100.0, 103.0, relative_tolerance=0.02)


class TestScoreMath:
    def test_clamp_within_range(self) -> None:
        assert clamp(0.5) == 0.5

    def test_clamp_above_high(self) -> None:
        assert clamp(1.5) == 1.0

    def test_clamp_below_low(self) -> None:
        assert clamp(-0.5) == 0.0

    def test_weighted_average_basic(self) -> None:
        scores = {"a": 1.0, "b": 0.0}
        weights = {"a": 1.0, "b": 1.0}
        assert weighted_average(scores, weights) == 0.5

    def test_weighted_average_uneven_weights(self) -> None:
        scores = {"a": 1.0, "b": 0.0}
        weights = {"a": 3.0, "b": 1.0}
        assert weighted_average(scores, weights) == 0.75

    def test_weighted_average_ignores_absent_dimensions(self) -> None:
        # A dimension present in `weights` but not in `scores` should not
        # affect the normalization denominator.
        scores = {"a": 1.0}
        weights = {"a": 1.0, "b": 1.0}
        assert weighted_average(scores, weights) == 1.0

    def test_severity_weights_are_monotonically_increasing(self) -> None:
        assert (
            SEVERITY_WEIGHTS["info"]
            <= SEVERITY_WEIGHTS["warning"]
            < SEVERITY_WEIGHTS["error"]
            < SEVERITY_WEIGHTS["critical"]
        )


class TestComputeExtractionFingerprint:
    def test_deterministic_for_same_inputs(self) -> None:
        kwargs = {
            "document_hash": "a" * 64,
            "prompt_hash": "b" * 64,
            "pipeline_version": "3.2.0",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
        }
        assert compute_extraction_fingerprint(**kwargs) == compute_extraction_fingerprint(**kwargs)

    def test_differs_when_document_hash_differs(self) -> None:
        base = {
            "prompt_hash": "b" * 64,
            "pipeline_version": "3.2.0",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
        }
        fp1 = compute_extraction_fingerprint(document_hash="a" * 64, **base)
        fp2 = compute_extraction_fingerprint(document_hash="c" * 64, **base)
        assert fp1 != fp2

    def test_differs_when_model_differs(self) -> None:
        base = {
            "document_hash": "a" * 64,
            "prompt_hash": "b" * 64,
            "pipeline_version": "3.2.0",
            "provider": "groq",
        }
        fp1 = compute_extraction_fingerprint(model="model-a", **base)
        fp2 = compute_extraction_fingerprint(model="model-b", **base)
        assert fp1 != fp2

    def test_returns_a_sha256_hex_digest(self) -> None:
        fingerprint = compute_extraction_fingerprint(
            document_hash="a" * 64,
            prompt_hash="b" * 64,
            pipeline_version="3.2.0",
            provider="groq",
            model="llama",
        )
        assert len(fingerprint) == 64
        int(fingerprint, 16)  # raises ValueError if not valid hex
