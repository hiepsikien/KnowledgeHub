from __future__ import annotations

from typing import Any

from .edition.pipeline import build_edition
from .edition.reflow import (
    is_all_caps_heading,
    is_hard_structural,
    is_soft_structural,
    unwrap_hard_wrap,
)

# Re-export helpers tests and older call sites may still import.
__all__ = [
    "is_all_caps_heading",
    "is_hard_structural",
    "is_soft_structural",
    "normalize_manuscript",
    "unwrap_hard_wrap",
]


def normalize_manuscript(
    text: str,
    *,
    language: str = "en",
    work: dict[str, Any] | None = None,
    use_llm: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Edition text for consumers. Does not rewrite the source file."""
    return build_edition(text, language=language, work=work, use_llm=use_llm)
