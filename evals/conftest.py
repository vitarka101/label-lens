"""Shared fixtures for Label Lens evals.

Provides:
  - `get_response`: sends a message to the chatbot, returns its response.
  - `judge_with_golden`: MaaJ judge comparing response to a reference answer (1-10).
  - `judge_with_rubric`: MaaJ judge scoring response against a rubric (1-10).
"""

import json
import os
import sys
from pathlib import Path

from litellm import completion

# Add parent directory so we can import app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import MODEL, build_initial_messages

# --- Config ---

JUDGE_MODEL = os.getenv("JUDGE_MODEL", MODEL)
LITELLM_API_BASE = os.getenv("LITELLM_API_BASE")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY")


def _call_model(model: str, messages: list[dict]) -> str:
    """Call LiteLLM with optional shared API base/key overrides."""
    completion_kwargs = {"model": model, "messages": messages}
    if LITELLM_API_BASE:
        completion_kwargs["api_base"] = LITELLM_API_BASE
    if LITELLM_API_KEY:
        completion_kwargs["api_key"] = LITELLM_API_KEY
    result = completion(**completion_kwargs)
    return result.choices[0].message.content


def get_response(text: str) -> str:
    """Send a message to Label Lens and return its response."""
    messages = build_initial_messages()
    messages.append({"role": "user", "content": text})
    return _call_model(model=MODEL, messages=messages)


# --- Judge helpers ---

JUDGE_SYSTEM_GOLDEN = """\
You are an expert evaluator. Given a user prompt, a reference response, and a \
generated response, rate the overall quality of the generated response on a \
scale of 1 to 10 based on how well it compares to the reference response. \
Consider accuracy, completeness, coherence, and helpfulness. \
Start your response with a valid JSON object containing a single key "rating" \
with an integer value between 1 and 10.

Example:
{
  "rating": 7
}"""

JUDGE_SYSTEM_RUBRIC = """\
You are an expert evaluator. Given a user prompt, a generated response, and a \
list of quality rubrics, rate the overall quality of the response on a scale \
of 1 to 10 based on how well it satisfies the rubrics. Consider all rubrics \
holistically. Start your response with a valid JSON object containing a single \
key "rating" with an integer value between 1 and 10.

Example:
{
  "rating": 7
}"""


def judge_with_golden(prompt: str, reference: str, response: str) -> int:
    """Judge a response against a golden reference. Returns rating 1-10."""
    user_msg = (
        "Rate the generated response against the reference on a scale of 1–10."
        f"\n\n<prompt>\n{prompt}\n</prompt>"
        f"\n\n<reference_response>\n{reference}\n</reference_response>"
        f"\n\n<generated_response>\n{response}\n</generated_response>"
    )
    return _parse_rating(
        _call_model(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_GOLDEN},
                {"role": "user", "content": user_msg},
            ],
        )
    )


def judge_with_rubric(prompt: str, response: str, rubric: str) -> int:
    """Judge a response against a rubric. Returns rating 1-10."""
    user_msg = (
        "Rate the response against the rubrics on a scale of 1–10."
        f"\n\n<prompt>\n{prompt}\n</prompt>"
        f"\n\n<response>\n{response}\n</response>"
        f"\n\n<rubrics>\n{rubric}\n</rubrics>"
    )
    return _parse_rating(
        _call_model(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_RUBRIC},
                {"role": "user", "content": user_msg},
            ],
        )
    )


def _parse_rating(text: str) -> int:
    """Extract the integer rating from the judge's JSON response."""
    start = text.index("{")
    end = text.index("}", start) + 1
    return int(json.loads(text[start:end])["rating"])
