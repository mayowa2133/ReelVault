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


def test_extracts_plural_share_reels_url():
    reels = InstagramService.extract_reel_urls("https://www.instagram.com/share/reels/PLURAL123xyz/?utm_source=ig")

    assert len(reels) == 1
    assert reels[0].url == "https://www.instagram.com/share/reel/PLURAL123xyz/"
    assert reels[0].shortcode == "PLURAL123xyz"
    assert reels[0].is_share_url is True


def test_extracts_instagram_reels_posts_and_tv_urls():
    references = InstagramService.extract_reel_urls(
        """
        https://www.instagram.com/reels/REELS123/?igsh=abc
        https://www.instagram.com/creator/reel/USERREEL123/?utm_source=ig_web_copy_link
        https://www.instagram.com/p/POST456/?utm_source=ig_web_copy_link
        https://www.instagram.com/p/EMBEDPOST/embed/
        https://www.instagram.com/tv/TV789/
        https://www.instagram.com/share/p/SHAREPOST/
        """
    )

    assert [(reference.url, reference.shortcode, reference.is_share_url) for reference in references] == [
        ("https://www.instagram.com/reel/REELS123/", "REELS123", False),
        ("https://www.instagram.com/reel/USERREEL123/", "USERREEL123", False),
        ("https://www.instagram.com/p/POST456/", "POST456", False),
        ("https://www.instagram.com/p/EMBEDPOST/", "EMBEDPOST", False),
        ("https://www.instagram.com/tv/TV789/", "TV789", False),
        ("https://www.instagram.com/share/p/SHAREPOST/", "SHAREPOST", True),
    ]


def test_extracts_instagram_story_item_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        story https://www.instagram.com/stories/creator/3570766765028588805/?igsh=abc
        highlight https://www.instagram.com/stories/highlights/18090946048123978/
        """
    )

    assert [(reference.url, reference.shortcode, reference.provider) for reference in references] == [
        ("https://www.instagram.com/stories/creator/3570766765028588805/", "3570766765028588805", "instagram"),
        ("https://www.instagram.com/stories/highlights/18090946048123978/", "18090946048123978", "instagram"),
    ]


def test_extracts_instagram_media_deep_links():
    references = SocialVideoService.extract_supported_urls(
        "Open instagram://media?id=482584233761418119_2815873 from a shared app link."
    )

    assert [(reference.url, reference.shortcode, reference.provider) for reference in references] == [
        ("https://www.instagram.com/tv/aye83DjauH/", "aye83DjauH", "instagram"),
    ]


def test_normalizes_instagram_media_deep_link():
    reference = SocialVideoService.normalize_url("instagram://media?id=482584233761418119")

    assert reference is not None
    assert reference.provider == "instagram"
    assert reference.shortcode == "aye83DjauH"
    assert reference.url == "https://www.instagram.com/tv/aye83DjauH/"


def test_unwraps_supported_social_redirect_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        youtube https://www.youtube.com/redirect?event=video_description&q=https%3A%2F%2Fyoutu.be%2FREDIR123%3Fsi%3Dabc
        instagram https://l.instagram.com/?u=https%3A%2F%2Fwww.instagram.com%2Freel%2FIGLINK123%2F&e=abc
        tiktok https://www.tiktok.com/link/v2?target=https%3A%2F%2Fwww.tiktok.com%2F%40creator%2Fvideo%2F7253412088251534598
        """
    )

    assert [(reference.provider, reference.shortcode, reference.url) for reference in references] == [
        ("youtube", "REDIR123", "https://youtu.be/REDIR123"),
        ("instagram", "IGLINK123", "https://www.instagram.com/reel/IGLINK123/"),
        ("tiktok", "7253412088251534598", "https://www.tiktok.com/@creator/video/7253412088251534598"),
    ]


def test_unwraps_youtube_url_query_redirect_targets():
    references = SocialVideoService.extract_supported_urls(
        """
        redirect https://www.youtube.com/redirect?url=https%3A%2F%2Fwww.youtube.com%2Fshorts%2FURLREDIR1234
        attribution https://www.youtube.com/attribution_link?url=%2Fwatch%3Fv%3DURLATTR1234
        """
    )

    assert [(reference.shortcode, reference.url) for reference in references] == [
        ("URLREDIR1234", "https://www.youtube.com/shorts/URLREDIR1234"),
        ("URLATTR1234", "https://www.youtube.com/watch?v=URLATTR1234"),
    ]


