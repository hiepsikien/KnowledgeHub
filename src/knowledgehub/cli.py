from __future__ import annotations

import argparse
import json
import sys

from .catalog import build_catalog, get_work, resolve_content_path, set_read_consumer
from .dotenv import load_dotenv
from .hash import refresh_hashes
from .normalize import normalize_manuscript
from .read_publish import PublishError, publish_to_read
from .translation.annotate import annotate_segment
from .translation.fetch import FetchError, fetch_raw
from .translation.draft import draft_chapter, draft_sample
from .translation.project import init_translation_project, select_translation_mode
from .translation.promote import promote_translation
from .translation.providers import ProviderError
from .translation.qa import qa_segment
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

    tr = sub.add_parser("translate", help="Translation project commands")
    tr_sub = tr.add_subparsers(dest="translate_cmd", required=True)
    tr_init = tr_sub.add_parser("init", help="Create translation project from local raw text")
    tr_init.add_argument("--work", required=True, help="Source work id")
    tr_init.add_argument("--lang", default="vi", help="Target language (default: vi)")
    tr_init.add_argument("--overwrite", action="store_true", help="Recreate existing project")
    tr_draft = tr_sub.add_parser("draft-sample", help="AI draft the sample segment (default: normal)")
    tr_draft.add_argument("--work", required=True, help="Source work id")
    tr_draft.add_argument("--mode", default="normal", choices=["tight", "normal", "loose"])
    tr_draft.add_argument("--skip-polish", action="store_true", help="DeepSeek draft only, no Gemini polish")
    tr_draft_ch = tr_sub.add_parser("draft", help="AI draft one chapter after mode is locked")
    tr_draft_ch.add_argument("--work", required=True, help="Source work id")
    tr_draft_ch.add_argument("--chapter", required=True, help="Chapter label, e.g. I")
    tr_draft_ch.add_argument("--skip-polish", action="store_true", help="DeepSeek draft only, no Gemini polish")
    tr_mode = tr_sub.add_parser("select-mode", help="Lock translation mode after sample review")
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
            text, report = normalize_manuscript(
                raw,
                language=str(work.get("language") or "en"),
                work=work,
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
    if args.cmd == "translate":
        if args.translate_cmd == "init":
            try:
                result = init_translation_project(
                    args.work,
                    target_language=args.lang,
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
                    mode=args.mode,
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
                )
            except (ProviderError, FileNotFoundError, KeyError, ValueError) as exc:
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
        uvicorn.run(
            "knowledgehub.server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
