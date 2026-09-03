# Read Edition Format (REF/1)

Hub produces REF/1 at publish time; Read consumes it for split, render, and TTS.

**Pilot contract (frozen):** see [ref-read-contract.md](./ref-read-contract.md) for the Hub→Read payload Read must honor on the first three English pilots (`arnold--essays_in_criticism`, `bastiat--economic_sophisms`, `bach--abdy_williams`).

**Final Touch / custom rules (plan):** see [final-touch-plan.md](./final-touch-plan.md) — parser fixes, Bach-specific rules, chapter editor, and translation inheritance. Not implemented yet.

**Rule reference:** see [ref-format-rules.md](./ref-format-rules.md) for parser pipeline, join rules, inline span classifiers, and corpus fixtures.

## Goals

- One canonical structured edition per `(work_id, raw content_hash)`.
- LLM labels line roles and join decisions; Python merges deterministically.
- Text tokens are never rewritten — only whitespace joins and hyphen de-joins.

## Block types

| `type` | Notes |
|--------|-------|
| `heading` | `level` 1–4; `CHAPTER I` stays plain text |
| `paragraph` | Prose; Gutenberg `_italic_` preserved in `text` |
| `blockquote` | Epigraphs, quoted Latin blocks |
| `verse_line` | Poetry — no reflow |
| `hr` | Rule / separator lines |
| `list_item` | Future |

## Payload (Hub → Read)

| Field | Required | Description |
|-------|----------|-------------|
| `edition_format` | when structured | `"ref/1"` |
| `edition_hash` | yes with REF | SHA-256 of `blocks` JSON |
| `content_kind` | yes with REF | `prose`, `verse`, `scholastic`, `mixed` |
| `reading_markdown` | yes with REF | Paragraphs separated by `\n\n`; headings plain |
| `blocks` | yes with REF | Canonical block array |
| `split_hints` | optional | Heading indices for chapter split |
| `quotation_profile` | optional | Rule-based inline marker counts |
| `raw_text` | yes | Same as `reading_markdown` when REF present (legacy) |

## Inline spans (rule detector — zero LLM cost)

Paragraph blocks may include `spans[]` with offsets into `text`:

| `style` | Example | Notes |
|---------|---------|-------|
| `footnote` | `[178]`, `[168]` | Numeric bracket markers only; `note` holds the chapter-end dump body when present |
| `bracket_note` | `[The Cambridge Modern History, I, 23-24, …]` | Long editorial note in brackets |
| `paren_cite` | `(Politics)`, `(foedus aequum)`, `(as X also says)` | Short citation / aside |
| `paren_quote` | long `(…quoted phrase…)` | Parenthetical quote |
| `paren_aside` | other `(...)` | Fallback |
| `quote` | `"..."`, `「…」` | Inline quotation marks |
| `em` | `_italic_` | Gutenberg emphasis |

`quotation_profile` summarizes counts per edition. Parentheses nested inside `[bracket notes]` are not re-parsed.

## Line labeling (Hub internal)

Each source line after rule strip gets:

```json
{"index": 4, "role": "prose", "join_next": true, "confidence": 0.95, "source": "rule"}
```

LLM may override labels for low-confidence segments only (`use_llm=True`).

## Cache

```
corpus/editions/{work_id}/{raw_content_hash}/blocks.json
```

Republish reuses cache when raw hash unchanged.

Cache entries include `cache_meta.json` with `ref_parser_version`; stale parser versions are rebuilt automatically.

## Read Edition package (Hub storage)

Per-work REF/1 export split by chapter for CMS preview, QA, and publish:

```
corpus/read-editions/{work_id}/{edition_hash}/
  manifest.json
  edition.full.json
  chapters/ch-NNN.json
  qa/report.json
  qa/overrides.json
  reading.md
```

CLI: `knowledgehub export-read-edition --work {id}`  
CMS: **Read Edition** nav → build, preview blocks, rule/LLM QA, edit overrides → **Publish Read**.

Translation projects can align segment boundaries via `POST /api/translations/{id}/sync-ref-chapters` (opt-in, `overwrite` required if segments exist).

When `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) is set, Read Edition build defaults to **LLM relabel** on low-confidence line segments; rule-only and LLM editions are cached separately (`cache_meta.json` → `llm_relabel`).

## Pilot

`grotius--freedom_of_the_seas` — Gutenberg bilingual treatise, Magoffin English chapters.
