from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from app.config import Settings
from app.models.schemas import ContentPillar, ReelAnalysis
from app.utils.errors import ExternalServiceError, public_error_message
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TranscriptScriptTargets:
    source_word_count: int
    source_thought_count: int
    target_word_min: int
    target_word_max: int
    target_line_min: int
    target_line_max: int
    target_line_count: int


class AnalysisService:
    """Generate structured original-content analysis from a transcript."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def analyze(
        self,
        transcript: str,
        reel_url: str,
        creator_username: str | None = None,
        selected_pillar: ContentPillar | None = None,
    ) -> ReelAnalysis:
        if not self.client:
            raise ExternalServiceError("OPENAI_API_KEY is not configured", step="analysis")
        if not transcript.strip():
            raise ExternalServiceError("Transcript is empty; cannot analyze Reel", step="analysis")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an ethical short-form content strategist. Analyze private inspiration "
                    "material and produce original ideas. Never suggest reposting, copying, impersonating, "
                    "or claiming ownership of the source creator's work. Adapt only the hook pattern, "
                    "structure, pacing, or communication strategy."
                ),
            },
            {
                "role": "user",
                "content": self._build_user_prompt(transcript, reel_url, creator_username, selected_pillar),
            },
        ]

        try:
            content = self._create_structured_response(messages)
            return self._parse_analysis(content)
        except ValidationError as exc:
            raise ExternalServiceError(f"OpenAI analysis returned invalid schema: {exc}", step="analysis") from exc
        except ExternalServiceError:
            raise
        except Exception as exc:
            logger.warning("openai_analysis_failed", extra={"error": public_error_message(exc)})
            raise ExternalServiceError(f"OpenAI analysis failed: {public_error_message(exc)}", step="analysis") from exc

    def _create_structured_response(self, messages: list[dict[str, str]]) -> str:
        assert self.client is not None
        schema = ReelAnalysis.model_json_schema()

        try:
            response = self.client.chat.completions.create(
                model=self.settings.openai_analysis_model,
                messages=messages,
                temperature=0.4,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "reel_analysis",
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except Exception as exc:
            logger.warning("openai_json_schema_fallback", extra={"error": public_error_message(exc)})
            response = self.client.chat.completions.create(
                model=self.settings.openai_analysis_model,
                messages=messages,
                temperature=0.4,
                response_format={"type": "json_object"},
            )

        content = response.choices[0].message.content
        if not content:
            raise ExternalServiceError("OpenAI analysis returned an empty response", step="analysis")
        return content

    def _parse_analysis(self, content: str) -> ReelAnalysis:
        try:
            return ReelAnalysis.model_validate_json(content)
        except ValidationError:
            extracted = extract_json_object(content)
            if extracted is None:
                raise
            return ReelAnalysis.model_validate(extracted)

    def _build_user_prompt(
        self,
        transcript: str,
        reel_url: str,
        creator_username: str | None,
        selected_pillar: ContentPillar | None,
    ) -> str:
        creator = creator_username or "unknown"
        targets = build_script_targets(transcript)
        pillar_instruction = (
            f'The user selected this primary pillar in Telegram: "{selected_pillar.value}". '
            "Return that exact value for pillar and set pillar_confidence to 1."
            if selected_pillar
            else (
                "Classify the source video into exactly one primary pillar from this list: "
                "Gym, Tech, Motivation, Morning Routine, Job Search, Faith."
            )
        )
        return f"""
Analyze this short-form social video transcript for private inspiration tracking.

Source URL: {reel_url}
Creator username, if known: {creator}
Pillar instruction: {pillar_instruction}
Source word count: {targets.source_word_count}
Estimated source spoken thought count: {targets.source_thought_count}
Custom script target word count range: {targets.target_word_min}-{targets.target_word_max}
Custom script target line count: {targets.target_line_count} lines, acceptable range {targets.target_line_min}-{targets.target_line_max}

