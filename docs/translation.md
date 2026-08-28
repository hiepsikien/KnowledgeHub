# Translation pipeline (Phase 0)

Pilot work: **Grotius — *The Freedom of the Seas*** (`grotius--freedom_of_the_seas`).

English treatise only (~20k words, 13 chapters) extracted from Gutenberg #75962 bilingual edition.

## Quick start

```bash
.venv/bin/knowledgehub fetch-raw --work grotius--freedom_of_the_seas
.venv/bin/knowledgehub hash
.venv/bin/knowledgehub translate init --work grotius--freedom_of_the_seas
```

Hub-wide Cài đặt is `corpus/hub-settings.json` (models + auto chú thích/QA). Translation project files live under `corpus/translations/{source_work_id}/`:

| File | Purpose |
|------|---------|
| `project.json` | Mode, models snapshot, status, sample segment pointer |
| `glossary.json` | Locked terms / entities |
| `style_brief.md` | Voice and genre notes |
| `segments/ch{i}.json` | Per-chapter source + draft slots (tight/normal/loose) |
| `segments/chi-sample.json` | Chapter I sample for mode selection |
| `annotations.json` | Structured notes for Read (filled after annotation pass) |

## Translation modes

- **tight** — sát cấu trúc & thuật ngữ
- **normal** — cân bằng (default after sample selection)
- **loose** — dễ hiểu, thoát ý có kiểm soát

Run AI draft ×3 on `segments/chi-sample.json`, choose mode, then lock:

```bash
knowledgehub translate select-mode --work grotius--freedom_of_the_seas --mode tight
```

Pilot: **tight** selected for Grotius (legal treatise — fidelity over fluency).

## Model roles (Cài đặt Hub)

Defaults live in **Cài đặt** (`corpus/hub-settings.json`). Saving there also writes `models` into each `project.json`. Runtime reads Hub settings first.

| Pass | Setting | Default |
|------|---------|---------|
| Draft | `translation.models.draft` | `deepseek-v4-flash` |
| Polish | `translation.models.polish` | `gemini-3.5-flash` |
| QA | `translation.models.qa` | `deepseek-v4-pro` |
| Annotations | `translation.models.annotations` | `gemini-3.5-flash` |

Any DeepSeek or Gemini text model returned by their list-models APIs can be used on any pass. Cài đặt loads that live catalog (`GET /models` / Gemini `models.list`); it is not a hardcoded shortlist.

After a Hub **Dịch chương** job finishes, Cài đặt can auto-queue chú thích then QA (`auto_annotate` / `auto_qa`, both on by default). CLI `translate draft` / `qa` / `annotate` still run one step at a time.

### Secrets (Cursor Cloud Agents dashboard)

| Env var | Provider |
|---------|----------|
| `DEEPSEEK_API_KEY` | Draft + QA |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Polish + annotations |

### Draft sample (Normal mode)

```bash
knowledgehub translate draft-sample --work grotius--freedom_of_the_seas --mode normal
```

Pipeline: DeepSeek draft → Gemini polish → writes `segments/chi-sample.json`.

### Draft a chapter (after mode is locked)

```bash
knowledgehub translate draft --work grotius--freedom_of_the_seas --chapter II
```

Uses the locked mode. Same DeepSeek → Gemini pipeline; writes `segments/chii.json`. The curator UI **Dịch chương** button enqueues the same work on a **background worker pool** (HTTP returns immediately). Pool size is `min_workers`–`max_workers` in Cài đặt (default 1–2). **Dịch chương còn thiếu** queues every chapter without `final`. QA and chú thích use the same queue. Workers claim **draft → annotate → QA** across the queue (all dịch before chú thích before QA); two jobs for the same chapter never run at once. Each job writes `phase` / `detail` as it moves (DeepSeek nháp → lưu nháp → Gemini chỉnh văn). **Hủy job đang chạy** marks jobs `cancelled` and skips the next LLM call (in-flight HTTP may still finish). Reload of `serve` marks a `running` job `interrupted` instead of retrying, so a restart cannot loop token spend. Cài đặt `max_attempts` (default 2) and `job_timeout_sec` (default 600) cap retries and wall time.

### QA scoring

After mode is locked and `final` is set on a chapter segment:

```bash
knowledgehub translate qa --work grotius--freedom_of_the_seas --chapter I
```

Writes `segment["qa"]` with scores (fidelity, fluency, terminology, completeness, overall), Vietnamese summary, and issues list. If the chapter already has notes in `annotations.json`, that pass also reviews them (`scores.annotations`, issues with `annotation_id`). Duyệt can rewrite `body_vi` the same way it rewrites `final`.

### Annotations

```bash
knowledgehub translate annotate --work grotius--freedom_of_the_seas --chapter I
```

Generates footnote/glossary/context notes into `annotations.json` (merged by `id`).

## Publish to Read

Hub keeps **two Works**, Read gets **two books** (`hub_work_id` is unique).

| | English source | Vietnamese edition |
|---|---|---|
| Catalog id | `grotius--freedom_of_the_seas` | `grotius--freedom_of_the_seas_vi` |
| `rights.basis` | `public_domain` | `editorial_derivative` |
| `license` | source PD id | `hub_editorial_vi` |
| Body | edition from `raw/` | `segments/*/final` assembled at publish |
| Glossary | numbered `FOOTNOTES:` | `annotations.json` |

Do not write the translation into `sources/*/raw/`. Promote after every chapter has `final`:

```bash
knowledgehub translate promote --work grotius--freedom_of_the_seas
knowledgehub allow-read --work grotius--freedom_of_the_seas_vi
knowledgehub publish-read --work grotius--freedom_of_the_seas_vi
```

`build-catalog` preserves `origin: hub_translation` rows.

## License

Translated work id: `grotius--freedom_of_the_seas_vi` with `rights.basis: editorial_derivative`.
