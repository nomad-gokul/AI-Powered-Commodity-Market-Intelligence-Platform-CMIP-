from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding

# Generous upper bound on a PDF page's dimension in points (72pt = 1
# inch); large-format trade documents run wider than US Letter/A4 but
# nothing plausible exceeds this.
_MAX_PAGE_POINTS = 5000.0


class ImpossibleBoundingBoxRule:
    """Flags an entity whose grounded bounding_box (real PyMuPDF
    coordinates, per Phase 3.2's grounding step) is geometrically
    impossible: negative coordinates, a zero/negative-size box, or a
    coordinate far outside any plausible page size. Entities with no
    bounding_box at all (ungrounded - see extraction/domain.py's
    ground_bounding_box) are not this rule's concern; that is what
    ConfidenceAgent's geometry_score measures instead."""

    rule_id = "geometry.impossible_bounding_box"
    validation_type = ValidationCategory.GEOMETRY
    applies_to = frozenset(EntityType)

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        box = entity.bounding_box
        if box is None:
            return None

        x0, y0, x1, y1 = box["x0"], box["y0"], box["x1"], box["y1"]
        problems = []
        if x0 < 0 or y0 < 0:
            problems.append("negative coordinate")
        if x1 <= x0 or y1 <= y0:
            problems.append("zero or negative-size box")
        if x1 > _MAX_PAGE_POINTS or y1 > _MAX_PAGE_POINTS:
            problems.append("coordinate exceeds a plausible page size")

        if problems:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Bounding box {box} is impossible: {', '.join(problems)}",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message="Bounding box geometry is plausible",
        )
