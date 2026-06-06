from app.config import Settings
from app.services.youtube_mirror_service import (
    YoutubeMirrorService,
    invidious_video_url,
    parse_base_urls,
    piped_streams_url,
    safe_youtube_mirror_filename,
    select_invidious_stream,
    select_piped_stream,
    youtube_video_id,
)


def test_parse_base_urls_splits_commas_newlines_and_dedupes():
    assert parse_base_urls(" https://a.example/,\nhttps://b.example,https://a.example ") == [
        "https://a.example",
        "https://b.example",
    ]


def test_youtube_video_id_handles_common_url_shapes():
    assert youtube_video_id("https://www.youtube.com/watch?v=jNQXAC9IVRw") == "jNQXAC9IVRw"
    assert youtube_video_id("https://youtu.be/jNQXAC9IVRw") == "jNQXAC9IVRw"
    assert youtube_video_id("https://www.youtube.com/shorts/XnjiprcNurg") == "XnjiprcNurg"
    assert youtube_video_id("https://example.com/watch?v=jNQXAC9IVRw") is None


def test_youtube_mirror_urls_are_normalized():
    assert piped_streams_url("https://piped.example/", "abc123") == "https://piped.example/streams/abc123"
    assert (
        invidious_video_url("https://invidious.example/", "abc123", "CA")
        == "https://invidious.example/api/v1/videos/abc123?local=true&region=CA"
    )


def test_select_piped_stream_prefers_best_progressive_mp4():
    stream = select_piped_stream(
        {
            "title": "Me at the zoo",
            "uploader": "jawed",
            "videoStreams": [
                {"url": "https://piped.example/240.mp4", "quality": "240p", "format": "MPEG_4", "videoOnly": False},
                {"url": "https://piped.example/720.mp4", "quality": "720p", "format": "MPEG_4", "videoOnly": False},
                {"url": "https://piped.example/video-only.mp4", "quality": "1080p", "format": "MPEG_4", "videoOnly": True},
            ],
        }
    )

    assert stream
    assert stream.service == "piped"
    assert stream.url == "https://piped.example/720.mp4"
    assert stream.title == "Me at the zoo"
    assert stream.author == "jawed"


def test_select_invidious_stream_prefers_best_mp4_format_stream():
    stream = select_invidious_stream(
        {
            "title": "Me at the zoo",
            "author": "jawed",
            "formatStreams": [
                {"url": "https://invidious.example/360.mp4", "qualityLabel": "360p", "container": "mp4"},
                {"url": "https://invidious.example/720.mp4", "qualityLabel": "720p", "container": "mp4"},
            ],
        }
    )

    assert stream
    assert stream.service == "invidious"
    assert stream.url == "https://invidious.example/720.mp4"
    assert stream.quality == "720p"


def test_safe_youtube_mirror_filename_sanitizes_title():
    assert safe_youtube_mirror_filename("abc123", "bad/name?", "mp4") == "bad_name.mp4"
    assert safe_youtube_mirror_filename("abc123", "", "mp4") == "abc123.mp4"


def test_youtube_mirror_service_downloads_piped_stream(tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self, data=None, chunks=None):
            self._data = data or {}
            self._chunks = chunks or []

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def iter_bytes(self):
            return iter(self._chunks)

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url, headers):
            assert url == "https://piped.example/streams/jNQXAC9IVRw"
            return FakeResponse(
                {
                    "title": "Me at the zoo",
                    "uploader": "jawed",
                    "videoStreams": [
                        {
                            "url": "https://media.example/video.mp4",
                            "quality": "240p",
                            "format": "MPEG_4",
                            "videoOnly": False,
                        }
                    ],
                }
            )

        def stream(self, method, url, headers):
            assert method == "GET"
            assert url == "https://media.example/video.mp4"
            return FakeResponse(chunks=[b"video"])

    monkeypatch.setattr("app.services.youtube_mirror_service.httpx.Client", FakeClient)
    service = YoutubeMirrorService(Settings(youtube_piped_api_base_urls="https://piped.example"))

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.file_path.read_bytes() == b"video"
    assert result.info["id"] == "jNQXAC9IVRw"
    assert result.info["extractor"] == "youtube_mirror"
    assert result.info["youtube_mirror_service"] == "piped"