Return only JSON with exactly this shape:
{{
  "pillar": "Gym | Tech | Motivation | Morning Routine | Job Search | Faith",
  "pillar_confidence": 0.0,
  "hook": "...",
  "main_idea": "...",
  "summary": "...",
  "content_structure": ["...", "...", "..."],
  "why_it_works": ["...", "...", "..."],
  "target_audience": "...",
  "tone": "...",
  "original_content_ideas": [
    {{
      "title": "...",
      "angle": "...",
      "sample_hook": "...",
      "short_script_outline": ["...", "...", "..."]
    }},
    {{
      "title": "...",
      "angle": "...",
      "sample_hook": "...",
      "short_script_outline": ["...", "...", "..."]
    }},
    {{
      "title": "...",
      "angle": "...",
      "sample_hook": "...",
      "short_script_outline": ["...", "...", "..."]
    }}
  ],
  "caption_options": ["...", "...", "..."],
  "searchable_tags": ["...", "...", "...", "...", "..."],
  "script_title": "...",
  "re_hooks": ["...", "...", "..."],
  "custom_script_lines": ["...", "...", "...", "...", "..."]
}}

Rules:
- The three video ideas must be original and suitable for TikTok, Instagram Reels, and YouTube Shorts.
- Set hook to the source video's actual opening hook as accurately as the transcript allows.
- Start custom_script_lines with that same hook. Line 1 should reuse the hook from the source, or make only the smallest necessary wording change to fit the user's version.
- The hook reuse is intentional because it anchors the rewrite to the source's proven opening pattern.
- After the opening hook, do not copy wording, claims, scenes, edits, or creator identity from the source.
- Focus on reusable structure, pacing, hook style, narrative pattern, and audience insight.
- Generate a custom original script that follows the same broad theme and communication pattern as the source, not the same wording.
- Identify the source tone in the tone field, then make custom_script_lines match that delivery style as closely as possible.
- If the source feels motivational, make the custom script motivational. If it feels blunt, make it blunt. If it feels sarcastic, funny, urgent, calm, reflective, or instructional, mirror that style.
- Match the tone without copying the creator's exact persona, catchphrases, identity, private details, or distinctive wording.
- Match the source length as closely as possible. The custom script should land inside the target word count range.
- Match the source spoken thought count as closely as possible. Use the target line count unless the script needs one line more or less to stay natural.
- The custom script should feel like it would take about the same amount of time to say as the original transcript.
- Use a staircase speaking method for custom_script_lines: line 1 creates the hook, each next line builds on the previous line, and the final line resolves or lands the point.
- Each custom_script_lines item must be one complete spoken thought.
- Each custom_script_lines item should be one complete sentence, not a fragment and not multiple sentences combined.
- Do not compress the original into a short summary. Write a full-length original version with a similar pacing shape.
- The re_hooks must be alternate original openings for the user's version of the content and are not counted toward the custom script target length.
- The re_hooks should be close variants of the source hook pattern, but the custom script itself should begin with the source hook first.
- If a detail is unclear from the transcript, say so plainly instead of inventing specifics.

Transcript:
\"\"\"
{transcript[:50000]}
\"\"\"
""".strip()


def build_script_targets(transcript: str) -> TranscriptScriptTargets:
    word_count = count_words(transcript)
    thought_count = estimate_spoken_thoughts(transcript, word_count)
    target_line_count = max(5, thought_count)
    line_padding = 1 if target_line_count < 12 else 2
    target_word_min = max(12, round(word_count * 0.9))
    target_word_max = max(target_word_min + 5, round(word_count * 1.1))
    return TranscriptScriptTargets(
        source_word_count=word_count,
        source_thought_count=thought_count,
        target_word_min=target_word_min,
        target_word_max=target_word_max,
        target_line_min=max(5, target_line_count - line_padding),
        target_line_max=target_line_count + line_padding,
        target_line_count=target_line_count,
    )


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def estimate_spoken_thoughts(transcript: str, word_count: int | None = None) -> int:
    sentence_parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", transcript.strip())
        if count_words(part) >= 2
    ]
    if len(sentence_parts) > 1:
        return len(sentence_parts)

    line_parts = [line.strip() for line in transcript.splitlines() if count_words(line) >= 2]
    if len(line_parts) > 1:
        return len(line_parts)

    words = word_count if word_count is not None else count_words(transcript)
    if words <= 0:
        return 5
    return max(1, round(words / 11))


def extract_json_object(content: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
