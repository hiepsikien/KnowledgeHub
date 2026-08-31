#!/usr/bin/env python3
"""Compare macro strategies: baseline vs PA1 (patterns) vs PA2 (patterns + heading content)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CACHE = Path("/tmp/pg_full")
OUT_DEFAULT = FIXTURES / "ref_corpus" / "macro_profile_compare_report.json"

STRATEGIES = ("baseline", "pa1", "pa2")

# Mix: known pass/fail from batch + completeness set
BOOKS = [
    {"id": "mill_on_liberty", "gutenberg_id": "34901", "language": "en"},
    {"id": "marx_communist", "gutenberg_id": "61", "language": "en"},
    {"id": "paine_common_sense", "gutenberg_id": "147", "language": "en"},
    {"id": "wilde_dorian", "gutenberg_id": "174", "language": "en"},
    {"id": "aristotle_politics", "gutenberg_id": "6762", "language": "en"},
    {"id": "austen_pride", "gutenberg_id": "1342", "language": "en"},
    {"id": "bastiat_the_law", "gutenberg_id": "44800", "language": "en"},
    {"id": "augustine_confessions", "gutenberg_id": "3296", "language": "en"},
    {"id": "truyen_kieu", "file": "vi/truyen_kieu.txt", "corpus": "ref_corpus", "language": "vi", "family": "plain"},
    {"id": "nam_cao_chi_pheo", "file": "vi/nam_cao_chi_pheo.txt", "corpus": "ref_corpus", "language": "vi", "family": "plain"},
]


def load_manifest_entry(book_id: str) -> dict | None:
    for corpus in ("ref_corpus", "ref_corpus_b"):
        path = FIXTURES / corpus / "manifest.json"
        if not path.is_file():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row.get("id") == book_id:
                return {**row, "_corpus": corpus}
    return None


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


def resolve(entry: dict) -> tuple[str, str, str]:
    gid = entry.get("gutenberg_id")
    if gid:
        raw = fetch_pg(str(gid))
        return raw, raw, f"gutenberg:{gid}"
    corpus = entry.get("_corpus") or entry.get("corpus") or "ref_corpus"
    file = entry.get("file")
    if not file:
        manifest = load_manifest_entry(entry["id"])
        if manifest:
            corpus = manifest.get("_corpus", corpus)
            file = manifest.get("file")
            entry.update(manifest)
    path = FIXTURES / corpus / file
    raw = path.read_text(encoding="utf-8")
    return raw, raw, f"fixture:{corpus}/{file}"


def run_strategy(
    text: str,
    raw: str,
    entry: dict,
    strategy: str,
    *,
    use_qa: bool,
    sleep_sec: float,
) -> dict:
    from knowledgehub.edition.macro import build_macro_structure
    from knowledgehub.edition.macro_qa import (
        count_expected_body_divisions,
        detect_body_markers,
        qa_macro_completeness,
    )

    lang = entry.get("language") or "en"
    family = entry.get("family") or ("gutenberg" if lang == "en" else "plain")
    markers = detect_body_markers(text)
    expected = count_expected_body_divisions(markers)

    structure = build_macro_structure(
        text,
        language=lang,
        family=family,
        use_llm=True,
        strategy=strategy,
        raw=raw,
    )
    if sleep_sec:
        time.sleep(sleep_sec)

    qa: dict = {}
    if use_qa:
        qa = qa_macro_completeness(text, raw, structure, book_id=entry["id"], language=lang)
        if sleep_sec:
            time.sleep(sleep_sec)

    llm_qa = qa.get("llm_qa") or {}
    profile = structure.get("profile") or {}
    return {
        "strategy": strategy,
        "mode": structure.get("mode"),
        "sections": structure.get("section_count"),
        "expected_body_divisions": expected["expected_body_divisions"],
        "expected_basis": expected["basis"],
        "candidate_count": structure.get("candidate_count"),
        "content_match_count": structure.get("content_match_count"),
        "profile_rules": profile.get("rule_count"),
        "profile_toc_entries": profile.get("toc_entry_count"),
        "deterministic_complete": qa.get("deterministic_complete"),
        "qa_verdict": llm_qa.get("verdict"),
        "qa_complete": qa.get("complete") if use_qa else None,
        "qa_score": llm_qa.get("score"),
        "missing_count": len(llm_qa.get("missing") or []),
        "llm_error": structure.get("llm_error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--skip-qa", action="store_true")
    parser.add_argument("--books", default="", help="comma-separated book ids")
    args = parser.parse_args()

    books = BOOKS
    if args.books.strip():
        ids = {x.strip() for x in args.books.split(",") if x.strip()}
        books = [b for b in BOOKS if b["id"] in ids]

    from knowledgehub.edition.pipeline import build_edition

    results: list[dict] = []
    for entry in books:
        print(f"\n=== {entry['id']} ===", flush=True)
        try:
            raw, _, source = resolve(entry)
            lang = entry.get("language") or "en"
            family = entry.get("family") or ("gutenberg" if lang == "en" else "plain")
            strip = family in {"gutenberg", "scholastic"}
            if strip:
                text, _ = build_edition(raw, language=lang, strip_only=True)
            else:
                text = raw.replace("\r\n", "\n").replace("\r", "\n")
        except (urllib.error.URLError, OSError, FileNotFoundError) as exc:
            results.append({"id": entry["id"], "error": str(exc)})
            print(f"  ERROR load: {exc}", flush=True)
            continue

        row: dict = {
            "id": entry["id"],
            "language": lang,
            "source": source,
            "text_chars": len(text),
        }
        strategies: dict[str, dict] = {}
        for strategy in STRATEGIES:
            print(f"  {strategy}...", flush=True)
            try:
                strategies[strategy] = run_strategy(
                    text,
                    raw,
                    entry,
                    strategy,
                    use_qa=not args.skip_qa,
                    sleep_sec=args.sleep,
                )
                s = strategies[strategy]
                print(
                    f"    mode={s['mode']} secs={s['sections']} exp={s['expected_body_divisions']} "
                    f"cand={s.get('candidate_count')} content={s.get('content_match_count')} "
                    f"QA={s.get('qa_verdict')}",
                    flush=True,
                )
            except Exception as exc:
                strategies[strategy] = {"strategy": strategy, "error": str(exc)}
                print(f"    ERROR: {exc}", flush=True)
        row["strategies"] = strategies
        results.append(row)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"books": results, "strategies": list(STRATEGIES)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # Summary
    summary: dict[str, dict[str, int]] = {s: {"pass": 0, "warn": 0, "fail": 0, "error": 0} for s in STRATEGIES}
    for row in results:
        for s in STRATEGIES:
            st = (row.get("strategies") or {}).get(s) or {}
            if st.get("error"):
                summary[s]["error"] += 1
            else:
                v = st.get("qa_verdict") or "none"
                if v in summary[s]:
                    summary[s][v] += 1

    report = {"summary_by_strategy": summary, "books": results, "strategies": list(STRATEGIES)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
