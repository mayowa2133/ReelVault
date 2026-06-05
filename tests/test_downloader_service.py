from app.config import Settings
from app.services.downloader_service import (
    DownloaderService,
    YOUTUBE_FALLBACK_FORMAT,
    YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES,
    should_retry_youtube_without_webpage,
    summarize_attempt_errors,
)


def test_downloader_ignores_configured_cookies_by_default(tmp_path):
    service = DownloaderService(Settings(instagram_cookies_text="# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc"))

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert "cookiefile" not in options


def test_downloader_uses_social_cookies_text_when_explicitly_enabled(tmp_path):
    service = DownloaderService(
        Settings(
            enable_auth_cookies=True,
            social_cookies_text="# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc",
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    cookie_file = tmp_path / "social_cookies.txt"
    assert options["cookiefile"] == str(cookie_file)
    assert "sessionid" in cookie_file.read_text(encoding="utf-8")


def test_downloader_uses_legacy_instagram_cookies_file_when_explicitly_enabled(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    service = DownloaderService(Settings(enable_auth_cookies=True, instagram_cookies_file=str(cookie_file)))

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["cookiefile"] == str(cookie_file)


def test_youtube_no_auth_fallback_options_skip_webpage(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    fallback = service._youtube_no_auth_fallback_options(options)

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["mweb"],
        "player_skip": ["webpage", "configs"],
    }
    assert fallback["format"] == YOUTUBE_FALLBACK_FORMAT
    assert "cookiefile" not in fallback


def test_youtube_all_clients_fallback_skips_video_webpage(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = next(item for item in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES if item.name == "all_clients_no_webpage")

    fallback = service._youtube_no_auth_fallback_options(options, strategy)

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["all"],
        "player_skip": ["webpage"],
    }
    assert fallback["format"] == YOUTUBE_FALLBACK_FORMAT


def test_youtube_bot_error_is_retryable():
    assert should_retry_youtube_without_webpage(
        "https://www.youtube.com/shorts/XnjiprcNurg",
        "ERROR: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies",
    )


def test_youtube_missing_player_response_is_retryable():
    assert should_retry_youtube_without_webpage(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "ERROR: [youtube] jNQXAC9IVRw: Failed to extract any player response",
    )


def test_non_youtube_bot_error_is_not_retryable():
    assert not should_retry_youtube_without_webpage(
        "https://www.instagram.com/reel/ABC123/",
        "ERROR: Sign in to confirm you're not a bot",
    )


def test_downloader_retries_youtube_bot_challenge_with_fallback(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies")
        return {"id": "XnjiprcNurg", "title": "Short", "uploader": "creator"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.youtube.com/shorts/XnjiprcNurg", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert len(calls) == 2
    assert calls[1]["extractor_args"]["youtube"]["player_client"] == ["mweb"]


def test_downloader_continues_to_all_clients_fallback_after_mweb_failure(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies")
        if len(calls) == 2:
            raise RuntimeError("Failed to extract any player response")
        return {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "uploader": "jawed"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert len(calls) == 3
    assert calls[1]["extractor_args"]["youtube"]["player_client"] == ["mweb"]
    assert calls[2]["extractor_args"]["youtube"]["player_client"] == ["all"]
    assert calls[2]["extractor_args"]["youtube"]["player_skip"] == ["webpage"]


def test_downloader_reports_all_youtube_fallback_failures(tmp_path, monkeypatch):
    service = DownloaderService(Settings())

    def fake_download(url, output_dir, options):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is False
    assert result.status == "download_failed"
    assert "YouTube no-auth fallback attempts also failed" in result.error_message
    assert "mweb_no_webpage_configs" in result.error_message
    assert "all_clients_no_webpage" in result.error_message


def test_summarize_attempt_errors_truncates_long_reasons():
    summary = summarize_attempt_errors([("strategy", "x" * 400)])

    assert summary.startswith("strategy: ")
    assert summary.endswith("...")
    assert len(summary) < 320
