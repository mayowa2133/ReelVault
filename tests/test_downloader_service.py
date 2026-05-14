from app.config import Settings
from app.services.downloader_service import DownloaderService


def test_downloader_uses_instagram_cookies_text(tmp_path):
    service = DownloaderService(Settings(instagram_cookies_text="# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc"))

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    cookie_file = tmp_path / "instagram_cookies.txt"
    assert options["cookiefile"] == str(cookie_file)
    assert "sessionid" in cookie_file.read_text(encoding="utf-8")


def test_downloader_uses_instagram_cookies_file(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    service = DownloaderService(Settings(instagram_cookies_file=str(cookie_file)))

    options = service._yt_dlp_options(str(tmp_path / "%(id)s.%(ext)s"), tmp_path)

    assert options["cookiefile"] == str(cookie_file)
