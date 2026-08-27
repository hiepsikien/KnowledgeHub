# Translation pipeline (Phase 0)

Pilot work: **Grotius — *The Freedom of the Seas*** (`grotius--freedom_of_the_seas`).

English treatise only (~20k words, 13 chapters) extracted from Gutenberg #75962 bilingual edition.

## Quick start

```bash
.venv/bin/knowledgehub fetch-raw --work grotius--freedom_of_the_seas
.venv/bin/knowledgehub hash
.venv/bin/knowledgehub translate init --work grotius--freedom_of_the_seas
```

Translation project files live under `corpus/translations/{source_work_id}/`:

| File | Purpose |
|------|---------|
| `project.json` | Mode, models, status, sample segment pointer |
| `glossary.json` | Locked terms / entities |
| `style_brief.md` | Voice and genre notes |
| `segments/ch{i}.json` | Per-chapter source + draft slots (tight/normal/loose) |
| `segments/chi-sample.json` | Chapter I sample for mode selection |
| `annotations.json` | Structured notes for Read (filled after annotation pass) |

## Translation modes

- **tight** — sát cấu trúc & thuật ngữ
- **normal** — cân bằng (default after sample selection)
- **loose** — dễ hiểu, thoát ý có kiểm soát

Run AI draft ×3 on `segments/chi-sample.json`, choose mode in Curator (UI TBD), then lock `translation_mode` in `project.json`.

## Model roles (configured in project.json)

| Pass | Default model slot |
|------|-------------------|
| Draft ×3 | `models.draft` (Claude) |
| Polish | `models.polish` (Gemini) |
| QA | `models.qa` (Claude) |
| Annotations | `models.annotations` (Gemini) |

## Read integration (next)

Publish payload will include `annotations` + `edition_meta`. Read repo: inline tap-to-expand notes.

## License

Translated work id: `grotius--freedom_of_the_seas--vi` with `rights.basis: editorial_derivative`.
