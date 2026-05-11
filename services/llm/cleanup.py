from __future__ import annotations

import re

from services.pipeline.models import AppContext


_FILLER_PATTERN = re.compile(r"\b(?:um|uh|you know|i mean)\b[,\s]*", re.IGNORECASE)
_LEADING_LIKE_FILLER_PATTERN = re.compile(r"(^|[.!?]\s+|,\s+)like[,\s]+", re.IGNORECASE)
_MAKE_THAT_PATTERN = re.compile(r"\b(?:actually|no)\s+make\s+that\s+", re.IGNORECASE)
_RESET_MARKERS = (
    re.compile(r"\bwait\s+no\b", re.IGNORECASE),
    re.compile(r"\bscratch\s+that\b", re.IGNORECASE),
    re.compile(
        r"\bsorry[,\s]+(?:i\s+)?(?:mean|meant)(?:\s+to\s+say)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bi\s+meant\s+to\s+say\b", re.IGNORECASE),
    re.compile(
        r"\bactually\s+(?=(?:tell|send|set|ship|cancel|schedule|write|say|call|email|text|use|turn|change|replace)\b)",
        re.IGNORECASE,
    ),
)

_HOUR_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_MINUTE_WORDS = {
    "oh one": 1,
    "oh two": 2,
    "oh three": 3,
    "oh four": 4,
    "oh five": 5,
    "oh six": 6,
    "oh seven": 7,
    "oh eight": 8,
    "oh nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty one": 21,
    "twenty two": 22,
    "twenty three": 23,
    "twenty four": 24,
    "twenty five": 25,
    "twenty six": 26,
    "twenty seven": 27,
    "twenty eight": 28,
    "twenty nine": 29,
    "thirty": 30,
    "forty": 40,
    "forty five": 45,
    "fifty": 50,
}
_K_NUMBER_WORDS = {
    "ten": 10,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}


def clean_dictation_text(
    raw_text: str,
    app_context: AppContext,
    vocabulary_hints: list[str] | None = None,
) -> str:
    prose_formatting = app_context.category != "code"
    text = raw_text.strip()
    if not text:
        return ""

    text = _apply_make_that_corrections(text)
    text = _apply_reset_corrections(text)
    text = _apply_spoken_punctuation(text)
    text = _normalize_common_dictation_forms(text)
    text = _apply_vocabulary_hints(text, vocabulary_hints or [])
    if prose_formatting:
        text = _remove_fillers(text)
    text = _tidy_spacing(text)
    if prose_formatting:
        text = _capitalize_sentences(text)
        text = _ensure_final_sentence_punctuation(text)
    return text


def _apply_make_that_corrections(text: str) -> str:
    match = _last_match(_MAKE_THAT_PATTERN, text)
    if match is None:
        return text

    before = text[: match.start()].rstrip(" ,")
    replacement = text[match.end() :].strip(" ,")
    if not replacement:
        return before

    before = re.sub(r"\s+\S+$", "", before).rstrip(" ,")
    return f"{before} {replacement}".strip()


def _apply_reset_corrections(text: str) -> str:
    matches = [match for pattern in _RESET_MARKERS for match in pattern.finditer(text)]
    if not matches:
        return text

    match = max(matches, key=lambda item: item.start())
    replacement = text[match.end() :].strip(" ,")
    return replacement or text[: match.start()].rstrip(" ,")


def _apply_spoken_punctuation(text: str) -> str:
    replacements = (
        (r"\bnew\s+paragraph\b", "\n\n"),
        (r"\bnew\s+line\b", "\n"),
        (r"\bnewline\b", "\n"),
        (r"\bquestion\s+mark\b", "?"),
        (r"\bfull\s+stop\b", "."),
        (r"\bperiod\b", "."),
        (r"\bcomma\b", ","),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalize_common_dictation_forms(text: str) -> str:
    minute_pattern = "|".join(sorted((re.escape(word) for word in _MINUTE_WORDS), key=len, reverse=True))
    hour_pattern = "|".join(_HOUR_WORDS)
    text = re.sub(
        rf"\b(?P<hour>{hour_pattern})\s+(?P<minute>{minute_pattern})\b",
        _replace_spoken_time,
        text,
        flags=re.IGNORECASE,
    )

    k_pattern = "|".join(_K_NUMBER_WORDS)
    return re.sub(
        rf"\b(?P<number>{k_pattern})\s+k\b",
        lambda match: f"{_K_NUMBER_WORDS[match.group('number').casefold()]}k",
        text,
        flags=re.IGNORECASE,
    )


def _replace_spoken_time(match: re.Match[str]) -> str:
    hour = _HOUR_WORDS[match.group("hour").casefold()]
    minute = _MINUTE_WORDS[match.group("minute").casefold()]
    return f"{hour}:{minute:02d}"


def _apply_vocabulary_hints(text: str, vocabulary_hints: list[str]) -> str:
    replacements: dict[str, str] = {}
    for hint in vocabulary_hints:
        hint = hint.strip()
        if not hint:
            continue
        if "->" in hint:
            original, corrected = (part.strip() for part in hint.split("->", 1))
            if original and corrected:
                replacements[original.casefold()] = corrected
            continue

        replacements[hint.casefold()] = hint
        spoken_form = _spoken_form_for_hint(hint)
        if spoken_form:
            replacements[spoken_form.casefold()] = hint

    for original, corrected in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(original)}(?!\w)", re.IGNORECASE)
        text = pattern.sub(corrected, text)
    return text


def _spoken_form_for_hint(hint: str) -> str:
    if " " in hint:
        return " ".join(hint.split())

    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", hint).split()
    if len(words) > 1:
        return " ".join(words)
    return hint


def _remove_fillers(text: str) -> str:
    text = _FILLER_PATTERN.sub("", text)
    return _LEADING_LIKE_FILLER_PATTERN.sub(lambda match: match.group(1), text)


def _tidy_spacing(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+([,?.!])", r"\1", text)
    text = re.sub(r",(?=\S)", ", ", text)
    text = re.sub(r"([?.!])(?=[^\s\n])", r"\1 ", text)
    return text.strip()


def _capitalize_sentences(text: str) -> str:
    return re.sub(
        r"(^|[.!?]\s+|\n+)([a-z])",
        lambda match: f"{match.group(1)}{match.group(2).upper()}",
        text,
    )


def _ensure_final_sentence_punctuation(text: str) -> str:
    if text and text[-1] not in ".!?":
        return f"{text}."
    return text


def _last_match(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    return matches[-1]
