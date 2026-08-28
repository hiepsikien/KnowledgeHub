from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..paths import corpus_root
from .paths import glossary_file, project_file, segments_dir, style_brief_file
from ..settings import resolve_models
from .project import load_project
from .providers import ProviderError, complete_chat, complete_prompt
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


def looks_cut_off(text: str) -> bool:
    """True when the text ends mid-word / mid-sentence instead of punctuation."""
    stripped = (text or "").rstrip()
    if len(stripped) < 20:
        return False
    return stripped[-1].isalnum()


def _require_complete(text: str, *, stage: str) -> str:
    if looks_cut_off(text):
        raise ProviderError(
            f"{stage} output looks truncated (ends mid-word). "
            "Raise max_tokens or re-run; do not save this draft."
        )
    return text


def _raw_for_mode(segment: dict[str, Any], mode: str) -> str:
    return str((segment.get("draft_raw") or {}).get(mode) or "").strip()


def _should_reuse_draft(segment: dict[str, Any], mode: str, *, force_draft: bool) -> bool:
    if force_draft:
        return False
    raw = _raw_for_mode(segment, mode)
    if not raw or looks_cut_off(raw):
        return False
    pipeline = segment.get("pipeline") if isinstance(segment.get("pipeline"), dict) else {}
    if pipeline.get("polish_pending"):
        return True
    return not str(segment.get("final") or "").strip()


def _checkpoint_draft(
    path: Path,
    segment: dict[str, Any],
    *,
    mode: str,
    draft_vi: str,
    draft_model: str,
    polish_model: str | None,
) -> None:
    segment.setdefault("draft_raw", {})[mode] = draft_vi
    pipeline = dict(segment.get("pipeline") or {}) if isinstance(segment.get("pipeline"), dict) else {}
    pipeline.update(
        {
            "mode": mode,
            "draft_model": draft_model,
            "polish_model": polish_model,
            "draft_completed_at": _now(),
            "polish_pending": True,
        }
    )
    pipeline.pop("completed_at", None)
    segment["pipeline"] = pipeline
    save_segment(path, segment)


def _finish_draft(
    path: Path,
    segment: dict[str, Any],
    *,
    mode: str,
    draft_vi: str,
    polished: str,
    draft_model: str,
    polish_model: str | None,
) -> None:
    prior = segment.get("pipeline") if isinstance(segment.get("pipeline"), dict) else {}
    segment.setdefault("drafts", {})[mode] = polished
    segment.setdefault("draft_raw", {})[mode] = draft_vi
    segment["final"] = polished
    segment["status"] = "draft_ready"
    segment["pipeline"] = {
        "mode": mode,
        "draft_model": draft_model,
        "polish_model": polish_model,
        "draft_completed_at": prior.get("draft_completed_at") or _now(),
        "completed_at": _now(),
        "polish_pending": False,
    }
    save_segment(path, segment)


def _run_draft(
    *,
    path: Path,
    segment: dict[str, Any],
    source_text: str,
    mode: str,
    glossary: dict[str, Any],
    style_brief: str,
    target_language: str,
    draft_model: str,
    polish_model: str,
    skip_polish: bool,
    force_draft: bool,
) -> tuple[str, str, bool]:
    from .jobs import raise_if_stopped, report_progress

    reused = _should_reuse_draft(segment, mode, force_draft=force_draft)
    if reused:
        report_progress("drafted", "Dùng lại bản nháp đã lưu")
        draft_vi = _raw_for_mode(segment, mode)
    else:
        messages = _build_draft_messages(
            source_text=source_text,
            mode=mode,
            glossary=glossary,
            style_brief=style_brief,
            target_language=target_language,
        )
        raise_if_stopped()
        report_progress("drafting", "Đang gọi DeepSeek nháp…")
        draft_vi = _require_complete(
            complete_chat(messages, model=draft_model, temperature=0.3),
            stage="DeepSeek draft",
        )
        raise_if_stopped()
        _checkpoint_draft(
            path,
            segment,
            mode=mode,
            draft_vi=draft_vi,
            draft_model=draft_model,
            polish_model=None if skip_polish else polish_model,
        )
        report_progress("drafted", "Đã lưu nháp")
    if skip_polish:
        return draft_vi, draft_vi, reused
    raise_if_stopped()
    report_progress("polishing", "Đang gọi Gemini chỉnh văn…")
    polished = _require_complete(
        complete_prompt(
            _polish_prompt(draft_vi=draft_vi, source_text=source_text, glossary=glossary),
            system="You polish Vietnamese literary translations. Never change meaning.",
            model=polish_model,
            temperature=0.35,
        ),
        stage="Gemini polish",
    )
    raise_if_stopped()
    return draft_vi, polished, reused


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

    models = resolve_models(project)
    draft_model = models["draft"]
    polish_model = models["polish"]
    target_language = project.get("target_language", "vi")

    draft_vi, polished, reused = _run_draft(
        path=sample_path,
        segment=segment,
        source_text=source_text,
        mode=mode,
        glossary=glossary,
        style_brief=style_brief,
        target_language=target_language,
        draft_model=draft_model,
        polish_model=polish_model,
        skip_polish=skip_polish,
        force_draft=False,
    )

    _finish_draft(
        sample_path,
        segment,
        mode=mode,
        draft_vi=draft_vi,
        polished=polished,
        draft_model=draft_model,
        polish_model=polish_model if not skip_polish else None,
    )

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
        "reused_draft": reused,
        "status": segment["status"],
    }


def draft_chapter(
    source_work_id: str,
    *,
    chapter: str,
    skip_polish: bool = False,
    force_draft: bool = False,
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
    models = resolve_models(project)
    draft_model = models["draft"]
    polish_model = models["polish"]
    target_language = project.get("target_language", "vi")

    draft_vi, polished, reused = _run_draft(
        path=path,
        segment=segment,
        source_text=source_text,
        mode=mode,
        glossary=glossary,
        style_brief=style_brief,
        target_language=target_language,
        draft_model=draft_model,
        polish_model=polish_model,
        skip_polish=skip_polish,
        force_draft=force_draft,
    )

    _finish_draft(
        path,
        segment,
        mode=mode,
        draft_vi=draft_vi,
        polished=polished,
        draft_model=draft_model,
        polish_model=polish_model if not skip_polish else None,
    )

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
        "reused_draft": reused,
        "status": segment["status"],
    }
