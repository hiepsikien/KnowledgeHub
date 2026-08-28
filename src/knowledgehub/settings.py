from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .paths import corpus_root

WORKER_MIN_FLOOR = 0
WORKER_MAX_CAP = 8

MODEL_SLOTS = ("draft", "polish", "qa", "annotations")
MODES = ("tight", "normal", "loose")
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"

DEFAULT_MODELS: dict[str, str] = {
    "draft": "deepseek-v4-flash",
    "polish": DEFAULT_GEMINI_MODEL,
    "qa": "deepseek-v4-pro",
    "annotations": DEFAULT_GEMINI_MODEL,
}

STAGES: list[dict[str, str]] = [
    {
        "id": "draft",
        "label": "Dịch nháp",
        "hint": "Bản dịch đầu từ tiếng Anh.",
    },
    {
        "id": "polish",
        "label": "Chỉnh văn",
        "hint": "Làm mượt tiếng Việt, không đổi nghĩa.",
    },
    {
        "id": "annotations",
        "label": "Chú thích",
        "hint": "Chú thích footnote / glossary / ngữ cảnh cho Read.",
    },
    {
        "id": "qa",
        "label": "QA",
        "hint": "Chấm bản dịch; nếu đã có chú thích thì chấm cả chú thích.",
    },
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "translation": {
        "models": dict(DEFAULT_MODELS),
        "auto_annotate": True,
        "auto_qa": True,
        "default_mode": "normal",
        "min_workers": 1,
        "max_workers": 2,
        "max_attempts": 2,
        "job_timeout_sec": 600,
    }
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _coerce_worker_int(value: Any, *, name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{name} must be an integer")
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{name} must be an integer")


def clamp_worker_limits(min_workers: Any, max_workers: Any) -> tuple[int, int]:
    min_w = _coerce_worker_int(min_workers, name="min_workers", default=1)
    max_w = _coerce_worker_int(max_workers, name="max_workers", default=2)
    max_w = max(1, min(WORKER_MAX_CAP, max_w))
    min_w = max(WORKER_MIN_FLOOR, min(max_w, min_w))
    return min_w, max_w


def settings_path():
    return corpus_root() / "hub-settings.json"


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def _merge_translation(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = deepcopy(DEFAULT_SETTINGS["translation"])
    incoming = raw if isinstance(raw, dict) else {}
    models = incoming.get("models") if isinstance(incoming.get("models"), dict) else {}
    merged_models = dict(base["models"])
    for slot in MODEL_SLOTS:
        value = models.get(slot)
        if isinstance(value, str) and value.strip():
            merged_models[slot] = value.strip()
    base["models"] = merged_models
    if "auto_annotate" in incoming:
        base["auto_annotate"] = bool(incoming["auto_annotate"])
    if "auto_qa" in incoming:
        base["auto_qa"] = bool(incoming["auto_qa"])
    mode = incoming.get("default_mode")
    if mode in MODES:
        base["default_mode"] = mode
    try:
        base["min_workers"], base["max_workers"] = clamp_worker_limits(
            incoming["min_workers"] if "min_workers" in incoming else base["min_workers"],
            incoming["max_workers"] if "max_workers" in incoming else base["max_workers"],
        )
    except ValueError:
        pass
    try:
        base["max_attempts"] = max(
            1,
            min(10, _coerce_worker_int(
                incoming["max_attempts"] if "max_attempts" in incoming else base["max_attempts"],
                name="max_attempts",
                default=2,
            )),
        )
        base["job_timeout_sec"] = max(
            60,
            min(3600, _coerce_worker_int(
                incoming["job_timeout_sec"] if "job_timeout_sec" in incoming else base["job_timeout_sec"],
                name="job_timeout_sec",
                default=600,
            )),
        )
    except ValueError:
        pass
    return base


def _normalize(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "translation": _merge_translation(data.get("translation") if isinstance(data.get("translation"), dict) else data),
        "updated_at": data.get("updated_at"),
    }


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return default_settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings()
    if not isinstance(raw, dict):
        return default_settings()
    return _normalize(raw)


def validate_model(model: str) -> str:
    from .translation.providers import provider_for_model

    text = (model or "").strip()
    provider_for_model(text)
    return text


def _validate_translation(translation: dict[str, Any]) -> dict[str, Any]:
    models = {slot: validate_model(str(translation["models"][slot])) for slot in MODEL_SLOTS}
    mode = translation.get("default_mode") or "normal"
    if mode not in MODES:
        raise ValueError(f"Unknown translation mode {mode!r}; expected one of {list(MODES)}")
    min_workers, max_workers = clamp_worker_limits(
        translation.get("min_workers"),
        translation.get("max_workers"),
    )
    max_attempts = max(
        1,
        min(10, _coerce_worker_int(translation.get("max_attempts"), name="max_attempts", default=2)),
    )
    job_timeout_sec = max(
        60,
        min(3600, _coerce_worker_int(translation.get("job_timeout_sec"), name="job_timeout_sec", default=600)),
    )
    return {
        "models": models,
        "auto_annotate": bool(translation.get("auto_annotate")),
        "auto_qa": bool(translation.get("auto_qa")),
        "default_mode": mode,
        "min_workers": min_workers,
        "max_workers": max_workers,
        "max_attempts": max_attempts,
        "job_timeout_sec": job_timeout_sec,
    }


def _sync_project_models(models: dict[str, str]) -> int:
    root = corpus_root() / "translations"
    if not root.is_dir():
        return 0
    n = 0
    for path in sorted(root.iterdir()):
        project_path = path / "project.json"
        if not path.is_dir() or not project_path.is_file():
            continue
        try:
            project = json.loads(project_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(project, dict):
            continue
        current = project.get("models") if isinstance(project.get("models"), dict) else {}
        project["models"] = {**current, **models}
        project["updated_at"] = _now()
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n += 1
    return n


def save_settings(payload: dict[str, Any], *, sync_projects: bool = True) -> dict[str, Any]:
    current = load_settings()
    incoming = payload if isinstance(payload, dict) else {}
    current_tr = current.get("translation") if isinstance(current.get("translation"), dict) else {}
    incoming_tr = incoming.get("translation") if isinstance(incoming.get("translation"), dict) else incoming
    if not isinstance(incoming_tr, dict):
        incoming_tr = {}
    current_models = current_tr.get("models") if isinstance(current_tr.get("models"), dict) else {}
    incoming_models = incoming_tr.get("models") if isinstance(incoming_tr.get("models"), dict) else {}
    merged = {
        "translation": _merge_translation(
            {
                **current_tr,
                **incoming_tr,
                "models": {**current_models, **incoming_models},
            }
        )
    }
    merged["translation"] = _validate_translation(merged["translation"])
    merged["updated_at"] = _now()
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if sync_projects:
        merged["projects_updated"] = _sync_project_models(merged["translation"]["models"])
    else:
        merged["projects_updated"] = 0
    from .translation.jobs import scale_workers

    scale_workers()
    return merged


def resolve_models(project: dict[str, Any] | None = None) -> dict[str, str]:
    hub = (load_settings().get("translation") or {}).get("models") or {}
    proj = (project or {}).get("models") if isinstance(project, dict) else {}
    if not isinstance(proj, dict):
        proj = {}
    out: dict[str, str] = {}
    for slot in MODEL_SLOTS:
        value = hub.get(slot) or proj.get(slot) or DEFAULT_MODELS[slot]
        out[slot] = str(value)
    return out


def worker_limits() -> tuple[int, int]:
    tr = load_settings().get("translation") or {}
    return clamp_worker_limits(tr.get("min_workers"), tr.get("max_workers"))


def job_guard_limits() -> tuple[int, int]:
    tr = load_settings().get("translation") or {}
    max_attempts = max(1, min(10, int(tr.get("max_attempts") or 2)))
    job_timeout_sec = max(60, min(3600, int(tr.get("job_timeout_sec") or 600)))
    return max_attempts, job_timeout_sec


def translation_pipeline() -> dict[str, Any]:
    tr = load_settings().get("translation") or {}
    min_workers, max_workers = worker_limits()
    max_attempts, job_timeout_sec = job_guard_limits()
    return {
        "auto_annotate": bool(tr.get("auto_annotate")),
        "auto_qa": bool(tr.get("auto_qa")),
        "default_mode": tr.get("default_mode") or "normal",
        "models": resolve_models(),
        "min_workers": min_workers,
        "max_workers": max_workers,
        "max_attempts": max_attempts,
        "job_timeout_sec": job_timeout_sec,
    }


def followup_kinds(kind: str) -> list[str]:
    tr = load_settings().get("translation") or {}
    auto_annotate = bool(tr.get("auto_annotate"))
    auto_qa = bool(tr.get("auto_qa"))
    if kind == "draft":
        if auto_annotate:
            return ["annotate"]
        if auto_qa:
            return ["qa"]
        return []
    if kind == "annotate" and auto_qa:
        return ["qa"]
    return []


def secrets_status() -> dict[str, Any]:
    deepseek = bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())
    gemini = bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())
    return {
        "deepseek": deepseek,
        "gemini": gemini,
        "read_token": bool((os.environ.get("READ_HUB_TOKEN") or "").strip()),
        "ops": bool((os.environ.get("KNOWLEDGEHUB_OPS_SECRET") or "").strip()),
        "read_api": os.environ.get("READ_API_URL") or "http://127.0.0.1:8000",
    }


def settings_payload(*, refresh: bool = False) -> dict[str, Any]:
    from .translation.providers import list_available_models

    stored = load_settings()
    live = list_available_models(refresh=refresh)
    return {
        "settings": {
            "translation": stored.get("translation") or deepcopy(DEFAULT_SETTINGS["translation"]),
        },
        "updated_at": stored.get("updated_at"),
        "model_catalog": live.get("models") or [],
        "model_catalog_errors": live.get("errors") or {},
        "model_catalog_fetched_at": live.get("fetched_at"),
        "model_catalog_counts": live.get("counts") or {},
        "stages": STAGES,
        "modes": list(MODES),
        "secrets": secrets_status(),
    }
