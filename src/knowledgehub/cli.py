from __future__ import annotations

import argparse
import json
import sys

from .catalog import build_catalog, get_work, set_read_consumer
from .hash import refresh_hashes
from .read_publish import PublishError, publish_to_read
from .validate import validate_catalog


def main(argv: list[str] | None = None) -> int:
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
