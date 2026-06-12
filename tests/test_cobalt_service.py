import pytest

from app.services.cobalt_service import (
    CobaltService,
    cobalt_endpoint_url,
    cobalt_source_id,
    parse_cobalt_base_urls,
    safe_cobalt_filename,
    select_cobalt_download,
)
from app.config import Settings
from app.utils.errors import DownloadFailedError


def test_parse_cobalt_base_urls_splits_commas_newlines_and_dedupes():
    assert parse_cobalt_base_urls(" https://a.example/,\nhttps://b.example,https://a.example ") == [
        "https://a.example",
        "https://b.example",
    ]


def test_cobalt_endpoint_url_normalizes_trailing_slash():
    assert cobalt_endpoint_url("https://cobalt.example") == "https://cobalt.example/"
    assert cobalt_endpoint_url("https://cobalt.example/") == "https://cobalt.example/"


def test_select_cobalt_download_accepts_tunnel_response():
    assert select_cobalt_download(
        {
            "status": "tunnel",
            "url": "https://cobalt.example/tunnel/file",
            "filename": "video.mp4",
        }
    ) == ("https://cobalt.example/tunnel/file", "video.mp4")


def test_select_cobalt_download_picks_first_video_item():
    assert select_cobalt_download(
        {
            "status": "picker",
            "picker": [
                {"type": "photo", "url": "https://cobalt.example/photo.jpg"},
                {"type": "video", "url": "https://cobalt.example/video.mp4", "filename": "picked.mp4"},
            ],
        }
    ) == ("https://cobalt.example/video.mp4", "picked.mp4")


def test_select_cobalt_download_rejects_error_status():
    with pytest.raises(DownloadFailedError, match="Cobalt returned error"):
        select_cobalt_download({"status": "error", "error": {"code": "error.api.link.unsupported"}})


def test_safe_cobalt_filename_sanitizes_and_adds_extension():
    assert safe_cobalt_filename("bad/name?", "https://www.youtube.com/watch?v=jNQXAC9IVRw") == "bad_name.mp4"


def test_cobalt_source_id_uses_last_path_part():
    assert cobalt_source_id("https://www.instagram.com/reel/DWuZeLziciR/") == "DWuZeLziciR"


def test_cobalt_service_tries_next_base_url_after_failure(tmp_path, monkeypatch):
    class FakePostResponse:
        def __init__(self, base_url):
            self.base_url = base_url

        def raise_for_status(self):
            if self.base_url == "https://a.example/":
                raise RuntimeError("first instance down")

        def json(self):
            return {
                "status": "tunnel",
                "url": "https://cdn.example/video.mp4",
                "filename": "picked.mp4",
                "service": "youtube",
            }

    class FakeStreamResponse:
        def raise_for_status(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def iter_bytes(self):
            return iter([b"vid", b"eo"])

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers):
            return FakePostResponse(url)

        def stream(self, method, url, headers):
            assert method == "GET"
            assert url == "https://cdn.example/video.mp4"
            return FakeStreamResponse()

    monkeypatch.setattr("app.services.cobalt_service.httpx.Client", FakeClient)

    result = CobaltService(
        Settings(cobalt_api_base_url="https://a.example,https://b.example", max_video_size_mb=1)
    ).download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.file_path.read_bytes() == b"video"
    assert result.file_path.name == "picked.mp4"
    assert result.info["extractor"] == "cobalt"
    assert result.info["cobalt_base_url"] == "https://b.example"