def test_extracts_youtube_fragment_video_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        hashbang https://www.youtube.com/watch#!v=HASHBANG123
        redirect-fragment https://www.youtube.com/#/watch?v=FRAGWATCH12
        """
    )

    assert [(reference.shortcode, reference.url) for reference in references] == [
        ("HASHBANG123", "https://www.youtube.com/watch?v=HASHBANG123"),
        ("FRAGWATCH12", "https://www.youtube.com/watch?v=FRAGWATCH12"),
    ]


def test_extracts_protocol_relative_social_video_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        youtube //www.youtube.com/embed/PROTOYT1234A?rel=0
        tiktok //www.tiktok.com/@creator/video/7253412088251534599
        instagram //www.instagram.com/reel/PROTOIG123/
        x //twitter.com/example/status/1790637656616943992
        """
    )

    assert [(reference.provider, reference.shortcode, reference.url) for reference in references] == [
        ("youtube", "PROTOYT1234A", "https://www.youtube.com/embed/PROTOYT1234A"),
        ("tiktok", "7253412088251534599", "https://www.tiktok.com/@creator/video/7253412088251534599"),
        ("instagram", "PROTOIG123", "https://www.instagram.com/reel/PROTOIG123/"),
        ("x", "1790637656616943992", "https://x.com/example/status/1790637656616943992"),
    ]


def test_normalizes_protocol_relative_social_video_url():
    reference = SocialVideoService.normalize_url("//www.youtube.com/embed/PROTOYT1234A?rel=0")

    assert reference is not None
    assert reference.provider == "youtube"
    assert reference.shortcode == "PROTOYT1234A"
    assert reference.url == "https://www.youtube.com/embed/PROTOYT1234A"


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


def test_ignores_instagram_reels_audio_pages():
    references = SocialVideoService.extract_supported_urls(
        "Audio page https://www.instagram.com/reels/audio/1234567890/?igsh=abc is not a video."
    )

    assert references == []


def test_ignores_youtube_non_video_embed_urls():
    references = SocialVideoService.extract_supported_urls(
        """
        playlist https://www.youtube.com/embed/videoseries?list=PL123
        livestream https://www.youtube.com/embed/live_stream?channel=UC123
        """
    )

    assert references == []


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
        nocookie https://www.youtube-nocookie.com/embed/NOCOOKIE123?rel=0
        root-query https://www.youtube.com/?v=ROOTQUERY1
        popup https://www.youtube.com/watch_popup?v=POPUP12345A
        movie https://www.youtube.com/movie_popup?v=MOVIE12345B
        kids https://www.youtubekids.com/watch?v=KIDS123456C
        attribution https://www.youtube.com/attribution_link?u=%2Fwatch%3Fv%3DATTR123%26feature%3Dshare
        source-shorts https://www.youtube.com/source/SRC12345678/shorts?feature=share
        tiktok-share https://www.tiktok.com/share/video/7253412088251534594/?region=US
        tiktok-mobile https://m.tiktok.com/v/7253412088251534595.html
        tiktok-embed https://www.tiktok.com/embed/7253412088251534596
        tiktok-embed-v2 https://www.tiktok.com/embed/v2/7253412088251534597?lang=en
        instagram-share https://www.instagram.com/share/BA123xyz/?utm_source=ig
        instagram-user https://www.instagram.com/creator/reel/USERREEL123/
        twitter-legacy https://twitter.com/statuses/1790637656616943991
        """
    )

    assert [(reference.provider, reference.shortcode, reference.is_share_url) for reference in references] == [
        ("youtube", "UgkxClip123", False),
        ("youtube", "BaW_jenozKc", False),
        ("youtube", "NOCOOKIE123", False),
        ("youtube", "ROOTQUERY1", False),
        ("youtube", "POPUP12345A", False),
        ("youtube", "MOVIE12345B", False),
        ("youtube", "KIDS123456C", False),
        ("youtube", "ATTR123", False),
        ("youtube", "SRC12345678", False),
        ("tiktok", "7253412088251534594", False),
        ("tiktok", "7253412088251534595", False),
        ("tiktok", "7253412088251534596", False),
        ("tiktok", "7253412088251534597", False),
        ("instagram", "BA123xyz", True),
        ("instagram", "USERREEL123", False),
        ("x", "1790637656616943991", False),
    ]
    assert references[0].url == "https://www.youtube.com/clip/UgkxClip123"
    assert references[1].url == "https://www.youtube.com/embed/BaW_jenozKc"
    assert references[2].url == "https://www.youtube.com/embed/NOCOOKIE123"
    assert references[3].url == "https://www.youtube.com/watch?v=ROOTQUERY1"
    assert references[4].url == "https://www.youtube.com/watch?v=POPUP12345A"
    assert references[5].url == "https://www.youtube.com/watch?v=MOVIE12345B"
    assert references[6].url == "https://www.youtube.com/watch?v=KIDS123456C"
    assert references[7].url == "https://www.youtube.com/watch?v=ATTR123"
    assert references[8].url == "https://www.youtube.com/shorts/SRC12345678"
    assert references[9].url == "https://www.tiktok.com/@_/video/7253412088251534594"
    assert references[10].url == "https://m.tiktok.com/v/7253412088251534595"
    assert references[11].url == "https://www.tiktok.com/embed/7253412088251534596"
    assert references[12].url == "https://www.tiktok.com/embed/7253412088251534597"
    assert references[13].url == "https://www.instagram.com/share/BA123xyz/"
    assert references[14].url == "https://www.instagram.com/reel/USERREEL123/"
    assert references[15].url == "https://x.com/i/status/1790637656616943991"
