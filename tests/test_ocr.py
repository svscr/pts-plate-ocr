from pts_plate_ocr.config import ConfidenceConfig
from pts_plate_ocr.models import ResultStatus
from pts_plate_ocr.ocr import LocalPlateOcr, Observation


def _observations() -> list[Observation]:
    return [
        Observation("35CZB379", "35CZB379", 0.99, "first", 0, 1.0),
        Observation("35CZB379", "35CZB379", 0.99, "second", 0, 1.0),
    ]


def test_configured_confidence_threshold_controls_automatic_copy() -> None:
    accepted = LocalPlateOcr._aggregate(
        _observations(),
        {},
        ConfidenceConfig(high_score=0.90, minimum_margin=0.08, minimum_agreeing_variants=2),
    )
    review = LocalPlateOcr._aggregate(
        _observations(),
        {},
        ConfidenceConfig(high_score=1.0, minimum_margin=0.08, minimum_agreeing_variants=2),
    )

    assert accepted.status == ResultStatus.HIGH_CONFIDENCE
    assert review.status == ResultStatus.REVIEW
