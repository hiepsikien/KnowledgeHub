from __future__ import annotations

import re
from typing import Any

PG_START = re.compile(
    r"\*\*\*\s*START OF (THE |THIS )?PROJECT GUTENBERG EBOOK[^*\n]*\*\*\*",
    re.I,
)
PG_END = re.compile(
    r"\*\*\*\s*END OF (THE |THIS )?PROJECT GUTENBERG EBOOK",
    re.I,
)
AOZORA_HINT = re.compile(r"本文終わり|底本[：:]|【テキスト中に現れる記号について】")
SCHOLASTIC_HINT = re.compile(r"(?m)^(?:QUESTION\s+\d|Objection\s+\d:|_On the contrary)")

FAMILIES = ("gutenberg", "aozora", "archive_scan", "scholastic", "plain")


def edition_overrides(work: dict[str, Any] | None) -> dict[str, Any]:
    if not work:
        return {}
    return dict((work.get("read") or {}).get("edition") or {})


def detect_family(text: str, *, work: dict[str, Any] | None = None, language: str = "en") -> str:
    override = str(edition_overrides(work).get("family") or "").strip()
    if override in FAMILIES:
        return override
    head = text[:80000]
    scholastic_hits = len(SCHOLASTIC_HINT.findall(head))
    has_question = bool(re.search(r"(?m)^QUESTION\s+\d", head))
    if PG_START.search(text) or PG_END.search(text):
        if scholastic_hits >= 4 or has_question:
            return "scholastic"
        return "gutenberg"
    lang = (language or (work or {}).get("language") or "en").lower()
    if lang.startswith("ja") or AOZORA_HINT.search(text[:8000]):
        return "aozora"
    license_id = str((work or {}).get("license") or "")
    source_url = str((work or {}).get("source_url") or "")
    if "archive" in license_id or "archive.org" in source_url:
        return "archive_scan"
    if scholastic_hits >= 4 or has_question:
        return "scholastic"
    return "plain"
