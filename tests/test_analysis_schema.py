from app.models.schemas import ReelAnalysis
from app.services.analysis_service import AnalysisService, build_script_targets


def test_reel_analysis_schema_accepts_expected_shape():
    analysis = ReelAnalysis.model_validate(
        {
            "pillar": "Motivation",
            "pillar_confidence": 0.87,
            "hook": "You are making this harder than it needs to be.",
            "main_idea": "Simplify a common workflow.",
            "summary": "The Reel explains a faster way to plan short-form content.",
            "content_structure": ["Pattern interrupt", "Problem", "Simple framework", "CTA"],
            "why_it_works": ["Clear pain point", "Fast payoff", "Easy to adapt"],
            "target_audience": "Creators who batch content.",
            "tone": "Direct and practical",
            "original_content_ideas": [
                {
                    "title": "The 10-Minute Planning Reset",
                    "angle": "Show a planning method for busy founders.",
                    "sample_hook": "Your content plan is too complicated.",
                    "short_script_outline": ["Name the pain", "Show the reset", "Give the next action"],
                },
                {
                    "title": "Steal Back Your Draft Folder",
                    "angle": "Turn messy saved posts into a weekly idea list.",
                    "sample_hook": "Your saved folder is not a strategy.",
                    "short_script_outline": ["Open loop", "Framework", "Example"],
                },
                {
                    "title": "One Hook, Three Angles",
                    "angle": "Teach creators to repurpose a hook ethically.",
                    "sample_hook": "Do not copy the video. Copy the job it does.",
                    "short_script_outline": ["Warning", "Method", "Demo"],
                },
            ],
            "caption_options": ["Caption one", "Caption two", "Caption three"],
            "searchable_tags": ["content strategy", "creator workflow", "shorts", "reels", "ideation"],
            "script_title": "Stop Overbuilding Your Content System",
            "re_hooks": [
                "Your content plan is doing too much.",
                "You do not need a bigger system.",
                "The problem is not your ideas.",
            ],
            "custom_script_lines": [
                "Your content plan is probably too heavy.",
                "That is why you keep avoiding it.",
                "You do not need another template.",
                "You need one clear idea you can say out loud.",
                "Start with the pain your audience already feels.",
                "Then show them the simplest next step.",
            ],
        }
    )

    assert analysis.pillar.value == "Motivation"
    assert analysis.original_content_ideas[0].title == "The 10-Minute Planning Reset"
    assert len(analysis.searchable_tags) == 5
    assert len(analysis.re_hooks) == 3


def test_script_targets_follow_source_length():
    transcript = (
        "This is the first thought. "
        "This is the second thought. "
        "This is the third thought. "
        "This is the fourth thought. "
        "This is the fifth thought. "
        "This is the sixth thought."
    )

    targets = build_script_targets(transcript)

    assert targets.source_thought_count == 6
    assert targets.target_line_count == 6
    assert targets.target_line_min == 5
    assert targets.target_word_min <= targets.source_word_count <= targets.target_word_max


def test_analysis_prompt_includes_length_matching_rules():
    transcript = "Line one has a complete thought. Line two builds on it. Line three lands the point."

    prompt = AnalysisService(settings=type("SettingsStub", (), {"openai_api_key": ""})())._build_user_prompt(
        transcript,
        "https://www.instagram.com/reel/ABC123/",
        None,
        None,
    )

    assert "Custom script target word count range:" in prompt
    assert "Custom script target line count:" in prompt
    assert "Match the source length as closely as possible" in prompt
    assert "Start custom_script_lines with that same hook" in prompt
    assert "Line 1 should reuse the hook from the source" in prompt
    assert "After the opening hook, do not copy wording" in prompt
    assert "make custom_script_lines match that delivery style" in prompt
    assert "motivational" in prompt
    assert "sarcastic" in prompt
    assert "Each custom_script_lines item should be one complete sentence" in prompt
