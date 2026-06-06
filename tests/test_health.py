from fastapi.testclient import TestClient

from app.main import app


def test_health_includes_downloader_runtime_info():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["downloader"]["yt_dlp_available"] is True
    assert body["downloader"]["yt_dlp_version"]
    assert "cobalt_configured" in body["downloader"]
    assert "yt_dlp_retries" in body["downloader"]
    assert "yt_dlp_socket_timeout_seconds" in body["downloader"]
