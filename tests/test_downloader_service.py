from app.config import Settings
from app.services.downloader_service import (
    DownloaderService,
    TIKTOK_NO_AUTH_FALLBACK_STRATEGIES,
    YOUTUBE_FALLBACK_FORMAT,
    YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES,
    X_NO_AUTH_FALLBACK_STRATEGIES,
    fetch_anonymous_youtube_visitor_data,
    fetch_instagram_redirect_url,
    fetch_tiktok_redirect_url,
    compact_yt_dlp_debug_log,
    instagram_fallback_urls,
    is_instagram_share_url,
    is_tiktok_short_url,
    parse_extractor_args_json,
    sanitize_yt_dlp_debug_message,
    should_retry_instagram_with_url_variants,
    should_retry_tiktok_with_mobile_api,
    should_try_cobalt_fallback,
    should_retry_x_with_api_fallbacks,
    should_retry_youtube_without_webpage,
    downloader_runtime_info,
    summarize_attempt_errors,
    x_fallback_urls,
    youtube_fallback_url,
)
from app.services.cobalt_service import CobaltDownloadResult


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


def test_downloader_applies_proxy_and_sleep_options(tmp_path):
    service = DownloaderService(
        Settings(
            social_download_proxy_url="socks5://user:pass@proxy.example:1080",
            yt_dlp_sleep_requests_seconds=2.5,
            yt_dlp_sleep_interval_seconds=3,
            yt_dlp_max_sleep_interval_seconds=7,
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["proxy"] == "socks5://user:pass@proxy.example:1080"
    assert options["sleep_interval_requests"] == 2.5
    assert options["sleep_interval"] == 3
    assert options["max_sleep_interval"] == 7


def test_downloader_applies_retry_timeout_and_header_options(tmp_path):
    service = DownloaderService(
        Settings(
            social_download_user_agent="Custom UA",
            social_download_accept_language="en-US,en;q=0.9",
            yt_dlp_retries=4,
            yt_dlp_extractor_retries=5,
            yt_dlp_fragment_retries=6,
            yt_dlp_file_access_retries=7,
            yt_dlp_retry_sleep_seconds=1.5,
            yt_dlp_socket_timeout_seconds=45,
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["http_headers"] == {
        "User-Agent": "Custom UA",
        "Accept-Language": "en-US,en;q=0.9",
    }
    assert options["retries"] == 4
    assert options["extractor_retries"] == 5
    assert options["fragment_retries"] == 6
    assert options["file_access_retries"] == 7
    assert options["socket_timeout"] == 45
    assert options["retry_sleep_functions"]["http"](1) == 1.5
    assert options["retry_sleep_functions"]["fragment"](2) == 1.5
    assert options["retry_sleep_functions"]["file_access"](3) == 1.5
    assert options["retry_sleep_functions"]["extractor"](4) == 1.5


def test_downloader_applies_impersonation_source_address_and_youtube_extractor_options(tmp_path):
    service = DownloaderService(
        Settings(
            social_download_source_address="0.0.0.0",
            yt_dlp_impersonate_client="chrome-120",
            youtube_fetch_pot_policy="always",
            youtube_include_missing_pot_formats=True,
            youtube_use_ad_playback_context=True,
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["source_address"] == "0.0.0.0"
    assert str(options["impersonate"]) == "chrome-120"
    assert options["extractor_args"]["youtube"] == {
        "fetch_pot": ["always"],
        "formats": ["missing_pot"],
        "use_ad_playback_context": ["true"],
    }


def test_downloader_applies_bgutil_po_token_provider_base_url(tmp_path):
    service = DownloaderService(
        Settings(
            youtube_fetch_pot_policy="always",
            youtube_pot_bgutil_base_url="https://pot-provider.example",
            youtube_pot_bgutil_script_server_home="/opt/bgutil-ytdlp-pot-provider/server",
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["extractor_args"]["youtube"] == {"fetch_pot": ["always"]}
    assert options["extractor_args"]["youtubepot-bgutilhttp"] == {
        "base_url": ["https://pot-provider.example"],
    }
    assert options["extractor_args"]["youtubepot-bgutilscript"] == {
        "server_home": ["/opt/bgutil-ytdlp-pot-provider/server"],
    }


def test_yt_dlp_debug_log_redacts_sensitive_values():
    message = (
        'debug: {"poToken":"secret-token"} '
        "po_token=another-secret "
        "https://example.test/videoplayback?pot=query-secret "
        "Authorization: Bearer auth-secret\n"
        "Cookie: session=secret-cookie"
    )

    sanitized = sanitize_yt_dlp_debug_message(message)

    assert "secret-token" not in sanitized
    assert "another-secret" not in sanitized
    assert "query-secret" not in sanitized
    assert "auth-secret" not in sanitized
    assert "secret-cookie" not in sanitized
    assert sanitized.count("[REDACTED]") == 5


def test_yt_dlp_debug_log_compaction_keeps_tail():
    compacted = compact_yt_dlp_debug_log(["alpha", "beta", "gamma"], max_chars=10)

    assert compacted == "[truncated 6 chars]\nbeta\ngamma"


def test_downloader_supports_any_impersonation_alias(tmp_path):
    service = DownloaderService(Settings(yt_dlp_impersonate_client="any"))

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert str(options["impersonate"]) == ""


def test_downloader_runtime_info_includes_package_spec(monkeypatch):
    monkeypatch.setenv("REELVAULT_YT_DLP_PACKAGE_SPEC", "yt-dlp @ https://example.test/archive.tar.gz")
    monkeypatch.setenv("REELVAULT_YT_DLP_PLUGIN_PACKAGE_SPECS", "bgutil-ytdlp-pot-provider==1.3.1")
    monkeypatch.setenv("REELVAULT_YOUTUBE_PO_TOKEN_PROVIDER_VERSION", "1.3.1")

    info = downloader_runtime_info(Settings())

    assert info["yt_dlp_package_spec"] == "yt-dlp @ https://example.test/archive.tar.gz"
    assert info["yt_dlp_plugin_package_specs"] == "bgutil-ytdlp-pot-provider==1.3.1"
    assert info["youtube_po_token_provider_version"] == "1.3.1"
    assert info["youtube_pot_bgutil_base_url_configured"] is False
    assert info["youtube_pot_bgutil_script_server_home_configured"] is False
    assert info["youtube_pot_bgutil_http_provider_reachable"] is None
    assert info["youtube_pot_bgutil_http_provider_status"] is None
    assert info["youtube_pot_bgutil_http_provider_version"] is None
    assert info["youtube_pot_bgutil_http_provider_error"] is None
    assert "youtube_po_token_provider_plugins_available" in info
    assert "youtube_po_token_provider_plugins" in info


def test_downloader_runtime_info_pings_bgutil_http_provider(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = '{"version":"1.3.1"}'
        headers = {"content-type": "application/json"}

        def json(self):
            return {"version": "1.3.1"}

    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse()

    monkeypatch.setattr("app.services.downloader_service.httpx.get", fake_get)

    info = downloader_runtime_info(Settings(youtube_pot_bgutil_base_url="http://127.0.0.1:4416"))

    assert calls == [("http://127.0.0.1:4416/ping", 0.75)]
    assert info["youtube_pot_bgutil_http_provider_reachable"] is True
    assert info["youtube_pot_bgutil_http_provider_status"] == 200
    assert info["youtube_pot_bgutil_http_provider_version"] == "1.3.1"
    assert info["youtube_pot_bgutil_http_provider_error"] is None


def test_downloader_runtime_info_reports_bgutil_http_provider_error(monkeypatch):
    def fake_get(url, timeout):
        raise TimeoutError("provider timeout")

    monkeypatch.setattr("app.services.downloader_service.httpx.get", fake_get)

    info = downloader_runtime_info(Settings(youtube_pot_bgutil_base_url="http://127.0.0.1:4416"))

    assert info["youtube_pot_bgutil_http_provider_reachable"] is False
    assert info["youtube_pot_bgutil_http_provider_status"] is None
    assert info["youtube_pot_bgutil_http_provider_version"] is None
    assert "provider timeout" in info["youtube_pot_bgutil_http_provider_error"]


def test_downloader_merges_custom_extractor_args_json(tmp_path):
    service = DownloaderService(
        Settings(
            youtube_fetch_pot_policy="auto",
            social_extractor_args_json='{"youtube":{"fetch-pot":"always","player-client":["ios"]},"instagram":{"app_id":"123"}}',
        )
    )

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["extractor_args"] == {
        "youtube": {
            "fetch_pot": ["always"],
            "player_client": ["ios"],
        },
        "instagram": {"app_id": ["123"]},
    }


def test_parse_extractor_args_json_ignores_invalid_json():
    assert parse_extractor_args_json("not json") == {}


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


def test_youtube_android_ios_fallback_skips_webpage_and_configs(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = next(item for item in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES if item.name == "android_ios_no_webpage_configs")

    fallback = service._youtube_no_auth_fallback_options(options, strategy)

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["android", "ios"],
        "player_skip": ["webpage", "configs"],
    }
    assert fallback["format"] == YOUTUBE_FALLBACK_FORMAT


def test_youtube_visitor_data_fallback_uses_configured_visitor_data(tmp_path):
    service = DownloaderService(Settings(youtube_visitor_data="VISITOR123"))
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = next(item for item in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES if item.name == "default_clients_with_visitor_data")

    fallback = service._youtube_no_auth_fallback_options(options, strategy, service._youtube_visitor_data())

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["default"],
        "player_skip": ["webpage", "configs"],
        "visitor_data": ["VISITOR123"],
    }
    assert "cookiefile" not in fallback


def test_youtube_po_token_fallback_uses_configured_token(tmp_path):
    service = DownloaderService(Settings(youtube_visitor_data="VISITOR123", youtube_po_token="web.gvs+TOKEN123"))
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = next(item for item in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES if item.name == "web_with_configured_po_token")

    fallback = service._youtube_no_auth_fallback_options(options, strategy, service._youtube_visitor_data())

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["web", "default"],
        "player_skip": ["webpage", "configs"],
        "visitor_data": ["VISITOR123"],
        "po_token": ["web.gvs+TOKEN123"],
    }
    assert "cookiefile" not in fallback


def test_youtube_embedded_fallback_uses_explicit_client_and_embed_url(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = next(
        item for item in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES if item.name == "web_embedded_embed_url_no_webpage_configs"
    )

    fallback = service._youtube_no_auth_fallback_options(options, strategy)

    assert fallback["extractor_args"]["youtube"] == {
        "player_client": ["web_embedded"],
        "player_skip": ["webpage", "configs"],
    }
    assert youtube_fallback_url("https://www.youtube.com/watch?v=jNQXAC9IVRw", strategy.url_variant) == (
        "https://www.youtube.com/embed/jNQXAC9IVRw?html5=1"
    )


def test_youtube_tv_and_android_vr_fallbacks_use_valid_clients(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    clients = {
        strategy.name: service._youtube_no_auth_fallback_options(options, strategy)["extractor_args"]["youtube"][
            "player_client"
        ]
        for strategy in YOUTUBE_NO_AUTH_FALLBACK_STRATEGIES
        if strategy.name in {"tv_no_webpage_configs", "android_vr_no_webpage_configs"}
    }

    assert clients == {
        "tv_no_webpage_configs": ["tv"],
        "android_vr_no_webpage_configs": ["android_vr"],
    }


def test_tiktok_mobile_api_fallback_options_configure_app_info(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.downloader_service.tiktok_install_id", lambda: "7250000000000000001")
    monkeypatch.setattr("app.services.downloader_service.tiktok_device_id", lambda: "7250000000000000002")
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = TIKTOK_NO_AUTH_FALLBACK_STRATEGIES[0]

    fallback = service._tiktok_no_auth_fallback_options(options, strategy)

    assert fallback["extractor_args"]["tiktok"] == {
        "app_info": ["7250000000000000001/musical_ly/35.1.3/2023501030/0"],
        "api_hostname": ["api16-normal-c-useast1a.tiktokv.com"],
        "device_id": ["7250000000000000002"],
    }
    assert fallback["format"] == "best[ext=mp4]/best"


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


def test_tiktok_public_error_is_retryable_with_mobile_api():
    assert should_retry_tiktok_with_mobile_api(
        "https://www.tiktok.com/@creator/video/7253412088251534594",
        "Video not available, status code 0",
    )


def test_tiktok_private_error_is_not_retryable_with_mobile_api():
    assert not should_retry_tiktok_with_mobile_api(
        "https://www.tiktok.com/@creator/video/7253412088251534594",
        "You do not have permission to view this post. Log into an account that has access",
    )


def test_x_public_error_is_retryable_with_api_fallback():
    assert should_retry_x_with_api_fallbacks(
        "https://x.com/example/status/1790637656616943991",
        "Twitter API returned not authorized",
    )


def test_x_url_fallbacks_include_twitter_and_i_web_variants():
    assert x_fallback_urls("https://x.com/example/status/1790637656616943991?s=20") == [
        ("twitter_status_url", "https://twitter.com/example/status/1790637656616943991"),
        ("x_i_web_status_url", "https://x.com/i/web/status/1790637656616943991"),
        ("twitter_i_web_status_url", "https://twitter.com/i/web/status/1790637656616943991"),
        ("twitter_statuses_url", "https://twitter.com/statuses/1790637656616943991"),
    ]


def test_x_legacy_api_fallback_options(tmp_path):
    service = DownloaderService(Settings())
    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)
    strategy = X_NO_AUTH_FALLBACK_STRATEGIES[0]

    fallback = service._x_no_auth_fallback_options(options, strategy)

    assert fallback["extractor_args"]["twitter"] == {"api": ["legacy"]}
    assert fallback["format"] == "best[ext=mp4]/best"


def test_tiktok_short_url_detection():
    assert is_tiktok_short_url("https://vm.tiktok.com/ZMabc123/")
    assert is_tiktok_short_url("https://vt.tiktok.com/ZMabc123/")
    assert is_tiktok_short_url("https://www.tiktok.com/t/ZMabc123/")
    assert is_tiktok_short_url("https://m.tiktok.com/v/7253412088251534594.html")
    assert not is_tiktok_short_url("https://www.tiktok.com/@creator/video/7253412088251534594")


def test_fetch_tiktok_redirect_url_returns_canonical_video(monkeypatch):
    class FakeResponse:
        url = "https://www.tiktok.com/@creator/video/7253412088251534594?is_from_webapp=1"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            assert url == "https://vm.tiktok.com/ZMabc123/"
            return FakeResponse()

    monkeypatch.setattr("app.services.downloader_service.httpx.Client", FakeClient)

    assert (
        fetch_tiktok_redirect_url("https://vm.tiktok.com/ZMabc123/", timeout_seconds=10, user_agent="UA")
        == "https://www.tiktok.com/@creator/video/7253412088251534594"
    )


def test_instagram_url_variant_error_is_retryable():
    assert should_retry_instagram_with_url_variants(
        "https://www.instagram.com/reel/ABC123/",
        "Requested content is not available, rate-limit reached or login required",
    )


def test_instagram_share_url_unsupported_error_is_retryable():
    assert should_retry_instagram_with_url_variants(
        "https://www.instagram.com/share/reel/BA123xyz/",
        "Unsupported URL: https://www.instagram.com/share/reel/BA123xyz/",
    )


def test_instagram_fallback_urls_include_reel_post_and_embed_variants():
    assert instagram_fallback_urls("https://www.instagram.com/reel/ABC123/") == [
        ("instagram_reels_url", "https://www.instagram.com/reels/ABC123/"),
        ("instagram_post_url", "https://www.instagram.com/p/ABC123/"),
        ("instagram_tv_url", "https://www.instagram.com/tv/ABC123/"),
        ("instagram_reel_embed_url", "https://www.instagram.com/reel/ABC123/embed/"),
        ("instagram_post_embed_url", "https://www.instagram.com/p/ABC123/embed/"),
        ("instagram_tv_embed_url", "https://www.instagram.com/tv/ABC123/embed/"),
    ]


def test_instagram_share_url_detection():
    assert is_instagram_share_url("https://www.instagram.com/share/reel/BA123xyz/")
    assert is_instagram_share_url("https://www.instagram.com/share/p/BA123xyz/")
    assert is_instagram_share_url("https://www.instagram.com/share/tv/BA123xyz/")
    assert not is_instagram_share_url("https://www.instagram.com/reel/ABC123/")


def test_cobalt_fallback_is_limited_to_supported_provider_hosts():
    assert should_try_cobalt_fallback("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert should_try_cobalt_fallback("https://www.instagram.com/reel/ABC123/")
    assert should_try_cobalt_fallback("https://www.tiktok.com/@creator/video/7253412088251534594")
    assert not should_try_cobalt_fallback("https://example.com/video")


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
        if len(calls) == 3:
            raise RuntimeError("No video formats found")
        return {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "uploader": "jawed"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert len(calls) == 4
    assert calls[1]["extractor_args"]["youtube"]["player_client"] == ["mweb"]
    assert calls[2]["extractor_args"]["youtube"]["player_client"] == ["android", "ios"]
    assert calls[2]["extractor_args"]["youtube"]["player_skip"] == ["webpage", "configs"]
    assert calls[3]["extractor_args"]["youtube"]["player_client"] == ["all"]
    assert calls[3]["extractor_args"]["youtube"]["player_skip"] == ["webpage"]


def test_downloader_retries_tiktok_with_mobile_api_fallback(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError("Video not available, status code 0")
        return {"id": "7253412088251534594", "title": "TikTok", "uploader": "creator"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.tiktok.com/@creator/video/7253412088251534594", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert len(calls) == 2
    assert calls[1]["extractor_args"]["tiktok"]["app_info"][0].endswith("/musical_ly/35.1.3/2023501030/0")


def test_downloader_resolves_tiktok_short_url_before_mobile_api_fallback(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")
    canonical_url = "https://www.tiktok.com/@creator/video/7253412088251534594"

    def fake_download(url, output_dir, options):
        calls.append((url, options))
        if len(calls) <= 2:
            raise RuntimeError("Video not available, status code 0")
        return {"id": "7253412088251534594", "title": "TikTok", "uploader": "creator"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)
    monkeypatch.setattr(
        "app.services.downloader_service.fetch_tiktok_redirect_url",
        lambda url, timeout_seconds, user_agent: canonical_url,
    )

    result = service.download("https://vm.tiktok.com/ZMabc123/", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert calls[0][0] == "https://vm.tiktok.com/ZMabc123/"
    assert calls[1][0] == canonical_url
    assert calls[2][0] == canonical_url
    assert calls[2][1]["extractor_args"]["tiktok"]["app_info"][0].endswith("/musical_ly/35.1.3/2023501030/0")


def test_downloader_retries_instagram_with_url_variants(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("Requested content is not available, rate-limit reached or login required")
        return {"id": "ABC123", "title": "Instagram Reel", "uploader": "creator"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.instagram.com/reel/ABC123/", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert calls == [
        "https://www.instagram.com/reel/ABC123/",
        "https://www.instagram.com/reels/ABC123/",
    ]


def test_downloader_resolves_instagram_share_redirect_before_retry(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError("Unsupported URL: https://www.instagram.com/share/reel/BA123xyz/")
        return {"id": "ABC123", "title": "Instagram Reel", "uploader": "creator"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)
    monkeypatch.setattr(
        "app.services.downloader_service.fetch_instagram_redirect_url",
        lambda url, timeout_seconds, user_agent: "https://www.instagram.com/reel/ABC123/",
    )

    result = service.download("https://www.instagram.com/share/reel/BA123xyz/", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert calls == [
        "https://www.instagram.com/share/reel/BA123xyz/",
        "https://www.instagram.com/reel/ABC123/",
    ]


def test_downloader_retries_x_with_url_variant_fallback(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append((url, options))
        if len(calls) == 1:
            raise RuntimeError("Twitter API returned not authorized")
        if url == "https://twitter.com/example/status/1790637656616943991":
            return {"id": "1790637656616943991", "title": "X video", "uploader": "example"}, output_file
        raise RuntimeError("No video could be found in this tweet")

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://x.com/example/status/1790637656616943991", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert calls[1][0] == "https://twitter.com/example/status/1790637656616943991"


def test_downloader_retries_x_with_legacy_api_after_url_variants_fail(tmp_path, monkeypatch):
    service = DownloaderService(Settings())
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append((url, options))
        twitter_args = options.get("extractor_args", {}).get("twitter", {})
        if twitter_args.get("api") == ["legacy"]:
            return {"id": "1790637656616943991", "title": "X video", "uploader": "example"}, output_file
        raise RuntimeError("Twitter API returned not authorized")

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://x.com/example/status/1790637656616943991", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert calls[-1][1]["extractor_args"]["twitter"]["api"] == ["legacy"]


def test_downloader_uses_visitor_data_fallback_after_non_visitor_failures(tmp_path, monkeypatch):
    service = DownloaderService(Settings(youtube_visitor_data="VISITOR123"))
    calls = []
    output_file = tmp_path / "video.mp4"
    output_file.write_bytes(b"video")

    def fake_download(url, output_dir, options):
        calls.append(options)
        if len(calls) <= 5:
            raise RuntimeError("Sign in to confirm you're not a bot")
        return {"id": "jNQXAC9IVRw", "title": "Me at the zoo", "uploader": "jawed"}, output_file

    monkeypatch.setattr(service, "_download_with_options", fake_download)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert len(calls) == 6
    assert calls[5]["extractor_args"]["youtube"] == {
        "player_client": ["default"],
        "player_skip": ["webpage", "configs"],
        "visitor_data": ["VISITOR123"],
    }


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


def test_downloader_uses_configured_cobalt_after_provider_fallbacks_fail(tmp_path, monkeypatch):
    service = DownloaderService(Settings(cobalt_api_base_url="https://cobalt.example", youtube_visitor_data="VISITOR123"))
    output_file = tmp_path / "cobalt.mp4"

    def fake_download(url, output_dir, options):
        raise RuntimeError("Sign in to confirm you're not a bot")

    class FakeCobaltService:
        def __init__(self, settings):
            self.settings = settings

        def download(self, url, output_dir):
            output_file.write_bytes(b"video")
            return CobaltDownloadResult(
                file_path=output_file,
                info={"id": "jNQXAC9IVRw", "title": "Cobalt", "webpage_url": url, "extractor": "cobalt"},
            )

    monkeypatch.setattr(service, "_download_with_options", fake_download)
    monkeypatch.setattr("app.services.downloader_service.CobaltService", FakeCobaltService)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert result.metadata["extractor"] == "cobalt"


def test_downloader_uses_configured_youtube_mirror_before_cobalt(tmp_path, monkeypatch):
    service = DownloaderService(
        Settings(
            youtube_piped_api_base_urls="https://piped.example",
            cobalt_api_base_url="https://cobalt.example",
        )
    )
    output_file = tmp_path / "mirror.mp4"

    def fake_download(url, output_dir, options):
        raise RuntimeError("Sign in to confirm you're not a bot")

    class FakeMirrorService:
        def __init__(self, settings):
            self.settings = settings

        def download(self, url, output_dir):
            output_file.write_bytes(b"video")
            return type(
                "MirrorResult",
                (),
                {
                    "file_path": output_file,
                    "info": {
                        "id": "jNQXAC9IVRw",
                        "title": "Mirror",
                        "webpage_url": url,
                        "extractor": "youtube_mirror",
                        "youtube_mirror_service": "piped",
                    },
                },
            )()

    class FailingCobaltService:
        def __init__(self, settings):
            self.settings = settings

        def download(self, url, output_dir):
            raise AssertionError("Cobalt should not be called when mirror fallback succeeds")

    monkeypatch.setattr(service, "_download_with_options", fake_download)
    monkeypatch.setattr("app.services.downloader_service.YoutubeMirrorService", FakeMirrorService)
    monkeypatch.setattr("app.services.downloader_service.CobaltService", FailingCobaltService)

    result = service.download("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path)

    assert result.success is True
    assert result.file_path == output_file
    assert result.metadata["extractor"] == "youtube_mirror"
    assert result.metadata["youtube_mirror_service"] == "piped"


def test_summarize_attempt_errors_truncates_long_reasons():
    summary = summarize_attempt_errors([("strategy", "x" * 400)])

    assert summary.startswith("strategy: ")
    assert summary.endswith("...")
    assert len(summary) < 320


def test_fetch_anonymous_youtube_visitor_data_parses_homepage(monkeypatch):
    class FakeResponse:
        text = '{"VISITOR_DATA":"VISITOR123"}'

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            assert url == "https://www.youtube.com/"
            return FakeResponse()

    monkeypatch.setattr("app.services.downloader_service.httpx.Client", FakeClient)

    visitor_data = fetch_anonymous_youtube_visitor_data(timeout_seconds=3, user_agent="UA")

    assert visitor_data == "VISITOR123"


def test_fetch_instagram_redirect_url_parses_final_url(monkeypatch):
    class FakeResponse:
        url = "https://www.instagram.com/reel/ABC123/?igsh=abc"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            assert url == "https://www.instagram.com/share/reel/BA123xyz/"
            return FakeResponse()

    monkeypatch.setattr("app.services.downloader_service.httpx.Client", FakeClient)

    redirect_url = fetch_instagram_redirect_url(
        "https://www.instagram.com/share/reel/BA123xyz/",
        timeout_seconds=3,
        user_agent="UA",
    )

    assert redirect_url == "https://www.instagram.com/reel/ABC123/"
