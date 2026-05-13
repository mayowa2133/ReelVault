from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
import re

from app.models.schemas import ContentPillar


class PillarParseKind(str, Enum):
    NONE = "none"
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PillarParseResult:
    kind: PillarParseKind
    pillar: ContentPillar | None = None
    source: str = ""
    confidence: float | None = None
    candidates: tuple[ContentPillar, ...] = ()

    @property
    def should_confirm(self) -> bool:
        return self.kind == PillarParseKind.FUZZY and self.pillar is not None


@dataclass(frozen=True)
class PillarCallbackAction:
    action: str
    row_index: int
    pillar: ContentPillar | None = None


URL_PATTERN = re.compile(r"https?://\S+", flags=re.IGNORECASE)
NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")

STOP_WORDS = {
    "as",
    "category",
    "classify",
    "for",
    "ig",
    "in",
    "instagram",
    "into",
    "please",
    "pillar",
    "reel",
    "reels",
    "save",
    "this",
    "under",
    "video",
}

PILLAR_SLUGS = {
    ContentPillar.GYM: "gym",
    ContentPillar.TECH: "tech",
    ContentPillar.MOTIVATION: "motivation",
    ContentPillar.MORNING_ROUTINE: "morning-routine",
    ContentPillar.JOB_SEARCH: "job-search",
    ContentPillar.FAITH: "faith",
}

SLUG_TO_PILLAR = {slug: pillar for pillar, slug in PILLAR_SLUGS.items()}


def normalize_phrase(value: str) -> str:
    normalized = NON_WORD_PATTERN.sub(" ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


CANONICAL_PHRASES = {
    normalize_phrase(pillar.value): pillar
    for pillar in ContentPillar
}

ALIAS_PHRASES = {
    "ai": ContentPillar.TECH,
    "career": ContentPillar.JOB_SEARCH,
    "careers": ContentPillar.JOB_SEARCH,
    "coding": ContentPillar.TECH,
    "discipline": ContentPillar.MOTIVATION,
    "fitness": ContentPillar.GYM,
    "god": ContentPillar.FAITH,
    "interview": ContentPillar.JOB_SEARCH,
    "interviews": ContentPillar.JOB_SEARCH,
    "job hunting": ContentPillar.JOB_SEARCH,
    "linkedin": ContentPillar.JOB_SEARCH,
    "mindset": ContentPillar.MOTIVATION,
    "morning": ContentPillar.MORNING_ROUTINE,
    "prayer": ContentPillar.FAITH,
    "programming": ContentPillar.TECH,
    "resume": ContentPillar.JOB_SEARCH,
    "self improvement": ContentPillar.MOTIVATION,
    "software": ContentPillar.TECH,
    "spiritual": ContentPillar.FAITH,
    "technology": ContentPillar.TECH,
    "training": ContentPillar.GYM,
    "weightlifting": ContentPillar.GYM,
    "workout": ContentPillar.GYM,
    "workouts": ContentPillar.GYM,
}

FUZZY_PHRASES = {**CANONICAL_PHRASES, **ALIAS_PHRASES}
CALLBACK_PREFIX = "rvp"


class PillarService:
    """Parse Telegram pillar hints and compact callback payloads."""

    @staticmethod
    def parse_message(text: str) -> PillarParseResult:
        hint = PillarService._clean_hint(text)
        if not hint:
            return PillarParseResult(kind=PillarParseKind.NONE)

        exact_matches = PillarService._phrase_matches(hint, CANONICAL_PHRASES)
        alias_matches = PillarService._phrase_matches(hint, ALIAS_PHRASES)
        all_matches = exact_matches | alias_matches
        if len(all_matches) > 1:
            return PillarParseResult(kind=PillarParseKind.AMBIGUOUS, candidates=tuple(sorted(all_matches, key=str)))
        if len(exact_matches) == 1:
            pillar = next(iter(exact_matches))
            return PillarParseResult(
                kind=PillarParseKind.EXACT,
                pillar=pillar,
                source="telegram_exact",
                confidence=1.0,
            )
        if len(alias_matches) == 1:
            pillar = next(iter(alias_matches))
            return PillarParseResult(
                kind=PillarParseKind.ALIAS,
                pillar=pillar,
                source="telegram_alias",
                confidence=1.0,
            )

        fuzzy = PillarService._fuzzy_match(hint)
        if fuzzy:
            pillar, confidence = fuzzy
            return PillarParseResult(
                kind=PillarParseKind.FUZZY,
                pillar=pillar,
                source="telegram_fuzzy_suggested",
                confidence=confidence,
            )

        return PillarParseResult(kind=PillarParseKind.NONE)

    @staticmethod
    def build_callback_data(action: str, row_index: int, pillar: ContentPillar | None = None) -> str:
        slug = PILLAR_SLUGS[pillar] if pillar else ""
        return f"{CALLBACK_PREFIX}:{action}:{row_index}:{slug}"

    @staticmethod
    def parse_callback_data(data: str) -> PillarCallbackAction | None:
        parts = data.split(":")
        if len(parts) != 4 or parts[0] != CALLBACK_PREFIX:
            return None
        action = parts[1]
        if action not in {"confirm", "ai", "cancel"}:
            return None
        try:
            row_index = int(parts[2])
        except ValueError:
            return None
        pillar = SLUG_TO_PILLAR.get(parts[3]) if parts[3] else None
        if action == "confirm" and pillar is None:
            return None
        return PillarCallbackAction(action=action, row_index=row_index, pillar=pillar)

    @staticmethod
    def _clean_hint(text: str) -> str:
        without_urls = URL_PATTERN.sub(" ", text)
        normalized = normalize_phrase(without_urls)
        words = [word for word in normalized.split() if word not in STOP_WORDS]
        return " ".join(words)

    @staticmethod
    def _phrase_matches(hint: str, phrases: dict[str, ContentPillar]) -> set[ContentPillar]:
        matches: set[ContentPillar] = set()
        for phrase, pillar in phrases.items():
            if re.search(rf"(^|\s){re.escape(phrase)}($|\s)", hint):
                matches.add(pillar)
        return matches

    @staticmethod
    def _fuzzy_match(hint: str) -> tuple[ContentPillar, float] | None:
        if len(hint) < 4 or len(hint.split()) > 3:
            return None

        scores = sorted(
            (
                (SequenceMatcher(None, hint, phrase).ratio(), pillar)
                for phrase, pillar in FUZZY_PHRASES.items()
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scores:
            return None
        top_score, top_pillar = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0
        if top_score >= 0.82 and top_score - second_score >= 0.06:
            return top_pillar, top_score
        return None
