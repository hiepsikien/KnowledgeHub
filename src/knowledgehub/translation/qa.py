from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..paths import corpus_root
from ..settings import resolve_models
from .llm_json import parse_json_object
from .paths import annotations_file, glossary_file
from .project import load_project
from .providers import ProviderError, complete_chat
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


def _chapter_annotations(source_work_id: str, chapter: str) -> list[dict[str, Any]]:
    path = annotations_file(source_work_id)
    if not path.is_file():
        return []
    store = json.loads(path.read_text(encoding="utf-8"))
    ch = str(chapter).strip().upper()
    return [
        a
        for a in (store.get("annotations") or [])
        if str(a.get("chapter") or "").upper() == ch
    ]


def _annotations_block(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        marker = item.get("marker") or ""
        lines.append(
            f"- id={item.get('id')} kind={item.get('kind') or 'note'} "
            f"marker={marker!r} title={item.get('title_vi')!r} "
            f"anchor={item.get('anchor_text')!r}\n"
            f"  body: {item.get('body_vi') or ''}"
        )
    return "\n".join(lines)


def _qa_prompt(
    *,
    source_text: str,
    translation_vi: str,
    mode: str,
    glossary: dict[str, Any],
    annotations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    annotation_schema = ""
    annotation_score = ""
    if annotations:
        annotation_score = '    "annotations": number,\n'
        annotation_schema = """
Also review existing Vietnamese reader annotations (footnotes, glossary, context).
Be strict on invented citations, wrong identifications, and notes that contradict the source or translation.
For those issues set annotation_id to the note id and translation_excerpt to the current body (or title) snippet to rewrite.
"""
    system = f"""You are a translation QA reviewer for Knowledge Hub.

Score the Vietnamese translation against the English source on a 1–10 scale (10 = excellent).
Be strict on legal-historical fidelity; generous on minor stylistic polish issues.
{annotation_schema}
Return ONLY valid JSON with this schema:
{{
  "scores": {{
    "fidelity": number,
    "fluency": number,
    "terminology": number,
    "completeness": number,
{annotation_score}    "overall": number
  }},
  "summary_vi": "2-4 sentences in Vietnamese",
  "issues": [
    {{
      "severity": "minor" | "major",
      "category": "fidelity" | "fluency" | "terminology" | "completeness" | "annotation" | "other",
      "note_vi": "short Vietnamese note",
      "source_excerpt": "optional short EN excerpt",
      "translation_excerpt": "optional short VI excerpt",
      "annotation_id": "required when the issue is about a reader annotation"
    }}
  ]
}}
"""
    ann_section = ""
    if annotations:
        ann_section = f"""
--- VIETNAMESE ANNOTATIONS ---
{_annotations_block(annotations)}
--- END ANNOTATIONS ---
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
{ann_section}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize_scores(scores: dict[str, Any], *, require_annotations: bool = False) -> dict[str, float]:
    keys = ["fidelity", "fluency", "terminology", "completeness", "overall"]
    normalized: dict[str, float] = {}
    for key in keys:
        if key not in scores:
            raise ProviderError(f"QA response missing scores.{key}: {scores!r}")
        try:
            value = float(scores[key])
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"QA scores.{key} is not a number: {scores[key]!r}") from exc
        if not 1 <= value <= 10:
            raise ProviderError(f"QA scores.{key} out of range 1–10: {value}")
        normalized[key] = int(value) if value == int(value) else value
    extra = scores.get("annotations")
    if extra is not None or require_annotations:
        if extra is None:
            raise ProviderError(f"QA response missing scores.annotations: {scores!r}")
        try:
            value = float(extra)
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"QA scores.annotations is not a number: {extra!r}") from exc
        if not 1 <= value <= 10:
            raise ProviderError(f"QA scores.annotations out of range 1–10: {value}")
        normalized["annotations"] = int(value) if value == int(value) else value
    return normalized


def _normalize_issues(raw: Any, valid_ann_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    issues: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        issue: dict[str, Any] = {
            "severity": str(item.get("severity") or "minor"),
            "category": str(item.get("category") or "other"),
            "note_vi": str(item.get("note_vi") or ""),
        }
        if item.get("source_excerpt"):
            issue["source_excerpt"] = str(item["source_excerpt"])
        if item.get("translation_excerpt"):
            issue["translation_excerpt"] = str(item["translation_excerpt"])
        aid = str(item.get("annotation_id") or "").strip()
        if aid:
            issue["annotation_id"] = aid
            if aid in valid_ann_ids:
                issue["target"] = "annotation"
        issues.append(issue)
    return issues


def qa_segment(source_work_id: str, chapter: str) -> dict[str, Any]:
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    if not mode:
        raise ValueError("translation_mode not locked; run translate select-mode first")

    glossary = json.loads(glossary_file(source_work_id).read_text(encoding="utf-8"))
    path, segment = load_segment(source_work_id, chapter)
    source_text = str(segment.get("source_text") or "")
    translation_vi = final_text(segment, project)
    if not source_text.strip() or not translation_vi.strip():
        raise ValueError("Segment missing source_text or final translation")
    annotations = _chapter_annotations(source_work_id, chapter)
    valid_ann_ids = {str(item.get("id") or "") for item in annotations if item.get("id")}

    qa_model = resolve_models(project)["qa"]
    from .jobs import raise_if_stopped, report_progress

    raise_if_stopped()
    report_progress("scoring", "Đang gọi DeepSeek QA…")
    raw = complete_chat(
        _qa_prompt(
            source_text=source_text,
            translation_vi=translation_vi,
            mode=mode,
            glossary=glossary,
            annotations=annotations,
        ),
        model=qa_model,
        temperature=0.2,
    )
    raise_if_stopped()
    report = parse_json_object(raw)
    scores = _normalize_scores(report.get("scores") or {}, require_annotations=False)
    issues = _normalize_issues(report.get("issues") or [], valid_ann_ids)

    payload: dict[str, Any] = {
        "mode": mode,
        "model": qa_model,
        "scores": scores,
        "summary_vi": report.get("summary_vi", ""),
        "issues": issues,
        "completed_at": _now(),
        "open_issue_count": len(issues),
        "annotations_reviewed": len(annotations),
    }
    segment["qa"] = payload
    save_segment(path, segment)

    return {
        "work_id": source_work_id,
        "chapter": chapter,
        "segment": str(path.relative_to(corpus_root())),
        "scores": scores,
        "issue_count": len(issues),
        "annotation_issue_count": sum(1 for issue in issues if issue.get("annotation_id")),
        "annotations_reviewed": len(annotations),
        "summary_vi": payload["summary_vi"],
    }


def _stamp_approved(issue: dict[str, Any], when: str) -> None:
    issue["approved"] = True
    issue["approved_at"] = when


def _clear_approved(issue: dict[str, Any]) -> None:
    issue.pop("approved", None)
    issue.pop("approved_at", None)


_QUOTES = frozenset("\"'‘’“”‹›«»‚‛„‟")
_TRAIL = frozenset(",.;:…")


def _fold_quotes(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        if ch in _QUOTES:
            continue
        folded.append(ch)
        index_map.append(i)
    return "".join(folded), index_map


def _expand_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and text[start - 1] in _QUOTES:
        start -= 1
    while end < len(text):
        ch = text[end]
        if ch in _QUOTES:
            end += 1
            continue
        if ch in _TRAIL and end + 1 < len(text) and text[end + 1] in _QUOTES:
            end += 1
            continue
        break
    return start, end


def _locate_excerpt(text: str, excerpt: str) -> tuple[int, int] | None:
    needle = (excerpt or "").strip()
    if not needle:
        return None
    exact = text.find(needle)
    if exact >= 0:
        return exact, exact + len(needle)
    folded_text, tmap = _fold_quotes(text)
    folded_needle, _ = _fold_quotes(needle)
    if len(folded_needle) < 12:
        return None
    pos = folded_text.find(folded_needle)
    if pos < 0:
        return None
    start = tmap[pos]
    end = tmap[pos + len(folded_needle) - 1] + 1
    return _expand_span(text, start, end)


def _replace_excerpt(
    text: str, excerpt: str, replacement: str, *, where: str = "bản dịch"
) -> tuple[str, int]:
    needle = (excerpt or "").strip()
    new = (replacement or "").strip()
    if not needle or not new or needle == new:
        return text, 0
    span = _locate_excerpt(text, needle)
    if span is None:
        raise ValueError(f"Không thấy đoạn VI trong {where}: {needle[:120]}")
    start, end = span
    return text[:start] + new + text[end:], 1


def _patch_annotation_text(
    source_work_id: str,
    annotation_id: str,
    excerpt: str,
    replacement: str,
) -> int:
    needle = (excerpt or "").strip()
    new = (replacement or "").strip()
    if not needle or not new or needle == new:
        return 0
    path = annotations_file(source_work_id)
    if not path.is_file():
        raise ValueError(f"Không thấy chú thích: {annotation_id}")
    store = json.loads(path.read_text(encoding="utf-8"))
    items = list(store.get("annotations") or [])
    target = next((item for item in items if str(item.get("id") or "") == annotation_id), None)
    if target is None:
        raise ValueError(f"Không thấy chú thích: {annotation_id}")
    for field in ("body_vi", "title_vi"):
        text = str(target.get(field) or "")
        try:
            updated, count = _replace_excerpt(text, excerpt, replacement, where="chú thích")
        except ValueError:
            continue
        if count:
            target[field] = updated
            store["annotations"] = items
            store["updated_at"] = _now()
            path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 1
    raise ValueError(f"Không thấy đoạn VI trong chú thích: {needle[:120]}")


def _apply_issue_fix(
    segment: dict[str, Any],
    issue: dict[str, Any],
    replacement: str | None,
    *,
    mode: str | None,
    source_work_id: str,
) -> int:
    if replacement is None:
        return 0
    ann_id = str(issue.get("annotation_id") or "").strip()
    if ann_id:
        count = _patch_annotation_text(
            source_work_id,
            ann_id,
            str(issue.get("translation_excerpt") or ""),
            replacement,
        )
        if count:
            issue["applied_replacement"] = str(replacement).strip()
        return count
    excerpt = str(issue.get("translation_excerpt") or "")
    final = str(segment.get("final") or "")
    updated, count = _replace_excerpt(final, excerpt, replacement)
    if count:
        segment["final"] = updated
        drafts = segment.setdefault("drafts", {})
        if mode and drafts.get(mode) == final:
            drafts[mode] = updated
        issue["applied_replacement"] = str(replacement).strip()
    return count


def approve_qa_issues(
    source_work_id: str,
    chapter: str,
    *,
    index: int | None = None,
    replacement: str | None = None,
    replacements: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Approve QA remarks and optionally rewrite ``final`` from the VI excerpt."""
    path, segment = load_segment(source_work_id, chapter)
    qa = segment.get("qa")
    issues = list((qa or {}).get("issues") or [])
    if not qa or not issues:
        raise ValueError("No QA issues to approve")
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    when = _now()
    applied = 0
    fix_map = dict(replacements or {})
    if index is None:
        for i, issue in enumerate(issues):
            if issue.get("approved"):
                continue
            applied += _apply_issue_fix(
                segment, issue, fix_map.get(i), mode=mode, source_work_id=source_work_id
            )
            _stamp_approved(issue, when)
    else:
        if index < 0 or index >= len(issues):
            raise ValueError(f"Issue index out of range: {index}")
        issue = issues[index]
        text = replacement if replacement is not None else fix_map.get(index)
        applied += _apply_issue_fix(segment, issue, text, mode=mode, source_work_id=source_work_id)
        _stamp_approved(issue, when)
    qa["issues"] = issues
    open_count = sum(1 for issue in issues if not issue.get("approved"))
    qa["open_issue_count"] = open_count
    qa["approved_at"] = when if open_count == 0 else qa.get("approved_at")
    segment["qa"] = qa
    save_segment(path, segment)
    return {
        "work_id": source_work_id,
        "chapter": chapter,
        "issue_count": len(issues),
        "open_issue_count": open_count,
        "applied_count": applied,
        "issues": issues,
    }


def _revert_issue_fix(
    segment: dict[str, Any],
    issue: dict[str, Any],
    *,
    mode: str | None,
    source_work_id: str,
) -> int:
    applied = str(issue.get("applied_replacement") or "").strip()
    original = str(issue.get("translation_excerpt") or "").strip()
    if not applied or not original or applied == original:
        issue.pop("applied_replacement", None)
        return 0
    ann_id = str(issue.get("annotation_id") or "").strip()
    if ann_id:
        try:
            count = _patch_annotation_text(source_work_id, ann_id, applied, original)
        except ValueError:
            count = 0
        issue.pop("applied_replacement", None)
        return count
    final = str(segment.get("final") or "")
    if applied not in final:
        issue.pop("applied_replacement", None)
        return 0
    updated = final.replace(applied, original, 1)
    segment["final"] = updated
    drafts = segment.setdefault("drafts", {})
    if mode and drafts.get(mode) == final:
        drafts[mode] = updated
    issue.pop("applied_replacement", None)
    return 1


def reopen_qa_issues(
    source_work_id: str,
    chapter: str,
    *,
    index: int | None = None,
) -> dict[str, Any]:
    """Undo curator approval. Reverts ``final`` only if a replacement was applied."""
    path, segment = load_segment(source_work_id, chapter)
    qa = segment.get("qa")
    issues = list((qa or {}).get("issues") or [])
    if not qa or not issues:
        raise ValueError("No QA issues to reopen")
    project = load_project(source_work_id)
    mode = project.get("translation_mode")
    reverted = 0
    if index is None:
        for issue in reversed(issues):
            if not issue.get("approved"):
                continue
            reverted += _revert_issue_fix(segment, issue, mode=mode, source_work_id=source_work_id)
            _clear_approved(issue)
    else:
        if index < 0 or index >= len(issues):
            raise ValueError(f"Issue index out of range: {index}")
        issue = issues[index]
        if not issue.get("approved"):
            raise ValueError("Issue is not approved")
        reverted += _revert_issue_fix(segment, issue, mode=mode, source_work_id=source_work_id)
        _clear_approved(issue)
    qa["issues"] = issues
    open_count = sum(1 for issue in issues if not issue.get("approved"))
    qa["open_issue_count"] = open_count
    if open_count:
        qa.pop("approved_at", None)
    segment["qa"] = qa
    save_segment(path, segment)
    return {
        "work_id": source_work_id,
        "chapter": chapter,
        "issue_count": len(issues),
        "open_issue_count": open_count,
        "reverted_count": reverted,
        "issues": issues,
    }
