from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .catalog import (
    catalog_stats,
    get_work,
    load_authors,
    load_works,
    set_read_consumer,
    work_summary,
)
from .dotenv import load_dotenv
from .hash import refresh_hashes
from .licenses import load_license_catalog
from .paths import corpus_root
from .read_options import read_publisher_options
from .read_publish import PublishError, preview_normalized, publish_to_read
from .settings import save_settings, settings_payload
from .translation.api import (
    enqueue_translation_job,
    cancel_translation_jobs,
    get_segment_detail,
    get_translation_project,
    list_annotations,
    list_translation_projects,
    run_annotate,
    run_approve_qa,
    run_draft,
    run_reopen_qa,
    run_promote,
    run_qa,
)
from .translation.assemble import IncompleteTranslation
from .translation.jobs import list_jobs as list_translation_jobs, start_worker, stop_worker, worker_alive, worker_status
from .translation.providers import ProviderError
from .validate import validate_catalog

WEB_DIR = Path(__file__).resolve().parent / "web"
COOKIE = "kh_ops"

load_dotenv()


class LoginBody(BaseModel):
    secret: str = Field(default="")


class AllowBody(BaseModel):
    allowed: bool = True


class PublishBody(BaseModel):
    apply: bool = False
    persist: bool = False
    title: str | None = None
    description: str | None = None
    category_slug: str | None = None
    price_cents: int | None = None
    split_length: str | None = None


class PromoteBody(BaseModel):
    title: str | None = None


class ApproveQaBody(BaseModel):
    index: int | None = None
    all: bool = False
    replacement: str | None = None
    replacements: dict[str, str] | None = None


class TranslationJobBody(BaseModel):
    kind: str = "draft"
    chapter: str | None = None
    missing: bool = False


class TranslationCancelBody(BaseModel):
    job_id: str | None = None
    chapter: str | None = None


class TranslationSettingsBody(BaseModel):
    models: dict[str, str] | None = None
    auto_annotate: bool | None = None
    auto_qa: bool | None = None
    default_mode: str | None = None
    min_workers: int | None = None
    max_workers: int | None = None
    max_attempts: int | None = None
    job_timeout_sec: int | None = None


class SettingsBody(BaseModel):
    translation: TranslationSettingsBody | None = None


def _ops_secret() -> str:
    return (os.environ.get("KNOWLEDGEHUB_OPS_SECRET") or "").strip()


def _authorized(request: Request) -> bool:
    secret = _ops_secret()
    if not secret:
        return True
    header = (request.headers.get("X-KH-Ops") or "").strip()
    cookie = (request.cookies.get(COOKIE) or "").strip()
    token = header or cookie
    return bool(token) and secrets.compare_digest(token, secret)


def require_ops(request: Request) -> None:
    if not _authorized(request):
        raise HTTPException(401, "ops secret required")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    start_worker()
    yield
    stop_worker()


