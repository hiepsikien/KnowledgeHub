from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import build_catalog, get_work, resolve_content_path, set_read_consumer
from .dotenv import load_dotenv
from .hash import refresh_hashes
from .normalize import normalize_manuscript
from .read_publish import PublishError, publish_to_read
from .translation.api import split_translation_parts
from .translation.annotate import annotate_segment
from .translation.fetch import FetchError, fetch_raw
from .translation.draft import draft_chapter, draft_sample
from .translation.project import init_translation_project, select_translation_mode
from .translation.promote import promote_translation
from .translation.providers import ProviderError
from .translation.qa import qa_segment
from .settings import translation_pipeline
from .validate import validate_catalog


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="knowledgehub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build-catalog", help="Rebuild catalog/ from Think-shaped sources/*/works.json")
    sub.add_parser("validate", help="Check catalog ids, authors, licenses")
    sub.add_parser("hash", help="Fill content_hash from local raw/*.txt")

    pub = sub.add_parser("publish-read", help="Push one work to Read (pending_review)")
    pub.add_argument("--work", required=True, help="Work id, e.g. locke--second_treatise")
    pub.add_argument("--apply", action="store_true", help="POST to Read; default is dry-run")
    pub.add_argument("--api-url", default=None)

    allow = sub.add_parser("allow-read", help="Permit a work to be published to Read")
    allow.add_argument("--work", required=True)
    allow.add_argument("--block", action="store_true")

    show = sub.add_parser("show", help="Print one catalog work")
    show.add_argument("--work", required=True)

    fetch = sub.add_parser("fetch-raw", help="Download and prepare manuscript for a work")
    fetch.add_argument("--work", required=True, help="Work id, e.g. grotius--freedom_of_the_seas")

    edition = sub.add_parser("edition", help="Preview reading edition (does not rewrite raw)")
    edition.add_argument("--work", required=True)
    edition.add_argument("--llm", action="store_true", help="Classify unsure spans with Gemini")
    edition.add_argument("--head", type=int, default=700, help="Chars of edition head to print")
    edition.add_argument("--tail", type=int, default=400, help="Chars of edition tail to print")

    ref_qa = sub.add_parser("ref-qa", help="QA REF/1 parse (rule checks + optional LLM review)")
    ref_qa.add_argument("--corpus", default=None, help="Corpus sample id from tests/fixtures/ref_corpus/manifest.json, or 'all'")
    ref_qa.add_argument("--work", default=None, help="Catalog work id (uses normalized manuscript)")
    ref_qa.add_argument("--file", default=None, type=Path, help="Raw text file to parse and QA")
    ref_qa.add_argument("--language", default=None, help="Language code when using --file")
    ref_qa.add_argument("--family", default=None, help="Source family override")
    ref_qa.add_argument("--model", default=None, help="LLM model override (default: settings qa slot or gemini-3.5-flash)")
    ref_qa.add_argument("--no-llm", action="store_true", help="Rule checks only (no LLM cost)")
    ref_qa.add_argument("--min-overall", type=float, default=7.0, help="Minimum LLM overall score to pass")
    ref_qa.add_argument("--fail-fast", action="store_true", help="Exit 1 on first failed sample")

    tr = sub.add_parser("translate", help="Translation project commands")
    tr_sub = tr.add_subparsers(dest="translate_cmd", required=True)
    tr_init = tr_sub.add_parser("init", help="Create translation project from local raw text")
    tr_init.add_argument("--work", required=True, help="Source work id")
    tr_init.add_argument("--lang", default="vi", help="Target language (default: vi)")
    tr_init.add_argument("--mode", default=None, choices=["tight", "normal", "loose"])
    tr_init.add_argument("--overwrite", action="store_true", help="Recreate existing project")
    tr_draft = tr_sub.add_parser("draft-sample", help="AI draft the sample segment (default: normal)")
    tr_draft.add_argument("--work", required=True, help="Source work id")
    tr_draft.add_argument("--mode", default=None, choices=["tight", "normal", "loose"])
    tr_draft.add_argument("--skip-polish", action="store_true", help="DeepSeek draft only, no Gemini polish")
    tr_draft_ch = tr_sub.add_parser("draft", help="AI draft one chapter after mode is locked")
    tr_draft_ch.add_argument("--work", required=True, help="Source work id")
    tr_draft_ch.add_argument("--chapter", required=True, help="Chapter label, e.g. I")
    tr_draft_ch.add_argument("--skip-polish", action="store_true", help="DeepSeek draft only, no Gemini polish")
    tr_draft_ch.add_argument(
        "--force-draft",
        action="store_true",
        help="Ignore saved DeepSeek draft and translate from English again",
    )
    tr_split = tr_sub.add_parser(
        "split-parts",
        help="Split long/truncated chapters into paragraph parts and requeue drafts",
    )
    tr_split.add_argument("--work", required=True, help="Source work id")
    tr_split.add_argument(
        "--no-enqueue",
        action="store_true",
        help="Rewrite segments only; do not queue draft jobs",
    )
    tr_mode = tr_sub.add_parser("select-mode", help="Lock translation mode (sample draft optional)")
    tr_mode.add_argument("--work", required=True, help="Source work id")
    tr_mode.add_argument("--mode", required=True, choices=["tight", "normal", "loose"])
    tr_qa = tr_sub.add_parser("qa", help="Run QA on a chapter translation (and annotations if present)")
    tr_qa.add_argument("--work", required=True, help="Source work id")
    tr_qa.add_argument("--chapter", required=True, help="Chapter label, e.g. I")
    tr_ann = tr_sub.add_parser("annotate", help="Generate reader annotations for a chapter")
    tr_ann.add_argument("--work", required=True, help="Source work id")
    tr_ann.add_argument("--chapter", required=True, help="Chapter label, e.g. I")
    tr_promote = tr_sub.add_parser(
        "promote",
        help="Create/update catalog Work from complete chapter finals (not raw/)",
    )
    tr_promote.add_argument("--work", required=True, help="Source work id")
    tr_promote.add_argument("--title", default=None, help="Override Vietnamese title")

    serve = sub.add_parser("serve", help="Open curator UI (FastAPI + static SPA)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--reload", action="store_true", default=True)
    serve.add_argument("--no-reload", action="store_false", dest="reload")

    args = parser.parse_args(argv)

    if args.cmd == "build-catalog":
        stats = build_catalog()
        print(json.dumps(stats, indent=2))
        return 0
    if args.cmd == "validate":
        errors = validate_catalog()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print("ok")
        return 0
    if args.cmd == "hash":
        print(json.dumps(refresh_hashes(), indent=2))
        return 0
    if args.cmd == "allow-read":
        row = set_read_consumer(args.work, allowed=not args.block)
        print(json.dumps(row.get("rights"), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "show":
        print(json.dumps(get_work(args.work), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "publish-read":
        try:
            result = publish_to_read(
                args.work,
                api_url=args.api_url,
                dry_run=not args.apply,
            )
        except (PublishError, KeyError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "fetch-raw":
        try:
            result = fetch_raw(args.work)
        except (FetchError, FileNotFoundError, KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "edition":
        try:
            work = get_work(args.work)
            path = resolve_content_path(work)
            raw = path.read_text(encoding="utf-8", errors="replace")
            from .paths import corpus_root

            text, report = normalize_manuscript(
                raw,
                language=str(work.get("language") or "en"),
                work={**work, "_corpus_root": str(corpus_root())},
                use_llm=args.llm,
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        drops = [
            s
            for s in report.get("spans") or []
            if s.get("action") == "drop" and float(s.get("confidence") or 0) >= 0.85
        ]
        summary = {
            "work_id": args.work,
            "family": report.get("family"),
            "edition_format": report.get("edition_format"),
            "edition_hash": report.get("edition_hash"),
            "content_kind": report.get("content_kind"),
            "block_count": report.get("block_count"),
            "ref": report.get("ref"),
            "source_chars": report.get("source_chars"),
            "published_chars": report.get("published_chars"),
            "kept_notes": report.get("kept_notes"),
            "dropped": [
                {
                    "kind": s["kind"],
                    "confidence": s["confidence"],
                    "reason": s["reason"],
                    "chars": s["end"] - s["start"],
                }
                for s in drops
            ],
            "unsure": report.get("unsure") or [],
            "head": text[: args.head],
            "tail": text[-args.tail :],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "ref-qa":
        from .edition.ref_qa import parse_and_qa

        corpus_dir = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ref_corpus"
        jobs: list[dict] = []
        if args.corpus:
            manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
            if args.corpus == "all":
                jobs = manifest
            else:
                jobs = [e for e in manifest if e["id"] == args.corpus]
                if not jobs:
                    print(f"Unknown corpus id: {args.corpus}", file=sys.stderr)
                    return 1
        elif args.work:
            work = get_work(args.work)
            path = resolve_content_path(work)
            jobs = [
                {
                    "id": args.work,
                    "file": None,
                    "language": work.get("language") or "en",
                    "family": None,
                    "work": work,
                    "path": path,
                }
            ]
        elif args.file:
            jobs = [
                {
                    "id": args.file.stem,
                    "file": None,
                    "language": args.language or "en",
                    "family": args.family,
                    "path": args.file,
                }
            ]
        else:
            print("Provide --corpus, --work, or --file", file=sys.stderr)
            return 1

        results: list[dict] = []
        exit_code = 0
        for job in jobs:
            if job.get("path"):
                raw = Path(job["path"]).read_text(encoding="utf-8", errors="replace")
                work = job.get("work")
                family = job.get("family")
                strip = family == "gutenberg" if family else bool(work)
            else:
                raw = (corpus_dir / job["file"]).read_text(encoding="utf-8")
                work = None
                family = job.get("family")
                strip = family == "gutenberg"
            try:
                edition, parse_report, qa_report = parse_and_qa(
                    raw,
                    language=str(job.get("language") or "en"),
                    family=family,
                    strip_first=strip,
                    work=work,
                    use_llm_qa=not args.no_llm,
                    min_overall=args.min_overall,
                    qa_model=args.model,
                )
            except (ProviderError, ValueError, FileNotFoundError, KeyError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            row = {
                "id": job["id"],
                "passed": qa_report.get("passed"),
                "block_count": len(edition.get("blocks") or []),
                "validation_errors": parse_report.get("validation_errors"),
                "fidelity": {
                    "passed": qa_report.get("fidelity", {}).get("passed"),
                    "failed_count": qa_report.get("fidelity", {}).get("failed_count"),
                },
                "summary_vi": qa_report.get("summary_vi"),
            }
            llm = qa_report.get("llm")
            if llm:
                row["llm"] = {
                    k: llm.get(k)
                    for k in ("model", "scores", "verdict", "open_issue_count", "issues", "error")
                    if k in llm
                }
            results.append(row)
            if not qa_report.get("passed"):
                exit_code = 1
                if args.fail_fast:
                    break
        print(json.dumps({"samples": len(results), "passed": sum(1 for r in results if r["passed"]), "results": results}, ensure_ascii=False, indent=2))
        return exit_code
    if args.cmd == "translate":
        if args.translate_cmd == "init":
            try:
                result = init_translation_project(
                    args.work,
                    target_language=args.lang,
                    translation_mode=args.mode,
                    overwrite=args.overwrite,
                )
            except (FileExistsError, FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "draft-sample":
            try:
                result = draft_sample(
                    args.work,
                    mode=args.mode or translation_pipeline()["default_mode"],
                    skip_polish=args.skip_polish,
                )
            except (ProviderError, FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "draft":
            try:
                result = draft_chapter(
                    args.work,
                    chapter=args.chapter,
                    skip_polish=args.skip_polish,
                    force_draft=args.force_draft,
                )
            except (ProviderError, FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "split-parts":
            try:
                result = split_translation_parts(args.work, enqueue=not args.no_enqueue)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "select-mode":
            try:
                result = select_translation_mode(args.work, args.mode)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "qa":
            try:
                result = qa_segment(args.work, args.chapter)
            except (ProviderError, FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "annotate":
            try:
                result = annotate_segment(args.work, args.chapter)
            except (ProviderError, FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.translate_cmd == "promote":
            try:
                result = promote_translation(args.work, title=args.title)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        return 2
    if args.cmd == "serve":
        try:
            import uvicorn
        except ImportError:
            print("Install UI extras: pip install -e '.[ui]'", file=sys.stderr)
            return 1
        print(f"Knowledge Hub UI → http://{args.host}:{args.port}")
        run_kw: dict = {
            "app": "knowledgehub.server:app",
            "host": args.host,
            "port": args.port,
            "reload": args.reload,
        }
        if args.reload:
            run_kw["reload_dirs"] = [str(Path(__file__).resolve().parent.parent)]
        uvicorn.run(**run_kw)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
