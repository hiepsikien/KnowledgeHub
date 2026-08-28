from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from .paths import glossary_file, project_file, segments_dir, style_brief_file
from .project import load_project
from .providers import DEFAULT_GEMINI_MODEL, deepseek_chat, gemini_generate
from .segments_io import load_segment, save_segment

MODE_INSTRUCTIONS = {
    "tight": (
        "Translate as literally as possible while remaining grammatical Vietnamese. "
        "Preserve sentence order where feasible. Keep legal terms precise."
    ),
    "normal": (
        "Translate for clarity and natural Vietnamese while faithfully preserving "
        "the author's argument, tone, and legal precision. Balance readability with fidelity."
    ),
    "loose": (
        "Prioritize fluent, accessible Vietnamese. You may restructure sentences for clarity "
        "but must not omit, invent, or distort arguments."
    ),
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _glossary_block(glossary: dict[str, Any]) -> str:
    lines: list[str] = []
    for term in glossary.get("terms", []):
        target = term.get("target")
        lock = "LOCKED" if term.get("locked") else "preferred"
        line = f"- {term.get('source')!r}"
        if target:
            line += f" → {target!r} ({lock})"
        else:
            line += f" ({lock}; choose consistent Vietnamese)"
        if term.get("notes"):
            line += f" — {term['notes']}"
        lines.append(line)
    return "\n".join(lines) if lines else "(none yet)"


def _build_draft_messages(
    *,
    source_text: str,
    mode: str,
    glossary: dict[str, Any],
    style_brief: str,
    target_language: str,
) -> list[dict[str, str]]:
    mode_line = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["normal"])
    system = f"""You are a scholarly literary translator for Knowledge Hub.

Target language: {target_language}
Translation mode: {mode}
{mode_line}

Rules:
- Do NOT add facts, examples, or explanations not present in the source.
- Do NOT omit substantive content from the source.
- Preserve paragraph breaks and headings (e.g. CHAPTER I).
- Keep inline footnote markers like [1], [2] unchanged.
- For poetry or quoted lines, translate faithfully; keep quotation marks.
- Use glossary terms consistently when provided.

Style brief:
{style_brief.strip()}

Glossary:
{_glossary_block(glossary)}
"""
    user = f"""Translate the following English source text to Vietnamese.

Return ONLY the Vietnamese translation — no commentary, no preface.

--- SOURCE ---
{source_text}
--- END SOURCE ---
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _polish_prompt(*, draft_vi: str, source_text: str, glossary: dict[str, Any]) -> str:
    return f"""You are polishing a Vietnamese translation of a 1609 legal treatise.

Improve fluency and rhythm in Vietnamese WITHOUT changing meaning.
Do NOT add or remove content. Keep footnote markers [1], [2], etc.
Keep glossary terms consistent.

Glossary:
{_glossary_block(glossary)}

--- ENGLISH SOURCE (reference only) ---
{source_text[:4000]}
{"..." if len(source_text) > 4000 else ""}
--- END SOURCE ---

--- VIETNAMESE DRAFT ---
{draft_vi}
--- END DRAFT ---

