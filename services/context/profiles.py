from __future__ import annotations

from services.pipeline.models import AppCategory


_BROWSER_PROCESS_NEEDLES = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi")

_PROCESS_CATEGORIES: tuple[tuple[AppCategory, tuple[str, ...]], ...] = (
    ("code", ("code", "cursor", "devenv", "pycharm", "webstorm", "idea", "sublime", "notepad++")),
    ("email", ("outlook", "thunderbird", "hxoutlook", "mail")),
    ("work_chat", ("teams", "slack", "zoom", "webex")),
    ("personal_chat", ("whatsapp", "telegram", "signal", "messenger", "discord")),
    ("browser", _BROWSER_PROCESS_NEEDLES),
)

_URL_CATEGORIES: tuple[tuple[AppCategory, tuple[str, ...]], ...] = (
    ("email", ("mail.google.", "outlook.office.", "outlook.live.", "mail.yahoo.")),
    ("work_chat", ("app.slack.com", "teams.microsoft.com", "zoom.us", "meet.google.com")),
    ("personal_chat", ("web.whatsapp.com", "web.telegram.org", "messenger.com", "discord.com")),
)


def classify_app(
    process_name: str,
    window_title: str = "",
    browser_url: str | None = None,
) -> AppCategory:
    """Classify an active app into the context categories used by the pipeline."""
    normalized_process = _normalize(process_name)
    normalized_title = _normalize(window_title)
    normalized_url = _normalize(browser_url or "")

    if normalized_url:
        for category, needles in _URL_CATEGORIES:
            if any(needle in normalized_url for needle in needles):
                return category

    haystack = f"{normalized_process} {normalized_title}"
    for category, needles in _PROCESS_CATEGORIES:
        if any(needle in haystack for needle in needles):
            return category

    return "other"


def is_browser_process(process_name: str) -> bool:
    normalized_process = _normalize(process_name)
    return any(needle in normalized_process for needle in _BROWSER_PROCESS_NEEDLES)


def _normalize(value: str) -> str:
    return value.casefold().strip()
