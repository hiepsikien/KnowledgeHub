from __future__ import annotations

from typing import Any

from .inline_spans import annotate_blocks
from .label_rules import label_lines_rules
from .lines import iter_lines
from .llm_blocks import relabel_uncertain_segments
from .merge_blocks import labels_to_blocks
from .reflow import unwrap_hard_wrap
from .serialize import build_edition_document, grotius_latin_to_blockquote


def build_read_edition(
    text: str,
    *,
    family: str = "plain",
    language: str = "en",
    use_llm: bool = False,
    work_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Structured REF/1 edition from stripped manuscript text."""
    lang = (language or "en").lower()[:2]
    if family in {"archive_scan"} or lang in {"ja", "zh", "ko"}:
        body, unwrapped = unwrap_hard_wrap(text, family=family, language=lang)
        lines = iter_lines(body)
        labels = label_lines_rules(lines, family=family)
        blocks = labels_to_blocks(lines, labels)
        blocks, quotation_profile = annotate_blocks(blocks)
        edition = build_edition_document(
            blocks,
            language=language,
            source_family=family,
            quotation_profile=quotation_profile,
        )
        return edition, {
            "ref_mode": "rule_fallback",
            "line_count": len(lines),
            "block_count": len(blocks),
            "unwrapped": unwrapped,
            "llm_segments": [],
            "quotation_profile": quotation_profile,
        }

    lines = iter_lines(text)
    labels = label_lines_rules(lines, family=family)
    labels, llm_events = relabel_uncertain_segments(lines, labels, enabled=use_llm)
    blocks = labels_to_blocks(lines, labels)
    if work_id and work_id.startswith("grotius--"):
        blocks = grotius_latin_to_blockquote(blocks)
    blocks, quotation_profile = annotate_blocks(blocks)
    joined = any(label.join_next for label in labels)
    edition = build_edition_document(
        blocks,
        language=language,
        source_family=family,
        quotation_profile=quotation_profile,
    )
    return edition, {
        "ref_mode": "llm_hybrid" if use_llm else "rule",
        "line_count": len(lines),
        "block_count": len(blocks),
        "llm_segments": llm_events,
        "unwrapped": joined,
        "quotation_profile": quotation_profile,
    }
