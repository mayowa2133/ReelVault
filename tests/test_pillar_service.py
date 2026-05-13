from app.models.schemas import ContentPillar
from app.services.pillar_service import PillarParseKind, PillarService


def test_exact_pillar_parse():
    result = PillarService.parse_message("motivation https://www.instagram.com/reel/ABC123/")

    assert result.kind == PillarParseKind.EXACT
    assert result.pillar == ContentPillar.MOTIVATION
    assert result.source == "telegram_exact"


def test_alias_pillar_parse():
    result = PillarService.parse_message("fitness reel https://www.instagram.com/reel/ABC123/")

    assert result.kind == PillarParseKind.ALIAS
    assert result.pillar == ContentPillar.GYM
    assert result.source == "telegram_alias"


def test_fuzzy_pillar_parse_requires_confirmation():
    result = PillarService.parse_message("motivaton https://www.instagram.com/reel/ABC123/")

    assert result.kind == PillarParseKind.FUZZY
    assert result.should_confirm
    assert result.pillar == ContentPillar.MOTIVATION


def test_ambiguous_pillar_parse():
    result = PillarService.parse_message("gym motivation https://www.instagram.com/reel/ABC123/")

    assert result.kind == PillarParseKind.AMBIGUOUS
    assert set(result.candidates) == {ContentPillar.GYM, ContentPillar.MOTIVATION}


def test_no_pillar_parse_for_generic_message():
    result = PillarService.parse_message("please save this https://www.instagram.com/reel/ABC123/")

    assert result.kind == PillarParseKind.NONE


def test_pillar_callback_data_round_trip():
    data = PillarService.build_callback_data("confirm", 42, ContentPillar.JOB_SEARCH)
    action = PillarService.parse_callback_data(data)

    assert action is not None
    assert action.action == "confirm"
    assert action.row_index == 42
    assert action.pillar == ContentPillar.JOB_SEARCH


def test_ai_callback_data_round_trip():
    data = PillarService.build_callback_data("ai", 42)
    action = PillarService.parse_callback_data(data)

    assert action is not None
    assert action.action == "ai"
    assert action.row_index == 42
    assert action.pillar is None
