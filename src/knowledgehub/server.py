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
from .read_edition_service import (
    confirm_hitl_trial as confirm_read_edition_hitl_trial,
    confirm_layout as confirm_read_edition_layout,
    confirm_toc as confirm_read_edition_toc,
    decide_hitl as decide_read_edition_hitl,
    edit_structure as edit_read_edition_structure,
    get_chapter as get_read_edition_chapter,
    get_hitl_job as get_read_edition_hitl_job,
    get_hitl_overview as get_read_edition_hitl_overview,
    get_section_source as get_read_edition_section_source,
    get_manifest as get_read_edition_manifest,
    get_review as get_read_edition_review,
    get_status as get_read_edition_status,
    list_sessions as list_read_edition_sessions,
    get_structure as get_read_edition_structure,
    parse_micro as parse_read_edition_micro,
    parse_micro_batch as parse_read_edition_micro_batch,
    patch_chapter as patch_read_edition_chapter,
    run_macro as run_read_edition_macro,
    reset_read_edition as reset_read_edition_package,
    run_qa as run_read_edition_qa,
    scan_hitl as scan_read_edition_hitl,
)
from .read_publish import PublishError, preview_normalized, publish_to_read
from .settings import save_settings, settings_payload
from .translation.api import (
    enqueue_translation_job,
    cancel_translation_jobs,
    create_translation_project,
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
from .translation.project import list_project_ids, translation_offer
from .translation.assemble import IncompleteTranslation
from .translation.ref_chapters import sync_translation_chapters_from_ref
from .translation.jobs import (
    configure_job_logging,
    job_log_event,
    list_jobs as list_translation_jobs,
    recent_job_log,
    start_worker,
    stop_worker,
    worker_alive,
    worker_status,
)
from .edition.jobs import (
    cancel_jobs as cancel_edition_jobs,
    enqueue_edition_job,
    jobs_payload as edition_jobs_payload,
    start_worker as start_edition_worker,
    stop_worker as stop_edition_worker,
)
from .translation.providers import ProviderError
from .validate import validate_catalog

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_NO_STORE = {"Cache-Control": "no-store"}
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


class CreateTranslationBody(BaseModel):
    source_work_id: str
    mode: str
    overwrite: bool = False
    target_language: str = "vi"


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
    max_part_words: int | None = None
    hard_max_part_words: int | None = None
    llm_retries: int | None = None
    gemini_rpm: int | None = None
    deepseek_rpm: int | None = None


class EditionSettingsBody(BaseModel):
    use_llm_macro: bool | None = None
    use_llm_relabel: bool | None = None
    use_llm_qa: bool | None = None
    min_workers: int | None = None
    max_workers: int | None = None
    max_attempts: int | None = None
    job_timeout_sec: int | None = None


class SettingsBody(BaseModel):
    translation: TranslationSettingsBody | None = None
    edition: EditionSettingsBody | None = None


class ReadEditionMacroBody(BaseModel):
    force: bool = False
    use_llm: bool = True
    keep_toc: bool = False


class ReadEditionParseBody(BaseModel):
    use_llm: bool | None = None


class ReadEditionParseBatchBody(BaseModel):
    chapter_ids: list[str] = Field(default_factory=list)
    use_llm: bool | None = None


class ReadEditionPatchBody(BaseModel):
    block_patches: list[dict[str, Any]] = Field(default_factory=list)
    curator_note: str | None = None


class ReadEditionQaBody(BaseModel):
    chapter_id: str | None = None
    use_llm: bool = True


class ReadEditionJobBody(BaseModel):
    kind: str
    chapter_id: str | None = None
    chapter_ids: list[str] = Field(default_factory=list)
    hitl_kind: str | None = None
    scope: str | None = None
    use_llm: bool | None = None
    force: bool = False
    keep_toc: bool = False


class ReadEditionCancelBody(BaseModel):
    job_id: str | None = None
    chapter: str | None = None


class ReadEditionTocBody(BaseModel):
    status: str
    excerpt: str | None = None


class ReadEditionStructureEditBody(BaseModel):
    action: str
    section_id: str
    start_line: int | None = None
    kind: str | None = None
    use_llm: bool | None = None


class ReadEditionHitlScanBody(BaseModel):
    chapter_id: str | None = None
    scope: str = "chapter"


class ReadEditionHitlDecideBody(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    decision: str
    suspects_only: bool = False
    chapter_id: str | None = None


class ReadEditionHitlConfirmBody(BaseModel):
    chapter_id: str | None = None


class SyncRefChaptersBody(BaseModel):
    overwrite: bool = False
    include_front_matter: bool = False


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
    configure_job_logging()
    start_worker()
    start_edition_worker()
    yield
    stop_edition_worker()
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
        project_ids = set(list_project_ids())
        rows = []
        for work in works:
            row = work_summary(work, root=root)
            row.update(translation_offer(work, project_ids=project_ids))
            rows.append(row)
        return {"works": rows, "total": len(rows)}

    @app.get("/api/works/{work_id}", dependencies=guard)
    def work_detail(work_id: str) -> dict[str, Any]:
        root = corpus_root()
        try:
            work = get_work(work_id, corpus=root)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        summary = work_summary(work, root=root)
        summary.update(translation_offer(work, project_ids=set(list_project_ids())))
        return {"work": work, "summary": summary}

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

    @app.post("/api/works/{work_id}/ingest-images", dependencies=guard)
    def ingest_work_images(work_id: str) -> dict[str, Any]:
        from .edition.figures import IMAGE_NAME, ensure_work_assets, work_asset_dir

        try:
            work = get_work(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        if not str(work.get("gutenberg_id") or "").strip():
            raise HTTPException(400, "work has no gutenberg_id")
        try:
            dest = ensure_work_assets(work, corpus_root(), fetch=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"could not download Gutenberg images: {exc}") from exc
        copied = [
            {"file": p.name, "bytes": p.stat().st_size}
            for p in sorted(dest.iterdir())
            if p.is_file() and IMAGE_NAME.search(p.name)
        ]
        return {"work_id": work_id, "dest": str(work_asset_dir(corpus_root(), work_id)), "copied": copied}

    @app.get("/assets/{work_id}/{filename}", dependencies=guard)
    def serve_work_asset(work_id: str, filename: str) -> FileResponse:
        from .edition.figures import IMAGE_NAME, work_asset_dir

        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(404, "not found")
        if not IMAGE_NAME.search(filename):
            raise HTTPException(404, "not found")
        path = work_asset_dir(corpus_root(), work_id) / filename
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    @app.get("/api/read-editions", dependencies=guard)
    def read_edition_sessions() -> dict[str, Any]:
        sessions = list_read_edition_sessions()
        return {"sessions": sessions, "total": len(sessions)}

    @app.get("/api/works/{work_id}/read-edition", dependencies=guard)
    def read_edition_status(work_id: str) -> dict[str, Any]:
        try:
            status = get_read_edition_status(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        status.update(edition_jobs_payload(work_id))
        return status

    @app.post("/api/works/{work_id}/read-edition/macro", dependencies=guard)
    def read_edition_macro(work_id: str, payload: ReadEditionMacroBody | None = None) -> dict[str, Any]:
        body = payload or ReadEditionMacroBody()
        try:
            return run_read_edition_macro(
                work_id, force=body.force, use_llm=body.use_llm, keep_toc=body.keep_toc
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/reset", dependencies=guard)
    def read_edition_reset(work_id: str) -> dict[str, Any]:
        try:
            return reset_read_edition_package(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/structure", dependencies=guard)
    def read_edition_structure(work_id: str) -> dict[str, Any]:
        try:
            return {"structure": get_read_edition_structure(work_id)}
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/review", dependencies=guard)
    def read_edition_review(work_id: str) -> dict[str, Any]:
        try:
            return get_read_edition_review(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/toc", dependencies=guard)
    def read_edition_toc(work_id: str, payload: ReadEditionTocBody) -> dict[str, Any]:
        try:
            return confirm_read_edition_toc(work_id, payload.status, excerpt=payload.excerpt)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/layout", dependencies=guard)
    def read_edition_layout(work_id: str) -> dict[str, Any]:
        try:
            return confirm_read_edition_layout(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/hitl", dependencies=guard)
    def read_edition_hitl_overview(work_id: str) -> dict[str, Any]:
        try:
            return get_read_edition_hitl_overview(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/hitl/{kind}", dependencies=guard)
    def read_edition_hitl_job(work_id: str, kind: str) -> dict[str, Any]:
        try:
            return get_read_edition_hitl_job(work_id, kind)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/hitl/{kind}/scan", dependencies=guard)
    def read_edition_hitl_scan(
        work_id: str, kind: str, payload: ReadEditionHitlScanBody | None = None
    ) -> dict[str, Any]:
        body = payload or ReadEditionHitlScanBody()
        try:
            return scan_read_edition_hitl(
                work_id, kind, chapter_id=body.chapter_id, scope=body.scope
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/hitl/{kind}/confirm", dependencies=guard)
    def read_edition_hitl_confirm(
        work_id: str, kind: str, payload: ReadEditionHitlConfirmBody | None = None
    ) -> dict[str, Any]:
        body = payload or ReadEditionHitlConfirmBody()
        try:
            return confirm_read_edition_hitl_trial(work_id, kind, chapter_id=body.chapter_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/hitl/{kind}/decide", dependencies=guard)
    def read_edition_hitl_decide(
        work_id: str, kind: str, payload: ReadEditionHitlDecideBody
    ) -> dict[str, Any]:
        try:
            return decide_read_edition_hitl(
                work_id,
                kind,
                decision=payload.decision,
                item_ids=payload.item_ids,
                suspects_only=payload.suspects_only,
                chapter_id=payload.chapter_id,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/structure/edit", dependencies=guard)
    def read_edition_structure_edit(work_id: str, payload: ReadEditionStructureEditBody) -> dict[str, Any]:
        try:
            return edit_read_edition_structure(
                work_id,
                action=payload.action,
                section_id=payload.section_id,
                start_line=payload.start_line,
                kind=payload.kind,
                use_llm=payload.use_llm,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/chapters/{chapter_id}/parse", dependencies=guard)
    def read_edition_parse_chapter(
        work_id: str, chapter_id: str, payload: ReadEditionParseBody | None = None
    ) -> dict[str, Any]:
        body = payload or ReadEditionParseBody()
        try:
            return parse_read_edition_micro(work_id, chapter_id, use_llm=body.use_llm)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/chapters/parse", dependencies=guard)
    def read_edition_parse_chapters(
        work_id: str, payload: ReadEditionParseBatchBody
    ) -> dict[str, Any]:
        if not payload.chapter_ids:
            raise HTTPException(400, "chapter_ids required")
        try:
            return parse_read_edition_micro_batch(
                work_id, payload.chapter_ids, use_llm=payload.use_llm
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/manifest", dependencies=guard)
    def read_edition_manifest(work_id: str) -> dict[str, Any]:
        try:
            return {"manifest": get_read_edition_manifest(work_id)}
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/chapters/{chapter_id}/source", dependencies=guard)
    def read_edition_chapter_source(work_id: str, chapter_id: str) -> dict[str, Any]:
        try:
            return get_read_edition_section_source(work_id, chapter_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/chapters/{chapter_id}", dependencies=guard)
    def read_edition_chapter(work_id: str, chapter_id: str) -> dict[str, Any]:
        try:
            return get_read_edition_chapter(work_id, chapter_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/works/{work_id}/read-edition/chapters/{chapter_id}", dependencies=guard)
    def read_edition_patch(
        work_id: str, chapter_id: str, payload: ReadEditionPatchBody
    ) -> dict[str, Any]:
        try:
            return patch_read_edition_chapter(
                work_id,
                chapter_id,
                block_patches=payload.block_patches,
                curator_note=payload.curator_note,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/qa", dependencies=guard)
    def read_edition_qa(work_id: str, payload: ReadEditionQaBody | None = None) -> dict[str, Any]:
        body = payload or ReadEditionQaBody()
        try:
            return run_read_edition_qa(
                work_id,
                chapter_id=body.chapter_id,
                use_llm=body.use_llm,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/works/{work_id}/read-edition/jobs", dependencies=guard)
    def read_edition_jobs(work_id: str) -> dict[str, Any]:
        try:
            get_read_edition_status(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        return edition_jobs_payload(work_id)

    @app.post("/api/works/{work_id}/read-edition/jobs", dependencies=guard)
    def read_edition_enqueue(work_id: str, payload: ReadEditionJobBody) -> dict[str, Any]:
        try:
            return enqueue_edition_job(
                work_id,
                kind=payload.kind,
                chapter_id=payload.chapter_id,
                chapter_ids=payload.chapter_ids,
                hitl_kind=payload.hitl_kind,
                scope=payload.scope,
                use_llm=payload.use_llm,
                force=payload.force,
                keep_toc=payload.keep_toc,
            )
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/works/{work_id}/read-edition/jobs/cancel", dependencies=guard)
    def read_edition_cancel(work_id: str, payload: ReadEditionCancelBody | None = None) -> dict[str, Any]:
        body = payload or ReadEditionCancelBody()
        try:
            get_read_edition_status(work_id)
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {work_id}") from exc
        return cancel_edition_jobs(work_id=work_id, chapter=body.chapter, job_id=body.job_id)

    @app.post("/api/translations/{source_work_id}/sync-ref-chapters", dependencies=guard)
    def translation_sync_ref_chapters(
        source_work_id: str, payload: SyncRefChaptersBody | None = None
    ) -> dict[str, Any]:
        body = payload or SyncRefChaptersBody()
        try:
            return sync_translation_chapters_from_ref(
                source_work_id,
                overwrite=body.overwrite,
                include_front_matter=body.include_front_matter,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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
        if payload.edition is not None:
            body["edition"] = payload.edition.model_dump(exclude_none=True)
        try:
            saved = save_settings(body)
        except (ProviderError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return settings_payload() | {"projects_updated": saved.get("projects_updated", 0)}

    @app.get("/api/translations", dependencies=guard)
    def translations_list() -> dict[str, Any]:
        return list_translation_projects()

    @app.post("/api/translations", dependencies=guard)
    def translations_create(payload: CreateTranslationBody) -> dict[str, Any]:
        try:
            return create_translation_project(
                payload.source_work_id,
                mode=payload.mode,
                overwrite=payload.overwrite,
                target_language=payload.target_language,
            )
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, f"unknown work: {payload.source_work_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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
                "log": recent_job_log(),
                "worker_alive": worker_alive(),
                "workers": worker_status(),
            }
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/translations/{source_work_id}/jobs", dependencies=guard)
    def translation_enqueue(source_work_id: str, payload: TranslationJobBody) -> dict[str, Any]:
        job_log_event(
            "api_enqueue",
            work_id=source_work_id,
            kind=payload.kind,
            chapter=payload.chapter,
            missing=payload.missing,
        )
        try:
            result = enqueue_translation_job(
                source_work_id,
                kind=payload.kind,
                chapter=payload.chapter,
                missing=payload.missing,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        job_log_event(
            "api_enqueue_ok",
            work_id=source_work_id,
            enqueued=result.get("enqueued"),
            missing_count=len(result.get("missing") or []),
            workers=(result.get("workers") or {}).get("alive"),
        )
        result["log"] = recent_job_log()
        return result

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
        return FileResponse(WEB_DIR / "index.html", headers=WEB_NO_STORE)

    @app.get("/{path:path}")
    def static_or_spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        web_root = WEB_DIR.resolve()
        candidate = (WEB_DIR / unquote(path)).resolve()
        if not candidate.is_relative_to(web_root):
            raise HTTPException(404, "not found")
        if candidate.is_file():
            return FileResponse(candidate, headers=WEB_NO_STORE)
        return FileResponse(WEB_DIR / "index.html", headers=WEB_NO_STORE)

    return app


app = create_app()
