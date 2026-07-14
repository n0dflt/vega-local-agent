from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Pattern, Tuple


class IntentType(str, Enum):
    DOCUMENT_ANALYSIS = "document_analysis"
    WORKSPACE_DIAGNOSTICS = "workspace_diagnostics"
    PROJECT_SEARCH = "project_search"
    BUG_FIX = "bug_fix"
    TEST_RUN = "test_run"
    CODE_REVIEW = "code_review"
    DOCUMENTATION_UPDATE = "documentation_update"
    RELEASE_CHECK = "release_check"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentAnalysis:
    """Structured result produced from a natural-language request."""

    intent: IntentType
    confidence: float
    original_text: str
    normalized_text: str
    matched_signals: Tuple[str, ...] = ()

    @property
    def is_actionable(self) -> bool:
        return self.intent is not IntentType.UNKNOWN

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "matched_signals": list(self.matched_signals),
            "is_actionable": self.is_actionable,
        }


@dataclass(frozen=True)
class IntentRule:
    intent: IntentType
    primary_patterns: Tuple[Pattern[str], ...]
    secondary_patterns: Tuple[Pattern[str], ...]
    required_patterns: Tuple[Pattern[str], ...] = ()

    def evaluate(self, text: str) -> tuple[int, Tuple[str, ...]]:
        if self.required_patterns and not any(
            pattern.search(text) is not None
            for pattern in self.required_patterns
        ):
            return 0, ()

        matches: list[str] = []
        score = 0

        for pattern in self.primary_patterns:
            match = pattern.search(text)
            if match is not None:
                score += 2
                matches.append(match.group(0))

        for pattern in self.secondary_patterns:
            match = pattern.search(text)
            if match is not None:
                score += 1
                matches.append(match.group(0))

        return score, tuple(dict.fromkeys(matches))


def _patterns(*values: str) -> Tuple[Pattern[str], ...]:
    return tuple(
        re.compile(value, flags=re.IGNORECASE)
        for value in values
    )


_RULES: Tuple[IntentRule, ...] = (
    IntentRule(
        intent=IntentType.WORKSPACE_DIAGNOSTICS,
        primary_patterns=_patterns(
            r"\b(?:pytest|compileall)\b",
            r"\b(?:тест\w*|test(?:s| suite)?)\b",
            r"\b(?:проект\w*|репозитор\w*|workspace|repository)\b",
            r"\b(?:диагностик\w*|провер(?:ь|ка) состояни\w*)\b",
        ),
        secondary_patterns=_patterns(
            r"\b(?:запуст\w*|выполн\w*|run|execute)\b",
            r"(?:без изменений|не изменяй|without modifying|read[- ]?only)",
            r"\b(?:готов\w*|ready|readiness|отч[её]т\w*|report)\b",
        ),
        required_patterns=_patterns(
            r"\b(?:compileall|проект\w*|репозитор\w*|workspace|repository)\b",
        ),
    ),
    IntentRule(
        intent=IntentType.RELEASE_CHECK,
        primary_patterns=_patterns(
            r"\bрелиз\w*",
            r"\brelease\b",
            r"\bтег\w*",
            r"\btag\b",
        ),
        secondary_patterns=_patterns(
            r"\bготов\w*",
            r"\bпровер\w*",
            r"\bподготов\w*",
            r"\bready\b",
            r"\bcheck\b",
        ),
    ),
    IntentRule(
        intent=IntentType.DOCUMENTATION_UPDATE,
        primary_patterns=_patterns(
            r"\bдокументац\w*",
            r"\breadme\b",
            r"\bchangelog\b",
            r"\bдокументирован\w*",
        ),
        secondary_patterns=_patterns(
            r"\bобнов\w*",
            r"\bизмен\w*",
            r"\bсинхрониз\w*",
            r"\bupdate\b",
        ),
    ),
    IntentRule(
        intent=IntentType.BUG_FIX,
        primary_patterns=_patterns(
            r"\bисправ\w*",
            r"\bпочин\w*",
            r"\bошиб\w*",
            r"\bбаг\w*",
            r"\bfix\b",
            r"\bdebug\w*",
            r"\berror\b",
            r"\btraceback\b",
        ),
        secondary_patterns=_patterns(
            r"\bкод\w*",
            r"\bфункц\w*",
            r"\bтест\w*",
            r"\bпаден\w*",
            r"\bfail\w*",
        ),
    ),
    IntentRule(
        intent=IntentType.CODE_REVIEW,
        primary_patterns=_patterns(
            r"\bревью\b",
            r"\breview\b",
            r"\bdiff\b",
            r"\bриск\w*",
            r"\bизменени\w*",
        ),
        secondary_patterns=_patterns(
            r"\bоцен\w*",
            r"\bпосмотр\w*",
            r"\bпровер\w*",
            r"\bпроанализ\w*",
        ),
    ),
    IntentRule(
        intent=IntentType.DOCUMENT_ANALYSIS,
        primary_patterns=_patterns(
            r"\bдокумент\w*",
            r"\b(?:document|file)\b",
            r"(?:^|[\s\"'«])(?:[A-Za-z]:[\\/]|\.{0,2}[\\/])?[^\s\"'«»]+\.(?:pdf|txt|md|docx|csv|json|ya?ml|toml)\b",
        ),
        secondary_patterns=_patterns(
            r"\bпроанализ\w*",
            r"\bкратк\w*",
            r"\bрезюме\b",
            r"\bсводк\w*",
            r"\bsummar\w*",
            r"\banaly[sz]\w*",
            r"\bотч[её]т\w*|\breport\b",
        ),
    ),
    IntentRule(
        intent=IntentType.PROJECT_SEARCH,
        primary_patterns=_patterns(
            r"\bнайд\w*",
            r"\bпоиск\w*",
            r"\bотыщ\w*",
            r"\bfind\b",
            r"\bsearch\b",
            r"\blocate\b",
        ),
        secondary_patterns=_patterns(
            r"\bпроект\w*",
            r"\bкод\w*",
            r"\bфайл\w*",
            r"\bиспользован\w*",
            r"\bapi\b",
        ),
    ),
    IntentRule(
        intent=IntentType.TEST_RUN,
        primary_patterns=_patterns(
            r"\bтест\w*",
            r"\bpytest\b",
            r"\btest\w*",
        ),
        secondary_patterns=_patterns(
            r"\bзапуст\w*",
            r"\bпровер\w*",
            r"\bвыполн\w*",
            r"\brun\b",
        ),
    ),
)


def normalize_request(text: str) -> str:
    normalized = text.strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized)


def analyze_intent(text: str) -> IntentAnalysis:
    """Classify a user request without executing any tools."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = normalize_request(text)

    if not normalized:
        return IntentAnalysis(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            original_text=text,
            normalized_text=normalized,
        )

    best_intent = IntentType.UNKNOWN
    best_score = 0
    best_matches: Tuple[str, ...] = ()

    for rule in _RULES:
        score, matches = rule.evaluate(normalized)

        if score > best_score:
            best_intent = rule.intent
            best_score = score
            best_matches = matches

    if best_score < 2:
        return IntentAnalysis(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            original_text=text,
            normalized_text=normalized,
        )

    # The deterministic feature scorer is intentionally capped below 1.0:
    # heuristic text signals are never absolute proof of user intent.
    confidence = min(0.95, round(0.4 + best_score * 0.1, 2))

    return IntentAnalysis(
        intent=best_intent,
        confidence=confidence,
        original_text=text,
        normalized_text=normalized,
        matched_signals=best_matches,
    )