def create_app() -> FastAPI:
    app = FastAPI(title="Knowledge Hub", version="0.1.0", lifespan=_lifespan)
    guard = [Depends(require_ops)]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "auth": bool(_ops_secret()),
            "read_api": os.environ.get("READ_API_URL") or "http://127.0.0.1:8000",
            "read_token_set": bool((os.environ.get("READ_HUB_TOKEN") or "").strip()),
        }

    @app.post("/api/login")
    def login(payload: LoginBody, response: Response) -> dict[str, Any]:
        secret = _ops_secret()
        given = (payload.secret or "").strip()
        if secret and (not given or not secrets.compare_digest(given, secret)):
            raise HTTPException(401, "sai secret")
        token = secret or "open"
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax")
        return {"ok": True}

    @app.get("/api/stats", dependencies=guard)
    def stats() -> dict[str, Any]:
        return catalog_stats()

    @app.get("/api/works", dependencies=guard)
    def list_works() -> dict[str, Any]:
        root = corpus_root()
        works = load_works(root / "catalog" / "works.json")
        rows = [work_summary(w, root=root) for w in works]
        return {"works": rows, "total": len(rows)}

    @app.get("/api/works/{work_id}", dependencies=guard)
    def work_detail(work_id: str) -> dict[str, Any]:
        root = corpus_root()
        try:
            work = get_work(work_id, corpus=root)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        return {"work": work, "summary": work_summary(work, root=root)}

    @app.get("/api/works/{work_id}/preview", dependencies=guard)
    def work_preview(work_id: str, full: bool = Query(default=False)) -> dict[str, Any]:
        try:
            return preview_normalized(work_id, full=full)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/allow-read", dependencies=guard)
    def allow_read(work_id: str, payload: AllowBody) -> dict[str, Any]:
        try:
            work = set_read_consumer(work_id, payload.allowed)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        return {"work": work, "summary": work_summary(work)}

    @app.get("/api/read-options", dependencies=guard)
    def read_options() -> dict[str, Any]:
        return read_publisher_options()

    @app.post("/api/works/{work_id}/publish-read", dependencies=guard)
    def publish_read(work_id: str, payload: PublishBody) -> dict[str, Any]:
        try:
            result = publish_to_read(
                work_id,
                dry_run=not payload.apply,
                persist=payload.persist,
                title=payload.title,
                description=payload.description,
                category_slug=payload.category_slug,
                price_cents=payload.price_cents,
                split_length=payload.split_length,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc
        return result

    @app.post("/api/validate", dependencies=guard)
    def validate() -> dict[str, Any]:
        errors = validate_catalog()
        return {"ok": not errors, "errors": errors}

    @app.post("/api/hash", dependencies=guard)
    def hash_all() -> dict[str, Any]:
        return refresh_hashes()

    @app.get("/api/authors", dependencies=guard)
    def authors() -> dict[str, Any]:
        return {"authors": load_authors()}

    @app.get("/api/licenses", dependencies=guard)
    def licenses() -> dict[str, Any]:
        return load_license_catalog()

    @app.get("/api/settings", dependencies=guard)
    def get_settings(refresh: bool = Query(default=False)) -> dict[str, Any]:
        return settings_payload(refresh=refresh)

    @app.post("/api/settings", dependencies=guard)
    def update_settings(payload: SettingsBody) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if payload.translation is not None:
            tr = payload.translation.model_dump(exclude_none=True)
            body["translation"] = tr
        try:
            saved = save_settings(body)
        except (ProviderError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return settings_payload() | {"projects_updated": saved.get("projects_updated", 0)}

    @app.get("/api/translations", dependencies=guard)
    def translations_list() -> dict[str, Any]:
        return list_translation_projects()

    @app.get("/api/translations/{source_work_id}", dependencies=guard)
    def translation_project(source_work_id: str) -> dict[str, Any]:
        try:
            return get_translation_project(source_work_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/translations/{source_work_id}/segments/{chapter}", dependencies=guard)
    def translation_segment(
        source_work_id: str,
        chapter: str,
        include_drafts: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            return get_segment_detail(source_work_id, chapter, include_drafts=include_drafts)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/translations/{source_work_id}/annotations", dependencies=guard)
    def translation_annotations(
        source_work_id: str,
        chapter: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return list_annotations(source_work_id, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/draft/{chapter}", dependencies=guard)
    def translation_draft(source_work_id: str, chapter: str) -> dict[str, Any]:
        try:
            return run_draft(source_work_id, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ProviderError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/qa/{chapter}", dependencies=guard)
    def translation_qa(source_work_id: str, chapter: str) -> dict[str, Any]:
        try:
            return run_qa(source_work_id, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ProviderError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/qa/{chapter}/approve", dependencies=guard)
    def translation_qa_approve(
        source_work_id: str, chapter: str, payload: ApproveQaBody | None = None
    ) -> dict[str, Any]:
        body = payload or ApproveQaBody()
        if body.all:
            index = None
        elif body.index is not None:
            index = body.index
        else:
            raise HTTPException(400, "Provide index or all=true.")
        raw_map = body.replacements or {}
        replacements: dict[int, str] = {}
        for key, value in raw_map.items():
            try:
                replacements[int(key)] = value
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, f"Invalid replacement index: {key}") from exc
        try:
            return run_approve_qa(
                source_work_id,
                chapter,
                index=index,
                replacement=body.replacement,
                replacements=replacements or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/qa/{chapter}/reopen", dependencies=guard)
    def translation_qa_reopen(
        source_work_id: str, chapter: str, payload: ApproveQaBody | None = None
    ) -> dict[str, Any]:
        body = payload or ApproveQaBody()
        if body.all:
            index = None
        elif body.index is not None:
            index = body.index
        else:
            raise HTTPException(400, "Provide index or all=true.")
        try:
            return run_reopen_qa(source_work_id, chapter, index=index)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/annotate/{chapter}", dependencies=guard)
    def translation_annotate(source_work_id: str, chapter: str) -> dict[str, Any]:
        try:
            return run_annotate(source_work_id, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ProviderError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/translations/{source_work_id}/jobs", dependencies=guard)
    def translation_jobs(source_work_id: str) -> dict[str, Any]:
        try:
            return {
                "jobs": list_translation_jobs(source_work_id),
                "worker_alive": worker_alive(),
                "workers": worker_status(),
            }
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/jobs", dependencies=guard)
    def translation_enqueue(source_work_id: str, payload: TranslationJobBody) -> dict[str, Any]:
        try:
            return enqueue_translation_job(
                source_work_id,
                kind=payload.kind,
                chapter=payload.chapter,
                missing=payload.missing,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/jobs/cancel", dependencies=guard)
    def translation_cancel(source_work_id: str, payload: TranslationCancelBody | None = None) -> dict[str, Any]:
        body = payload or TranslationCancelBody()
        try:
            return cancel_translation_jobs(
                source_work_id,
                job_id=body.job_id,
                chapter=body.chapter,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/promote", dependencies=guard)
    def translation_promote(source_work_id: str, payload: PromoteBody | None = None) -> dict[str, Any]:
        try:
            return run_promote(source_work_id, title=(payload.title if payload else None))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (IncompleteTranslation, KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/{path:path}")
    def static_or_spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        web_root = WEB_DIR.resolve()
        candidate = (WEB_DIR / unquote(path)).resolve()
        if not candidate.is_relative_to(web_root):
            raise HTTPException(404, "not found")
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
