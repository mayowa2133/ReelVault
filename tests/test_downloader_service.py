from app.config import Settings
from app.services.downloader_service import DownloaderService


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
