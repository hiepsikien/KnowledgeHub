from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..paths import corpus_root
from .llm_json import parse_json_object
from .paths import annotations_file, glossary_file
from .project import load_project
from .providers import DEFAULT_GEMINI_MODEL, ProviderError, gemini_generate
from .segments_io import final_text, load_segment


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _annotate_prompt(
    *,
    source_text: str,
    translation_vi: str,
    glossary: dict[str, Any],
    chapter: str,
    segment_id: str,
) -> str:
    glossary_json = json.dumps(glossary, ensure_ascii=False, indent=2)
    return f"""You generate reader-facing annotations for a Vietnamese translation of Grotius (1609 legal treatise).

Chapter: {chapter}
Segment id: {segment_id}

Create annotations for:
1. Every inline footnote marker [1], [2], ... in the translation — explain the reference for Vietnamese readers.
2. Locked glossary terms when they first appear.
3. At most 3 optional "context" notes for dense legal phrases (kind=context).

Rules:
- Write body_vi in clear Vietnamese, 1–3 sentences each.
- Do NOT invent citations; use well-known classical/legal references only.
- Keep marker exactly like "[1]" when kind is footnote.
- anchor_text: a short phrase from the Vietnamese text near the marker (for tap-to-expand UI).

Return ONLY JSON:
{{
  "annotations": [
    {{
      "id": "{segment_id}--fn-1",
      "segment_id": "{segment_id}",
      "chapter": "{chapter}",
      "marker": "[1]",
      "kind": "footnote",
      "anchor_text": "Pliny",
      "title_vi": "Chú thích [1]",
      "body_vi": "..."
    }}
  ]
}}

Glossary:
{glossary_json}

--- ENGLISH SOURCE ---
{source_text}
--- END SOURCE ---

--- VIETNAMESE TRANSLATION ---
{translation_vi}
--- END TRANSLATION ---
"""


def annotate_segment(source_work_id: str, chapter: str) -> dict[str, Any]:
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    if not mode:
        raise ValueError("translation_mode not locked; run translate select-mode first")

    glossary = json.loads(glossary_file(source_work_id).read_text(encoding="utf-8"))
    path, segment = load_segment(source_work_id, chapter)
    segment_id = str(segment.get("id") or f"{source_work_id}--ch{chapter.lower()}")
    source_text = str(segment.get("source_text") or "")
    translation_vi = final_text(segment, project)

    ann_model = (project.get("models") or {}).get("annotations", DEFAULT_GEMINI_MODEL)
    raw = gemini_generate(
        _annotate_prompt(
            source_text=source_text,
            translation_vi=translation_vi,
            glossary=glossary,
            chapter=str(chapter),
            segment_id=segment_id,
        ),
        system="You produce structured JSON annotations for literary translations. Never wrap in markdown.",
        model=ann_model,
        temperature=0.35,
    )
    parsed = parse_json_object(raw)
    new_items = parsed.get("annotations")
    if not isinstance(new_items, list):
        raise ProviderError(f"Annotations response missing list: {parsed!r}")

    ann_path = annotations_file(source_work_id)
    store = json.loads(ann_path.read_text(encoding="utf-8")) if ann_path.is_file() else {"annotations": []}
    existing = store.get("annotations") or []
    by_id = {str(a.get("id")): a for a in existing if a.get("id")}
    for item in new_items:
        if not item.get("id"):
            raise ProviderError(f"Annotation missing id: {item!r}")
        item["chapter"] = str(chapter)
        item["segment_id"] = segment_id
        item["generated_at"] = _now()
        by_id[str(item["id"])] = item

    merged = sorted(by_id.values(), key=lambda a: (str(a.get("chapter", "")), str(a.get("marker", "")), str(a.get("id", ""))))
    store["annotations"] = merged
    store["updated_at"] = _now()
    ann_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    segment["annotations_generated_at"] = _now()
    from .segments_io import save_segment

    save_segment(path, segment)

    return {
        "work_id": source_work_id,
        "chapter": chapter,
        "annotations_file": str(ann_path.relative_to(corpus_root())),
        "added_or_updated": len(new_items),
        "total": len(merged),
    }
