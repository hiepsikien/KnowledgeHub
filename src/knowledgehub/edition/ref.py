from __future__ import annotations

from typing import Any

from .hitl_ops import apply_wrap_overrides
from .inline_spans import annotate_blocks
from .label_rules import label_lines_rules
from .lines import iter_lines, normalize_wiki_source
from .llm_blocks import relabel_uncertain_segments
from .llm_defaults import default_use_llm_relabel, ref_llm_model
from .merge_blocks import labels_to_blocks
from .reflow import unwrap_hard_wrap
from .serialize import build_edition_document, grotius_latin_to_blockquote
from .structure import group_dramatis_blocks, group_stanzas, merge_adjacent_blockquotes, merge_adjacent_headings, merge_adjacent_metadata


def build_read_edition(
    text: str,
    *,
    family: str = "plain",
    language: str = "en",
    use_llm: bool | None = None,
    work_id: str | None = None,
    wrap_overrides: dict[int, bool] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Structured REF/1 edition from stripped manuscript text."""
    llm_enabled = default_use_llm_relabel() if use_llm is None else use_llm
    lang = (language or "en").lower()[:2]
    apparatus: list[str] = []
    body = text
    unwrapped = False
    if family == "plain":
        body, wiki_apparatus = normalize_wiki_source(text)
        apparatus.extend(wiki_apparatus)
    elif family in {"scholastic", "archive_scan"} and lang not in {"ja", "zh", "ko"}:
        body, unwrapped = unwrap_hard_wrap(text, family=family, language=lang)

    if lang in {"ja", "zh", "ko"}:
        unwrapped_body, unwrapped = unwrap_hard_wrap(body, family=family, language=lang)
        lines = iter_lines(unwrapped_body)
        labels = label_lines_rules(lines, family=family, source_text=unwrapped_body)
        if wrap_overrides:
            apply_wrap_overrides(labels, wrap_overrides)
        blocks = labels_to_blocks(lines, labels)
        blocks, quotation_profile = annotate_blocks(blocks)
        edition = build_edition_document(
            blocks,
            language=language,
            source_family=family,
            quotation_profile=quotation_profile,
            apparatus_dropped=apparatus or None,
        )
        return edition, {
            "ref_mode": "rule_fallback",
            "line_count": len(lines),
            "block_count": len(blocks),
            "unwrapped": unwrapped,
            "llm_segments": [],
            "quotation_profile": quotation_profile,
            "apparatus_dropped": apparatus,
        }

    lines = iter_lines(body)
    labels = label_lines_rules(lines, family=family, source_text=body)
    labels, llm_events = relabel_uncertain_segments(
        lines, labels, enabled=llm_enabled, model=ref_llm_model()
    )
    if wrap_overrides:
        apply_wrap_overrides(labels, wrap_overrides)
    blocks = labels_to_blocks(lines, labels)
    if work_id and work_id.startswith("grotius--"):
        blocks = grotius_latin_to_blockquote(blocks)
    blocks = merge_adjacent_headings(blocks)
    blocks = merge_adjacent_metadata(blocks)
    blocks = merge_adjacent_blockquotes(blocks)
    blocks = group_dramatis_blocks(blocks)
    blocks = group_stanzas(blocks)
    blocks, quotation_profile = annotate_blocks(blocks)
    joined = any(label.join_next for label in labels) or unwrapped
    edition = build_edition_document(
        blocks,
        language=language,
        source_family=family,
        quotation_profile=quotation_profile,
        apparatus_dropped=apparatus or None,
    )
    return edition, {
        "ref_mode": "llm_hybrid" if llm_enabled else "rule",
        "line_count": len(lines),
        "block_count": len(blocks),
        "llm_segments": llm_events,
        "unwrapped": joined,
        "quotation_profile": quotation_profile,
        "apparatus_dropped": apparatus,
    }
