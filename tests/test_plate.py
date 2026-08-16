from pts_plate_ocr.plate import clean_ocr_text, is_date_like_plate, parse_best, parse_candidates


def test_standard_plate_is_formatted() -> None:
    parsed = parse_best("35czb379")
    assert parsed is not None
    assert parsed.canonical == "35CZB379"
    assert parsed.correction_count == 0


def test_contextual_ocr_substitution_is_allowed() -> None:
    parsed = parse_best("35C2B379")
    assert parsed is not None
    assert parsed.canonical == "35CZB379"
    assert parsed.correction_count == 1


def test_invalid_province_is_rejected() -> None:
    assert parse_candidates("99ABC123") == []


def test_special_format_is_not_accepted() -> None:
    assert parse_candidates("CD1234") == []


def test_text_cleaning() -> None:
    assert clean_ocr_text("35-CZB 379\n") == "35CZB379"


def test_one_letter_plate_is_compact() -> None:
    parsed = parse_best("20 F 8849")
    assert parsed is not None
    assert parsed.canonical == "20F8849"


def test_date_misread_as_plate_is_rejected() -> None:
    assert is_date_like_plate("15O82026")
    assert parse_candidates("15O82026") == []


def test_normal_plates_are_not_treated_as_dates() -> None:
    assert not is_date_like_plate("35CZB379")
    assert not is_date_like_plate("20F8849")
    assert not is_date_like_plate("34A12345")
