import pytest

from app.services.cobalt_service import (
    cobalt_endpoint_url,
    cobalt_source_id,
    safe_cobalt_filename,
    select_cobalt_download,
)
from app.utils.errors import DownloadFailedError


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
