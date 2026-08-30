#!/usr/bin/env python3
"""Run Step 1 macro (rule vs LLM) on ~10 corpus books + smart boundary QA."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "ref_corpus"

DEFAULT_IDS = [
    "grotius_treatise",
    "locke_second_treatise",
    "melville_moby",
    "austen_pride",
    "shakespeare_hamlet",
    "aquinas_summa",
    "machiavelli_prince",
    "federalist_papers",
    "truyen_kieu",
    "nam_cao_chi_pheo",
]


def _load_manifest() -> dict[str, dict]:
    rows = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return {r["id"]: r for r in rows}


def _stripped_text(entry: dict, raw: str) -> tuple[str, str]:
    from knowledgehub.edition.pipeline import build_edition

    lang = entry["language"]
    family = entry.get("family") or "gutenberg"
    strip = entry.get("strip_first", family in {"gutenberg", "scholastic"})
    if not strip:
        return raw, family
    text, report = build_edition(raw, language=lang, strip_only=True)
    return text, str(report.get("family") or family)


def run_one(entry: dict, *, use_llm_qa: bool, sleep_sec: float) -> dict:
    from knowledgehub.edition.macro import build_macro_structure
    from knowledgehub.edition.macro_qa import compare_structures, qa_macro_pair

    book_id = entry["id"]
    path = CORPUS / entry["file"]
    raw = path.read_text(encoding="utf-8")
    text, family = _stripped_text(entry, raw)
    lang = entry["language"]

    rule = build_macro_structure(text, language=lang, family=family, use_llm=False)
    llm: dict | None = None
    llm_err: str | None = None
    try:
        llm = build_macro_structure(text, language=lang, family=family, use_llm=True)
        if llm.get("mode") == "rule_fallback":
            llm_err = str(llm.get("llm_error") or "fallback")
    except Exception as exc:
        llm_err = str(exc)

    diff = compare_structures(rule, llm) if llm else {"llm_sections": None}

    qa = qa_macro_pair(
        text,
        rule,
        llm,
        book_id=book_id,
        language=lang,
        family=family,
        use_llm=use_llm_qa,
    )
    if use_llm_qa and sleep_sec > 0:
        time.sleep(sleep_sec)

    llm_qa = qa.get("llm_qa") or {}
    rule_v = (llm_qa.get("rule") or {}).get("verdict", "n/a")
    llm_v = (llm_qa.get("llm") or {}).get("verdict", "n/a")
    better = (llm_qa.get("llm") or {}).get("better_than_rule")

    return {
        "id": book_id,
        "language": lang,
        "family": family,
        "text_chars": len(text),
        "rule": {
            "mode": rule.get("mode"),
            "sections": rule.get("section_count"),
            "content_kind": rule.get("content_kind"),
            "preflight_toc_starts": qa.get("preflight", {}).get("rule_toc_line_used_as_start"),
        },
        "llm": {
            "mode": (llm or {}).get("mode"),
            "sections": (llm or {}).get("section_count"),
            "content_kind": (llm or {}).get("content_kind"),
            "summary_vi": (llm or {}).get("summary_vi"),
            "error": llm_err,
        },
        "diff": diff,
        "qa": {
            "passed": qa.get("passed"),
            "recommendation": qa.get("recommendation") or llm_qa.get("recommendation"),
            "rule_verdict": rule_v,
            "llm_verdict": llm_v,
            "llm_better_than_rule": better,
            "summary_vi": llm_qa.get("summary_vi"),
            "rule_score": (llm_qa.get("rule") or {}).get("score"),
            "llm_score": (llm_qa.get("llm") or {}).get("score"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Macro step 1 corpus test (rule vs LLM + smart QA)")
    parser.add_argument("--ids", nargs="*", default=DEFAULT_IDS, help="manifest ids")
    parser.add_argument("--out", type=Path, default=CORPUS / "macro_qa_report.json")
    parser.add_argument("--no-llm-qa", action="store_true", help="skip LLM QA (preflight only)")
    parser.add_argument("--sleep", type=float, default=1.5, help="seconds between LLM QA calls")
    args = parser.parse_args()

    manifest = _load_manifest()
    results: list[dict] = []
    errors: list[str] = []

    print(f"Macro corpus test — {len(args.ids)} books\n", flush=True)
    for i, bid in enumerate(args.ids):
        entry = manifest.get(bid)
        if not entry:
            errors.append(f"unknown id: {bid}")
            continue
        print(f"[{i+1}/{len(args.ids)}] {bid}...", flush=True)
        try:
            row = run_one(entry, use_llm_qa=not args.no_llm_qa, sleep_sec=args.sleep)
            results.append(row)
            q = row["qa"]
            print(
                f"  rule={row['rule']['sections']} ({row['rule']['mode']}) "
                f"llm={row['llm']['sections']} ({row['llm']['mode']}) "
                f"toc_false_starts={row['rule']['preflight_toc_starts']} "
                f"QA rule={q['rule_verdict']} llm={q['llm_verdict']} rec={q['recommendation']}",
                flush=True,
            )
        except Exception as exc:
            errors.append(f"{bid}: {exc}")
            print(f"  ERROR: {exc}", flush=True)

    llm_better = sum(1 for r in results if r["qa"].get("llm_better_than_rule") is True)
    rec_llm = sum(1 for r in results if r["qa"].get("recommendation") == "llm")
    rule_fail = sum(1 for r in results if r["qa"].get("rule_verdict") == "fail")

    report = {
        "books": len(results),
        "errors": errors,
        "summary": {
            "llm_better_than_rule_count": llm_better,
            "recommend_llm_count": rec_llm,
            "rule_fail_count": rule_fail,
        },
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}", flush=True)
    print(
        f"Summary: {llm_better}/{len(results)} LLM better, "
        f"{rec_llm} recommend llm, {rule_fail} rule fail",
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
