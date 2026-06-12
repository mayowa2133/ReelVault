from fastapi.testclient import TestClient

from app.main import app


def test_health_includes_downloader_runtime_info():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "service" in body["runtime"]
    assert "revision" in body["runtime"]
    assert "configuration" in body["runtime"]
    assert body["diagnostics"]["routes"] == [
        "/diagnostics/download",
        "/diagnostics/normalize",
    ]
    assert "instagram_deep_link_media_urls" in body["url_support"]["features"]
    assert "instagram_story_item_urls" in body["url_support"]["features"]
    assert "protocol_relative_social_urls" in body["url_support"]["features"]
    assert "social_redirect_unwrapping" in body["url_support"]["features"]
    assert "youtube_legacy_watch_query_urls" in body["url_support"]["features"]
    assert "youtube_nocookie_embed_urls" in body["url_support"]["features"]
    assert "youtube_redirect_urls" in body["url_support"]["features"]
    assert "youtube_source_shorts_urls" in body["url_support"]["features"]
    assert body["downloader"]["yt_dlp_available"] is True
    assert body["downloader"]["yt_dlp_version"]
    assert "yt_dlp_package_spec" in body["downloader"]
    assert "yt_dlp_plugin_package_specs" in body["downloader"]
    assert "youtube_po_token_provider_version" in body["downloader"]
    assert "youtube_po_token_provider_plugins_available" in body["downloader"]
    assert "youtube_po_token_provider_plugins" in body["downloader"]
    assert "youtube_pot_bgutil_base_url_configured" in body["downloader"]
    assert "youtube_pot_bgutil_script_server_home_configured" in body["downloader"]
    assert "youtube_pot_bgutil_http_provider_reachable" in body["downloader"]
    assert "youtube_pot_bgutil_http_provider_status" in body["downloader"]
    assert "youtube_pot_bgutil_http_provider_version" in body["downloader"]
    assert "youtube_pot_bgutil_http_provider_error" in body["downloader"]
    assert "cobalt_configured" in body["downloader"]
    assert "yt_dlp_retries" in body["downloader"]
    assert "yt_dlp_socket_timeout_seconds" in body["downloader"]
