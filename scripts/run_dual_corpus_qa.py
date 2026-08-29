#!/usr/bin/env python3
"""Run LLM QA on corpus A (old 50) and corpus B (new 50) separately."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CORPUS_A = ROOT / "tests" / "fixtures" / "ref_corpus"
CORPUS_B = ROOT / "tests" / "fixtures" / "ref_corpus_b"


def _load_manifest(corpus_dir: Path) -> list[dict]:
    path = corpus_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def run_qa(manifest: list[dict], corpus_dir: Path, *, use_llm: bool = True) -> dict:
    from knowledgehub.edition.ref_qa import parse_and_qa

    results = []
    rule_pass = llm_ok = llm_err = v_pass = v_warn = v_fail = 0
    model = None
    for i, entry in enumerate(manifest):
        path = corpus_dir / entry["file"]
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        if len(raw.strip()) < 80:
            continue
        strip = entry.get("strip_first", entry.get("family") == "gutenberg")
        print(f"  [{i+1}/{len(manifest)}] {entry['id']}...", flush=True)
        try:
            edition, _, qa = parse_and_qa(
                raw,
                language=entry["language"],
                family=entry.get("family"),
                strip_first=strip,
                use_llm_qa=use_llm,
            )
        except Exception as exc:
            llm_err += 1
            results.append({
                "id": entry["id"],
                "error": str(exc),
                "llm_passed": False,
                "fidelity_passed": False,
            })
            if use_llm:
                time.sleep(2)
            continue
        fid = qa.get("fidelity", {}).get("passed", False)
        llm = qa.get("llm") or {}
        model = llm.get("model") or model
        rule_pass += int(fid)
        llm_ok += int(qa.get("passed", False) and use_llm)
        if use_llm and llm:
            v = llm.get("verdict", "fail")
            v_pass += int(v == "pass")
            v_warn += int(v == "warn")
            v_fail += int(v == "fail")
        results.append({
            "id": entry["id"],
            "language": entry["language"],
            "blocks": len(edition.get("blocks") or []),
            "fidelity_passed": fid,
            "llm_passed": qa.get("passed") if use_llm else None,
            "model": llm.get("model"),
            "scores": llm.get("scores"),
            "verdict": llm.get("verdict"),
            "issue_count": len(llm.get("issues") or []),
            "summary_vi": llm.get("summary_vi"),
            "error": llm.get("error"),
            "top_issues": (llm.get("issues") or [])[:2],
        })
        if use_llm:
            time.sleep(2.5)
    overalls = [
        (r.get("scores") or {}).get("overall")
        for r in results
        if (r.get("scores") or {}).get("overall") is not None
    ]
    avg_overall = sum(overalls) / len(overalls) if overalls else None
    return {
        "corpus": corpus_dir.name,
        "parser_version": "v1.6",
        "model": model,
        "samples": len(results),
        "rule_passed": rule_pass,
        "llm_ok": llm_ok if use_llm else None,
        "llm_errors": llm_err,
        "verdict_pass": v_pass if use_llm else None,
        "verdict_warn": v_warn if use_llm else None,
        "verdict_fail": v_fail if use_llm else None,
        "avg_overall": round(avg_overall, 2) if avg_overall is not None else None,
        "results": results,
    }


def _summarize(report: dict) -> dict:
    warns = [r["id"] for r in report.get("results", []) if r.get("verdict") == "warn"]
    fails = [r["id"] for r in report.get("results", []) if r.get("verdict") == "fail"]
    return {
        "corpus": report.get("corpus"),
        "samples": report.get("samples"),
        "rule_passed": report.get("rule_passed"),
        "verdict_pass": report.get("verdict_pass"),
        "verdict_warn": report.get("verdict_warn"),
        "verdict_fail": report.get("verdict_fail"),
        "avg_overall": report.get("avg_overall"),
        "warn_ids": warns,
        "fail_ids": fails,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--corpus", choices=("a", "b", "both"), default="both")
    p.add_argument("--skip-fetch-b", action="store_true")
    args = p.parse_args()

    if args.corpus in ("b", "both") and not args.skip_fetch_b:
        import subprocess

        print("Exporting corpus B from Knowledge Hub catalog...", flush=True)
        rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "export_ref_corpus_from_hub.py")])
        if rc != 0:
            print("Warning: corpus B export incomplete", file=sys.stderr)

    use_llm = not args.no_llm
    summaries = []

    if args.corpus in ("a", "both"):
        print("\n=== Corpus A (ref_corpus — 50 mẫu cũ) ===", flush=True)
        manifest_a = _load_manifest(CORPUS_A)
        report_a = run_qa(manifest_a, CORPUS_A, use_llm=use_llm)
        out_a = CORPUS_A / "qa_report_v16.json"
        out_a.write_text(json.dumps(report_a, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summaries.append(_summarize(report_a))
        print(json.dumps(_summarize(report_a), ensure_ascii=False, indent=2))

    if args.corpus in ("b", "both"):
        print("\n=== Corpus B (ref_corpus_b — 50 mẫu mới) ===", flush=True)
        manifest_b = _load_manifest(CORPUS_B)
        report_b = run_qa(manifest_b, CORPUS_B, use_llm=use_llm)
        out_b = CORPUS_B / "qa_report_v16.json"
        out_b.write_text(json.dumps(report_b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summaries.append(_summarize(report_b))
        print(json.dumps(_summarize(report_b), ensure_ascii=False, indent=2))

    combined = ROOT / "tests" / "fixtures" / "ref_corpus_qa_dual_v16.json"
    combined.write_text(json.dumps({"summaries": summaries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nCombined summary -> {combined}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
