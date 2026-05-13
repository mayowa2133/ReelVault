from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

from app.models.schemas import ReelReference


INSTAGRAM_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/[^\s<>\"]+",
    flags=re.IGNORECASE,
)

TRAILING_PUNCTUATION = ".,!?;:)']}>"


class InstagramService:
    """Instagram URL extraction and normalization helpers."""

    @staticmethod
    def extract_reel_urls(text: str) -> list[ReelReference]:
        if not text:
            return []

        found: list[ReelReference] = []
        seen: set[str] = set()
        for match in INSTAGRAM_URL_PATTERN.finditer(text):
            raw_url = match.group(0).rstrip(TRAILING_PUNCTUATION)
            reel = InstagramService.normalize_reel_url(raw_url)
            if reel and reel.url not in seen:
                found.append(reel)
                seen.add(reel.url)
        return found

    @staticmethod
    def normalize_reel_url(raw_url: str) -> ReelReference | None:
        parsed = urlsplit(raw_url)
        host = parsed.netloc.lower()
        if host not in {"instagram.com", "www.instagram.com"}:
            return None

        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0].lower() == "reel":
            shortcode = parts[1]
            normalized = f"https://www.instagram.com/reel/{quote(shortcode)}/"
            return ReelReference(url=normalized, raw_url=raw_url, shortcode=shortcode)

        if len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() == "reel":
            share_token = parts[2]
            normalized = f"https://www.instagram.com/share/reel/{quote(share_token)}/"
            return ReelReference(url=normalized, raw_url=raw_url, shortcode=share_token, is_share_url=True)

        return None

