from app.models.schemas import ReelReference
from app.services.social_video_service import SocialVideoService, normalize_instagram_url


class InstagramService:
    """Instagram URL extraction and normalization helpers."""

    @staticmethod
    def extract_reel_urls(text: str) -> list[ReelReference]:
        return [reference for reference in SocialVideoService.extract_supported_urls(text) if reference.provider == "instagram"]

    @staticmethod
    def normalize_reel_url(raw_url: str) -> ReelReference | None:
        return normalize_instagram_url(raw_url)
