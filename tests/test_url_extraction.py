from app.services.instagram_service import InstagramService
from app.services.social_video_service import SocialVideoService


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


def test_extracts_instagram_reels_posts_and_tv_urls():
    references = InstagramService.extract_reel_urls(
        """
        https://www.instagram.com/reels/REELS123/?igsh=abc
        https://www.instagram.com/p/POST456/?utm_source=ig_web_copy_link
        https://www.instagram.com/tv/TV789/
        https://www.instagram.com/share/p/SHAREPOST/
        """
    )

    assert [(reference.url, reference.shortcode, reference.is_share_url) for reference in references] == [
        ("https://www.instagram.com/reel/REELS123/", "REELS123", False),
        ("https://www.instagram.com/p/POST456/", "POST456", False),
        ("https://www.instagram.com/tv/TV789/", "TV789", False),
        ("https://www.instagram.com/share/p/SHAREPOST/", "SHAREPOST", True),
    ]


def test_extracts_multiple_unique_reel_urls():
    text = """
    First: https://instagram.com/reel/ONE123/
    Duplicate: https://www.instagram.com/reel/ONE123/?x=y
    Second: https://www.instagram.com/reel/TWO456/.
    """

    reels = InstagramService.extract_reel_urls(text)

    assert [reel.shortcode for reel in reels] == ["ONE123", "TWO456"]


def test_ignores_non_reel_urls():
    reels = InstagramService.extract_reel_urls("Read https://example.com and https://www.instagram.com/explore/")

    assert reels == []


def test_extracts_supported_social_video_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        youtube https://www.youtube.com/watch?v=BaW_jenozKc&utm_source=x
        short https://youtu.be/BaW_jenozKc?si=tracking
        tiktok https://www.tiktok.com/@creator/video/7234567890123456789?lang=en
        x https://twitter.com/example/status/1790637656616943991?s=20
        instagram https://www.instagram.com/reel/C7abcDEF123/?igsh=abc
        """
    )

    assert [(reference.provider, reference.shortcode) for reference in references] == [
        ("youtube", "BaW_jenozKc"),
        ("tiktok", "7234567890123456789"),
        ("x", "1790637656616943991"),
        ("instagram", "C7abcDEF123"),
    ]
    assert references[0].url == "https://www.youtube.com/watch?v=BaW_jenozKc"
    assert references[1].url == "https://www.tiktok.com/@creator/video/7234567890123456789"
    assert references[2].url == "https://x.com/example/status/1790637656616943991"


def test_extracts_additional_supported_social_video_url_shapes():
    references = SocialVideoService.extract_supported_urls(
        """
        clip https://www.youtube.com/clip/UgkxClip123?si=tracking
        old-embed https://www.youtube.com/v/BaW_jenozKc?version=3
        attribution https://www.youtube.com/attribution_link?u=%2Fwatch%3Fv%3DATTR123%26feature%3Dshare
        tiktok-share https://www.tiktok.com/share/video/7253412088251534594/?region=US
        tiktok-mobile https://m.tiktok.com/v/7253412088251534595.html
        tiktok-embed https://www.tiktok.com/embed/7253412088251534596
        tiktok-embed-v2 https://www.tiktok.com/embed/v2/7253412088251534597?lang=en
        instagram-share https://www.instagram.com/share/BA123xyz/?utm_source=ig
        twitter-legacy https://twitter.com/statuses/1790637656616943991
        """
    )

    assert [(reference.provider, reference.shortcode, reference.is_share_url) for reference in references] == [
        ("youtube", "UgkxClip123", False),
        ("youtube", "BaW_jenozKc", False),
        ("youtube", "ATTR123", False),
        ("tiktok", "7253412088251534594", False),
        ("tiktok", "7253412088251534595", False),
        ("tiktok", "7253412088251534596", False),
        ("tiktok", "7253412088251534597", False),
        ("instagram", "BA123xyz", True),
        ("x", "1790637656616943991", False),
    ]
    assert references[0].url == "https://www.youtube.com/clip/UgkxClip123"
    assert references[1].url == "https://www.youtube.com/embed/BaW_jenozKc"
    assert references[2].url == "https://www.youtube.com/watch?v=ATTR123"
    assert references[3].url == "https://www.tiktok.com/@_/video/7253412088251534594"
    assert references[4].url == "https://m.tiktok.com/v/7253412088251534595"
    assert references[5].url == "https://www.tiktok.com/embed/7253412088251534596"
    assert references[6].url == "https://www.tiktok.com/embed/v2/7253412088251534597"
    assert references[7].url == "https://www.instagram.com/share/BA123xyz/"
    assert references[8].url == "https://x.com/i/status/1790637656616943991"
