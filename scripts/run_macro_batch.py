#!/usr/bin/env python3
"""Batch macro Step 1 (LLM) + completeness QA over EN/VI corpus (~50 books)."""

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


def load_manifests(*corpora: str) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for name in corpora:
        path = FIXTURES / name / "manifest.json"
        if not path.is_file():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            entry = dict(row)
            entry["_corpus"] = name
            seen[entry["id"]] = entry
    return seen


def select_books(
    by_id: dict[str, dict],
    *,
    langs: list[str],
    limit: int,
    vi_all: bool,
) -> list[dict]:
    vi = [by_id[k] for k in sorted(by_id) if by_id[k].get("language") in langs and by_id[k].get("language") == "vi"]
    en = [by_id[k] for k in sorted(by_id) if by_id[k].get("language") == "en"]
    if vi_all:
        picked = list(vi)
        need_en = max(0, limit - len(picked))
        picked.extend(en[:need_en])
    else:
        picked = [by_id[k] for k in sorted(by_id) if by_id[k].get("language") in langs][:limit]
    return picked[:limit]


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


def resolve_raw(entry: dict) -> tuple[str, str]:
    """Returns (raw_text, source_note)."""
    gid = entry.get("gutenberg_id")
    lang = entry.get("language") or "en"
    if lang == "en" and gid:
        try:
            return fetch_pg(str(gid)), f"gutenberg:{gid}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            pass
    corpus = entry.get("_corpus") or "ref_corpus"
    path = FIXTURES / corpus / entry["file"]
    if not path.is_file():
        alt = FIXTURES / "ref_corpus" / entry["file"]
        path = alt if alt.is_file() else path
    if not path.is_file():
        raise FileNotFoundError(entry["file"])
    return path.read_text(encoding="utf-8"), f"fixture:{corpus}/{entry['file']}"


def run_one(entry: dict, *, skip_qa: bool, sleep_sec: float) -> dict:
    from knowledgehub.edition.macro import build_macro_structure
    from knowledgehub.edition.macro_qa import (
        count_expected_body_divisions,
        detect_body_markers,
        extract_toc_from_raw,
        qa_macro_completeness,
    )
    from knowledgehub.edition.pipeline import build_edition

    raw, source = resolve_raw(entry)
    lang = entry.get("language") or "en"
    family = entry.get("family") or ("gutenberg" if lang == "en" else "plain")
    strip = entry.get("strip_first", family in {"gutenberg", "scholastic"})
    if strip:
        text, _rep = build_edition(raw, language=lang, strip_only=True, work={"language": lang})
    else:
        text = raw.replace("\r\n", "\n").replace("\r", "\n")

    markers = detect_body_markers(text)
    expected = count_expected_body_divisions(markers)
    toc_len = len(extract_toc_from_raw(raw) or "")

    llm = build_macro_structure(text, language=lang, family=family, use_llm=True, raw=raw)
    if sleep_sec:
        time.sleep(sleep_sec)

    qa: dict = {}
    if not skip_qa:
        qa = qa_macro_completeness(text, raw, llm, book_id=entry["id"], language=lang)
        if sleep_sec:
            time.sleep(sleep_sec)

    llm_qa = qa.get("llm_qa") or {}
    return {
        "id": entry["id"],
        "corpus": entry.get("_corpus"),
        "language": lang,
        "family": family,
        "source": source,
        "gutenberg_id": entry.get("gutenberg_id"),
        "text_chars": len(text),
        "raw_chars": len(raw),
        "toc_chars": toc_len,
        "expected_body_divisions": expected["expected_body_divisions"],
        "expected_basis": expected["basis"],
        "llm_mode": llm.get("mode"),
        "llm_sections": llm.get("section_count"),
        "llm_content_kind": llm.get("content_kind"),
        "llm_error": llm.get("llm_error"),
        "deterministic_complete": qa.get("deterministic_complete"),
        "qa_complete": qa.get("complete"),
        "qa_verdict": qa.get("verdict"),
        "qa_summary_vi": llm_qa.get("summary_vi"),
        "qa_score": llm_qa.get("score"),
        "missing_count": len(llm_qa.get("missing") or []),
        "missing": (llm_qa.get("missing") or [])[:5],
        "toc_body_estimate": llm_qa.get("toc_body_entries_estimate"),
        "macro_body_count": llm_qa.get("macro_body_sections"),
    }


def save_report(path: Path, results: list[dict], errors: list[dict]) -> None:
    vi = [r for r in results if r.get("language") == "vi"]
    en = [r for r in results if r.get("language") == "en"]
    summary = {
        "total": len(results),
        "errors": len(errors),
        "en": len(en),
        "vi": len(vi),
        "llm_qa_pass": sum(1 for r in results if r.get("qa_verdict") == "pass"),
        "llm_qa_warn": sum(1 for r in results if r.get("qa_verdict") == "warn"),
        "llm_qa_fail": sum(1 for r in results if r.get("qa_verdict") == "fail"),
        "qa_complete_true": sum(1 for r in results if r.get("qa_complete")),
        "det_complete": sum(1 for r in results if r.get("deterministic_complete")),
        "mode_markers": sum(1 for r in results if r.get("llm_mode") == "markers"),
        "full_pg_en": sum(1 for r in en if str(r.get("source", "")).startswith("gutenberg:")),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"summary": summary, "errors": errors, "results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--langs", default="en,vi")
    parser.add_argument("--corpora", default="ref_corpus,ref_corpus_b")
    parser.add_argument("--out", type=Path, default=FIXTURES / "ref_corpus" / "macro_batch_50_report.json")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--skip-qa", action="store_true")
    parser.add_argument("--start", type=int, default=0, help="resume offset")
    args = parser.parse_args()

    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    corpora = [x.strip() for x in args.corpora.split(",") if x.strip()]
    by_id = load_manifests(*corpora)
    books = select_books(by_id, langs=langs, limit=args.limit, vi_all=True)

    results: list[dict] = []
    errors: list[dict] = []
    if args.start and args.out.is_file():
        prev = json.loads(args.out.read_text(encoding="utf-8"))
        results = list(prev.get("results") or [])
        errors = list(prev.get("errors") or [])
        done = {r["id"] for r in results}
        books = [b for b in books if b["id"] not in done]

    print(f"Macro batch: {len(books)} books (langs={langs}, limit={args.limit})\n", flush=True)
    for i, entry in enumerate(books):
        idx = args.start + len(results) + 1
        print(f"[{idx}/{args.limit}] {entry['id']} ({entry.get('language')})...", flush=True)
        try:
            row = run_one(entry, skip_qa=args.skip_qa, sleep_sec=args.sleep)
            results.append(row)
            print(
                f"  src={row['source'][:40]} chars={row['text_chars']} "
                f"secs={row['llm_sections']} exp={row['expected_body_divisions']} "
                f"QA={row.get('qa_verdict')} complete={row.get('qa_complete')}",
                flush=True,
            )
        except Exception as exc:
            errors.append({"id": entry["id"], "error": str(exc)})
            print(f"  ERROR: {exc}", flush=True)
        save_report(args.out, results, errors)

    save_report(args.out, results, errors)
    s = json.loads(args.out.read_text())["summary"]
    print(f"\nWrote {args.out}", flush=True)
    print(
        f"Done: {s['total']} ok, {s['errors']} err | "
        f"QA pass/warn/fail={s['llm_qa_pass']}/{s['llm_qa_warn']}/{s['llm_qa_fail']} | "
        f"complete={s['qa_complete_true']}",
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
