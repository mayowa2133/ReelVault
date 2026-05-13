from app.services.instagram_service import InstagramService


def test_extracts_and_normalizes_standard_reel_url():
    reels = InstagramService.extract_reel_urls(
        "Save this https://www.instagram.com/reel/C7abcDEF123/?igsh=abc for later"
    )

    assert len(reels) == 1
    assert reels[0].url == "https://www.instagram.com/reel/C7abcDEF123/"
    assert reels[0].shortcode == "C7abcDEF123"


def test_extracts_share_reel_url():
    reels = InstagramService.extract_reel_urls("https://www.instagram.com/share/reel/BA123xyz/?utm_source=ig")

    assert len(reels) == 1
    assert reels[0].url == "https://www.instagram.com/share/reel/BA123xyz/"
    assert reels[0].shortcode == "BA123xyz"
    assert reels[0].is_share_url is True


def test_extracts_multiple_unique_reel_urls():
    text = """
    First: https://instagram.com/reel/ONE123/
    Duplicate: https://www.instagram.com/reel/ONE123/?x=y
    Second: https://www.instagram.com/reel/TWO456/.
    """

    reels = InstagramService.extract_reel_urls(text)

    assert [reel.shortcode for reel in reels] == ["ONE123", "TWO456"]


def test_ignores_non_reel_urls():
    reels = InstagramService.extract_reel_urls("Read https://example.com and https://www.instagram.com/p/ABC/")

    assert reels == []

