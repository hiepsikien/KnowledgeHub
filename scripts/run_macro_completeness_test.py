#!/usr/bin/env python3
"""Test macro Step 1 on full PG books (<=20 body divisions) with full TOC + all-boundary QA."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path("/tmp/pg_full")
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "ref_corpus" / "macro_completeness_report.json"

# Full PG texts with <= ~20 body divisions (verified via marker scan)
BOOKS = [
    {"id": "mill_on_liberty", "gutenberg_id": "34901", "language": "en", "max_expected": 6},
    {"id": "wilde_dorian", "gutenberg_id": "174", "language": "en", "max_expected": 21},
    {"id": "marx_communist", "gutenberg_id": "61", "language": "en", "max_expected": 5},
    {"id": "cicero_offices", "gutenberg_id": "541", "language": "en", "max_expected": 4},
    {"id": "paine_common_sense", "gutenberg_id": "147", "language": "en", "max_expected": 6},
]


def fetch_pg(gid: str) -> str:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"pg{gid}.txt"
    if not path.is_file():
        url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
        path.write_text(
            urllib.request.urlopen(url, timeout=120).read().decode("utf-8", errors="replace"),
            encoding="utf-8",
        )
    return path.read_text(encoding="utf-8")


def run_book(entry: dict, *, sleep_sec: float) -> dict:
    from knowledgehub.edition.macro import build_macro_structure
    from knowledgehub.edition.macro_qa import (
        count_expected_body_divisions,
        detect_body_markers,
        extract_toc_from_raw,
        qa_macro_completeness,
    )
    from knowledgehub.edition.pipeline import build_edition

    gid = entry["gutenberg_id"]
    raw = fetch_pg(gid)
    text, _ = build_edition(raw, language=entry["language"], strip_only=True)
    markers = detect_body_markers(text)
    expected = count_expected_body_divisions(markers)
    toc = extract_toc_from_raw(raw)

    rule = build_macro_structure(text, language=entry["language"], family="gutenberg", use_llm=False)
    llm = build_macro_structure(text, language=entry["language"], family="gutenberg", use_llm=True)

    qa_rule = qa_macro_completeness(
        text, raw, rule, book_id=f"{entry['id']}_rule", language=entry["language"]
    )
    if sleep_sec:
        time.sleep(sleep_sec)
    qa_llm = qa_macro_completeness(
        text, raw, llm, book_id=f"{entry['id']}_llm", language=entry["language"]
    )
    if sleep_sec:
        time.sleep(sleep_sec)

    return {
        "id": entry["id"],
        "gutenberg_id": gid,
        "text_chars": len(text),
        "toc_chars": len(toc),
        "expected_body_divisions": expected["expected_body_divisions"],
        "expected_basis": expected["basis"],
        "expected_by_kind": expected["by_kind"],
        "rule": {
            "sections": rule.get("section_count"),
            "body_sections": qa_rule.get("macro_body_section_count"),
            "deterministic_complete": qa_rule.get("deterministic_complete"),
            "qa_complete": qa_rule.get("complete"),
            "qa_verdict": qa_rule.get("verdict"),
            "qa_summary_vi": (qa_rule.get("llm_qa") or {}).get("summary_vi"),
            "missing": (qa_rule.get("llm_qa") or {}).get("missing"),
        },
        "llm": {
            "mode": llm.get("mode"),
            "sections": llm.get("section_count"),
            "content_kind": llm.get("content_kind"),
            "body_sections": qa_llm.get("macro_body_section_count"),
            "deterministic_complete": qa_llm.get("deterministic_complete"),
            "qa_complete": qa_llm.get("complete"),
            "qa_verdict": qa_llm.get("verdict"),
            "qa_summary_vi": (qa_llm.get("llm_qa") or {}).get("summary_vi"),
            "missing": (qa_llm.get("llm_qa") or {}).get("missing"),
            "toc_body_estimate": (qa_llm.get("llm_qa") or {}).get("toc_body_entries_estimate"),
            "macro_body_count": (qa_llm.get("llm_qa") or {}).get("macro_body_sections"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--sleep", type=float, default=2.0)
    args = parser.parse_args()

    results = []
    print("Macro completeness test (full PG, <=20 divisions)\n", flush=True)
    for i, entry in enumerate(BOOKS):
        print(f"[{i+1}/{len(BOOKS)}] {entry['id']}...", flush=True)
        row = run_book(entry, sleep_sec=args.sleep)
        results.append(row)
        print(
            f"  expected~={row['expected_body_divisions']} ({row['expected_basis']}) "
            f"rule={row['rule']['sections']} llm={row['llm']['sections']} "
            f"QA complete: rule={row['rule']['qa_complete']}/{row['rule']['qa_verdict']} "
            f"llm={row['llm']['qa_complete']}/{row['llm']['qa_verdict']}",
            flush=True,
        )
        if row["llm"].get("missing"):
            print(f"  llm missing: {row['llm']['missing'][:2]}", flush=True)

    summary = {
        "llm_qa_complete_count": sum(1 for r in results if r["llm"].get("qa_complete")),
        "llm_det_complete_count": sum(1 for r in results if r["llm"].get("deterministic_complete")),
        "rule_qa_complete_count": sum(1 for r in results if r["rule"].get("qa_complete")),
    }
    report = {"books": len(results), "summary": summary, "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}", flush=True)
    print(f"Summary: LLM QA complete {summary['llm_qa_complete_count']}/{len(results)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
