from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..paths import corpus_root
from .llm_json import parse_json_object
from .project import load_project
from .providers import ProviderError, deepseek_chat
from .segments_io import final_text, load_segment, save_segment


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _glossary_block(glossary: dict[str, Any]) -> str:
    lines: list[str] = []
    for term in glossary.get("terms", []):
        target = term.get("target")
        line = f"- {term.get('source')!r}"
        if target:
            line += f" → {target!r}"
        lines.append(line)
    return "\n".join(lines) if lines else "(none)"


def _qa_prompt(
    *,
    source_text: str,
    translation_vi: str,
    mode: str,
    glossary: dict[str, Any],
) -> list[dict[str, str]]:
    system = """You are a translation QA reviewer for Knowledge Hub.

Score the Vietnamese translation against the English source on a 1–10 scale (10 = excellent).
Be strict on legal-historical fidelity; generous on minor stylistic polish issues.

Return ONLY valid JSON with this schema:
{
  "scores": {
    "fidelity": number,
    "fluency": number,
    "terminology": number,
    "completeness": number,
    "overall": number
  },
  "summary_vi": "2-4 sentences in Vietnamese",
  "issues": [
    {
      "severity": "minor" | "major",
      "category": "fidelity" | "fluency" | "terminology" | "completeness" | "other",
      "note_vi": "short Vietnamese note",
      "source_excerpt": "optional short EN excerpt",
      "translation_excerpt": "optional short VI excerpt"
    }
  ]
}
"""
    user = f"""Translation mode: {mode}

Glossary (locked terms):
{_glossary_block(glossary)}

--- ENGLISH SOURCE ---
{source_text}
--- END SOURCE ---

--- VIETNAMESE TRANSLATION ---
{translation_vi}
--- END TRANSLATION ---
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def qa_segment(source_work_id: str, chapter: str) -> dict[str, Any]:
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    if not mode:
        raise ValueError("translation_mode not locked; run translate select-mode first")

    from .paths import glossary_file

    glossary = json.loads(glossary_file(source_work_id).read_text(encoding="utf-8"))
    path, segment = load_segment(source_work_id, chapter)
    source_text = str(segment.get("source_text") or "")
    translation_vi = final_text(segment, project)
    if not source_text.strip() or not translation_vi.strip():
        raise ValueError("Segment missing source_text or final translation")

    qa_model = (project.get("models") or {}).get("qa", "deepseek-reasoner")
    raw = deepseek_chat(
        _qa_prompt(
            source_text=source_text,
            translation_vi=translation_vi,
            mode=mode,
            glossary=glossary,
        ),
        model=qa_model,
        temperature=0.2,
    )
    report = parse_json_object(raw)
    scores = report.get("scores") or {}
    normalized: dict[str, float] = {}
    for key in ("fidelity", "fluency", "terminology", "completeness", "overall"):
        if key not in scores:
            raise ProviderError(f"QA response missing scores.{key}: {report!r}")
        try:
            value = float(scores[key])
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"QA scores.{key} is not a number: {scores[key]!r}") from exc
        if not 1 <= value <= 10:
            raise ProviderError(f"QA scores.{key} out of range 1–10: {value}")
        normalized[key] = int(value) if value == int(value) else value
    scores = normalized

    payload: dict[str, Any] = {
        "mode": mode,
        "model": qa_model,
        "scores": scores,
        "summary_vi": report.get("summary_vi", ""),
        "issues": report.get("issues") or [],
        "completed_at": _now(),
    }
    segment["qa"] = payload
    save_segment(path, segment)

    return {
        "work_id": source_work_id,
        "chapter": chapter,
        "segment": str(path.relative_to(corpus_root())),
        "scores": scores,
        "issue_count": len(payload["issues"]),
        "summary_vi": payload["summary_vi"],
    }
