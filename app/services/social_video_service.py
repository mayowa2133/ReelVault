from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from app.models.schemas import ReelReference


SUPPORTED_SOCIAL_DOMAINS = (
    "instagram.com",
    "youtube.com",
    "youtube-nocookie.com",
    "youtubekids.com",
    "youtu.be",
    "tiktok.com",
    "x.com",
    "twitter.com",
)

SOCIAL_URL_PATTERN = re.compile(
    r"(?:instagram://media\?id=[^\s<>\"]+|(?:https?:)?//(?:[A-Za-z0-9-]+\.)?(?:instagram\.com|youtube(?:-nocookie|kids)?\.com|youtu\.be|tiktok\.com|x\.com|twitter\.com)/[^\s<>\"]+)",
    flags=re.IGNORECASE,
)

TRAILING_PUNCTUATION = ".,!?;:)']}>"
INSTAGRAM_SHORTCODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

SUPPORTED_URL_FEATURES = (
    "instagram_deep_link_media_urls",
    "instagram_media_urls",
    "instagram_reels_audio_pages_ignored",
    "instagram_share_urls",
    "instagram_story_item_urls",
    "instagram_username_media_urls",
    "protocol_relative_social_urls",
    "social_redirect_unwrapping",
    "tiktok_embed_urls",
    "tiktok_mobile_and_share_urls",
    "x_twitter_status_urls",
    "youtube_attribution_urls",
    "youtube_clip_urls",
    "youtube_fragment_urls",
    "youtube_legacy_watch_query_urls",
    "youtube_nocookie_embed_urls",
    "youtube_non_video_embed_urls_ignored",
    "youtube_redirect_urls",
    "youtube_semicolon_query_urls",
    "youtube_shorts_live_embed_urls",
    "youtube_source_shorts_urls",
)


