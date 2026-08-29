"""LLM + rule QA for REF/1 parse output."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

DEFAULT_REF_QA_MODEL = "gemini-3.1-flash-lite"
from ..translation.llm_json import parse_json_object
from ..translation.providers import ProviderError, complete_chat
from .fidelity import run_fidelity_checks
from .ref_parser import parse_manuscript_to_ref


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _blocks_digest(edition: dict[str, Any], *, max_blocks: int = 40, preview: int = 220) -> str:
    rows: list[str] = []
    for index, block in enumerate((edition.get("blocks") or [])[:max_blocks]):
        kind = block.get("type")
        level = block.get("level")
        text = str(block.get("text") or "")
        preview_text = text[:preview].replace("\n", " ")
        if len(text) > preview:
            preview_text += "…"
        spans = block.get("spans") or []
        span_summary = ", ".join(f"{s.get('style')}:{s.get('text','')!r}" for s in spans[:6])
        extra = f" level={level}" if kind == "heading" else ""
        span_part = f" spans=[{span_summary}]" if span_summary else ""
        rows.append(f"{index}: {kind}{extra} char_len={len(text)} | {preview_text!r}{span_part}")
    total = len(edition.get("blocks") or [])
    if total > max_blocks:
        rows.append(f"... ({total - max_blocks} more blocks)")
    return "\n".join(rows)


def _llm_qa_prompt(
    *,
    source_text: str,
    edition: dict[str, Any],
    fidelity: dict[str, Any],
    language: str,
) -> list[dict[str, str]]:
    profile = edition.get("quotation_profile") or {}
    failed_rules = [c for c in fidelity.get("checks") or [] if not c.get("passed")]
    system = """You are a REF/1 edition parse QA reviewer for Knowledge Hub.

The parser must NEVER rewrite prose — only join wrapped lines (whitespace / hyphen de-join) and label blocks/spans.

Review the SOURCE excerpt against the PARSED BLOCKS digest. Be strict on:
- rewritten or missing words (text preservation)
- bad paragraph joins (mid-sentence breaks that should merge, or merged headings)
- wrong heading vs paragraph labels
- inline span styles that look wrong (footnote vs bracket_note, paren_cite vs paren_aside)

REF/1 policies (do NOT penalize these as errors):
- Project Gutenberg table-of-contents runs (3+ consecutive CHAPTER/BOOK/SECT list lines) grouped into one `metadata` block — this is CORRECT, not a missing heading split.
- Wikisource / wiki apparatus (nav lines, project links, edition IDs) listed in `apparatus_dropped[]` or omitted from blocks — intentional, not text loss.
- A single real chapter heading followed by body prose should remain `heading` + `paragraph`; only long TOC lists become `metadata`.

IMPORTANT: Block digest lines end with "…" when truncated for display only. Each block lists char_len= — if char_len > preview length, the block is NOT truncated in the edition. Only flag missing text if words from SOURCE are absent from the full edition (not just the preview).

Return ONLY valid JSON:
{
  "scores": {
    "text_preservation": number,
    "block_structure": number,
    "join_quality": number,
    "inline_spans": number,
    "overall": number
  },
  "summary_vi": "2-4 câu tiếng Việt",
  "issues": [
    {
      "severity": "minor" | "major" | "critical",
      "category": "text_preservation" | "block_structure" | "join_quality" | "inline_spans" | "other",
      "note_vi": "mô tả ngắn",
      "block_index": number | null,
      "source_excerpt": "optional",
      "edition_excerpt": "optional"
    }
  ],
  "verdict": "pass" | "warn" | "fail"
}

Scores are 1–10 (10 = excellent). verdict=fail if any critical issue or text_preservation < 7."""
    apparatus = edition.get("apparatus_dropped") or []
    user = f"""Language: {language}
Content kind: {edition.get("content_kind")}
Source family: {edition.get("source_family")}
Block count: {len(edition.get("blocks") or [])}
Quotation profile: {json.dumps(profile, ensure_ascii=False)}
Apparatus dropped (intentional, not text loss): {json.dumps(apparatus[:12], ensure_ascii=False)}{"…" if len(apparatus) > 12 else ""}

Rule checks already run:
{json.dumps(failed_rules, ensure_ascii=False, indent=2) if failed_rules else "(all passed)"}

--- SOURCE (excerpt) ---
{source_text[:4000]}
--- END SOURCE ---