Return ONLY the polished Vietnamese text.
"""


def _run_draft(
    *,
    source_text: str,
    mode: str,
    glossary: dict[str, Any],
    style_brief: str,
    target_language: str,
    draft_model: str,
    polish_model: str,
    skip_polish: bool,
) -> tuple[str, str]:
    messages = _build_draft_messages(
        source_text=source_text,
        mode=mode,
        glossary=glossary,
        style_brief=style_brief,
        target_language=target_language,
    )
    draft_vi = deepseek_chat(messages, model=draft_model, temperature=0.3)
    polished = draft_vi
    if not skip_polish:
        polished = gemini_generate(
            _polish_prompt(draft_vi=draft_vi, source_text=source_text, glossary=glossary),
            system="You polish Vietnamese literary translations. Never change meaning.",
            model=polish_model,
            temperature=0.35,
        )
    return draft_vi, polished


def draft_sample(
    source_work_id: str,
    *,
    mode: str = "normal",
    skip_polish: bool = False,
) -> dict[str, Any]:
    project = load_project(source_work_id)
    sample_rel = project.get("sample_segment", {}).get("file")
    if not sample_rel:
        raise ValueError("Project has no sample_segment")
    sample_path = segments_dir(source_work_id) / Path(sample_rel).name
    if not sample_path.is_file():
        raise FileNotFoundError(f"Sample segment not found: {sample_path}")

    segment = json.loads(sample_path.read_text(encoding="utf-8"))
    glossary = json.loads(glossary_file(source_work_id).read_text(encoding="utf-8"))
    style_brief = style_brief_file(source_work_id).read_text(encoding="utf-8")
    source_text = str(segment.get("source_text") or "")
    if not source_text.strip():
        raise ValueError("Sample segment has empty source_text")

    models = project.get("models") or {}
    draft_model = models.get("draft", "deepseek-chat")
    polish_model = models.get("polish", DEFAULT_GEMINI_MODEL)
    target_language = project.get("target_language", "vi")

    draft_vi, polished = _run_draft(
        source_text=source_text,
        mode=mode,
        glossary=glossary,
        style_brief=style_brief,
        target_language=target_language,
        draft_model=draft_model,
        polish_model=polish_model,
        skip_polish=skip_polish,
    )

    segment.setdefault("drafts", {})[mode] = polished
    segment.setdefault("draft_raw", {})[mode] = draft_vi
    segment["final"] = polished
    segment["status"] = "draft_ready"
    segment["pipeline"] = {
        "mode": mode,
        "draft_model": draft_model,
        "polish_model": polish_model if not skip_polish else None,
        "completed_at": _now(),
    }
    sample_path.write_text(json.dumps(segment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project["status"] = "sample_ready"
    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "work_id": source_work_id,
        "mode": mode,
        "sample": str(sample_path.relative_to(corpus_root())),
        "draft_chars": len(draft_vi),
        "final_chars": len(polished),
        "status": segment["status"],
    }


def draft_chapter(
    source_work_id: str,
    *,
    chapter: str,
    skip_polish: bool = False,
) -> dict[str, Any]:
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    if not mode:
        raise ValueError("translation_mode not locked; run translate select-mode first")

    path, segment = load_segment(source_work_id, chapter)
    source_text = str(segment.get("source_text") or "")
    if not source_text.strip():
        raise ValueError("Segment has empty source_text")

    glossary = json.loads(glossary_file(source_work_id).read_text(encoding="utf-8"))
    style_brief = style_brief_file(source_work_id).read_text(encoding="utf-8")
    models = project.get("models") or {}
    draft_model = models.get("draft", "deepseek-chat")
    polish_model = models.get("polish", DEFAULT_GEMINI_MODEL)
    target_language = project.get("target_language", "vi")

    draft_vi, polished = _run_draft(
        source_text=source_text,
        mode=mode,
        glossary=glossary,
        style_brief=style_brief,
        target_language=target_language,
        draft_model=draft_model,
        polish_model=polish_model,
        skip_polish=skip_polish,
    )

    segment.setdefault("drafts", {})[mode] = polished
    segment.setdefault("draft_raw", {})[mode] = draft_vi
    segment["final"] = polished
    segment["status"] = "draft_ready"
    segment["pipeline"] = {
        "mode": mode,
        "draft_model": draft_model,
        "polish_model": polish_model if not skip_polish else None,
        "completed_at": _now(),
    }
    save_segment(path, segment)

    project["updated_at"] = _now()
    project_file(source_work_id).write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "work_id": source_work_id,
        "chapter": str(segment.get("chapter") or chapter),
        "mode": mode,
        "segment": str(path.relative_to(corpus_root())),
        "draft_chars": len(draft_vi),
        "final_chars": len(polished),
        "status": segment["status"],
    }
