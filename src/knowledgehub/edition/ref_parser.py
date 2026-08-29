"""Unified REF/1 parser entry point."""

from __future__ import annotations

from typing import Any

from .pipeline import build_edition
from .profile import detect_family
from .ref import build_read_edition
from .ref_schema import validate_edition


def parse_manuscript_to_ref(
    text: str,
    *,
    language: str = "en",
    work: dict[str, Any] | None = None,
    family: str | None = None,
    use_llm: bool = False,
    strip_first: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Full pipeline: optional rule strip → REF blocks → validated edition document."""
    work = dict(work or {})
    lang = str(language or work.get("language") or "en")
    fam = family or detect_family(text, work=work, language=lang)
    report: dict[str, Any] = {"family": fam, "language": lang}

    if strip_first:
        stripped, strip_report = build_edition(
            text,
            language=lang,
            work=work,
            use_llm=False,
        )
        report["strip"] = strip_report
        source = stripped
        fam = str(strip_report.get("family") or fam)
    else:
        source = text

    edition, ref_report = build_read_edition(
        source,
        family=fam,
        language=lang,
        use_llm=use_llm,
        work_id=str(work.get("id") or "") or None,
    )
    report.update(ref_report)
    report["validation_errors"] = validate_edition(edition)
    return edition, report


def assert_valid_edition(doc: dict[str, Any]) -> None:
    errors = validate_edition(doc)
    if errors:
        raise ValueError("; ".join(errors))