--- PARSED BLOCKS (digest) ---
{_blocks_digest(edition, max_blocks=20, preview=120)}

--- READING MARKDOWN (excerpt) ---
{str(edition.get("reading_markdown") or "")[:4000]}
--- END ---"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize_scores(scores: dict[str, Any]) -> dict[str, float]:
    keys = ["text_preservation", "block_structure", "join_quality", "inline_spans", "overall"]
    out: dict[str, float] = {}
    for key in keys:
        if key not in scores:
            raise ProviderError(f"REF QA missing scores.{key}: {scores!r}")
        value = float(scores[key])
        if not 1 <= value <= 10:
            raise ProviderError(f"REF QA scores.{key} out of range: {value}")
        out[key] = int(value) if value == int(value) else value
    return out


def _normalize_issues(raw: Any) -> list[dict[str, Any]]:
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
        block_index = item.get("block_index")
        if isinstance(block_index, int):
            issue["block_index"] = block_index
        if item.get("source_excerpt"):
            issue["source_excerpt"] = str(item["source_excerpt"])
        if item.get("edition_excerpt"):
            issue["edition_excerpt"] = str(item["edition_excerpt"])
        issues.append(issue)
    return issues


def qa_read_edition(
    source_text: str,
    edition: dict[str, Any],
    *,
    language: str = "en",
    use_llm: bool = True,
    model: str | None = None,
    min_overall: float = 7.0,
) -> dict[str, Any]:
    """Rule checks always; LLM review when use_llm=True and API key set."""
    fidelity = run_fidelity_checks(source_text, edition)
    payload: dict[str, Any] = {
        "completed_at": _now(),
        "fidelity": fidelity,
        "llm": None,
        "passed": fidelity["passed"],
    }

    if not use_llm:
        payload["summary_vi"] = (
            "Chỉ chạy rule checks (không gọi LLM)."
            if fidelity["passed"]
            else "Rule checks thất bại — cần sửa parser trước khi QA LLM."
        )
        return payload

    qa_model = model or DEFAULT_REF_QA_MODEL
    try:
        raw = complete_chat(
            _llm_qa_prompt(
                source_text=source_text,
                edition=edition,
                fidelity=fidelity,
                language=language,
            ),
            model=qa_model,
            temperature=0.1,
            max_tokens=2048,
        )
        report = parse_json_object(raw)
        scores = _normalize_scores(report.get("scores") or {})
        issues = _normalize_issues(report.get("issues") or [])
        verdict = str(report.get("verdict") or "warn").lower()
        if verdict not in {"pass", "warn", "fail"}:
            verdict = "warn"
        llm_ok = verdict != "fail" and scores["overall"] >= min_overall and fidelity["passed"]
        payload["llm"] = {
            "model": qa_model,
            "scores": scores,
            "summary_vi": str(report.get("summary_vi") or ""),
            "issues": issues,
            "verdict": verdict,
            "open_issue_count": len(issues),
        }
        payload["passed"] = llm_ok
        payload["summary_vi"] = payload["llm"]["summary_vi"]
    except (ProviderError, ValueError) as exc:
        payload["llm"] = {"error": str(exc), "model": qa_model}
        payload["passed"] = False
        payload["summary_vi"] = f"LLM QA không chạy được: {exc}"

    return payload


def parse_and_qa(
    text: str,
    *,
    language: str = "en",
    family: str | None = None,
    use_llm_parse: bool = False,
    use_llm_qa: bool = True,
    strip_first: bool = True,
    work: dict[str, Any] | None = None,
    qa_model: str | None = None,
    min_overall: float = 7.0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Parse manuscript then QA. Returns (edition, parse_report, qa_report)."""
    edition, parse_report = parse_manuscript_to_ref(
        text,
        language=language,
        family=family,
        use_llm=use_llm_parse,
        strip_first=strip_first,
        work=work,
    )
    # QA against the text actually fed to REF (post-strip when applicable).
    source_used = text
    if strip_first and parse_report.get("strip"):
        from .pipeline import build_edition

        source_used, _ = build_edition(
            text,
            language=language,
            work=work,
            use_llm=False,
            preserve_toc=True,
            strip_only=True,
        )
    qa_report = qa_read_edition(
        source_used,
        edition,
        language=language,
        use_llm=use_llm_qa,
        model=qa_model,
        min_overall=min_overall,
    )
    return edition, parse_report, qa_report
