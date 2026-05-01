"""Pre-send tone linter (PRD §10.6).

Bot messages should be friendly, clear, and lightly energetic. The linter is a
last line of defence against:
  - hype tone ("guaranteed", "you can't lose", ...)
  - cold/robotic tone ("execute according to parameters", ...)
  - emoji over-use (more than 8 in a single message)

`scan()` returns the list of issues found (empty if the message is fine).
`assert_clean()` raises `ToneError` so production code can fail loudly during
tests but degrade gracefully in prod via `lint()`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Regex source-of-truth for forbidden phrases. Case-insensitive.
HYPE_PHRASES: tuple[str, ...] = (
    r"guaranteed (?:winner|profit|return)",
    r"\bguaranteed\b",
    r"can'?t lose",
    r"surefire",
    r"100% (?:win|profit|return)",
    r"to the moon",
    r"easy money",
    r"\brisk-?free\b",
)

COLD_PHRASES: tuple[str, ...] = (
    r"execute according to parameters",
    r"recommendation generated\.?\s*execute",
    r"proceed with execution",
)

# Light emoji palette (PRD §10.6) — used for "looks too plain?" hints.
LIGHT_EMOJI = ("🚀", "📊", "⚠️", "✅", "🔍", "🧠", "📈", "🗓", "💰", "🎚", "🌎", "🏦", "📜", "🔢")

EMOJI_PATTERN = re.compile(
    "["
    "\U0001f300-\U0001fad6"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "]"
)

MAX_EMOJI = 8


class ToneError(ValueError):
    """Raised when assert_clean() finds tone issues."""


@dataclass(slots=True, frozen=True)
class ToneIssue:
    kind: str
    detail: str


def scan(text: str) -> list[ToneIssue]:
    issues: list[ToneIssue] = []
    lower = text.lower()
    for pattern in HYPE_PHRASES:
        if re.search(pattern, lower):
            issues.append(ToneIssue("hype", pattern))
    for pattern in COLD_PHRASES:
        if re.search(pattern, lower):
            issues.append(ToneIssue("cold", pattern))
    emoji_count = len(EMOJI_PATTERN.findall(text))
    if emoji_count > MAX_EMOJI:
        issues.append(ToneIssue("emoji_overuse", f"{emoji_count} emoji"))
    return issues


def assert_clean(text: str) -> None:
    issues = scan(text)
    if issues:
        raise ToneError("; ".join(f"{i.kind}:{i.detail}" for i in issues))


def lint(text: str) -> tuple[bool, Iterable[ToneIssue]]:
    """Non-raising variant. Returns (ok, issues)."""
    issues = scan(text)
    return (not issues, issues)
