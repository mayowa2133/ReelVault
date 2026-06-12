from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from app.models.schemas import ReelReference


SUPPORTED_SOCIAL_DOMAINS = (
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "x.com",
    "twitter.com",
)

SOCIAL_URL_PATTERN = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?(?:instagram\.com|youtube\.com|youtu\.be|tiktok\.com|x\.com|twitter\.com)/[^\s<>\"]+",
    flags=re.IGNORECASE,
)

TRAILING_PUNCTUATION = ".,!?;:)']}>"


class SocialVideoService:
    """URL extraction and normalization for yt-dlp-backed social videos."""

    @staticmethod
    def extract_supported_urls(text: str) -> list[ReelReference]:
        if not text:
            return []

        found: list[ReelReference] = []
        seen: set[str] = set()
        for match in SOCIAL_URL_PATTERN.finditer(text):
            raw_url = match.group(0).rstrip(TRAILING_PUNCTUATION)
            reference = SocialVideoService.normalize_url(raw_url)
            dedupe_key = f"{reference.provider}:{reference.shortcode or reference.url}" if reference else ""
            if reference and dedupe_key not in seen:
                found.append(reference)
                seen.add(dedupe_key)
        return found

    @staticmethod
    def normalize_url(raw_url: str) -> ReelReference | None:
        parsed = urlsplit(raw_url)
        host = parsed.netloc.lower()
        host = host.removeprefix("www.")

        if host == "instagram.com":
            return normalize_instagram_url(raw_url)
        if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
            return normalize_youtube_url(raw_url)
        if host in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
            return normalize_tiktok_url(raw_url)
        if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
            return normalize_x_url(raw_url)
        return None


def normalize_instagram_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    host = parsed.netloc.lower()
    if host not in {"instagram.com", "www.instagram.com"}:
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    canonical_media_kinds = {
        "reel": "reel",
        "reels": "reel",
        "p": "p",
        "tv": "tv",
    }
    if len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() in {"reel", "p", "tv"}:
        media_kind = parts[1].lower()
        share_token = parts[2]
        normalized = f"https://www.instagram.com/share/{media_kind}/{quote(share_token)}/"
        return ReelReference(
            url=normalized,
            raw_url=raw_url,
            shortcode=share_token,
            is_share_url=True,
            provider="instagram",
        )

    if len(parts) >= 2 and parts[0].lower() == "share":
        share_token = parts[1]
        normalized = f"https://www.instagram.com/share/{quote(share_token)}/"
        return ReelReference(
            url=normalized,
            raw_url=raw_url,
            shortcode=share_token,
            is_share_url=True,
            provider="instagram",
        )

    if len(parts) >= 3 and parts[0].lower() == "stories":
        user = parts[1]
        story_id = parts[2]
        normalized = f"https://www.instagram.com/stories/{quote(user)}/{quote(story_id)}/"
        return ReelReference(url=normalized, raw_url=raw_url, shortcode=story_id, provider="instagram")

    media_index = next(
        (
            index
            for index, part in enumerate(parts[:2])
            if part.lower() in canonical_media_kinds
        ),
        None,
    )
    if media_index is not None and len(parts) > media_index + 1:
        media_kind = parts[media_index].lower()
        shortcode = parts[media_index + 1]
        normalized = f"https://www.instagram.com/{canonical_media_kinds[media_kind]}/{quote(shortcode)}/"
        return ReelReference(url=normalized, raw_url=raw_url, shortcode=shortcode, provider="instagram")

    return None


def normalize_youtube_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    query = parse_qs(parsed.query)

    if host == "youtu.be":
        video_id = first_path_part(parsed.path)
        if not video_id:
            return None
        return ReelReference(
            url=f"https://youtu.be/{quote(video_id)}",
            raw_url=raw_url,
            shortcode=video_id,
            provider="youtube",
        )

    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    video_id = None
    normalized_path = parsed.path
    normalized_query = ""

    if parts and parts[0].lower() == "attribution_link":
        target_url = youtube_attribution_target_url(query)
        if target_url:
            return normalize_youtube_url(target_url)
        return None
    if parts and parts[0].lower() == "watch":
        video_id = first_query_value(query, "v")
        if not video_id:
            return None
        normalized_path = "/watch"
        normalized_query = urlencode({"v": video_id})
    elif len(parts) >= 2 and parts[0].lower() in {"shorts", "live", "embed", "clip", "v", "e"}:
        video_id = parts[1]
        path_kind = {"v": "embed", "e": "embed"}.get(parts[0].lower(), parts[0].lower())
        normalized_path = f"/{path_kind}/{quote(video_id)}"
    else:
        return None

    return ReelReference(
        url=urlunsplit(("https", "www.youtube.com", normalized_path, normalized_query, "")),
        raw_url=raw_url,
        shortcode=video_id,
        provider="youtube",
    )


def youtube_attribution_target_url(query: dict[str, list[str]]) -> str | None:
    target = first_query_value(query, "u") or first_query_value(query, "q")
    if not target:
        return None
    target = unquote(target)
    return urljoin("https://www.youtube.com", target)


def normalize_tiktok_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if not parts:
        return None

    shortcode = None
    normalized_path = "/" + "/".join(quote(part, safe="@") for part in parts)
    if len(parts) >= 3 and parts[0].startswith("@") and parts[1].lower() == "video":
        shortcode = clean_tiktok_video_id(parts[2])
        normalized_path = f"/{quote(parts[0], safe='@')}/video/{quote(shortcode)}"
    elif host in {"vm.tiktok.com", "vt.tiktok.com"}:
        shortcode = parts[0]
    elif len(parts) >= 2 and parts[0].lower() in {"t", "v"}:
        shortcode = clean_tiktok_video_id(parts[1])
        normalized_path = f"/{parts[0].lower()}/{quote(shortcode)}"
    elif len(parts) >= 2 and parts[0].lower() == "embed":
        if len(parts) >= 3 and parts[1].lower() == "v2":
            shortcode = clean_tiktok_video_id(parts[2])
            normalized_path = f"/embed/{quote(shortcode)}"
        else:
            shortcode = clean_tiktok_video_id(parts[1])
            normalized_path = f"/embed/{quote(shortcode)}"
    elif len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() == "video":
        shortcode = clean_tiktok_video_id(parts[2])
        normalized_path = f"/@_/video/{quote(shortcode)}"

    if not shortcode:
        return None

    return ReelReference(
        url=urlunsplit(("https", parsed.netloc.lower(), normalized_path, "", "")),
        raw_url=raw_url,
        shortcode=shortcode,
        provider="tiktok",
    )


def clean_tiktok_video_id(value: str) -> str:
    return re.sub(r"\.html\Z", "", value, flags=re.IGNORECASE)


def normalize_x_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    status_index = next((index for index, part in enumerate(parts) if part.lower() in {"status", "statuses"}), None)
    if status_index is None or len(parts) <= status_index + 1:
        return None

    status_id = parts[status_index + 1]
    username = parts[status_index - 1] if status_index > 0 else "i"
    normalized = f"https://x.com/{quote(username)}/status/{quote(status_id)}"
    return ReelReference(url=normalized, raw_url=raw_url, shortcode=status_id, provider="x")


def first_path_part(path: str) -> str | None:
    for part in path.split("/"):
        if part:
            return unquote(part)
    return None


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None