class SocialVideoService:
    """URL extraction and normalization for yt-dlp-backed social videos."""

    @staticmethod
    def extract_supported_urls(text: str) -> list[ReelReference]:
        if not text:
            return []

        found: list[ReelReference] = []
        seen: set[str] = set()
        for match in SOCIAL_URL_PATTERN.finditer(text):
            raw_url = ensure_url_scheme(match.group(0).rstrip(TRAILING_PUNCTUATION))
            reference = SocialVideoService.normalize_url(raw_url)
            dedupe_key = f"{reference.provider}:{reference.shortcode or reference.url}" if reference else ""
            if reference and dedupe_key not in seen:
                found.append(reference)
                seen.add(dedupe_key)
        return found

    @staticmethod
    def normalize_url(raw_url: str) -> ReelReference | None:
        raw_url = ensure_url_scheme(raw_url)
        parsed = urlsplit(raw_url)
        host = parsed.netloc.lower()
        host = host.removeprefix("www.")

        if parsed.scheme.lower() == "instagram":
            return normalize_instagram_deep_link_url(raw_url)
        if (target_url := social_redirect_target_url(parsed, host)) and target_url != raw_url:
            return SocialVideoService.normalize_url(target_url)

        if host == "instagram.com":
            return normalize_instagram_url(raw_url)
        if host in {
            "youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtube-nocookie.com",
            "youtubekids.com",
            "youtu.be",
        }:
            return normalize_youtube_url(raw_url)
        if host in {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
            return normalize_tiktok_url(raw_url)
        if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
            return normalize_x_url(raw_url)
        return None


def ensure_url_scheme(raw_url: str) -> str:
    return f"https:{raw_url}" if raw_url.startswith("//") else raw_url


def social_redirect_target_url(parsed, host: str) -> str | None:
    query = parse_query_values(parsed.query)
    parts = [part.lower() for part in parsed.path.split("/") if part]
    target = None

    if host in {"l.instagram.com", "lm.instagram.com"}:
        target = first_query_value(query, "u")
    elif host in {"youtube.com", "m.youtube.com"} and parts[:1] == ["redirect"]:
        target = first_query_value(query, "q") or first_query_value(query, "u") or first_query_value(query, "url")
    elif host == "tiktok.com" and parts[:2] == ["link", "v2"]:
        target = first_query_value(query, "target")

    if not target:
        return None
    return urljoin(f"{parsed.scheme or 'https'}://{parsed.netloc}", unquote(target))


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
    if len(parts) >= 3 and parts[0].lower() == "share" and parts[1].lower() in {"reel", "reels", "p", "tv"}:
        media_kind = parts[1].lower()
        share_token = parts[2]
        normalized_media_kind = "reel" if media_kind == "reels" else media_kind
        normalized = f"https://www.instagram.com/share/{normalized_media_kind}/{quote(share_token)}/"
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
        if media_kind in {"reel", "reels"} and shortcode.lower() == "audio":
            return None
        normalized = f"https://www.instagram.com/{canonical_media_kinds[media_kind]}/{quote(shortcode)}/"
        return ReelReference(url=normalized, raw_url=raw_url, shortcode=shortcode, provider="instagram")

    return None


def normalize_instagram_deep_link_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() != "instagram" or parsed.netloc.lower() != "media":
        return None

    media_id = first_query_value(parse_query_values(parsed.query), "id")
    shortcode = instagram_media_id_to_shortcode(media_id)
    if not shortcode:
        return None

    normalized = f"https://www.instagram.com/tv/{quote(shortcode)}/"
    return ReelReference(url=normalized, raw_url=raw_url, shortcode=shortcode, provider="instagram")


def instagram_media_id_to_shortcode(media_id: str | None) -> str | None:
    pk_text = str(media_id or "").split("_", 1)[0]
    if not pk_text.isdigit():
        return None

    pk = int(pk_text)
    if pk == 0:
        return INSTAGRAM_SHORTCODE_CHARS[0]

    shortcode = ""
    while pk:
        pk, index = divmod(pk, len(INSTAGRAM_SHORTCODE_CHARS))
        shortcode = INSTAGRAM_SHORTCODE_CHARS[index] + shortcode
    return shortcode


def normalize_youtube_url(raw_url: str) -> ReelReference | None:
    parsed = urlsplit(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    query = parse_query_values(parsed.query)

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

    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtubekids.com"}:
        return None

    if target_url := youtube_fragment_target_url(parsed):
        return normalize_youtube_url(target_url)
    if "v" not in query:
        query = youtube_fragment_query(parsed.fragment) or query

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    video_id = None
    normalized_path = parsed.path
    normalized_query = ""

    if parts and parts[0].lower() == "attribution_link":
        target_url = youtube_attribution_target_url(query)
        if target_url:
            return normalize_youtube_url(target_url)
        return None
    if not parts or (
        len(parts) == 1
        and parts[0].lower() in {"watch", "watch_popup", "watch.php", "movie", "movie_popup", "movie.php"}
    ):
        video_id = first_query_value(query, "v")
        if not video_id:
            return None
        normalized_path = "/watch"
        normalized_query = urlencode({"v": video_id})
    elif len(parts) >= 3 and parts[0].lower() == "source" and parts[2].lower() == "shorts":
        video_id = parts[1]
        normalized_path = f"/shorts/{quote(video_id)}"
    elif len(parts) >= 2 and parts[0].lower() in {"shorts", "live", "embed", "clip", "v", "e"}:
        video_id = parts[1]
        path_kind = {"v": "embed", "e": "embed"}.get(parts[0].lower(), parts[0].lower())
        if path_kind == "embed" and video_id.lower() in {"videoseries", "live_stream"}:
            return None
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
    target = first_query_value(query, "u") or first_query_value(query, "q") or first_query_value(query, "url")
    if not target:
        return None
    target = unquote(target)
    return urljoin("https://www.youtube.com", target)


def youtube_fragment_target_url(parsed) -> str | None:
    fragment = unquote(parsed.fragment or "").lstrip("!")
    if not fragment.startswith("/"):
        return None
    return urljoin(f"{parsed.scheme or 'https'}://{parsed.netloc}", fragment)


def youtube_fragment_query(fragment: str) -> dict[str, list[str]]:
    fragment = unquote(fragment or "").lstrip("!")
    if not fragment:
        return {}
    if "?" in fragment:
        fragment = fragment.split("?", 1)[1]
    return parse_query_values(fragment)


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


def parse_query_values(query: str) -> dict[str, list[str]]:
    return parse_qs(query.replace(";", "&"))
